#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from _workflow_lib import write_json
from run_workflow import RUN_STAGES, resolve_job_path, scaffold_run


DEFAULT_CODEX_BIN = "codex"
DEFAULT_GEMINI_BIN = "gemini"
DEFAULT_ANTIGRAVITY_BIN = "antigravity"
DEFAULT_JOBS_INDEX_ROOT = Path(__file__).resolve().parents[1] / "jobs-index"
STAGE_CLAIM_STAGE_IDS = {"research-a", "research-b", "judge"}
SECTION_HEADING_PATTERN = re.compile(r"^#\s+(.+)$")
LIST_ITEM_PATTERN = re.compile(r"^\s*\d+[.)]\s+")
CONFIDENCE_LABEL_PATTERN = re.compile(r"\bconfidence\s*:\s*(low|medium|high)\b", re.IGNORECASE)
EVIDENCE_MARKER_PATTERN = re.compile(r"^(?:SRC|DOC)-[A-Z0-9._-]+$|^S[0-9]{1,6}$|^https?://\S+$", re.IGNORECASE)
FENCED_BLOCK_PATTERN = re.compile(r"```(?:markdown)?\n(.*?)```", re.IGNORECASE | re.DOTALL)


@dataclass(frozen=True)
class StageExecution:
    stage_id: str
    agent_role: str
    packet_name: str
    output_name: str


EXECUTION_PLAN = [
    [StageExecution("intake", "primary", "01-intake.md", "01-intake.json")],
    [
        StageExecution("research-a", "primary", "02-research-a.md", "02-research-a.md"),
        StageExecution("research-b", "secondary", "03-research-b.md", "03-research-b.md"),
    ],
    [
        StageExecution("critique-a-on-b", "primary", "04-critique-a-on-b.md", "04-critique-a-on-b.md"),
        StageExecution("critique-b-on-a", "secondary", "05-critique-b-on-a.md", "05-critique-b-on-a.md"),
    ],
    [StageExecution("judge", "secondary", "06-judge.md", "06-judge.md")],
]

GREEN = "\x1b[32m"
RED = "\x1b[31m"
RESET = "\x1b[0m"


@dataclass(frozen=True)
class CLIAdapter:
    name: str
    command_builder: Callable[[str, Path, str], list[str]]
    stdout_artifact_recovery: bool = False


def build_codex_command(binary: str, job_dir: Path, prompt: str) -> list[str]:
    return [binary, "exec", "--full-auto", "-C", str(job_dir), prompt]


def build_gemini_command(binary: str, job_dir: Path, prompt: str) -> list[str]:
    return [binary, "-p", prompt, "-y"]


def build_antigravity_command(binary: str, job_dir: Path, prompt: str) -> list[str]:
    return [binary, "chat", "--mode", "agent", "--yes", prompt]


CLI_ADAPTERS: dict[str, CLIAdapter] = {
    "codex": CLIAdapter(name="codex", command_builder=build_codex_command),
    "gemini": CLIAdapter(name="gemini", command_builder=build_gemini_command, stdout_artifact_recovery=True),
    "antigravity": CLIAdapter(name="antigravity", command_builder=build_antigravity_command, stdout_artifact_recovery=True),
}


class ProgressReporter:
    def __init__(self, stream: object) -> None:
        self.stream = stream
        self.lock = threading.Lock()
        self.agent_status: dict[str, str] = {}
        self.completed_events: list[str] = []
        self.rendered_line_count = 0
        self.is_tty = bool(getattr(stream, "isatty", lambda: False)())

    def start(self, actor: str, stage_id: str) -> None:
        with self.lock:
            message = f"{actor}: {stage_id} started"
            self.agent_status[actor] = message
            self._emit_event_locked(message)
            if self.is_tty:
                self._render_locked()

    def complete(self, actor: str, stage_id: str) -> None:
        with self.lock:
            message = f"{actor}: {stage_id} completed"
            self.completed_events.append(message)
            self.agent_status.pop(actor, None)
            self._emit_event_locked(message)
            if self.is_tty:
                self._render_locked()

    def fail(self, actor: str, stage_id: str) -> None:
        with self.lock:
            message = f"{actor}: {stage_id} failed"
            self.agent_status[actor] = message
            self._emit_event_locked(message)
            if self.is_tty:
                self._render_locked()

    def _build_lines(self) -> list[str]:
        lines = [self._format_line(line) for line in self.completed_events]
        for line in self.agent_status.values():
            lines.append(self._format_line(line))
        return lines or ["workflow: pending"]

    def _format_line(self, line: str) -> str:
        if not self.is_tty:
            return line
        if line.endswith(" completed"):
            return line[: -len("completed")] + f"{GREEN}completed{RESET}"
        if line.endswith(" failed"):
            return line[: -len("failed")] + f"{RED}failed{RESET}"
        return line

    def _render_locked(self) -> None:
        lines = self._build_lines()
        if self.is_tty:
            if self.rendered_line_count:
                self.stream.write(f"\x1b[{self.rendered_line_count}F")
            self.stream.write("\x1b[J")
            for line in lines:
                self.stream.write(line + "\n")
            self.stream.flush()
            self.rendered_line_count = len(lines)
            return

    def _emit_event_locked(self, message: str) -> None:
        if self.is_tty:
            return
        self.stream.write(message + "\n")
        self.stream.flush()
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Execute the current 2-pass research workflow using Codex and Antigravity adapters."
    )
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--job-name", help="Job name to resolve via jobs-index or jobs root.")
    target.add_argument("--job-id", help="Job id to resolve via jobs-index metadata or jobs root.")
    target.add_argument("--job-path", help="Explicit path to the target job repository.")
    parser.add_argument("--run-id", required=True, help="Run identifier to execute or create.")
    parser.add_argument("--jobs-root", default=str(Path.home() / "Projects" / "research-hub" / "jobs"))
    parser.add_argument("--jobs-index-root", default=str(DEFAULT_JOBS_INDEX_ROOT))
    parser.add_argument("--primary-adapter", default="codex", help="Adapter name for the primary execution role.")
    parser.add_argument("--secondary-adapter", default="gemini", help="Adapter name for the secondary execution role.")
    parser.add_argument("--codex-bin", default=DEFAULT_CODEX_BIN, help="Path to the Codex CLI.")
    parser.add_argument("--gemini-bin", default=DEFAULT_GEMINI_BIN, help="Path to the Gemini CLI.")
    parser.add_argument("--antigravity-bin", default=DEFAULT_ANTIGRAVITY_BIN, help="Path to the Antigravity CLI.")
    parser.add_argument(
        "--claim-output",
        help="Optional path for the generated claim register. Defaults to job evidence/claims-<run-id>.json.",
    )
    parser.add_argument(
        "--final-output",
        help="Optional path for the generated final artifact. Defaults to job outputs/final-<run-id>.md.",
    )
    return parser.parse_args()


def load_state(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def save_state(path: Path, payload: dict[str, object]) -> None:
    write_json(path, payload)


def is_placeholder_content(content: str) -> bool:
    lowered = content.lower()
    return "not_started" in lowered or "status: not started" in lowered or "stage output placeholder" in lowered


def is_stage_output_complete(path: Path) -> bool:
    if not path.is_file():
        return False
    return not is_placeholder_content(path.read_text(encoding="utf-8"))


def read_output_preview(path: Path, max_chars: int = 400) -> str:
    if not path.is_file():
        return "<missing>"
    content = path.read_text(encoding="utf-8")
    preview = content[:max_chars]
    if len(content) > max_chars:
        preview += "\n...[truncated]"
    return preview


def expected_first_heading(stage_id: str) -> str | None:
    return {
        "research-a": "# Executive Summary",
        "research-b": "# Executive Summary",
        "critique-a-on-b": "# Claims That Survive Review",
        "critique-b-on-a": "# Claims That Survive Review",
        "judge": "# Supported Conclusions",
    }.get(stage_id)


def extract_markdown_artifact(stage_id: str, stdout: str) -> str | None:
    expected_heading = expected_first_heading(stage_id)
    for match in FENCED_BLOCK_PATTERN.finditer(stdout):
        block = match.group(1).strip()
        if expected_heading is None or expected_heading in block:
            return block.rstrip() + "\n"

    lines = stdout.splitlines()
    start_index: int | None = None
    for index, line in enumerate(lines):
        if expected_heading is not None:
            if line.strip() == expected_heading:
                start_index = index
                break
        elif line.startswith("# "):
            start_index = index
            break
    if start_index is None:
        return None
    artifact = "\n".join(lines[start_index:]).strip()
    if not artifact:
        return None
    return artifact + "\n"


def recover_output_from_stdout(adapter: CLIAdapter, stage_id: str, output_path: Path, stdout: str) -> bool:
    if not adapter.stdout_artifact_recovery or output_path.suffix.lower() != ".md":
        return False
    artifact = extract_markdown_artifact(stage_id, stdout)
    if artifact is None:
        return False
    output_path.write_text(artifact, encoding="utf-8")
    return True


def stage_output_path(run_dir: Path, output_name: str) -> Path:
    return run_dir / "stage-outputs" / output_name


def stage_packet_path(run_dir: Path, packet_name: str) -> Path:
    return run_dir / "prompt-packets" / packet_name


def stage_claim_output_path(run_dir: Path, stage_id: str) -> Path:
    output_name_by_stage = {
        str(stage["id"]): Path(str(stage["output"])).stem
        for stage in RUN_STAGES
    }
    return run_dir / "stage-claims" / f"{output_name_by_stage[stage_id]}.claims.json"


def parse_markdown_sections(markdown: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for raw_line in markdown.splitlines():
        match = SECTION_HEADING_PATTERN.match(raw_line)
        if match:
            current = match.group(1).strip()
            sections.setdefault(current, [])
            continue
        if current is not None:
            sections[current].append(raw_line)
    return sections


def collect_numbered_items(lines: list[str]) -> list[str]:
    items: list[str] = []
    current: list[str] = []
    for raw_line in lines:
        if not raw_line.strip():
            continue
        if raw_line.startswith("# "):
            break
        if LIST_ITEM_PATTERN.match(raw_line):
            if current:
                items.append(" ".join(part.strip() for part in current))
            current = [LIST_ITEM_PATTERN.sub("", raw_line, count=1).strip()]
            continue
        if current:
            current.append(raw_line.strip())
    if current:
        items.append(" ".join(part.strip() for part in current))
    return items


def has_evidence_marker(text: str) -> bool:
    for block in re.findall(r"\[([^\[\]]+)\]", text):
        for part in block.split(","):
            if EVIDENCE_MARKER_PATTERN.match(part.strip()):
                return True
    return False


def validate_stage_markdown_contract(stage_id: str, markdown: str) -> list[str]:
    sections = parse_markdown_sections(markdown)
    errors: list[str] = []

    if stage_id in {"research-a", "research-b"}:
        facts = collect_numbered_items(sections.get("Facts", []))
        inferences = collect_numbered_items(sections.get("Inferences", []))
        for index, item in enumerate(facts, start=1):
            if not has_evidence_marker(item):
                errors.append(f"Facts item {index} lacks an external evidence citation.")
        for index, item in enumerate(inferences, start=1):
            if not has_evidence_marker(item):
                errors.append(f"Inferences item {index} lacks an external evidence citation.")
            if not CONFIDENCE_LABEL_PATTERN.search(item):
                errors.append(f"Inferences item {index} lacks an explicit confidence label.")
        return errors

    if stage_id == "judge":
        conclusions = collect_numbered_items(sections.get("Supported Conclusions", []))
        inferences = collect_numbered_items(sections.get("Inferences And Synthesis Judgments", []))
        for index, item in enumerate(conclusions, start=1):
            if not has_evidence_marker(item):
                errors.append(f"Supported Conclusions item {index} lacks an external evidence citation.")
        for index, item in enumerate(inferences, start=1):
            if not has_evidence_marker(item):
                errors.append(f"Inferences And Synthesis Judgments item {index} lacks an external evidence citation.")
            if not CONFIDENCE_LABEL_PATTERN.search(item):
                errors.append(f"Inferences And Synthesis Judgments item {index} lacks an explicit confidence label.")
        return errors

    return errors


def set_stage_status(state: dict[str, object], stage_id: str, status: str) -> None:
    for stage in state["stages"]:
        if stage["id"] == stage_id:
            stage["status"] = status
            return
    raise KeyError(f"Unknown stage id: {stage_id}")


def ensure_post_processing_state(state: dict[str, object], claim_output: Path, final_output: Path) -> None:
    post_processing = state.setdefault("post_processing", {})
    stage_claims = post_processing.setdefault("stage_claims", {})
    run_dir = Path(str(state["run_dir"]))
    for stage_id in STAGE_CLAIM_STAGE_IDS:
        stage_claims.setdefault(
            stage_id,
            {"output_path": str(stage_claim_output_path(run_dir, stage_id)), "status": "pending"},
        )
    post_processing.setdefault("claim_extraction", {"output_path": str(claim_output), "status": "pending"})
    post_processing.setdefault("final_artifact", {"output_path": str(final_output), "status": "pending"})


def set_post_processing_status(state: dict[str, object], key: str, status: str) -> None:
    state["post_processing"][key]["status"] = status


def set_stage_claim_status(state: dict[str, object], stage_id: str, status: str) -> None:
    state["post_processing"]["stage_claims"][stage_id]["status"] = status


def build_agent_prompt(stage: StageExecution, run_dir: Path) -> str:
    packet_path = stage_packet_path(run_dir, stage.packet_name)
    output_path = stage_output_path(run_dir, stage.output_name)
    return "\n".join(
        [
            f"STAGE_ID={stage.stage_id}",
            f"OUTPUT_PATH={output_path}",
            f"PROMPT_PACKET={packet_path}",
            "",
            f"Execute workflow stage `{stage.stage_id}`.",
            f"Read the stage instructions from `{packet_path}`.",
            f"Write the completed stage output to `{output_path}`.",
            "Do not leave placeholder content in the output file.",
            "Use upstream stage output artifacts when the prompt packet references them.",
        ]
    )


def resolve_adapter(adapter_name: str) -> CLIAdapter:
    adapter = CLI_ADAPTERS.get(adapter_name)
    if adapter is None:
        supported = ", ".join(sorted(CLI_ADAPTERS))
        raise ValueError(f"Unknown adapter '{adapter_name}'. Supported adapters: {supported}.")
    return adapter


def build_adapter_bin_map(args: argparse.Namespace) -> dict[str, str]:
    return {
        "codex": args.codex_bin,
        "gemini": args.gemini_bin,
        "antigravity": args.antigravity_bin,
    }


def resolve_role_assignments(args: argparse.Namespace) -> dict[str, str]:
    assignments = {
        "primary": args.primary_adapter,
        "secondary": args.secondary_adapter,
    }
    for adapter_name in assignments.values():
        resolve_adapter(adapter_name)
    return assignments


def run_agent_stage(
    stage: StageExecution,
    run_dir: Path,
    job_dir: Path,
    role_assignments: dict[str, str],
    adapter_bins: dict[str, str],
    reporter: ProgressReporter,
) -> tuple[str, str]:
    adapter_name = role_assignments[stage.agent_role]
    adapter = resolve_adapter(adapter_name)
    adapter_bin = adapter_bins[adapter_name]
    reporter.start(adapter.name, stage.stage_id)
    prompt = build_agent_prompt(stage, run_dir)
    output_path = stage_output_path(run_dir, stage.output_name)
    log_path = run_dir / "logs" / f"{stage.stage_id}.{adapter.name}.driver.log"
    cmd = adapter.command_builder(adapter_bin, job_dir, prompt)

    completed = subprocess.run(
        cmd,
        cwd=job_dir,
        capture_output=True,
        text=True,
    )
    recovered_from_stdout = False
    if completed.returncode == 0 and not is_stage_output_complete(output_path):
        recovered_from_stdout = recover_output_from_stdout(adapter, stage.stage_id, output_path, completed.stdout)
    output_exists = output_path.is_file()
    output_complete = is_stage_output_complete(output_path)
    log_path.write_text(
        "\n".join(
            [
                "COMMAND:",
                " ".join(cmd),
                "",
                "RETURN_CODE:",
                str(completed.returncode),
                "",
                "OUTPUT_PATH:",
                str(output_path),
                "",
                "OUTPUT_EXISTS:",
                str(output_exists),
                "",
                "OUTPUT_COMPLETE:",
                str(output_complete),
                "",
                "OUTPUT_RECOVERED_FROM_STDOUT:",
                str(recovered_from_stdout),
                "",
                "OUTPUT_PREVIEW:",
                read_output_preview(output_path),
                "",
                "STDOUT:",
                completed.stdout,
                "",
                "STDERR:",
                completed.stderr,
            ]
        ),
        encoding="utf-8",
    )

    if completed.returncode != 0:
        reporter.fail(adapter.name, stage.stage_id)
        raise RuntimeError(f"Stage {stage.stage_id} failed via {adapter.name}: {completed.stderr.strip()}")
    if not output_complete:
        reporter.fail(adapter.name, stage.stage_id)
        raise RuntimeError(f"Stage {stage.stage_id} did not produce a completed output artifact: {output_path}")
    reporter.complete(adapter.name, stage.stage_id)
    return stage.stage_id, "completed"


def run_stage_claim_extraction(
    stage_id: str,
    run_dir: Path,
    job_dir: Path,
    state: dict[str, object],
    state_path: Path,
    reporter: ProgressReporter,
) -> None:
    if stage_id not in STAGE_CLAIM_STAGE_IDS:
        return
    claim_output = stage_claim_output_path(run_dir, stage_id)
    if state["post_processing"]["stage_claims"][stage_id]["status"] == "completed" and claim_output.is_file():
        reporter.complete("system", f"{stage_id}-claims")
        return

    reporter.start("system", f"{stage_id}-claims")
    set_stage_claim_status(state, stage_id, "running")
    save_state(state_path, state)

    stage_output = next(
        run_dir / "stage-outputs" / str(stage["output"])
        for stage in RUN_STAGES
        if str(stage["id"]) == stage_id
    )
    cmd = [
        sys.executable,
        str(Path(__file__).resolve().parents[1] / "scripts" / "extract_claims.py"),
        "--input",
        str(stage_output),
        "--output",
        str(claim_output),
    ]
    completed = subprocess.run(cmd, cwd=job_dir, capture_output=True, text=True)
    validation_errors: list[str] = []
    if completed.returncode == 0:
        validation_errors = validate_stage_markdown_contract(stage_id, stage_output.read_text(encoding="utf-8"))
    (run_dir / "logs" / f"{stage_id}.claims.driver.log").write_text(
        "\n".join(
            [
                "COMMAND:",
                " ".join(cmd),
                "",
                "STDOUT:",
                completed.stdout,
                "",
                "STDERR:",
                completed.stderr,
                "",
                "VALIDATION_ERRORS:",
                "\n".join(validation_errors) if validation_errors else "<none>",
            ]
        ),
        encoding="utf-8",
    )
    if completed.returncode != 0 or validation_errors:
        set_stage_status(state, stage_id, "failed")
        set_stage_claim_status(state, stage_id, "failed")
        save_state(state_path, state)
        reporter.fail("system", f"{stage_id}-claims")
        details = completed.stderr.strip() or "; ".join(validation_errors)
        if validation_errors and completed.stderr.strip():
            details = completed.stderr.strip() + " " + "; ".join(validation_errors)
        details = details.replace("lacks an external evidence citation", "is an uncited inference or fact")
        raise RuntimeError(f"Stage claim extraction failed for {stage_id}: {details}")

    set_stage_claim_status(state, stage_id, "completed")
    save_state(state_path, state)
    reporter.complete("system", f"{stage_id}-claims")


def run_stage_group(
    stages: list[StageExecution],
    run_dir: Path,
    job_dir: Path,
    state_path: Path,
    state: dict[str, object],
    role_assignments: dict[str, str],
    adapter_bins: dict[str, str],
    reporter: ProgressReporter,
) -> None:
    runnable: list[StageExecution] = []
    for stage in stages:
        if is_stage_output_complete(stage_output_path(run_dir, stage.output_name)):
            set_stage_status(state, stage.stage_id, "completed")
            adapter_name = role_assignments[stage.agent_role]
            reporter.complete(adapter_name, stage.stage_id)
            save_state(state_path, state)
            run_stage_claim_extraction(stage.stage_id, run_dir, job_dir, state, state_path, reporter)
        else:
            runnable.append(stage)
    for stage in runnable:
        set_stage_status(state, stage.stage_id, "running")
    save_state(state_path, state)

    if not runnable:
        return

    with ThreadPoolExecutor(max_workers=len(runnable)) as executor:
        futures = {
            executor.submit(run_agent_stage, stage, run_dir, job_dir, role_assignments, adapter_bins, reporter): stage
            for stage in runnable
        }
        pending_error: Exception | None = None
        for future in as_completed(futures):
            stage = futures[future]
            try:
                stage_id, status = future.result()
                set_stage_status(state, stage_id, status)
                save_state(state_path, state)
                run_stage_claim_extraction(stage_id, run_dir, job_dir, state, state_path, reporter)
            except Exception as exc:
                set_stage_status(state, stage.stage_id, "failed")
                save_state(state_path, state)
                if pending_error is None:
                    pending_error = exc
        if pending_error is not None:
            raise pending_error


def run_extract_claims(
    run_dir: Path,
    job_dir: Path,
    run_id: str,
    claim_output: Path,
    state: dict[str, object],
    state_path: Path,
    reporter: ProgressReporter,
) -> None:
    if claim_output.is_file():
        set_post_processing_status(state, "claim_extraction", "completed")
        save_state(state_path, state)
        reporter.complete("system", "claim-extraction")
        return

    reporter.start("system", "claim-extraction")
    set_post_processing_status(state, "claim_extraction", "running")
    save_state(state_path, state)

    judge_output = run_dir / "stage-outputs" / "06-judge.md"
    cmd = [
        sys.executable,
        str(Path(__file__).resolve().parents[1] / "scripts" / "extract_claims.py"),
        "--input",
        str(judge_output),
        "--output",
        str(claim_output),
        "--strict",
    ]
    completed = subprocess.run(cmd, cwd=job_dir, capture_output=True, text=True)
    (run_dir / "logs" / "claim-extraction.driver.log").write_text(
        "\n".join(["COMMAND:", " ".join(cmd), "", "STDOUT:", completed.stdout, "", "STDERR:", completed.stderr]),
        encoding="utf-8",
    )
    if completed.returncode != 0:
        reporter.fail("system", "claim-extraction")
        raise RuntimeError(f"Claim extraction failed: {completed.stderr.strip()}")
    set_post_processing_status(state, "claim_extraction", "completed")
    save_state(state_path, state)
    reporter.complete("system", "claim-extraction")


def run_final_artifact(
    run_dir: Path,
    job_dir: Path,
    claim_output: Path,
    final_output: Path,
    state: dict[str, object],
    state_path: Path,
    reporter: ProgressReporter,
) -> None:
    if final_output.is_file():
        set_post_processing_status(state, "final_artifact", "completed")
        save_state(state_path, state)
        reporter.complete("system", "final-artifact")
        return

    reporter.start("system", "final-artifact")
    set_post_processing_status(state, "final_artifact", "running")
    save_state(state_path, state)

    judge_output = run_dir / "stage-outputs" / "06-judge.md"
    validate_cmd = [
        sys.executable,
        str(Path(__file__).resolve().parents[1] / "scripts" / "validate_job.py"),
        "--job-dir",
        str(job_dir),
        "--final-artifact-ready",
        "--judge-artifact",
        str(judge_output),
        "--claim-register",
        str(claim_output),
    ]
    validate_result = subprocess.run(validate_cmd, cwd=job_dir, capture_output=True, text=True)
    (run_dir / "logs" / "final-artifact-readiness.driver.log").write_text(
        "\n".join(
            ["COMMAND:", " ".join(validate_cmd), "", "STDOUT:", validate_result.stdout, "", "STDERR:", validate_result.stderr]
        ),
        encoding="utf-8",
    )
    if validate_result.returncode != 0:
        reporter.fail("system", "final-artifact")
        raise RuntimeError(f"Final artifact readiness validation failed: {validate_result.stderr.strip() or validate_result.stdout.strip()}")

    cmd = [
        sys.executable,
        str(Path(__file__).resolve().parents[1] / "scripts" / "generate_final_artifact.py"),
        "--judge-input",
        str(judge_output),
        "--claim-register",
        str(claim_output),
        "--output",
        str(final_output),
    ]
    completed = subprocess.run(cmd, cwd=job_dir, capture_output=True, text=True)
    (run_dir / "logs" / "final-artifact.driver.log").write_text(
        "\n".join(["COMMAND:", " ".join(cmd), "", "STDOUT:", completed.stdout, "", "STDERR:", completed.stderr]),
        encoding="utf-8",
    )
    if completed.returncode != 0:
        reporter.fail("system", "final-artifact")
        raise RuntimeError(f"Final artifact generation failed: {completed.stderr.strip()}")
    set_post_processing_status(state, "final_artifact", "completed")
    save_state(state_path, state)
    reporter.complete("system", "final-artifact")


def main() -> int:
    args = parse_args()
    reporter = ProgressReporter(sys.stdout)
    try:
        role_assignments = resolve_role_assignments(args)
        adapter_bins = build_adapter_bin_map(args)
        job_name, job_dir = resolve_job_path(
            job_name=args.job_name,
            job_id=args.job_id,
            job_path=args.job_path,
            jobs_root=Path(args.jobs_root).expanduser(),
            jobs_index_root=Path(args.jobs_index_root).expanduser(),
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    run_dir = job_dir / "runs" / args.run_id
    if not run_dir.exists():
        scaffold_run(job_name, job_dir, args.run_id)

    claim_output = Path(args.claim_output).expanduser() if args.claim_output else job_dir / "evidence" / f"claims-{args.run_id}.json"
    final_output = Path(args.final_output).expanduser() if args.final_output else job_dir / "outputs" / f"final-{args.run_id}.md"
    claim_output.parent.mkdir(parents=True, exist_ok=True)
    final_output.parent.mkdir(parents=True, exist_ok=True)

    state_path = run_dir / "workflow-state.json"
    state = load_state(state_path)
    ensure_post_processing_state(state, claim_output, final_output)
    save_state(state_path, state)
    already_complete = all(
        is_stage_output_complete(stage_output_path(run_dir, stage["expected_output_target"].split("/")[-1]))
        for stage in state["stages"]
    ) and claim_output.is_file() and final_output.is_file()

    try:
        for group in EXECUTION_PLAN:
            run_stage_group(group, run_dir, job_dir, state_path, state, role_assignments, adapter_bins, reporter)

        run_extract_claims(run_dir, job_dir, args.run_id, claim_output, state, state_path, reporter)
        run_final_artifact(run_dir, job_dir, claim_output, final_output, state, state_path, reporter)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if already_complete:
        print(f"Workflow already complete for run {args.run_id}")
    else:
        print(str(run_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

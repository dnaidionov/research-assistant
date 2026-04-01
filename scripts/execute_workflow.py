#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from _adapter_qualification import (
    STRUCTURED_TRUST_LEVELS,
    classify_adapter_qualification,
    persist_adapter_qualification,
    profile_for_required_trust,
    trust_satisfies,
)
from _job_config import load_execution_config, load_yaml_document
from _provider_runtime import (
    apply_provider_runtime_policy,
    record_provider_qualification,
    record_provider_repair_attempt,
    record_provider_stage_result,
)
from _stage_contracts import (
    build_claim_map_from_stage_json,
    is_structured_stage,
    load_json as load_contract_json,
    merge_stage_substep_payloads,
    merge_source_registry,
    persist_source_registry,
    render_stage_markdown_from_json,
    sanitize_claim_pass_payload,
    source_registry_path,
    source_registry_placeholder,
    stage_structured_output_path,
    validate_claim_pass_payload,
    validate_source_pass_payload,
)
from _intake_contracts import (
    merge_intake_substep_payloads,
    sanitize_intake_fact_lineage_payload,
    sanitize_intake_normalization_payload,
    sanitize_intake_sources_payload,
    validate_intake_fact_lineage_payload,
    validate_intake_normalization_payload,
    validate_intake_payload,
    validate_intake_sources_payload,
)
from _usage_telemetry import (
    append_usage_record,
    build_manual_usage_record,
    build_usage_record,
    finish_operation,
    timed_operation_bounds,
    utc_now_iso,
)
from _stage_validation import validate_structured_stage_artifact
from _workflow_lib import write_json
from _workflow_state import (
    append_workflow_event,
    derive_workflow_state_from_events,
    initial_stage_substeps,
)
from run_workflow import RUN_STAGES, resolve_job_path, scaffold_run


DEFAULT_CODEX_BIN = "codex"
DEFAULT_GEMINI_BIN = "gemini"
DEFAULT_ANTIGRAVITY_BIN = "antigravity"
DEFAULT_CLAUDE_BIN = "claude"
DEFAULT_GEMINI_MODEL = "gemini-3.1-pro-preview"
DEFAULT_JOBS_INDEX_ROOT = Path(__file__).resolve().parents[1] / "jobs-index"
STAGE_CLAIM_STAGE_IDS = {"research-a", "research-b", "critique-a-on-b", "critique-b-on-a", "judge"}
INCREMENTAL_RUN_ID_PATTERN = re.compile(r"^run-(\d+)$")
DEFAULT_REQUIRED_PROVIDER_TRUST = "structured_safe_smoke"


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
YELLOW = "\x1b[33m"
RESET = "\x1b[0m"


@dataclass(frozen=True)
class CLIAdapter:
    name: str
    command_builder: Callable[[str, Path, str, str | None], list[str]]
    stdout_materialization: set[str] = field(default_factory=set)
    supports_model_selection: bool = False


@dataclass(frozen=True)
class StageAdapterSelection:
    adapter_name: str
    model: str | None = None
    provider_name: str | None = None


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str
    started_at: str | None = None
    finished_at: str | None = None
    duration_ms: int | None = None
    prompt_chars: int | None = None
    prompt_bytes: int | None = None
    stdout_bytes: int | None = None
    stderr_bytes: int | None = None
    usage_status: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


class StageCancelledError(RuntimeError):
    pass


class SubstepExecutionError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        command_result: CommandResult,
        repair_attempted: bool = False,
        repair_result: CommandResult | None = None,
    ) -> None:
        super().__init__(message)
        self.command_result = command_result
        self.repair_attempted = repair_attempted
        self.repair_result = repair_result


class StageProcessController:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._processes: dict[str, subprocess.Popen[str]] = {}
        self._cancelled: set[str] = set()

    def register(self, stage_id: str, process: subprocess.Popen[str]) -> None:
        with self._lock:
            self._processes[stage_id] = process

    def unregister(self, stage_id: str, process: subprocess.Popen[str]) -> None:
        with self._lock:
            if self._processes.get(stage_id) is process:
                self._processes.pop(stage_id, None)

    def mark_cancelled(self, stage_id: str) -> None:
        with self._lock:
            self._cancelled.add(stage_id)

    def is_cancelled(self, stage_id: str) -> bool:
        with self._lock:
            return stage_id in self._cancelled

    def cancel_others(self, failing_stage_id: str) -> None:
        with self._lock:
            targets = [
                (stage_id, process)
                for stage_id, process in self._processes.items()
                if stage_id != failing_stage_id and process.poll() is None
            ]
            for stage_id, _ in targets:
                self._cancelled.add(stage_id)

        for _, process in targets:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                continue

        deadline = time.time() + 0.5
        for _, process in targets:
            remaining = max(0.0, deadline - time.time())
            try:
                process.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    continue


def build_codex_command(binary: str, job_dir: Path, prompt: str, model: str | None = None) -> list[str]:
    return [binary, "exec", "--full-auto", "-C", str(job_dir), prompt]


def build_gemini_command(binary: str, job_dir: Path, prompt: str, model: str | None = None) -> list[str]:
    return [binary, "--model", model or DEFAULT_GEMINI_MODEL, "-p", prompt, "-y", "--output-format", "text"]


def build_antigravity_command(binary: str, job_dir: Path, prompt: str, model: str | None = None) -> list[str]:
    return [binary, "chat", "--mode", "agent", "--yes", prompt]


def build_claude_command(binary: str, job_dir: Path, prompt: str, model: str | None = None) -> list[str]:
    command = [binary]
    if model:
        command.extend(["--model", model])
    command.extend(["-p", "--output-format", "text", "--permission-mode", "bypassPermissions", prompt])
    return command


CLI_ADAPTERS: dict[str, CLIAdapter] = {
    "codex": CLIAdapter(name="codex", command_builder=build_codex_command),
    "gemini": CLIAdapter(
        name="gemini",
        command_builder=build_gemini_command,
        stdout_materialization={"markdown", "structured_json"},
        supports_model_selection=True,
    ),
    "antigravity": CLIAdapter(
        name="antigravity",
        command_builder=build_antigravity_command,
        stdout_materialization={"markdown", "structured_json"},
    ),
    "claude": CLIAdapter(
        name="claude",
        command_builder=build_claude_command,
        stdout_materialization={"markdown", "structured_json"},
        supports_model_selection=True,
    ),
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

    def cancel(self, actor: str, stage_id: str) -> None:
        with self.lock:
            message = f"{actor}: {stage_id} cancelled"
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
        if line.endswith(" cancelled"):
            return line[: -len("cancelled")] + f"{YELLOW}cancelled{RESET}"
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
        description="Execute the current 2-pass research workflow using CLI adapters with structured contracts for research and judge stages."
    )
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--job-name", help="Job name to resolve via jobs-index or jobs root.")
    target.add_argument("--job-id", help="Job id to resolve via jobs-index metadata or jobs root.")
    target.add_argument("--job-path", help="Explicit path to the target job repository.")
    parser.add_argument("--run-id", help="Run identifier to execute or create. Defaults to the next incremental run id such as run-001.")
    parser.add_argument("--jobs-root", default=str(Path.home() / "Projects" / "research-hub" / "jobs"))
    parser.add_argument("--jobs-index-root", default=str(DEFAULT_JOBS_INDEX_ROOT))
    parser.add_argument("--primary-adapter", default="codex", help="Adapter name for the primary execution role.")
    parser.add_argument("--secondary-adapter", default="gemini", help="Adapter name for the secondary execution role.")
    parser.add_argument("--codex-bin", default=DEFAULT_CODEX_BIN, help="Path to the Codex CLI.")
    parser.add_argument("--gemini-bin", default=DEFAULT_GEMINI_BIN, help="Path to the Gemini CLI.")
    parser.add_argument("--antigravity-bin", default=DEFAULT_ANTIGRAVITY_BIN, help="Path to the Antigravity CLI.")
    parser.add_argument("--claude-bin", default=DEFAULT_CLAUDE_BIN, help="Path to the Claude CLI.")
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
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return derive_workflow_state_from_events(path.parent)


def next_incremental_run_id(job_dir: Path) -> str:
    runs_dir = job_dir / "runs"
    if not runs_dir.is_dir():
        return "run-001"
    max_index = 0
    for candidate in runs_dir.iterdir():
        match = INCREMENTAL_RUN_ID_PATTERN.match(candidate.name)
        if match is None:
            continue
        max_index = max(max_index, int(match.group(1)))
    return f"run-{max_index + 1:03d}"


def confirm_existing_run(run_id: str, run_dir: Path, input_stream: object = sys.stdin, output_stream: object = sys.stdout) -> None:
    output_stream.write(f"Run {run_id} already exists at {run_dir}. Continue? [y/N]: ")
    output_stream.flush()
    response = getattr(input_stream, "readline", lambda: "")()
    if response is None or response == "":
        raise ValueError(f"Confirmation required to continue existing run {run_id}.")
    if response.strip().lower() not in {"y", "yes"}:
        raise ValueError(f"Aborted by user for existing run {run_id}.")


def recompute_run_status(state: dict[str, object]) -> str:
    stage_statuses = [str(stage.get("status", "pending")) for stage in state.get("stages", []) if isinstance(stage, dict)]
    post_processing = state.get("post_processing", {})
    post_statuses: list[str] = []
    if isinstance(post_processing, dict):
        for key, value in post_processing.items():
            if key == "stage_claims" and isinstance(value, dict):
                for stage_claim in value.values():
                    if isinstance(stage_claim, dict):
                        post_statuses.append(str(stage_claim.get("status", "pending")))
            elif isinstance(value, dict):
                post_statuses.append(str(value.get("status", "pending")))

    all_statuses = stage_statuses + post_statuses
    if any(status in {"failed", "cancelled"} for status in all_statuses):
        return "failed"
    if any(status == "running" for status in all_statuses):
        return "running"
    if all_statuses and all(status == "completed" for status in all_statuses):
        return "completed"
    if any(status == "completed" for status in all_statuses):
        return "running"
    return "scaffolded"


def save_state(path: Path, payload: dict[str, object]) -> None:
    payload["status"] = recompute_run_status(payload)
    write_json(path, payload)
    append_workflow_event(path.parent, "state_checkpoint", state=payload)


def apply_state_update(
    state_lock: threading.RLock,
    state_path: Path,
    state: dict[str, object],
    update_fn: Callable[[], None],
) -> None:
    with state_lock:
        update_fn()
        save_state(state_path, state)


def is_placeholder_content(content: str) -> bool:
    lowered = content.lower()
    return "not_started" in lowered or "status: not started" in lowered or "stage output placeholder" in lowered


def is_stage_output_complete(path: Path) -> bool:
    if not path.is_file():
        return False
    return not is_placeholder_content(path.read_text(encoding="utf-8"))


def is_stage_execution_complete(run_dir: Path, stage: StageExecution) -> bool:
    if not is_stage_output_complete(stage_output_path(run_dir, stage.output_name)):
        return False
    if not is_structured_stage(stage.stage_id):
        return True
    return is_json_artifact_complete(stage_structured_output_path(run_dir, stage.stage_id))


def read_output_preview(path: Path, max_chars: int = 400) -> str:
    if not path.is_file():
        return "<missing>"
    content = path.read_text(encoding="utf-8")
    preview = content[:max_chars]
    if len(content) > max_chars:
        preview += "\n...[truncated]"
    return preview


def is_json_artifact_complete(path: Path) -> bool:
    if not path.is_file():
        return False
    return not is_placeholder_content(path.read_text(encoding="utf-8"))


def expected_first_heading(stage_id: str) -> str | None:
    return {
        "research-a": "# Executive Summary",
        "research-b": "# Executive Summary",
        "critique-a-on-b": "# Claims That Survive Review",
        "critique-b-on-a": "# Claims That Survive Review",
        "judge": "# Supported Conclusions",
    }.get(stage_id)


def build_adapter_executor(adapter_name: str, adapter_bin: Path | str, artifact_kind: str) -> Callable[..., CommandResult]:
    adapter = resolve_adapter(adapter_name)
    if artifact_kind not in {"markdown", "structured_json"}:
        raise ValueError(f"Unsupported artifact kind: {artifact_kind}")
    if artifact_kind not in adapter.stdout_materialization and adapter.name != "codex":
        raise ValueError(
            f"Adapter '{adapter_name}' does not support deterministic {artifact_kind} materialization."
        )

    def executor(
        cmd: list[str],
        *,
        job_dir: Path,
        output_path: Path,
        stage_id: str,
        prompt_text: str | None = None,
        process_controller: StageProcessController | None = None,
    ) -> CommandResult:
        result = execute_adapter_command(
            cmd,
            job_dir=job_dir,
            stage_id=stage_id,
            prompt_text=prompt_text,
            process_controller=process_controller,
        )
        if result.returncode != 0:
            return result
        if artifact_kind == "markdown":
            if not is_stage_output_complete(output_path):
                output_path.write_text(result.stdout, encoding="utf-8")
            return result
        if not is_json_artifact_complete(output_path):
            stripped = result.stdout.strip()
            if not stripped:
                return result
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError:
                return result
            write_json(output_path, payload)
        return result

    return executor


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


def stage_substep_output_path(run_dir: Path, stage_id: str, substep: str) -> Path:
    substeps_dir = run_dir / "audit" / "substeps"
    substeps_dir.mkdir(parents=True, exist_ok=True)
    return substeps_dir / f"{stage_id}.{substep}.json"


def stage_substep_markdown_path(run_dir: Path, stage_id: str, substep: str) -> Path:
    substeps_dir = run_dir / "audit" / "substeps"
    substeps_dir.mkdir(parents=True, exist_ok=True)
    return substeps_dir / f"{stage_id}.{substep}.md"


def dependency_structured_payloads(stage_id: str, run_dir: Path) -> list[dict[str, object]]:
    payloads: list[dict[str, object]] = []
    stage_map = {str(stage["id"]): stage for stage in RUN_STAGES}
    stage = stage_map.get(stage_id)
    if stage is None:
        return payloads
    for dependency_stage_id in stage.get("depends_on", []):
        if not is_structured_stage(str(dependency_stage_id)):
            continue
        structured_path = stage_structured_output_path(run_dir, str(dependency_stage_id))
        if structured_path.is_file():
            payloads.append(load_contract_json(structured_path))
    return payloads


def merge_stage_sources_into_registry(stage_id: str, run_dir: Path) -> None:
    source_path = source_registry_path(run_dir)
    source_registry = load_contract_json(source_path)
    payload = load_contract_json(stage_structured_output_path(run_dir, stage_id))
    merged = merge_source_registry(source_registry, list(payload.get("sources", [])))
    persist_source_registry(source_path, merged)


def merge_intake_sources_into_registry(run_dir: Path) -> None:
    source_path = source_registry_path(run_dir)
    source_registry = load_contract_json(source_path)
    intake_payload = load_contract_json(stage_output_path(run_dir, "01-intake.json"))
    merged = merge_source_registry(source_registry, list(intake_payload.get("sources", [])))
    persist_source_registry(source_path, merged)


def set_stage_status(state: dict[str, object], stage_id: str, status: str) -> None:
    for stage in state["stages"]:
        if stage["id"] == stage_id:
            stage["status"] = status
            return
    raise KeyError(f"Unknown stage id: {stage_id}")


def set_stage_substep_status(state: dict[str, object], stage_id: str, substep: str, status: str) -> None:
    for stage in state["stages"]:
        if stage["id"] == stage_id:
            substeps = stage.setdefault("substeps", initial_stage_substeps(stage_id))
            if not isinstance(substeps, dict):
                substeps = initial_stage_substeps(stage_id)
                stage["substeps"] = substeps
            entry = substeps.setdefault(substep, {"status": "pending"})
            entry["status"] = status
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


def append_command_usage_record(
    *,
    run_dir: Path,
    scope: str,
    stage_id: str,
    provider_key: str,
    adapter: str,
    model: str | None,
    result: CommandResult,
    status: str,
    prompt_text: str | None,
    failure_reason: str | None = None,
    substep: str | None = None,
    attempt_index: int = 1,
) -> None:
    started_at = result.started_at or utc_now_iso()
    finished_at = result.finished_at or started_at
    duration_ms = result.duration_ms or 0
    record = build_usage_record(
        scope=scope,
        stage_id=stage_id,
        status=status,
        provider_key=provider_key,
        adapter=adapter,
        model=model,
        started_at=started_at,
        finished_at=finished_at,
        duration_ms=duration_ms,
        prompt_text=prompt_text,
        stdout=result.stdout,
        stderr=result.stderr,
        attempt_index=attempt_index,
        failure_reason=failure_reason,
        substep=substep,
        usage_status=result.usage_status,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        total_tokens=result.total_tokens,
    )
    append_usage_record(run_dir, record)


def append_manual_stage_usage_record(
    *,
    run_dir: Path,
    scope: str,
    stage_id: str,
    status: str,
    provider_key: str,
    adapter: str,
    model: str | None,
    started_at: str,
    finished_at: str,
    failure_reason: str | None = None,
    substep: str | None = None,
) -> None:
    append_usage_record(
        run_dir,
        build_manual_usage_record(
            scope=scope,
            stage_id=stage_id,
            status=status,
            provider_key=provider_key,
            adapter=adapter,
            model=model,
            started_at=started_at,
            finished_at=finished_at,
            failure_reason=failure_reason,
            substep=substep,
        ),
    )


def execution_snapshot_path(run_dir: Path) -> Path:
    return run_dir / "audit" / "execution-config.json"


def serialize_stage_selection(selection: StageAdapterSelection) -> dict[str, object]:
    return {
        "provider_key": selection.provider_name or selection.adapter_name,
        "adapter": selection.adapter_name,
        "model": selection.model,
    }


def stable_payload_sha256(payload: object) -> str:
    normalized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def build_execution_snapshot(
    *,
    job_dir: Path,
    run_dir: Path,
    args: argparse.Namespace,
    execution_config: dict[str, object] | None,
    provider_catalog: dict[str, StageAdapterSelection],
    configured_stage_assignments: dict[str, StageAdapterSelection],
    resolved_stage_assignments: dict[str, StageAdapterSelection],
    stage_required_trust: dict[str, str],
    runtime_policy: dict[str, object] | None,
) -> dict[str, object]:
    config_path = job_dir / "config.yaml"
    snapshot = {
        "schema_version": 1,
        "run_id": run_dir.name,
        "job_dir": str(job_dir.resolve()),
        "config_path": str(config_path.resolve()),
        "config_source": "job_config" if execution_config is not None else "fallback_cli",
        "execution_config": execution_config,
        "provider_catalog": {
            provider_key: serialize_stage_selection(selection)
            for provider_key, selection in sorted(provider_catalog.items())
        },
        "configured_stage_assignments": {
            stage_id: serialize_stage_selection(selection)
            for stage_id, selection in sorted(configured_stage_assignments.items())
        },
        "resolved_stage_assignments": {
            stage_id: serialize_stage_selection(selection)
            for stage_id, selection in sorted(resolved_stage_assignments.items())
        },
        "stage_required_provider_trust": dict(sorted(stage_required_trust.items())),
        "provider_runtime_policy": runtime_policy,
    }
    if execution_config is not None:
        snapshot["execution_config_sha256"] = stable_payload_sha256(execution_config)
    else:
        fallback_cli_adapters = {
            "primary_adapter": args.primary_adapter,
            "secondary_adapter": args.secondary_adapter,
        }
        snapshot["fallback_cli_adapters"] = fallback_cli_adapters
        snapshot["execution_config_sha256"] = stable_payload_sha256(fallback_cli_adapters)
    return snapshot


def persist_execution_snapshot(
    *,
    run_dir: Path,
    snapshot: dict[str, object],
) -> dict[str, object]:
    path = execution_snapshot_path(run_dir)
    if path.is_file():
        existing = json.loads(path.read_text(encoding="utf-8"))
        if existing != snapshot:
            raise ValueError(
                "Execution configuration snapshot mismatch for existing run. "
                "This run was already started with a different resolved provider/model configuration."
            )
        return existing
    write_json(path, snapshot)
    append_workflow_event(run_dir, "execution_config_resolved", snapshot_path=str(path.relative_to(run_dir)), **snapshot)
    return snapshot


def transition_stage_status(run_dir: Path, state: dict[str, object], stage_id: str, status: str) -> None:
    state_status = "running" if status == "started" else status
    for stage in state["stages"]:
        if stage["id"] == stage_id and stage.get("status") == state_status:
            return
    set_stage_status(state, stage_id, state_status)
    append_workflow_event(run_dir, f"stage_{status}", stage_id=stage_id)


def transition_substep_status(run_dir: Path, state: dict[str, object], stage_id: str, substep: str, status: str) -> None:
    state_status = "running" if status == "started" else status
    for stage in state["stages"]:
        if stage["id"] == stage_id:
            substeps = stage.setdefault("substeps", initial_stage_substeps(stage_id))
            if isinstance(substeps, dict) and isinstance(substeps.get(substep), dict) and substeps[substep].get("status") == state_status:
                return
    set_stage_substep_status(state, stage_id, substep, state_status)
    append_workflow_event(run_dir, f"substep_{status}", stage_id=stage_id, substep=substep)


def transition_post_processing_status(
    run_dir: Path,
    state: dict[str, object],
    key: str,
    status: str,
    *,
    stage_id: str | None = None,
) -> None:
    state_status = "running" if status == "started" else status
    if key == "stage_claims":
        if state["post_processing"]["stage_claims"].get(stage_id or "", {}).get("status") == state_status:
            return
    elif state["post_processing"].get(key, {}).get("status") == state_status:
        return
    if key == "stage_claims":
        set_stage_claim_status(state, stage_id or "", state_status)
    else:
        set_post_processing_status(state, key, state_status)
    payload: dict[str, object] = {"key": key}
    if stage_id is not None:
        payload["stage_id"] = stage_id
    append_workflow_event(run_dir, f"post_processing_{status}", **payload)


def build_agent_prompt(stage: StageExecution, run_dir: Path) -> str:
    packet_path = stage_packet_path(run_dir, stage.packet_name)
    output_path = stage_output_path(run_dir, stage.output_name)
    json_output_path = stage_structured_output_path(run_dir, stage.stage_id) if is_structured_stage(stage.stage_id) else None
    sources_path = source_registry_path(run_dir)
    return "\n".join(
        [
            f"STAGE_ID={stage.stage_id}",
            f"OUTPUT_PATH={output_path}",
            f"OUTPUT_JSON_PATH={json_output_path}" if json_output_path is not None else "OUTPUT_JSON_PATH=not_applicable",
            f"SOURCE_REGISTRY_PATH={sources_path}",
            f"PROMPT_PACKET={packet_path}",
            "",
            f"Execute workflow stage `{stage.stage_id}`.",
            f"Read the stage instructions from `{packet_path}`.",
            f"Write the completed stage output to `{output_path}`.",
            (
                f"Write the completed structured JSON output to `{json_output_path}`."
                if json_output_path is not None
                else "This stage does not require a structured JSON artifact."
            ),
            f"Use `{sources_path}` as the run-level source registry reference only. Do not modify that file directly.",
            "Do not leave placeholder content in the output file.",
            "Use upstream stage output artifacts when the prompt packet references them.",
            "Evidence is never obvious. Every fact and world-claim inference must carry explicit evidence support on that exact item; nearby citations do not count.",
        ]
    )


def intake_source_materials(job_dir: Path) -> tuple[str, str]:
    brief_path = job_dir / "brief.md"
    config_path = job_dir / "config.yaml"
    brief_text = brief_path.read_text(encoding="utf-8") if brief_path.is_file() else ""
    config_text = config_path.read_text(encoding="utf-8") if config_path.is_file() else ""
    return brief_text, config_text


def build_intake_source_prompt(job_dir: Path, run_dir: Path, output_json_path: Path, scratch_markdown_path: Path) -> str:
    brief_text, config_text = intake_source_materials(job_dir)
    return "\n".join(
        [
            "STAGE_ID=intake",
            "SUBSTEP=source-pass",
            f"OUTPUT_PATH={output_json_path}",
            f"OUTPUT_JSON_PATH={output_json_path}",
            "",
            "Execute only the source declaration pass for intake.",
            "Return JSON only.",
            'Allowed JSON shape: {"stage": "intake", "sources": [...]}',
            "Define only canonical job_input sources for the provided materials you actually used.",
            "Do not emit facts, inferences, or normalization fields.",
            "",
            "SOURCE MATERIALS:",
            "### brief.md",
            brief_text,
            "",
            "### config.yaml",
            config_text,
        ]
    )


def build_intake_fact_prompt(
    job_dir: Path,
    run_dir: Path,
    source_output_path: Path,
    output_json_path: Path,
    scratch_markdown_path: Path,
) -> str:
    brief_text, config_text = intake_source_materials(job_dir)
    return "\n".join(
        [
            "STAGE_ID=intake",
            "SUBSTEP=fact-lineage",
            f"OUTPUT_PATH={output_json_path}",
            f"OUTPUT_JSON_PATH={output_json_path}",
            f"SOURCE_PASS_PATH={source_output_path}",
            "",
            "Execute only the direct fact-lineage pass for intake.",
            "Return JSON only.",
            'Allowed JSON shape: {"stage": "intake", "known_facts": [...]}',
            "Use only the source IDs defined in SOURCE_PASS_PATH.",
            "known_facts must contain only directly stated brief/config facts with source_ids, source_excerpt, and source_anchor.",
            "Do not emit assumptions, constraints, missing information, or working inferences.",
            "",
            "SOURCE MATERIALS:",
            "### brief.md",
            brief_text,
            "",
            "### config.yaml",
            config_text,
        ]
    )


def build_intake_normalization_prompt(
    job_dir: Path,
    run_dir: Path,
    fact_output_path: Path,
    output_json_path: Path,
    scratch_markdown_path: Path,
) -> str:
    brief_text, config_text = intake_source_materials(job_dir)
    return "\n".join(
        [
            "STAGE_ID=intake",
            "SUBSTEP=normalization",
            f"OUTPUT_PATH={output_json_path}",
            f"OUTPUT_JSON_PATH={output_json_path}",
            f"FACT_LINEAGE_PATH={fact_output_path}",
            "",
            "Execute only the intake normalization pass.",
            "Return JSON only.",
            'Allowed JSON shape: {"stage": "intake", "question": ..., "scope": [...], "constraints": [...], "assumptions": [...], "missing_information": [...], "required_artifacts": [...], "notes_for_researchers": [...], "working_inferences": [...], "uncertainty_notes": [...]}',
            "Do not repeat known_facts here. Use FACT_LINEAGE_PATH only to avoid restating direct facts as working_inferences.",
            "Keep assumptions, missing information, and working inferences separate from direct facts.",
            "",
            "SOURCE MATERIALS:",
            "### brief.md",
            brief_text,
            "",
            "### config.yaml",
            config_text,
        ]
    )


def build_source_pass_prompt(stage: StageExecution, run_dir: Path, source_output_path: Path, scratch_markdown_path: Path) -> str:
    packet_path = stage_packet_path(run_dir, stage.packet_name)
    sources_path = source_registry_path(run_dir)
    return "\n".join(
        [
            f"STAGE_ID={stage.stage_id}",
            "SUBSTEP=source-pass",
            f"OUTPUT_PATH={scratch_markdown_path}",
            f"OUTPUT_JSON_PATH={source_output_path}",
            f"SOURCE_REGISTRY_PATH={sources_path}",
            f"PROMPT_PACKET={packet_path}",
            "",
            f"Execute only the source pass for workflow stage `{stage.stage_id}`.",
            f"Read the full stage instructions from `{packet_path}`.",
            f"Write JSON to `{source_output_path}`.",
            "Return only the structured source payload for this stage.",
            "Required JSON shape:",
            '{"stage": "<stage-id>", "sources": [...]}',
            "Do not write claims, summaries, conclusions, or markdown in the authoritative JSON output for this substep.",
            "Retain exact source locators. Evidence is never obvious.",
        ]
    )


def build_claim_pass_prompt(
    stage: StageExecution,
    run_dir: Path,
    source_output_path: Path,
    claim_output_path: Path,
    scratch_markdown_path: Path,
) -> str:
    packet_path = stage_packet_path(run_dir, stage.packet_name)
    sources_path = source_registry_path(run_dir)
    return "\n".join(
        [
            f"STAGE_ID={stage.stage_id}",
            "SUBSTEP=claim-pass",
            f"OUTPUT_PATH={scratch_markdown_path}",
            f"OUTPUT_JSON_PATH={claim_output_path}",
            f"SOURCE_PASS_PATH={source_output_path}",
            f"SOURCE_REGISTRY_PATH={sources_path}",
            f"PROMPT_PACKET={packet_path}",
            "",
            f"Execute only the claim pass for workflow stage `{stage.stage_id}`.",
            f"Read the full stage instructions from `{packet_path}`.",
            f"Read the validated stage-local sources from `{source_output_path}` and use only those source IDs.",
            f"Write JSON to `{claim_output_path}`.",
            "Return the structured claim payload for this stage without a sources list; the runner will attach validated sources separately.",
            "Evidence is never obvious. Every fact and world-claim inference must carry explicit evidence on that exact item; nearby citations do not count.",
        ]
    )


def build_substep_repair_prompt(
    stage: StageExecution,
    *,
    run_dir: Path,
    substep: str,
    output_json_path: Path,
    validation_errors: list[str],
    scratch_markdown_path: Path,
    source_output_path: Path | None = None,
) -> str:
    packet_path = stage_packet_path(run_dir, stage.packet_name)
    sources_path = source_registry_path(run_dir)
    current_json = output_json_path.read_text(encoding="utf-8") if output_json_path.is_file() else "<missing>"
    prompt_lines = [
        f"STAGE_ID={stage.stage_id}",
        f"SUBSTEP={substep}",
        "REPAIR_ATTEMPT=1",
        f"OUTPUT_PATH={scratch_markdown_path}",
        f"OUTPUT_JSON_PATH={output_json_path}",
        f"SOURCE_REGISTRY_PATH={sources_path}",
        f"PROMPT_PACKET={packet_path}",
        "",
        f"Repair only the `{substep}` output for workflow stage `{stage.stage_id}`.",
        "Do not perform fresh research. Fix structure and support only.",
        "Evidence is never obvious. Nearby citations do not count.",
    ]
    if source_output_path is not None:
        prompt_lines.append(f"SOURCE_PASS_PATH={source_output_path}")
    prompt_lines.extend(
        [
            "",
            "VALIDATION_ERRORS:",
            *validation_errors,
            "",
            "CURRENT_STRUCTURED_OUTPUT:",
            current_json,
        ]
    )
    return "\n".join(prompt_lines)


def build_repair_prompt(
    stage: StageExecution,
    run_dir: Path,
    validation_errors: list[str],
) -> str:
    packet_path = stage_packet_path(run_dir, stage.packet_name)
    output_path = stage_output_path(run_dir, stage.output_name)
    json_output_path = stage_structured_output_path(run_dir, stage.stage_id) if is_structured_stage(stage.stage_id) else None
    sources_path = source_registry_path(run_dir)
    markdown_content = output_path.read_text(encoding="utf-8") if output_path.is_file() else "<missing>"
    json_content = (
        json_output_path.read_text(encoding="utf-8")
        if json_output_path is not None and json_output_path.is_file()
        else "<missing>"
    )
    return "\n".join(
        [
            f"STAGE_ID={stage.stage_id}",
            "REPAIR_ATTEMPT=1",
            f"OUTPUT_PATH={output_path}",
            f"OUTPUT_JSON_PATH={json_output_path}" if json_output_path is not None else "OUTPUT_JSON_PATH=not_applicable",
            f"SOURCE_REGISTRY_PATH={sources_path}",
            f"PROMPT_PACKET={packet_path}",
            "",
            f"Repair workflow stage `{stage.stage_id}`.",
            "Do not perform new research or reinterpret the task.",
            "Repair only the existing stage artifacts so they satisfy the contract.",
            "Evidence is never obvious. Every fact and world-claim inference must carry explicit evidence support on that exact item; nearby citations do not count.",
            "Keep source IDs canonical and keep local claim references only in claim_dependencies.",
            "",
            "VALIDATION_ERRORS:",
            *validation_errors,
            "",
            "CURRENT_MARKDOWN_ARTIFACT:",
            markdown_content,
            "",
            "CURRENT_STRUCTURED_ARTIFACT:",
            json_content,
        ]
    )


def execute_adapter_command(
    cmd: list[str],
    *,
    job_dir: Path,
    stage_id: str,
    prompt_text: str | None = None,
    process_controller: StageProcessController | None = None,
) -> CommandResult:
    started_monotonic, started_at = timed_operation_bounds()
    process = subprocess.Popen(
        cmd,
        cwd=job_dir,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    if process_controller is not None:
        process_controller.register(stage_id, process)
    try:
        stdout, stderr = process.communicate()
    finally:
        if process_controller is not None:
            process_controller.unregister(stage_id, process)
    finished_at, duration_ms = finish_operation(started_monotonic)
    usage_record = build_usage_record(
        scope="stage",
        stage_id=stage_id,
        status="completed" if process.returncode == 0 else "failed",
        provider_key="<unknown>",
        adapter="<unknown>",
        model=None,
        started_at=started_at,
        finished_at=finished_at,
        duration_ms=duration_ms,
        prompt_text=prompt_text,
        stdout=stdout,
        stderr=stderr,
        failure_reason=stderr.strip() or None if process.returncode != 0 else None,
    )
    return CommandResult(
        returncode=process.returncode,
        stdout=stdout,
        stderr=stderr,
        started_at=started_at,
        finished_at=finished_at,
        duration_ms=duration_ms,
        prompt_chars=usage_record["prompt_chars"],
        prompt_bytes=usage_record["prompt_bytes"],
        stdout_bytes=usage_record["stdout_bytes"],
        stderr_bytes=usage_record["stderr_bytes"],
        usage_status=usage_record["usage_status"],
        input_tokens=usage_record["input_tokens"],
        output_tokens=usage_record["output_tokens"],
        total_tokens=usage_record["total_tokens"],
    )


def execute_json_substep(
    *,
    stage: StageExecution,
    substep: str,
    provider_key: str,
    adapter: CLIAdapter,
    adapter_bin: str,
    job_dir: Path,
    run_dir: Path,
    output_json_path: Path,
    prompt: str,
    model: str | None,
    process_controller: StageProcessController | None,
    validator: Callable[[dict[str, object]], list[str]],
    repair_prompt_builder: Callable[[list[str]], str],
    sanitizer: Callable[[dict[str, object]], dict[str, object]] | None = None,
) -> tuple[CommandResult, dict[str, object], bool, CommandResult | None, list[str]]:
    repair_attempted = False
    repair_result: CommandResult | None = None
    attempt_records: list[dict[str, object]] = []
    executor = build_adapter_executor(adapter.name, adapter_bin, "structured_json")
    result = executor(
        adapter.command_builder(adapter_bin, job_dir, prompt, model),
        job_dir=job_dir,
        output_path=output_json_path,
        stage_id=stage.stage_id,
        prompt_text=prompt,
        process_controller=process_controller,
    )

    def load_and_validate(command_result: CommandResult) -> tuple[dict[str, object] | None, list[str], bool]:
        if command_result.returncode != 0:
            return None, [], False
        if not is_json_artifact_complete(output_json_path):
            return None, [
                f"Stage {stage.stage_id} did not produce a completed output artifact: {output_json_path}; completed structured output artifact is missing."
            ], False
        try:
            payload = load_contract_json(output_json_path)
        except (ValueError, json.JSONDecodeError) as exc:
            return None, [str(exc)], False
        if sanitizer is not None:
            payload = sanitizer(payload)
            write_json(output_json_path, payload)
        validation_errors = validator(payload)
        return payload, validation_errors, True

    def queue_attempt_record(
        *,
        command_result: CommandResult,
        status: str,
        prompt_text: str,
        failure_reason: str | None,
        attempt_index: int,
    ) -> None:
        attempt_records.append(
            {
                "result": command_result,
                "status": status,
                "prompt_text": prompt_text,
                "failure_reason": failure_reason,
                "attempt_index": attempt_index,
            }
        )

    def flush_attempt_records() -> None:
        for record in attempt_records:
            append_command_usage_record(
                run_dir=run_dir,
                scope="stage",
                stage_id=stage.stage_id,
                provider_key=provider_key,
                adapter=adapter.name,
                model=model,
                result=record["result"],
                status=record["status"],
                prompt_text=record["prompt_text"],
                failure_reason=record["failure_reason"],
                substep=substep,
                attempt_index=record["attempt_index"],
            )

    payload, validation_errors, repairable = load_and_validate(result)
    queue_attempt_record(
        command_result=result,
        status="completed" if result.returncode == 0 and not validation_errors else "failed",
        prompt_text=prompt,
        failure_reason=None if result.returncode == 0 and not validation_errors else (result.stderr.strip() or "; ".join(validation_errors) or "validation failed"),
        attempt_index=1,
    )
    if result.returncode == 0 and validation_errors and repairable:
        repair_attempted = True
        repair_prompt = repair_prompt_builder(validation_errors)
        repair_result = executor(
            adapter.command_builder(adapter_bin, job_dir, repair_prompt, model),
            job_dir=job_dir,
            output_path=output_json_path,
            stage_id=stage.stage_id,
            prompt_text=repair_prompt,
            process_controller=process_controller,
        )
        result = repair_result
        payload, validation_errors, _ = load_and_validate(repair_result)
        queue_attempt_record(
            command_result=repair_result,
            status="completed" if repair_result.returncode == 0 and not validation_errors else "failed",
            prompt_text=repair_prompt,
            failure_reason=None if repair_result.returncode == 0 and not validation_errors else (repair_result.stderr.strip() or "; ".join(validation_errors) or "validation failed"),
            attempt_index=2,
        )

    if process_controller is not None and process_controller.is_cancelled(stage.stage_id):
        marker = "cancelled_due_to_parallel_stage_failure"
        if marker not in result.stderr:
            result = CommandResult(result.returncode, result.stdout, result.stderr + ("\n" if result.stderr else "") + marker)
        if repair_result is None:
            attempt_records = [
                {
                    "result": result,
                    "status": "cancelled",
                    "prompt_text": prompt,
                    "failure_reason": marker,
                    "attempt_index": 1,
                }
            ]
        else:
            last_attempt = attempt_records[-1]
            last_attempt["result"] = result
            last_attempt["status"] = "cancelled"
            last_attempt["failure_reason"] = marker
        flush_attempt_records()
        raise StageCancelledError(f"Stage {stage.stage_id} cancelled due to parallel stage failure.")

    flush_attempt_records()

    if result.returncode != 0:
        raise SubstepExecutionError(
            f"{substep} failed via {adapter.name}: {result.stderr.strip()}",
            command_result=result,
            repair_attempted=repair_attempted,
            repair_result=repair_result,
        )
    if payload is None or validation_errors:
        raise SubstepExecutionError(
            f"{substep} failed validation: {'; '.join(validation_errors)}",
            command_result=result,
            repair_attempted=repair_attempted,
            repair_result=repair_result,
        )
    return result, payload, repair_attempted, repair_result, validation_errors


def run_intake_stage(
    stage: StageExecution,
    run_dir: Path,
    job_dir: Path,
    state: dict[str, object],
    state_path: Path,
    state_lock: threading.RLock,
    stage_selection: StageAdapterSelection,
    adapter: CLIAdapter,
    adapter_bin: str,
    reporter: ProgressReporter,
    process_controller: StageProcessController | None,
) -> tuple[str, str]:
    reporter.start(adapter.name, stage.stage_id)
    stage_started_monotonic, stage_started_at = timed_operation_bounds()
    output_path = stage_output_path(run_dir, stage.output_name)
    source_output_path = stage_substep_output_path(run_dir, stage.stage_id, "source-pass")
    fact_output_path = stage_substep_output_path(run_dir, stage.stage_id, "fact-lineage")
    normalization_output_path = stage_substep_output_path(run_dir, stage.stage_id, "normalization")
    source_scratch_path = stage_substep_markdown_path(run_dir, stage.stage_id, "source-pass")
    fact_scratch_path = stage_substep_markdown_path(run_dir, stage.stage_id, "fact-lineage")
    normalization_scratch_path = stage_substep_markdown_path(run_dir, stage.stage_id, "normalization")
    provider_key = stage_selection.provider_name or stage_selection.adapter_name
    stage_failure_reason: str | None = None
    stage_status = "completed"

    def try_resume_sources() -> tuple[bool, dict[str, object] | None]:
        if not is_json_artifact_complete(source_output_path):
            return False, None
        payload = sanitize_intake_sources_payload(load_contract_json(source_output_path))
        write_json(source_output_path, payload)
        if validate_intake_sources_payload(payload):
            return False, None
        return True, payload

    def try_resume_fact_lineage(sources_payload: dict[str, object]) -> tuple[bool, dict[str, object] | None]:
        if not is_json_artifact_complete(fact_output_path):
            return False, None
        payload = sanitize_intake_fact_lineage_payload(load_contract_json(fact_output_path))
        write_json(fact_output_path, payload)
        if validate_intake_fact_lineage_payload(payload, sources_payload):
            return False, None
        return True, payload

    def try_resume_normalization(fact_payload: dict[str, object]) -> tuple[bool, dict[str, object] | None]:
        if not is_json_artifact_complete(normalization_output_path):
            return False, None
        payload = sanitize_intake_normalization_payload(load_contract_json(normalization_output_path))
        write_json(normalization_output_path, payload)
        if validate_intake_normalization_payload(payload, fact_payload):
            return False, None
        return True, payload

    if is_json_artifact_complete(output_path):
        final_payload = load_contract_json(output_path)
        if not validate_intake_payload(final_payload):
            reporter.complete(adapter.name, stage.stage_id)
            return stage.stage_id, "completed"

    source_prompt = build_intake_source_prompt(job_dir, run_dir, source_output_path, source_scratch_path)
    fact_prompt = build_intake_fact_prompt(job_dir, run_dir, source_output_path, fact_output_path, fact_scratch_path)
    normalization_prompt = build_intake_normalization_prompt(
        job_dir,
        run_dir,
        fact_output_path,
        normalization_output_path,
        normalization_scratch_path,
    )

    try:
        resumed_sources, sources_payload = try_resume_sources()
        if resumed_sources:
            apply_state_update(
                state_lock,
                state_path,
                state,
                lambda: transition_substep_status(run_dir, state, stage.stage_id, "source-pass", "completed"),
            )
        else:
            apply_state_update(
                state_lock,
                state_path,
                state,
                lambda: transition_substep_status(run_dir, state, stage.stage_id, "source-pass", "started"),
            )
            _result, sources_payload, repair_attempted, _repair_result, _errors = execute_json_substep(
                stage=stage,
                substep="source-pass",
                provider_key=provider_key,
                adapter=adapter,
                adapter_bin=adapter_bin,
                job_dir=job_dir,
                run_dir=run_dir,
                output_json_path=source_output_path,
                prompt=source_prompt,
                model=stage_selection.model,
                process_controller=process_controller,
                validator=validate_intake_sources_payload,
                sanitizer=sanitize_intake_sources_payload,
                repair_prompt_builder=lambda errors: "\n".join(
                    [
                        "STAGE_ID=intake",
                        "SUBSTEP=source-pass",
                        "REPAIR_ATTEMPT=1",
                        f"OUTPUT_PATH={source_output_path}",
                        f"OUTPUT_JSON_PATH={source_output_path}",
                        "",
                        "Repair only the intake source declaration output.",
                        "Do not invent new sources or emit non-source fields.",
                        "",
                        "VALIDATION_ERRORS:",
                        *errors,
                    ]
                ),
            )
            if repair_attempted:
                record_provider_repair_attempt(job_dir, provider_key, stage_id=stage.stage_id, run_id=run_dir.name)
            apply_state_update(
                state_lock,
                state_path,
                state,
                lambda: transition_substep_status(run_dir, state, stage.stage_id, "source-pass", "completed"),
            )

        resumed_facts, fact_payload = try_resume_fact_lineage(sources_payload)
        if resumed_facts:
            apply_state_update(
                state_lock,
                state_path,
                state,
                lambda: transition_substep_status(run_dir, state, stage.stage_id, "fact-lineage", "completed"),
            )
        else:
            apply_state_update(
                state_lock,
                state_path,
                state,
                lambda: transition_substep_status(run_dir, state, stage.stage_id, "fact-lineage", "started"),
            )
            _result, fact_payload, repair_attempted, _repair_result, _errors = execute_json_substep(
                stage=stage,
                substep="fact-lineage",
                provider_key=provider_key,
                adapter=adapter,
                adapter_bin=adapter_bin,
                job_dir=job_dir,
                run_dir=run_dir,
                output_json_path=fact_output_path,
                prompt=fact_prompt,
                model=stage_selection.model,
                process_controller=process_controller,
                validator=lambda payload: validate_intake_fact_lineage_payload(payload, sources_payload),
                sanitizer=sanitize_intake_fact_lineage_payload,
                repair_prompt_builder=lambda errors: "\n".join(
                    [
                        "STAGE_ID=intake",
                        "SUBSTEP=fact-lineage",
                        "REPAIR_ATTEMPT=1",
                        f"OUTPUT_PATH={fact_output_path}",
                        f"OUTPUT_JSON_PATH={fact_output_path}",
                        f"SOURCE_PASS_PATH={source_output_path}",
                        "",
                        "Repair only the intake fact-lineage output.",
                        "Keep only directly grounded known_facts with source_ids, source_excerpt, and source_anchor.",
                        "",
                        "VALIDATION_ERRORS:",
                        *errors,
                    ]
                ),
            )
            if repair_attempted:
                record_provider_repair_attempt(job_dir, provider_key, stage_id=stage.stage_id, run_id=run_dir.name)
            apply_state_update(
                state_lock,
                state_path,
                state,
                lambda: transition_substep_status(run_dir, state, stage.stage_id, "fact-lineage", "completed"),
            )

        resumed_normalization, normalization_payload = try_resume_normalization(fact_payload)
        if resumed_normalization:
            apply_state_update(
                state_lock,
                state_path,
                state,
                lambda: transition_substep_status(run_dir, state, stage.stage_id, "normalization", "completed"),
            )
        else:
            apply_state_update(
                state_lock,
                state_path,
                state,
                lambda: transition_substep_status(run_dir, state, stage.stage_id, "normalization", "started"),
            )
            _result, normalization_payload, repair_attempted, _repair_result, _errors = execute_json_substep(
                stage=stage,
                substep="normalization",
                provider_key=provider_key,
                adapter=adapter,
                adapter_bin=adapter_bin,
                job_dir=job_dir,
                run_dir=run_dir,
                output_json_path=normalization_output_path,
                prompt=normalization_prompt,
                model=stage_selection.model,
                process_controller=process_controller,
                validator=lambda payload: validate_intake_normalization_payload(payload, fact_payload),
                sanitizer=sanitize_intake_normalization_payload,
                repair_prompt_builder=lambda errors: "\n".join(
                    [
                        "STAGE_ID=intake",
                        "SUBSTEP=normalization",
                        "REPAIR_ATTEMPT=1",
                        f"OUTPUT_PATH={normalization_output_path}",
                        f"OUTPUT_JSON_PATH={normalization_output_path}",
                        f"FACT_LINEAGE_PATH={fact_output_path}",
                        "",
                        "Repair only the intake normalization output.",
                        "Do not duplicate known_facts. Keep direct facts out of working_inferences.",
                        "",
                        "VALIDATION_ERRORS:",
                        *errors,
                    ]
                ),
            )
            if repair_attempted:
                record_provider_repair_attempt(job_dir, provider_key, stage_id=stage.stage_id, run_id=run_dir.name)
            apply_state_update(
                state_lock,
                state_path,
                state,
                lambda: transition_substep_status(run_dir, state, stage.stage_id, "normalization", "completed"),
            )

        apply_state_update(
            state_lock,
            state_path,
            state,
            lambda: transition_substep_status(run_dir, state, stage.stage_id, "merge", "started"),
        )
        merge_started_at = utc_now_iso()
        merged_payload = merge_intake_substep_payloads(sources_payload, fact_payload, normalization_payload)
        validation_errors = validate_intake_payload(merged_payload)
        if validation_errors:
            merge_failed_at = utc_now_iso()
            append_manual_stage_usage_record(
                run_dir=run_dir,
                scope="stage",
                stage_id=stage.stage_id,
                status="failed",
                provider_key=provider_key,
                adapter=adapter.name,
                model=stage_selection.model,
                started_at=merge_started_at,
                finished_at=merge_failed_at,
                failure_reason="; ".join(validation_errors),
                substep="merge",
            )
            apply_state_update(
                state_lock,
                state_path,
                state,
                lambda: transition_substep_status(run_dir, state, stage.stage_id, "merge", "failed"),
            )
            raise RuntimeError(f"intake validation failed: {'; '.join(validation_errors)}")
        write_json(output_path, merged_payload)
        apply_state_update(
            state_lock,
            state_path,
            state,
            lambda: transition_substep_status(run_dir, state, stage.stage_id, "merge", "completed"),
        )
        merge_finished_at = utc_now_iso()
        append_manual_stage_usage_record(
            run_dir=run_dir,
            scope="stage",
            stage_id=stage.stage_id,
            status="completed",
            provider_key=provider_key,
            adapter=adapter.name,
            model=stage_selection.model,
            started_at=merge_started_at,
            finished_at=merge_finished_at,
            substep="merge",
        )
        reporter.complete(adapter.name, stage.stage_id)
        return stage.stage_id, "completed"
    except SubstepExecutionError as exc:
        stage_failure_reason = str(exc)
        stage_status = "failed"
        raise RuntimeError(str(exc)) from exc
    except Exception as exc:
        stage_failure_reason = str(exc)
        stage_status = "failed"
        raise
    finally:
        stage_finished_at, _stage_duration_ms = finish_operation(stage_started_monotonic)
        append_manual_stage_usage_record(
            run_dir=run_dir,
            scope="stage",
            stage_id=stage.stage_id,
            status=stage_status,
            provider_key=provider_key,
            adapter=adapter.name,
            model=stage_selection.model,
            started_at=stage_started_at,
            finished_at=stage_finished_at,
            failure_reason=stage_failure_reason,
        )


def run_structured_stage(
    stage: StageExecution,
    run_dir: Path,
    job_dir: Path,
    state: dict[str, object],
    state_path: Path,
    state_lock: threading.RLock,
    stage_selection: StageAdapterSelection,
    adapter: CLIAdapter,
    adapter_bin: str,
    reporter: ProgressReporter,
    process_controller: StageProcessController | None,
) -> tuple[str, str]:
    reporter.start(adapter.name, stage.stage_id)
    stage_started_monotonic, stage_started_at = timed_operation_bounds()
    provider_key = stage_selection.provider_name or stage_selection.adapter_name
    output_path = stage_output_path(run_dir, stage.output_name)
    structured_output_path = stage_structured_output_path(run_dir, stage.stage_id)
    source_output_path = stage_substep_output_path(run_dir, stage.stage_id, "source-pass")
    claim_output_path = stage_substep_output_path(run_dir, stage.stage_id, "claim-pass")
    source_scratch_path = stage_substep_markdown_path(run_dir, stage.stage_id, "source-pass")
    claim_scratch_path = stage_substep_markdown_path(run_dir, stage.stage_id, "claim-pass")
    source_registry_file = source_registry_path(run_dir)
    source_registry_snapshot = source_registry_file.read_text(encoding="utf-8") if source_registry_file.is_file() else json.dumps({"sources": []})
    source_registry_restored = False

    source_prompt = build_source_pass_prompt(stage, run_dir, source_output_path, source_scratch_path)
    source_result: CommandResult | None = None
    source_payload: dict[str, object] | None = None
    source_repair_attempted = False
    source_repair_result: CommandResult | None = None
    claim_result: CommandResult | None = None
    claim_repair_attempted = False
    claim_repair_result: CommandResult | None = None
    structured_validation_errors: list[str] = []
    structured_validation_warnings: list[str] = []
    markdown_validation_errors: list[str] = []
    cancellation_marker = ""
    source_pass_resumed = False
    claim_pass_resumed = False
    stage_status = "completed"
    stage_failure_reason: str | None = None

    def restore_source_registry() -> None:
        nonlocal source_registry_restored
        if source_registry_file.is_file() and source_registry_file.read_text(encoding="utf-8") != source_registry_snapshot:
            source_registry_file.write_text(source_registry_snapshot, encoding="utf-8")
            source_registry_restored = True

    def try_resume_source_pass() -> tuple[bool, dict[str, object] | None]:
        if not is_json_artifact_complete(source_output_path):
            return False, None
        try:
            payload = load_contract_json(source_output_path)
        except (ValueError, json.JSONDecodeError):
            return False, None
        if validate_source_pass_payload(stage.stage_id, payload):
            return False, None
        return True, payload

    def validate_combined_claim_payload(source_payload_value: dict[str, object]) -> tuple[dict[str, object], object]:
        claim_payload = sanitize_claim_pass_payload(stage.stage_id, load_contract_json(claim_output_path))
        merged_payload = merge_stage_substep_payloads(stage.stage_id, source_payload_value, claim_payload)
        validation = validate_structured_stage_artifact(
            stage.stage_id,
            merged_payload,
            json.loads(source_registry_snapshot),
            render_stage_markdown_from_json(stage.stage_id, merged_payload),
            dependency_structured_payloads(stage.stage_id, run_dir),
        )
        return merged_payload, validation

    def try_resume_claim_pass(source_payload_value: dict[str, object]) -> tuple[bool, dict[str, object] | None, object | None]:
        if not is_json_artifact_complete(claim_output_path):
            return False, None, None
        try:
            claim_payload = load_contract_json(claim_output_path)
        except (ValueError, json.JSONDecodeError):
            return False, None, None
        if validate_claim_pass_payload(stage.stage_id, claim_payload):
            return False, None, None
        merged_payload, validation = validate_combined_claim_payload(source_payload_value)
        if validation.structured_errors or validation.markdown_errors:
            return False, None, None
        return True, merged_payload, validation

    try:
        if is_json_artifact_complete(structured_output_path) and is_stage_output_complete(output_path):
            final_payload = load_contract_json(structured_output_path)
            final_validation = validate_structured_stage_artifact(
                stage.stage_id,
                final_payload,
                json.loads(source_registry_snapshot),
                output_path.read_text(encoding="utf-8"),
                dependency_structured_payloads(stage.stage_id, run_dir),
            )
            if not final_validation.structured_errors and not final_validation.markdown_errors:
                reporter.complete(adapter.name, stage.stage_id)
                return stage.stage_id, "completed"

        resumed, resumed_source_payload = try_resume_source_pass()
        if resumed:
            source_pass_resumed = True
            source_payload = resumed_source_payload
            apply_state_update(
                state_lock,
                state_path,
                state,
                lambda: transition_substep_status(run_dir, state, stage.stage_id, "source-pass", "completed"),
            )
        else:
            apply_state_update(
                state_lock,
                state_path,
                state,
                lambda: transition_substep_status(run_dir, state, stage.stage_id, "source-pass", "started"),
            )
            try:
                source_result, source_payload, source_repair_attempted, source_repair_result, _ = execute_json_substep(
                    stage=stage,
                    substep="source-pass",
                    provider_key=provider_key,
                    adapter=adapter,
                    adapter_bin=adapter_bin,
                    job_dir=job_dir,
                    run_dir=run_dir,
                    output_json_path=source_output_path,
                    prompt=source_prompt,
                    model=stage_selection.model,
                    process_controller=process_controller,
                    validator=lambda payload: validate_source_pass_payload(stage.stage_id, payload),
                    repair_prompt_builder=lambda errors: build_substep_repair_prompt(
                        stage,
                        run_dir=run_dir,
                        substep="source-pass",
                        output_json_path=source_output_path,
                        validation_errors=errors,
                        scratch_markdown_path=source_scratch_path,
                    ),
                )
                if source_repair_attempted:
                    record_provider_repair_attempt(job_dir, provider_key, stage_id=stage.stage_id, run_id=run_dir.name)
            except SubstepExecutionError as exc:
                source_result = exc.command_result
                source_repair_attempted = exc.repair_attempted
                source_repair_result = exc.repair_result
                if source_repair_attempted:
                    record_provider_repair_attempt(job_dir, provider_key, stage_id=stage.stage_id, run_id=run_dir.name)
                apply_state_update(
                    state_lock,
                    state_path,
                    state,
                    lambda: transition_substep_status(run_dir, state, stage.stage_id, "source-pass", "failed"),
                )
                raise RuntimeError(str(exc)) from exc
            restore_source_registry()
            apply_state_update(
                state_lock,
                state_path,
                state,
                lambda: transition_substep_status(run_dir, state, stage.stage_id, "source-pass", "completed"),
            )

        resumed_claim, merged_payload, validation = (False, None, None)
        if source_pass_resumed:
            resumed_claim, merged_payload, validation = try_resume_claim_pass(source_payload)
        if resumed_claim:
            claim_pass_resumed = True
            apply_state_update(
                state_lock,
                state_path,
                state,
                lambda: transition_substep_status(run_dir, state, stage.stage_id, "claim-pass", "completed"),
            )
        else:
            apply_state_update(
                state_lock,
                state_path,
                state,
                lambda: transition_substep_status(run_dir, state, stage.stage_id, "claim-pass", "started"),
            )
            claim_prompt = build_claim_pass_prompt(stage, run_dir, source_output_path, claim_output_path, claim_scratch_path)
            try:
                claim_result, _claim_payload, claim_repair_attempted, claim_repair_result, _ = execute_json_substep(
                    stage=stage,
                    substep="claim-pass",
                    provider_key=provider_key,
                    adapter=adapter,
                    adapter_bin=adapter_bin,
                    job_dir=job_dir,
                    run_dir=run_dir,
                    output_json_path=claim_output_path,
                    prompt=claim_prompt,
                    model=stage_selection.model,
                    process_controller=process_controller,
                    validator=lambda payload: validate_claim_pass_payload(stage.stage_id, payload),
                    repair_prompt_builder=lambda errors: build_substep_repair_prompt(
                        stage,
                        run_dir=run_dir,
                        substep="claim-pass",
                        output_json_path=claim_output_path,
                        validation_errors=errors,
                        scratch_markdown_path=claim_scratch_path,
                        source_output_path=source_output_path,
                    ),
                )
                if claim_repair_attempted:
                    record_provider_repair_attempt(job_dir, provider_key, stage_id=stage.stage_id, run_id=run_dir.name)
            except SubstepExecutionError as exc:
                claim_result = exc.command_result
                claim_repair_attempted = exc.repair_attempted
                claim_repair_result = exc.repair_result
                if claim_repair_attempted:
                    record_provider_repair_attempt(job_dir, provider_key, stage_id=stage.stage_id, run_id=run_dir.name)
                apply_state_update(
                    state_lock,
                    state_path,
                    state,
                    lambda: transition_substep_status(run_dir, state, stage.stage_id, "claim-pass", "failed"),
                )
                raise RuntimeError(str(exc)) from exc
            restore_source_registry()
            merged_payload, validation = validate_combined_claim_payload(source_payload)

        structured_validation_errors = validation.structured_errors
        structured_validation_warnings = validation.structured_warnings
        markdown_validation_errors = validation.markdown_errors
        if structured_validation_errors or markdown_validation_errors:
            claim_repair_attempted = True
            record_provider_repair_attempt(job_dir, provider_key, stage_id=stage.stage_id, run_id=run_dir.name)
            repair_prompt = build_substep_repair_prompt(
                stage,
                    run_dir=run_dir,
                    substep="claim-pass",
                    output_json_path=claim_output_path,
                    validation_errors=[*structured_validation_errors, *markdown_validation_errors],
                    scratch_markdown_path=claim_scratch_path,
                    source_output_path=source_output_path,
                )
            claim_repair_result = execute_adapter_command(
                adapter.command_builder(adapter_bin, job_dir, repair_prompt, stage_selection.model),
                job_dir=job_dir,
                stage_id=stage.stage_id,
                prompt_text=repair_prompt,
                process_controller=process_controller,
            )
            restore_source_registry()
            if not is_json_artifact_complete(claim_output_path):
                if process_controller is not None and process_controller.is_cancelled(stage.stage_id):
                    marker = "cancelled_due_to_parallel_stage_failure"
                    cancellation_marker = marker
                    if marker not in claim_repair_result.stderr:
                        claim_repair_result = CommandResult(
                            claim_repair_result.returncode,
                            claim_repair_result.stdout,
                            claim_repair_result.stderr + ("\n" if claim_repair_result.stderr else "") + marker,
                        )
                    apply_state_update(
                        state_lock,
                        state_path,
                        state,
                        lambda: transition_substep_status(run_dir, state, stage.stage_id, "claim-pass", "cancelled"),
                    )
                    raise StageCancelledError(f"Stage {stage.stage_id} cancelled due to parallel stage failure.")
                apply_state_update(
                    state_lock,
                    state_path,
                    state,
                    lambda: transition_substep_status(run_dir, state, stage.stage_id, "claim-pass", "failed"),
                )
                raise RuntimeError(
                    f"claim-pass repair did not produce a completed structured output artifact: {claim_output_path}"
                )
            if claim_repair_result.returncode != 0:
                apply_state_update(
                    state_lock,
                    state_path,
                    state,
                    lambda: transition_substep_status(run_dir, state, stage.stage_id, "claim-pass", "failed"),
                )
                raise RuntimeError(f"claim-pass failed via {adapter.name}: {claim_repair_result.stderr.strip()}")
            merged_payload, validation = validate_combined_claim_payload(source_payload)
            structured_validation_errors = validation.structured_errors
            structured_validation_warnings = validation.structured_warnings
            markdown_validation_errors = validation.markdown_errors
        if structured_validation_errors:
            apply_state_update(
                state_lock,
                state_path,
                state,
                lambda: transition_substep_status(run_dir, state, stage.stage_id, "claim-pass", "failed"),
            )
            details = "; ".join(structured_validation_errors)
            details = re.sub(
                r"inferences\[\d+\] must include at least one evidence source\.",
                "uncited inference detected in structured stage output.",
                details,
                flags=re.IGNORECASE,
            )
            details = re.sub(
                r"facts\[\d+\] must include at least one evidence source\.",
                "uncited fact detected in structured stage output.",
                details,
                flags=re.IGNORECASE,
            )
            raise RuntimeError(f"Stage {stage.stage_id} failed structured validation: {details}")
        if markdown_validation_errors:
            apply_state_update(
                state_lock,
                state_path,
                state,
                lambda: transition_substep_status(run_dir, state, stage.stage_id, "claim-pass", "failed"),
            )
            raise RuntimeError(f"Stage {stage.stage_id} failed markdown contract validation: {'; '.join(markdown_validation_errors)}")

        apply_state_update(
            state_lock,
            state_path,
            state,
            lambda: (
                transition_substep_status(run_dir, state, stage.stage_id, "claim-pass", "completed"),
                transition_substep_status(run_dir, state, stage.stage_id, "render", "started"),
            ),
        )
        render_started_at = utc_now_iso()
        write_json(structured_output_path, validation.normalized_payload)
        output_path.write_text(validation.canonical_markdown, encoding="utf-8")
        apply_state_update(
            state_lock,
            state_path,
            state,
            lambda: transition_substep_status(run_dir, state, stage.stage_id, "render", "completed"),
        )
        render_finished_at = utc_now_iso()
        append_manual_stage_usage_record(
            run_dir=run_dir,
            scope="stage",
            stage_id=stage.stage_id,
            status="completed",
            provider_key=provider_key,
            adapter=adapter.name,
            model=stage_selection.model,
            started_at=render_started_at,
            finished_at=render_finished_at,
            substep="render",
        )
        reporter.complete(adapter.name, stage.stage_id)
        return stage.stage_id, "completed"
    except StageCancelledError:
        cancellation_marker = "cancelled_due_to_parallel_stage_failure"
        stage_status = "cancelled"
        stage_failure_reason = "cancelled_due_to_parallel_stage_failure"
        apply_state_update(
            state_lock,
            state_path,
            state,
            lambda: transition_substep_status(run_dir, state, stage.stage_id, "render", "cancelled"),
        )
        reporter.cancel(adapter.name, stage.stage_id)
        raise
    except Exception as exc:
        stage_status = "failed"
        stage_failure_reason = str(exc)
        with state_lock:
            render_running = False
            for stage_state in state["stages"]:
                if stage_state["id"] == stage.stage_id:
                    render_entry = stage_state.get("substeps", {}).get("render", {})
                    render_running = isinstance(render_entry, dict) and render_entry.get("status") == "running"
                    break
        if render_running:
            render_failed_at = utc_now_iso()
            append_manual_stage_usage_record(
                run_dir=run_dir,
                scope="stage",
                stage_id=stage.stage_id,
                status="failed",
                provider_key=provider_key,
                adapter=adapter.name,
                model=stage_selection.model,
                started_at=stage_started_at,
                finished_at=render_failed_at,
                failure_reason="render failed",
                substep="render",
            )
            apply_state_update(
                state_lock,
                state_path,
                state,
                lambda: transition_substep_status(run_dir, state, stage.stage_id, "render", "failed"),
            )
        reporter.fail(adapter.name, stage.stage_id)
        raise
    finally:
        stage_finished_at, _stage_duration_ms = finish_operation(stage_started_monotonic)
        append_manual_stage_usage_record(
            run_dir=run_dir,
            scope="stage",
            stage_id=stage.stage_id,
            status=stage_status,
            provider_key=provider_key,
            adapter=adapter.name,
            model=stage_selection.model,
            started_at=stage_started_at,
            finished_at=stage_finished_at,
            failure_reason=stage_failure_reason,
        )
        log_path = run_dir / "logs" / f"{stage.stage_id}.{adapter.name}.driver.log"
        log_path.write_text(
            "\n".join(
                [
                    "COMMAND:",
                    "<decomposed-structured-stage>",
                    "",
                    "RETURN_CODE:",
                    str(source_result.returncode) if source_result is not None else (str(claim_result.returncode) if claim_result is not None else "<not-run>"),
                    "",
                    "SOURCE_PASS_COMMAND:",
                    " ".join(adapter.command_builder(adapter_bin, job_dir, source_prompt, stage_selection.model)),
                    "",
                    "SOURCE_PASS_RETURN_CODE:",
                    str(source_result.returncode) if source_result is not None else ("<resumed>" if source_pass_resumed else "<not-run>"),
                    "",
                    "SOURCE_PASS_REPAIR_ATTEMPTED:",
                    str(source_repair_attempted),
                    "",
                    "SOURCE_PASS_REPAIR_RETURN_CODE:",
                    str(source_repair_result.returncode) if source_repair_result is not None else "<not-run>",
                    "",
                    "CLAIM_PASS_COMMAND:",
                    " ".join(
                        adapter.command_builder(
                            adapter_bin,
                            job_dir,
                            build_claim_pass_prompt(stage, run_dir, source_output_path, claim_output_path, claim_scratch_path),
                            stage_selection.model,
                        )
                    ),
                    "",
                    "CLAIM_PASS_RETURN_CODE:",
                    str(claim_result.returncode) if claim_result is not None else ("<resumed>" if claim_pass_resumed else "<not-run>"),
                    "",
                    "CLAIM_PASS_REPAIR_ATTEMPTED:",
                    str(claim_repair_attempted),
                    "",
                    "CLAIM_PASS_REPAIR_RETURN_CODE:",
                    str(claim_repair_result.returncode) if claim_repair_result is not None else "<not-run>",
                    "",
                    "REPAIR_ATTEMPTED:",
                    str(source_repair_attempted or claim_repair_attempted),
                    "",
                    "REPAIR_RETURN_CODE:",
                    str(claim_repair_result.returncode)
                    if claim_repair_result is not None
                    else (str(source_repair_result.returncode) if source_repair_result is not None else "<not-run>"),
                    "",
                    "OUTPUT_PATH:",
                    str(output_path),
                    "",
                    "OUTPUT_EXISTS:",
                    str(output_path.is_file()),
                    "",
                    "OUTPUT_COMPLETE:",
                    str(is_stage_output_complete(output_path)),
                    "",
                    "STRUCTURED_OUTPUT_PATH:",
                    str(structured_output_path),
                    "",
                    "STRUCTURED_OUTPUT_EXISTS:",
                    str(structured_output_path.is_file()),
                    "",
                    "STRUCTURED_OUTPUT_COMPLETE:",
                    str(is_json_artifact_complete(structured_output_path)),
                    "",
                    "STRUCTURED_OUTPUT_PREVIEW:",
                    read_output_preview(structured_output_path),
                    "",
                    "SOURCE_REGISTRY_RESTORED_AFTER_STAGE:",
                    str(source_registry_restored),
                    "",
                    "STRUCTURED_VALIDATION_ERRORS:",
                    "\n".join(structured_validation_errors) if structured_validation_errors else "<none>",
                    "",
                    "STRUCTURED_VALIDATION_WARNINGS:",
                    "\n".join(structured_validation_warnings) if structured_validation_warnings else "<none>",
                    "",
                    "MARKDOWN_VALIDATION_ERRORS:",
                    "\n".join(markdown_validation_errors) if markdown_validation_errors else "<none>",
                    "",
                    "OUTPUT_PREVIEW:",
                    read_output_preview(output_path),
                    "",
                    "SOURCE_PASS_STDOUT:",
                    source_result.stdout if source_result is not None else "",
                    "",
                    "SOURCE_PASS_STDERR:",
                    source_result.stderr if source_result is not None else cancellation_marker,
                    "",
                    "CLAIM_PASS_STDOUT:",
                    claim_result.stdout if claim_result is not None else "",
                    "",
                    "CLAIM_PASS_STDERR:",
                    claim_result.stderr if claim_result is not None else cancellation_marker,
                ]
            ),
            encoding="utf-8",
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
        "claude": args.claude_bin,
    }


def resolve_role_assignments(args: argparse.Namespace) -> dict[str, str]:
    assignments = {
        "primary": args.primary_adapter,
        "secondary": args.secondary_adapter,
    }
    for adapter_name in assignments.values():
        resolve_adapter(adapter_name)
    return assignments


def build_default_stage_assignments(args: argparse.Namespace) -> dict[str, StageAdapterSelection]:
    role_assignments = resolve_role_assignments(args)
    return {
        stage.stage_id: StageAdapterSelection(adapter_name=role_assignments[stage.agent_role], provider_name=stage.agent_role)
        for group in EXECUTION_PLAN
        for stage in group
    }


def load_provider_catalog_from_job_config(job_dir: Path) -> dict[str, StageAdapterSelection] | None:
    execution = load_execution_config(job_dir)
    if execution is None:
        return None
    providers = execution.get("providers")
    stage_providers = execution.get("stage_providers")
    if providers is None and stage_providers is None:
        return None
    if not isinstance(providers, dict) or not isinstance(stage_providers, dict):
        raise ValueError("workflow.execution must define mapping values for both providers and stage_providers.")

    provider_configs: dict[str, StageAdapterSelection] = {}
    for provider_name, raw_provider in providers.items():
        if not isinstance(provider_name, str) or not isinstance(raw_provider, dict):
            raise ValueError("workflow.execution.providers must be a mapping of provider names to provider settings.")
        adapter_name = raw_provider.get("adapter")
        model_name = raw_provider.get("model")
        if not isinstance(adapter_name, str) or not adapter_name:
            raise ValueError(f"workflow.execution.providers.{provider_name} must define a non-empty adapter.")
        adapter = resolve_adapter(adapter_name)
        if model_name is not None and not isinstance(model_name, str):
            raise ValueError(f"workflow.execution.providers.{provider_name}.model must be a string when provided.")
        if model_name and not adapter.supports_model_selection:
            raise ValueError(
                f"Adapter '{adapter_name}' does not support explicit model selection in workflow.execution.providers.{provider_name}."
            )
        provider_configs[provider_name] = StageAdapterSelection(
            adapter_name=adapter_name,
            model=model_name,
            provider_name=provider_name,
        )

    expected_stage_ids = [stage["id"] for stage in RUN_STAGES]
    missing_stage_ids = [stage_id for stage_id in expected_stage_ids if stage_id not in stage_providers]
    unknown_stage_ids = [stage_id for stage_id in stage_providers if stage_id not in expected_stage_ids]
    if missing_stage_ids:
        raise ValueError(
            "workflow.execution.stage_providers is missing stage assignments for: " + ", ".join(sorted(missing_stage_ids))
        )
    if unknown_stage_ids:
        raise ValueError(
            "workflow.execution.stage_providers contains unknown stage IDs: " + ", ".join(sorted(unknown_stage_ids))
        )

    return provider_configs


def load_stage_assignments_from_job_config(job_dir: Path) -> dict[str, StageAdapterSelection] | None:
    execution = load_execution_config(job_dir)
    if execution is None:
        return None
    provider_configs = load_provider_catalog_from_job_config(job_dir)
    stage_providers = execution.get("stage_providers")
    if provider_configs is None or not isinstance(stage_providers, dict):
        return None
    stage_assignments: dict[str, StageAdapterSelection] = {}
    for stage_id, provider_name in stage_providers.items():
        if not isinstance(provider_name, str) or provider_name not in provider_configs:
            raise ValueError(
                f"workflow.execution.stage_providers.{stage_id} must reference a defined provider name."
            )
        stage_assignments[str(stage_id)] = provider_configs[provider_name]
    return stage_assignments


def resolve_stage_assignments(args: argparse.Namespace, job_dir: Path) -> dict[str, StageAdapterSelection]:
    configured = load_stage_assignments_from_job_config(job_dir)
    if configured is not None:
        return configured
    return build_default_stage_assignments(args)


def resolve_provider_runtime_policy(job_dir: Path) -> dict[str, object] | None:
    execution = load_execution_config(job_dir)
    if execution is None:
        return None
    runtime_policy = execution.get("provider_runtime_policy")
    return runtime_policy if isinstance(runtime_policy, dict) else None


def resolve_stage_required_provider_trust(job_dir: Path) -> dict[str, str]:
    requirements = {
        str(stage["id"]): DEFAULT_REQUIRED_PROVIDER_TRUST
        for stage in RUN_STAGES
        if stage_requires_structured_safe_adapter(str(stage["id"]))
    }
    execution = load_execution_config(job_dir)
    if execution is None:
        return requirements

    global_required = execution.get("required_provider_trust")
    if global_required is not None:
        if not isinstance(global_required, str) or global_required not in STRUCTURED_TRUST_LEVELS:
            raise ValueError(
                "workflow.execution.required_provider_trust must be one of: "
                + ", ".join(STRUCTURED_TRUST_LEVELS)
            )
        for stage_id in requirements:
            requirements[stage_id] = global_required

    stage_required = execution.get("stage_required_provider_trust")
    if stage_required is None:
        return requirements
    if not isinstance(stage_required, dict):
        raise ValueError("workflow.execution.stage_required_provider_trust must be a mapping when provided.")

    expected_stage_ids = {str(stage["id"]) for stage in RUN_STAGES}
    for stage_id, required_trust in stage_required.items():
        if stage_id not in expected_stage_ids:
            raise ValueError(
                f"workflow.execution.stage_required_provider_trust.{stage_id} references an unknown stage."
            )
        if not stage_requires_structured_safe_adapter(str(stage_id)):
            raise ValueError(
                f"workflow.execution.stage_required_provider_trust.{stage_id} is not allowed for non-structured stages."
            )
        if not isinstance(required_trust, str) or required_trust not in STRUCTURED_TRUST_LEVELS:
            raise ValueError(
                f"workflow.execution.stage_required_provider_trust.{stage_id} must be one of: "
                + ", ".join(STRUCTURED_TRUST_LEVELS)
            )
        requirements[str(stage_id)] = required_trust
    return requirements


def stage_requires_structured_safe_adapter(stage_id: str) -> bool:
    if stage_id == "intake":
        return True
    return is_structured_stage(stage_id)


def qualify_stage_adapters(
    *,
    run_dir: Path,
    job_dir: Path,
    stage_assignments: dict[str, StageAdapterSelection],
    stage_required_trust: dict[str, str],
    adapter_bins: dict[str, str],
) -> dict[str, dict[str, object]]:
    reports: dict[str, dict[str, object]] = {}
    provider_required_trust: dict[tuple[str, str], str] = {}
    for stage_id, selection in stage_assignments.items():
        if not stage_requires_structured_safe_adapter(stage_id):
            continue
        provider_key = selection.provider_name or selection.adapter_name
        pair = (provider_key, selection.adapter_name)
        required_trust = stage_required_trust.get(stage_id, DEFAULT_REQUIRED_PROVIDER_TRUST)
        current = provider_required_trust.get(pair)
        if current is None or STRUCTURED_TRUST_LEVELS.index(required_trust) > STRUCTURED_TRUST_LEVELS.index(current):
            provider_required_trust[pair] = required_trust

    for (provider_key, adapter_name), required_trust in provider_required_trust.items():
        profile = profile_for_required_trust(required_trust)
        report = classify_adapter_qualification(
            adapter_name=adapter_name,
            adapter_bin=Path(adapter_bins[adapter_name]),
            job_dir=job_dir,
            profile=profile,
        )
        persist_adapter_qualification(run_dir, provider_key, adapter_name, report, profile=profile)
        record_provider_qualification(job_dir, provider_key, report, run_id=run_dir.name)
        reports[provider_key] = report

    for stage_id, selection in stage_assignments.items():
        if not stage_requires_structured_safe_adapter(stage_id):
            continue
        provider_key = selection.provider_name or selection.adapter_name
        report = reports[provider_key]
        required_trust = stage_required_trust.get(stage_id, DEFAULT_REQUIRED_PROVIDER_TRUST)
        if not trust_satisfies(str(report.get("trust_level", "unsupported")), required_trust):
            raise ValueError(
                f"Provider '{provider_key}' using adapter '{selection.adapter_name}' is not qualified for structured stage execution; "
                f"required_trust={required_trust}; trust_level={report.get('trust_level')}; "
                f"classification={report.get('classification')}."
            )
    return reports


def run_agent_stage(
    stage: StageExecution,
    run_dir: Path,
    job_dir: Path,
    state: dict[str, object],
    state_path: Path,
    state_lock: threading.RLock,
    stage_assignments: dict[str, StageAdapterSelection],
    adapter_bins: dict[str, str],
    reporter: ProgressReporter,
    process_controller: StageProcessController | None = None,
) -> tuple[str, str]:
    stage_selection = stage_assignments[stage.stage_id]
    adapter = resolve_adapter(stage_selection.adapter_name)
    adapter_bin = adapter_bins[stage_selection.adapter_name]
    if stage.stage_id == "intake":
        return run_intake_stage(
            stage,
            run_dir,
            job_dir,
            state,
            state_path,
            state_lock,
            stage_selection,
            adapter,
            adapter_bin,
            reporter,
            process_controller,
        )
    if is_structured_stage(stage.stage_id):
        return run_structured_stage(
            stage,
            run_dir,
            job_dir,
            state,
            state_path,
            state_lock,
            stage_selection,
            adapter,
            adapter_bin,
            reporter,
            process_controller,
        )
    reporter.start(adapter.name, stage.stage_id)
    stage_started_monotonic, stage_started_at = timed_operation_bounds()
    prompt = build_agent_prompt(stage, run_dir)
    output_path = stage_output_path(run_dir, stage.output_name)
    structured_output_path = stage_structured_output_path(run_dir, stage.stage_id) if is_structured_stage(stage.stage_id) else None
    source_registry_file = source_registry_path(run_dir) if is_structured_stage(stage.stage_id) else None
    source_registry_snapshot = (
        source_registry_file.read_text(encoding="utf-8") if source_registry_file is not None and source_registry_file.is_file() else None
    )
    log_path = run_dir / "logs" / f"{stage.stage_id}.{adapter.name}.driver.log"
    cmd = adapter.command_builder(adapter_bin, job_dir, prompt, stage_selection.model)
    repair_attempted = False
    repair_result: CommandResult | None = None
    stage_status = "completed"
    stage_failure_reason: str | None = None
    artifact_kind = "structured_json" if output_path.suffix.lower() == ".json" else "markdown"
    adapter_executor = build_adapter_executor(adapter.name, adapter_bin, artifact_kind)

    def evaluate_stage_result(command_result: CommandResult) -> dict[str, object]:
        restored_source_registry = False
        structured_output_exists = structured_output_path.is_file() if structured_output_path is not None else False
        structured_output_complete = is_json_artifact_complete(structured_output_path) if structured_output_path is not None else False
        structured_validation_errors: list[str] = []
        structured_validation_warnings: list[str] = []
        intake_validation_errors: list[str] = []
        markdown_validation_errors: list[str] = []

        output_exists = output_path.is_file()
        output_complete = is_stage_output_complete(output_path)
        if command_result.returncode == 0 and output_complete and stage.stage_id == "intake":
            try:
                intake_validation_errors = validate_intake_payload(load_contract_json(output_path))
            except (ValueError, json.JSONDecodeError) as exc:
                intake_validation_errors = [str(exc)]
        if command_result.returncode == 0 and output_complete and structured_output_path is not None:
            if (
                source_registry_file is not None
                and source_registry_snapshot is not None
                and source_registry_file.read_text(encoding="utf-8") != source_registry_snapshot
            ):
                source_registry_file.write_text(source_registry_snapshot, encoding="utf-8")
                restored_source_registry = True
            structured_output_exists = structured_output_path.is_file()
            structured_output_complete = is_json_artifact_complete(structured_output_path)
            if structured_output_complete:
                try:
                    validation = validate_structured_stage_artifact(
                        stage.stage_id,
                        load_contract_json(structured_output_path),
                        json.loads(source_registry_snapshot) if source_registry_snapshot is not None else {"sources": []},
                        output_path.read_text(encoding="utf-8"),
                        dependency_structured_payloads(stage.stage_id, run_dir),
                    )
                    structured_validation_errors = validation.structured_errors
                    structured_validation_warnings = validation.structured_warnings
                    markdown_validation_errors = validation.markdown_errors
                    if validation.should_rewrite_markdown:
                        output_path.write_text(validation.canonical_markdown, encoding="utf-8")
                        output_complete = is_stage_output_complete(output_path)
                except ValueError as exc:
                    structured_validation_errors = [str(exc)]
        return {
            "restored_source_registry": restored_source_registry,
            "structured_output_exists": structured_output_exists,
            "structured_output_complete": structured_output_complete,
            "structured_validation_errors": structured_validation_errors,
            "structured_validation_warnings": structured_validation_warnings,
            "intake_validation_errors": intake_validation_errors,
            "markdown_validation_errors": markdown_validation_errors,
            "output_exists": output_exists,
            "output_complete": output_complete,
        }

    completed = adapter_executor(
        cmd,
        job_dir=job_dir,
        output_path=output_path,
        stage_id=stage.stage_id,
        prompt_text=prompt,
        process_controller=process_controller,
    )
    evaluation = evaluate_stage_result(completed)
    if (
        completed.returncode == 0
        and structured_output_path is not None
        and evaluation["output_complete"]
        and evaluation["structured_output_complete"]
        and not evaluation["intake_validation_errors"]
        and (evaluation["structured_validation_errors"] or evaluation["markdown_validation_errors"])
    ):
        repair_attempted = True
        repair_prompt = build_repair_prompt(
            stage,
            run_dir,
            [*evaluation["structured_validation_errors"], *evaluation["markdown_validation_errors"]],
        )
        repair_cmd = adapter.command_builder(adapter_bin, job_dir, repair_prompt, stage_selection.model)
        repair_result = adapter_executor(
            repair_cmd,
            job_dir=job_dir,
            output_path=output_path,
            stage_id=stage.stage_id,
            prompt_text=repair_prompt,
            process_controller=process_controller,
        )
        completed = repair_result
        cmd = repair_cmd
        evaluation = evaluate_stage_result(repair_result)
    if process_controller is not None and process_controller.is_cancelled(stage.stage_id):
        marker = "cancelled_due_to_parallel_stage_failure"
        if marker not in completed.stderr:
            completed = CommandResult(
                returncode=completed.returncode,
                stdout=completed.stdout,
                stderr=(completed.stderr + ("\n" if completed.stderr else "") + marker),
            )
    log_path.write_text(
        "\n".join(
            [
                "COMMAND:",
                " ".join(cmd),
                "",
                "RETURN_CODE:",
                str(completed.returncode),
                "",
                "REPAIR_ATTEMPTED:",
                str(repair_attempted),
                "",
                "REPAIR_RETURN_CODE:",
                str(repair_result.returncode) if repair_result is not None else "<not-run>",
                "",
                "OUTPUT_PATH:",
                str(output_path),
                "",
                "OUTPUT_EXISTS:",
                str(evaluation["output_exists"]),
                "",
                "OUTPUT_COMPLETE:",
                str(evaluation["output_complete"]),
                "",
                "STRUCTURED_OUTPUT_PATH:",
                str(structured_output_path) if structured_output_path is not None else "<not-applicable>",
                "",
                "STRUCTURED_OUTPUT_EXISTS:",
                str(evaluation["structured_output_exists"]),
                "",
                "STRUCTURED_OUTPUT_COMPLETE:",
                str(evaluation["structured_output_complete"]),
                "",
                "SOURCE_REGISTRY_RESTORED_AFTER_STAGE:",
                str(evaluation["restored_source_registry"]),
                "",
                "STRUCTURED_OUTPUT_PREVIEW:",
                read_output_preview(structured_output_path) if structured_output_path is not None else "<not-applicable>",
                "",
                "STRUCTURED_VALIDATION_ERRORS:",
                "\n".join(evaluation["structured_validation_errors"]) if evaluation["structured_validation_errors"] else "<none>",
                "",
                "STRUCTURED_VALIDATION_WARNINGS:",
                "\n".join(evaluation["structured_validation_warnings"]) if evaluation["structured_validation_warnings"] else "<none>",
                "",
                "INTAKE_VALIDATION_ERRORS:",
                "\n".join(evaluation["intake_validation_errors"]) if evaluation["intake_validation_errors"] else "<none>",
                "",
                "MARKDOWN_VALIDATION_ERRORS:",
                "\n".join(evaluation["markdown_validation_errors"]) if evaluation["markdown_validation_errors"] else "<none>",
                "",
                "OUTPUT_PREVIEW:",
                read_output_preview(output_path),
                "",
                "STDOUT:",
                completed.stdout,
                "",
                "STDERR:",
                completed.stderr,
                "",
                "REPAIR_STDOUT:",
                repair_result.stdout if repair_result is not None else "",
                "",
                "REPAIR_STDERR:",
                repair_result.stderr if repair_result is not None else "",
            ]
        ),
        encoding="utf-8",
    )

    if completed.returncode != 0 and process_controller is not None and process_controller.is_cancelled(stage.stage_id):
        stage_status = "cancelled"
        stage_failure_reason = "cancelled_due_to_parallel_stage_failure"
        append_manual_stage_usage_record(
            run_dir=run_dir,
            scope="stage",
            stage_id=stage.stage_id,
            status=stage_status,
            provider_key=stage_selection.provider_name or stage_selection.adapter_name,
            adapter=adapter.name,
            model=stage_selection.model,
            started_at=stage_started_at,
            finished_at=utc_now_iso(),
            failure_reason=stage_failure_reason,
        )
        reporter.cancel(adapter.name, stage.stage_id)
        raise StageCancelledError(f"Stage {stage.stage_id} cancelled due to parallel stage failure.")
    if completed.returncode != 0:
        stage_status = "failed"
        stage_failure_reason = completed.stderr.strip() or f"Stage {stage.stage_id} failed via {adapter.name}"
        append_manual_stage_usage_record(
            run_dir=run_dir,
            scope="stage",
            stage_id=stage.stage_id,
            status=stage_status,
            provider_key=stage_selection.provider_name or stage_selection.adapter_name,
            adapter=adapter.name,
            model=stage_selection.model,
            started_at=stage_started_at,
            finished_at=utc_now_iso(),
            failure_reason=stage_failure_reason,
        )
        reporter.fail(adapter.name, stage.stage_id)
        raise RuntimeError(f"Stage {stage.stage_id} failed via {adapter.name}: {completed.stderr.strip()}")
    if not evaluation["output_complete"]:
        stage_status = "failed"
        stage_failure_reason = f"Stage {stage.stage_id} did not produce a completed output artifact: {output_path}"
        append_manual_stage_usage_record(
            run_dir=run_dir,
            scope="stage",
            stage_id=stage.stage_id,
            status=stage_status,
            provider_key=stage_selection.provider_name or stage_selection.adapter_name,
            adapter=adapter.name,
            model=stage_selection.model,
            started_at=stage_started_at,
            finished_at=utc_now_iso(),
            failure_reason=stage_failure_reason,
        )
        reporter.fail(adapter.name, stage.stage_id)
        raise RuntimeError(f"Stage {stage.stage_id} did not produce a completed output artifact: {output_path}")
    if evaluation["intake_validation_errors"]:
        stage_status = "failed"
        stage_failure_reason = "; ".join(evaluation["intake_validation_errors"])
        append_manual_stage_usage_record(
            run_dir=run_dir,
            scope="stage",
            stage_id=stage.stage_id,
            status=stage_status,
            provider_key=stage_selection.provider_name or stage_selection.adapter_name,
            adapter=adapter.name,
            model=stage_selection.model,
            started_at=stage_started_at,
            finished_at=utc_now_iso(),
            failure_reason=stage_failure_reason,
        )
        reporter.fail(adapter.name, stage.stage_id)
        raise RuntimeError(f"Stage {stage.stage_id} failed intake validation: {'; '.join(evaluation['intake_validation_errors'])}")
    if structured_output_path is not None and not evaluation["structured_output_complete"]:
        stage_status = "failed"
        stage_failure_reason = f"Stage {stage.stage_id} did not produce a completed structured output artifact: {structured_output_path}"
        append_manual_stage_usage_record(
            run_dir=run_dir,
            scope="stage",
            stage_id=stage.stage_id,
            status=stage_status,
            provider_key=stage_selection.provider_name or stage_selection.adapter_name,
            adapter=adapter.name,
            model=stage_selection.model,
            started_at=stage_started_at,
            finished_at=utc_now_iso(),
            failure_reason=stage_failure_reason,
        )
        reporter.fail(adapter.name, stage.stage_id)
        raise RuntimeError(f"Stage {stage.stage_id} did not produce a completed structured output artifact: {structured_output_path}")
    if evaluation["structured_validation_errors"]:
        stage_status = "failed"
        reporter.fail(adapter.name, stage.stage_id)
        details = "; ".join(evaluation["structured_validation_errors"])
        details = re.sub(
            r"inferences\[\d+\] must include at least one evidence source\.",
            "uncited inference detected in structured stage output.",
            details,
            flags=re.IGNORECASE,
        )
        details = re.sub(
            r"facts\[\d+\] must include at least one evidence source\.",
            "uncited fact detected in structured stage output.",
            details,
            flags=re.IGNORECASE,
        )
        if "references unresolved source id" in details.lower():
            details = re.sub(r"references unresolved source id", "references unresolved source ID", details, flags=re.IGNORECASE)
        stage_failure_reason = details
        append_manual_stage_usage_record(
            run_dir=run_dir,
            scope="stage",
            stage_id=stage.stage_id,
            status=stage_status,
            provider_key=stage_selection.provider_name or stage_selection.adapter_name,
            adapter=adapter.name,
            model=stage_selection.model,
            started_at=stage_started_at,
            finished_at=utc_now_iso(),
            failure_reason=stage_failure_reason,
        )
        raise RuntimeError(f"Stage {stage.stage_id} failed structured validation: {details}")
    if evaluation["markdown_validation_errors"]:
        stage_status = "failed"
        stage_failure_reason = "; ".join(evaluation["markdown_validation_errors"])
        append_manual_stage_usage_record(
            run_dir=run_dir,
            scope="stage",
            stage_id=stage.stage_id,
            status=stage_status,
            provider_key=stage_selection.provider_name or stage_selection.adapter_name,
            adapter=adapter.name,
            model=stage_selection.model,
            started_at=stage_started_at,
            finished_at=utc_now_iso(),
            failure_reason=stage_failure_reason,
        )
        reporter.fail(adapter.name, stage.stage_id)
        raise RuntimeError(f"Stage {stage.stage_id} failed markdown contract validation: {'; '.join(evaluation['markdown_validation_errors'])}")
    append_manual_stage_usage_record(
        run_dir=run_dir,
        scope="stage",
        stage_id=stage.stage_id,
        status=stage_status,
        provider_key=stage_selection.provider_name or stage_selection.adapter_name,
        adapter=adapter.name,
        model=stage_selection.model,
        started_at=stage_started_at,
        finished_at=utc_now_iso(),
        failure_reason=stage_failure_reason,
    )
    reporter.complete(adapter.name, stage.stage_id)
    return stage.stage_id, "completed"


def run_stage_claim_extraction(
    stage_id: str,
    run_dir: Path,
    job_dir: Path,
    state: dict[str, object],
    state_path: Path,
    state_lock: threading.RLock,
    reporter: ProgressReporter,
) -> None:
    if stage_id not in STAGE_CLAIM_STAGE_IDS:
        return
    claim_output = stage_claim_output_path(run_dir, stage_id)
    with state_lock:
        stage_claim_status = state["post_processing"]["stage_claims"][stage_id]["status"]
    if stage_claim_status == "completed" and claim_output.is_file():
        reporter.complete("system", f"{stage_id}-claims")
        return

    reporter.start("system", f"{stage_id}-claims")
    apply_state_update(
        state_lock,
        state_path,
        state,
        lambda: transition_post_processing_status(run_dir, state, "stage_claims", "started", stage_id=stage_id),
    )

    stage_output = next(
        run_dir / "stage-outputs" / str(stage["output"])
        for stage in RUN_STAGES
        if str(stage["id"]) == stage_id
    )
    validation_errors: list[str] = []
    completed_stdout = ""
    completed_stderr = ""
    command_display = "<structured-stage-claim-map>"
    completed_return_code = 0
    try:
        if is_structured_stage(stage_id):
            json_path = stage_structured_output_path(run_dir, stage_id)
            payload = load_contract_json(json_path)
            source_registry_file = source_registry_path(run_dir)
            source_registry = load_contract_json(source_registry_file) if source_registry_file.is_file() else {"sources": []}
            validation = validate_structured_stage_artifact(
                stage_id,
                payload,
                source_registry,
                stage_output.read_text(encoding="utf-8"),
                dependency_structured_payloads(stage_id, run_dir),
            )
            validation_errors = validation.structured_errors + validation.markdown_errors
            if not validation_errors:
                if validation.should_rewrite_markdown:
                    stage_output.write_text(validation.canonical_markdown, encoding="utf-8")
                write_json(claim_output, validation.claim_map)
            completed_return_code = 0
        else:
            cmd = [
                sys.executable,
                str(Path(__file__).resolve().parents[1] / "scripts" / "extract_claims.py"),
                "--input",
                str(stage_output),
                "--output",
                str(claim_output),
                "--source-registry",
                str(source_registry_path(run_dir)),
            ]
            completed = subprocess.run(cmd, cwd=job_dir, capture_output=True, text=True)
            command_display = " ".join(cmd)
            completed_stdout = completed.stdout
            completed_stderr = completed.stderr
            completed_return_code = completed.returncode
            if completed.returncode == 0:
                validation_errors = validate_stage_markdown_contract(stage_id, stage_output.read_text(encoding="utf-8"))
    except Exception as exc:
        completed_return_code = 1
        completed_stderr = str(exc)
    (run_dir / "logs" / f"{stage_id}.claims.driver.log").write_text(
        "\n".join(
            [
                "COMMAND:",
                command_display,
                "",
                "STDOUT:",
                completed_stdout,
                "",
                "STDERR:",
                completed_stderr,
                "",
                "VALIDATION_ERRORS:",
                "\n".join(validation_errors) if validation_errors else "<none>",
            ]
        ),
        encoding="utf-8",
    )
    if completed_return_code != 0 or validation_errors:
        apply_state_update(
            state_lock,
            state_path,
            state,
            lambda: (
                transition_stage_status(run_dir, state, stage_id, "failed"),
                transition_post_processing_status(run_dir, state, "stage_claims", "failed", stage_id=stage_id),
            ),
        )
        reporter.fail("system", f"{stage_id}-claims")
        details = completed_stderr.strip() or "; ".join(validation_errors)
        if validation_errors and completed_stderr.strip():
            details = completed_stderr.strip() + " " + "; ".join(validation_errors)
        details = details.replace("lacks an external evidence citation", "is an uncited inference or fact")
        raise RuntimeError(f"Stage claim extraction failed for {stage_id}: {details}")

    apply_state_update(
        state_lock,
        state_path,
        state,
        lambda: transition_post_processing_status(run_dir, state, "stage_claims", "completed", stage_id=stage_id),
    )
    reporter.complete("system", f"{stage_id}-claims")


def run_stage_group(
    stages: list[StageExecution],
    run_dir: Path,
    job_dir: Path,
    state_path: Path,
    state: dict[str, object],
    stage_assignments: dict[str, StageAdapterSelection],
    adapter_bins: dict[str, str],
    reporter: ProgressReporter,
) -> None:
    state_lock = threading.RLock()
    runnable: list[StageExecution] = []
    for stage in stages:
        if is_stage_execution_complete(run_dir, stage):
            apply_state_update(
                state_lock,
                state_path,
                state,
                lambda: transition_stage_status(run_dir, state, stage.stage_id, "completed"),
            )
            selection = stage_assignments[stage.stage_id]
            adapter_name = selection.adapter_name
            reporter.complete(adapter_name, stage.stage_id)
            if stage.stage_id == "intake":
                merge_intake_sources_into_registry(run_dir)
            elif is_structured_stage(stage.stage_id):
                merge_stage_sources_into_registry(stage.stage_id, run_dir)
            run_stage_claim_extraction(stage.stage_id, run_dir, job_dir, state, state_path, state_lock, reporter)
        else:
            runnable.append(stage)
    for stage in runnable:
        apply_state_update(
            state_lock,
            state_path,
            state,
            lambda stage_id=stage.stage_id: transition_stage_status(run_dir, state, stage_id, "started"),
        )

    if not runnable:
        return

    process_controller = StageProcessController()
    with ThreadPoolExecutor(max_workers=len(runnable)) as executor:
        futures = {
            executor.submit(
                run_agent_stage,
                stage,
                run_dir,
                job_dir,
                state,
                state_path,
                state_lock,
                stage_assignments,
                adapter_bins,
                reporter,
                process_controller,
            ): stage
            for stage in runnable
        }
        pending_error: Exception | None = None
        for future in as_completed(futures):
            stage = futures[future]
            try:
                stage_id, status = future.result()
                selection = stage_assignments[stage_id]
                provider_key = selection.provider_name or selection.adapter_name
                apply_state_update(
                    state_lock,
                    state_path,
                    state,
                    lambda: transition_stage_status(run_dir, state, stage_id, status),
                )
                record_provider_stage_result(
                    job_dir,
                    provider_key,
                    stage_id,
                    status,
                    run_id=run_dir.name,
                    adapter_name=selection.adapter_name,
                    model=selection.model,
                )
                if stage_id == "intake":
                    merge_intake_sources_into_registry(run_dir)
                elif is_structured_stage(stage_id):
                    merge_stage_sources_into_registry(stage_id, run_dir)
                try:
                    run_stage_claim_extraction(stage_id, run_dir, job_dir, state, state_path, state_lock, reporter)
                except Exception as exc:
                    if pending_error is None:
                        pending_error = exc
                        process_controller.cancel_others(stage_id)
            except StageCancelledError:
                selection = stage_assignments[stage.stage_id]
                provider_key = selection.provider_name or selection.adapter_name
                apply_state_update(
                    state_lock,
                    state_path,
                    state,
                    lambda: (
                        transition_stage_status(run_dir, state, stage.stage_id, "cancelled"),
                        transition_post_processing_status(run_dir, state, "stage_claims", "cancelled", stage_id=stage.stage_id)
                        if stage.stage_id in STAGE_CLAIM_STAGE_IDS
                        else None,
                    ),
                )
                record_provider_stage_result(
                    job_dir,
                    provider_key,
                    stage.stage_id,
                    "cancelled",
                    run_id=run_dir.name,
                    adapter_name=selection.adapter_name,
                    model=selection.model,
                )
            except Exception as exc:
                selection = stage_assignments[stage.stage_id]
                provider_key = selection.provider_name or selection.adapter_name
                apply_state_update(
                    state_lock,
                    state_path,
                    state,
                    lambda: (
                        transition_stage_status(run_dir, state, stage.stage_id, "failed"),
                        transition_post_processing_status(run_dir, state, "stage_claims", "failed", stage_id=stage.stage_id)
                        if stage.stage_id in STAGE_CLAIM_STAGE_IDS
                        else None,
                    ),
                )
                record_provider_stage_result(
                    job_dir,
                    provider_key,
                    stage.stage_id,
                    "failed",
                    run_id=run_dir.name,
                    adapter_name=selection.adapter_name,
                    model=selection.model,
                )
                if pending_error is None:
                    pending_error = exc
                    process_controller.cancel_others(stage.stage_id)
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
    _started_monotonic, started_at = timed_operation_bounds()
    if claim_output.is_file():
        transition_post_processing_status(run_dir, state, "claim_extraction", "completed")
        save_state(state_path, state)
        reporter.complete("system", "claim-extraction")
        return

    reporter.start("system", "claim-extraction")
    transition_post_processing_status(run_dir, state, "claim_extraction", "started")
    save_state(state_path, state)

    judge_output = run_dir / "stage-outputs" / "06-judge.md"
    judge_json = stage_structured_output_path(run_dir, "judge")
    if is_json_artifact_complete(judge_json):
        payload = load_contract_json(judge_json)
        claim_map = build_claim_map_from_stage_json("judge", payload)
        write_json(claim_output, claim_map)
        (run_dir / "logs" / "claim-extraction.driver.log").write_text(
            "\n".join(
                [
                    "COMMAND:",
                    "<structured-judge-claim-map>",
                    "",
                    "STDOUT:",
                    "",
                    "",
                    "STDERR:",
                    "",
                ]
            ),
            encoding="utf-8",
        )
    else:
        cmd = [
            sys.executable,
            str(Path(__file__).resolve().parents[1] / "scripts" / "extract_claims.py"),
            "--input",
            str(judge_output),
            "--output",
            str(claim_output),
            "--source-registry",
            str(source_registry_path(run_dir)),
            "--strict",
        ]
        completed = subprocess.run(cmd, cwd=job_dir, capture_output=True, text=True)
        (run_dir / "logs" / "claim-extraction.driver.log").write_text(
            "\n".join(["COMMAND:", " ".join(cmd), "", "STDOUT:", completed.stdout, "", "STDERR:", completed.stderr]),
            encoding="utf-8",
        )
        if completed.returncode != 0:
            transition_post_processing_status(run_dir, state, "claim_extraction", "failed")
            save_state(state_path, state)
            finished_at = utc_now_iso()
            append_command_usage_record(
                run_dir=run_dir,
                scope="post_processing",
                stage_id="claim-extraction",
                provider_key="system",
                adapter="system",
                model=None,
                result=CommandResult(
                    completed.returncode,
                    completed.stdout,
                    completed.stderr,
                    started_at=started_at,
                    finished_at=finished_at,
                    duration_ms=0,
                ),
                status="failed",
                prompt_text=" ".join(cmd),
                failure_reason=completed.stderr.strip() or "claim extraction failed",
            )
            reporter.fail("system", "claim-extraction")
            raise RuntimeError(f"Claim extraction failed: {completed.stderr.strip()}")
        finished_at = utc_now_iso()
        append_command_usage_record(
            run_dir=run_dir,
            scope="post_processing",
            stage_id="claim-extraction",
            provider_key="system",
            adapter="system",
            model=None,
            result=CommandResult(
                completed.returncode,
                completed.stdout,
                completed.stderr,
                started_at=started_at,
                finished_at=finished_at,
                duration_ms=0,
            ),
            status="completed",
            prompt_text=" ".join(cmd),
        )
    if is_json_artifact_complete(judge_json):
        append_manual_stage_usage_record(
            run_dir=run_dir,
            scope="post_processing",
            stage_id="claim-extraction",
            status="completed",
            provider_key="system",
            adapter="system",
            model=None,
            started_at=started_at,
            finished_at=utc_now_iso(),
        )
    set_post_processing_status(state, "claim_extraction", "completed")
    transition_post_processing_status(run_dir, state, "claim_extraction", "completed")
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
    _started_monotonic, started_at = timed_operation_bounds()
    if final_output.is_file():
        transition_post_processing_status(run_dir, state, "final_artifact", "completed")
        save_state(state_path, state)
        reporter.complete("system", "final-artifact")
        return

    reporter.start("system", "final-artifact")
    transition_post_processing_status(run_dir, state, "final_artifact", "started")
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
        transition_post_processing_status(run_dir, state, "final_artifact", "failed")
        save_state(state_path, state)
        finished_at = utc_now_iso()
        append_command_usage_record(
            run_dir=run_dir,
            scope="post_processing",
            stage_id="final-artifact",
            provider_key="system",
            adapter="system",
            model=None,
            result=CommandResult(
                validate_result.returncode,
                validate_result.stdout,
                validate_result.stderr,
                started_at=started_at,
                finished_at=finished_at,
                duration_ms=0,
            ),
            status="failed",
            prompt_text=" ".join(validate_cmd),
            failure_reason=validate_result.stderr.strip() or validate_result.stdout.strip() or "final artifact readiness validation failed",
        )
        reporter.fail("system", "final-artifact")
        raise RuntimeError(f"Final artifact readiness validation failed: {validate_result.stderr.strip() or validate_result.stdout.strip()}")

    cmd = [
        sys.executable,
        str(Path(__file__).resolve().parents[1] / "scripts" / "generate_final_artifact.py"),
        "--judge-input",
        str(judge_output),
        "--judge-structured-input",
        str(stage_structured_output_path(run_dir, "judge")),
        "--claim-register",
        str(claim_output),
        "--output",
        str(final_output),
        "--config",
        str(job_dir / "config.yaml"),
    ]
    completed = subprocess.run(cmd, cwd=job_dir, capture_output=True, text=True)
    (run_dir / "logs" / "final-artifact.driver.log").write_text(
        "\n".join(["COMMAND:", " ".join(cmd), "", "STDOUT:", completed.stdout, "", "STDERR:", completed.stderr]),
        encoding="utf-8",
    )
    if completed.returncode != 0:
        transition_post_processing_status(run_dir, state, "final_artifact", "failed")
        save_state(state_path, state)
        finished_at = utc_now_iso()
        append_command_usage_record(
            run_dir=run_dir,
            scope="post_processing",
            stage_id="final-artifact",
            provider_key="system",
            adapter="system",
            model=None,
            result=CommandResult(
                completed.returncode,
                completed.stdout,
                completed.stderr,
                started_at=started_at,
                finished_at=finished_at,
                duration_ms=0,
            ),
            status="failed",
            prompt_text=" ".join(cmd),
            failure_reason=completed.stderr.strip() or "final artifact generation failed",
        )
        reporter.fail("system", "final-artifact")
        raise RuntimeError(f"Final artifact generation failed: {completed.stderr.strip()}")
    finished_at = utc_now_iso()
    append_command_usage_record(
        run_dir=run_dir,
        scope="post_processing",
        stage_id="final-artifact",
        provider_key="system",
        adapter="system",
        model=None,
        result=CommandResult(
            completed.returncode,
            completed.stdout,
            completed.stderr,
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=0,
        ),
        status="completed",
        prompt_text=" ".join(cmd),
    )
    transition_post_processing_status(run_dir, state, "final_artifact", "completed")
    save_state(state_path, state)
    reporter.complete("system", "final-artifact")


def main() -> int:
    args = parse_args()
    reporter = ProgressReporter(sys.stdout)
    try:
        adapter_bins = build_adapter_bin_map(args)
        job_name, job_dir = resolve_job_path(
            job_name=args.job_name,
            job_id=args.job_id,
            job_path=args.job_path,
            jobs_root=Path(args.jobs_root).expanduser(),
            jobs_index_root=Path(args.jobs_index_root).expanduser(),
        )
        execution_config = load_execution_config(job_dir)
        configured_stage_assignments = resolve_stage_assignments(args, job_dir)
        provider_catalog = load_provider_catalog_from_job_config(job_dir) or {
            selection.provider_name or selection.adapter_name: selection
            for selection in configured_stage_assignments.values()
        }
        runtime_policy = resolve_provider_runtime_policy(job_dir)
        stage_assignments = apply_provider_runtime_policy(
            job_dir,
            configured_stage_assignments,
            provider_catalog,
            runtime_policy,
        )
        stage_required_trust = resolve_stage_required_provider_trust(job_dir)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    run_id = args.run_id or next_incremental_run_id(job_dir)

    run_dir = job_dir / "runs" / run_id
    if run_dir.exists():
        if args.run_id is not None:
            confirm_existing_run(run_id, run_dir)
    else:
        scaffold_run(job_name, job_dir, run_id)

    source_path = source_registry_path(run_dir)
    if not source_path.exists():
        write_json(source_path, source_registry_placeholder(run_id))

    claim_output = Path(args.claim_output).expanduser() if args.claim_output else job_dir / "evidence" / f"claims-{run_id}.json"
    final_output = Path(args.final_output).expanduser() if args.final_output else job_dir / "outputs" / f"final-{run_id}.md"
    claim_output.parent.mkdir(parents=True, exist_ok=True)
    final_output.parent.mkdir(parents=True, exist_ok=True)

    state_path = run_dir / "workflow-state.json"
    state = load_state(state_path)
    ensure_post_processing_state(state, claim_output, final_output)
    save_state(state_path, state)
    try:
        persist_execution_snapshot(
            run_dir=run_dir,
            snapshot=build_execution_snapshot(
                job_dir=job_dir,
                run_dir=run_dir,
                args=args,
                execution_config=execution_config,
                provider_catalog=provider_catalog,
                configured_stage_assignments=configured_stage_assignments,
                resolved_stage_assignments=stage_assignments,
                stage_required_trust=stage_required_trust,
                runtime_policy=runtime_policy,
            ),
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    already_complete = all(
        is_stage_output_complete(stage_output_path(run_dir, stage["expected_output_target"].split("/")[-1]))
        for stage in state["stages"]
    ) and claim_output.is_file() and final_output.is_file()

    try:
        qualify_stage_adapters(
            run_dir=run_dir,
            job_dir=job_dir,
            stage_assignments=stage_assignments,
            stage_required_trust=stage_required_trust,
            adapter_bins=adapter_bins,
        )
        for group in EXECUTION_PLAN:
            run_stage_group(group, run_dir, job_dir, state_path, state, stage_assignments, adapter_bins, reporter)

        run_extract_claims(run_dir, job_dir, run_id, claim_output, state, state_path, reporter)
        run_final_artifact(run_dir, job_dir, claim_output, final_output, state, state_path, reporter)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if already_complete:
        print(f"Workflow already complete for run {run_id}")
    else:
        print(str(run_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

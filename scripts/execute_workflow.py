#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from _workflow_lib import write_json
from run_workflow import RUN_STAGES, resolve_job_path, scaffold_run


DEFAULT_CODEX_BIN = "codex"
DEFAULT_ANTIGRAVITY_BIN = "antigravity"
DEFAULT_JOBS_INDEX_ROOT = Path(__file__).resolve().parents[1] / "jobs-index"


@dataclass(frozen=True)
class StageExecution:
    stage_id: str
    agent: str
    packet_name: str
    output_name: str


EXECUTION_PLAN = [
    [StageExecution("intake", "codex", "01-intake.md", "01-intake.json")],
    [
        StageExecution("research-a", "codex", "02-research-a.md", "02-research-a.md"),
        StageExecution("research-b", "antigravity", "03-research-b.md", "03-research-b.md"),
    ],
    [
        StageExecution("critique-a-on-b", "codex", "04-critique-a-on-b.md", "04-critique-a-on-b.md"),
        StageExecution("critique-b-on-a", "antigravity", "05-critique-b-on-a.md", "05-critique-b-on-a.md"),
    ],
    [StageExecution("judge", "antigravity", "06-judge.md", "06-judge.md")],
]


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
    parser.add_argument("--codex-bin", default=DEFAULT_CODEX_BIN, help="Path to the Codex CLI.")
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


def stage_output_path(run_dir: Path, output_name: str) -> Path:
    return run_dir / "stage-outputs" / output_name


def stage_packet_path(run_dir: Path, packet_name: str) -> Path:
    return run_dir / "prompt-packets" / packet_name


def set_stage_status(state: dict[str, object], stage_id: str, status: str) -> None:
    for stage in state["stages"]:
        if stage["id"] == stage_id:
            stage["status"] = status
            return
    raise KeyError(f"Unknown stage id: {stage_id}")


def ensure_post_processing_state(state: dict[str, object], claim_output: Path, final_output: Path) -> None:
    state.setdefault(
        "post_processing",
        {
            "claim_extraction": {"output_path": str(claim_output), "status": "pending"},
            "final_artifact": {"output_path": str(final_output), "status": "pending"},
        },
    )


def set_post_processing_status(state: dict[str, object], key: str, status: str) -> None:
    state["post_processing"][key]["status"] = status


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


def run_agent_stage(
    stage: StageExecution,
    run_dir: Path,
    job_dir: Path,
    codex_bin: str,
    antigravity_bin: str,
) -> tuple[str, str]:
    prompt = build_agent_prompt(stage, run_dir)
    output_path = stage_output_path(run_dir, stage.output_name)
    log_path = run_dir / "logs" / f"{stage.stage_id}.{stage.agent}.driver.log"

    if stage.agent == "codex":
        cmd = [codex_bin, "exec", "--full-auto", "-C", str(job_dir), prompt]
    elif stage.agent == "antigravity":
        cmd = [antigravity_bin, "chat", "--mode", "agent", "--yes", prompt]
    else:
        raise ValueError(f"Unsupported agent: {stage.agent}")

    completed = subprocess.run(
        cmd,
        cwd=job_dir,
        capture_output=True,
        text=True,
    )
    log_path.write_text(
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
            ]
        ),
        encoding="utf-8",
    )

    if completed.returncode != 0:
        raise RuntimeError(f"Stage {stage.stage_id} failed via {stage.agent}: {completed.stderr.strip()}")
    if not is_stage_output_complete(output_path):
        raise RuntimeError(f"Stage {stage.stage_id} did not produce a completed output artifact: {output_path}")
    return stage.stage_id, "completed"


def run_stage_group(
    stages: list[StageExecution],
    run_dir: Path,
    job_dir: Path,
    state_path: Path,
    state: dict[str, object],
    codex_bin: str,
    antigravity_bin: str,
) -> None:
    runnable: list[StageExecution] = []
    for stage in stages:
        if is_stage_output_complete(stage_output_path(run_dir, stage.output_name)):
            set_stage_status(state, stage.stage_id, "completed")
        else:
            runnable.append(stage)
    for stage in runnable:
        set_stage_status(state, stage.stage_id, "running")
    save_state(state_path, state)

    if not runnable:
        return

    with ThreadPoolExecutor(max_workers=len(runnable)) as executor:
        futures = [
            executor.submit(run_agent_stage, stage, run_dir, job_dir, codex_bin, antigravity_bin)
            for stage in runnable
        ]
        for future in futures:
            stage_id, status = future.result()
            set_stage_status(state, stage_id, status)
            save_state(state_path, state)


def run_extract_claims(run_dir: Path, job_dir: Path, run_id: str, claim_output: Path, state: dict[str, object], state_path: Path) -> None:
    if claim_output.is_file():
        set_post_processing_status(state, "claim_extraction", "completed")
        save_state(state_path, state)
        return

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
        raise RuntimeError(f"Claim extraction failed: {completed.stderr.strip()}")
    set_post_processing_status(state, "claim_extraction", "completed")
    save_state(state_path, state)


def run_final_artifact(
    run_dir: Path,
    job_dir: Path,
    claim_output: Path,
    final_output: Path,
    state: dict[str, object],
    state_path: Path,
) -> None:
    if final_output.is_file():
        set_post_processing_status(state, "final_artifact", "completed")
        save_state(state_path, state)
        return

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
        raise RuntimeError(f"Final artifact generation failed: {completed.stderr.strip()}")
    set_post_processing_status(state, "final_artifact", "completed")
    save_state(state_path, state)


def main() -> int:
    args = parse_args()
    job_name, job_dir = resolve_job_path(
        job_name=args.job_name,
        job_id=args.job_id,
        job_path=args.job_path,
        jobs_root=Path(args.jobs_root).expanduser(),
        jobs_index_root=Path(args.jobs_index_root).expanduser(),
    )

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
            run_stage_group(group, run_dir, job_dir, state_path, state, args.codex_bin, args.antigravity_bin)

        run_extract_claims(run_dir, job_dir, args.run_id, claim_output, state, state_path)
        run_final_artifact(run_dir, job_dir, claim_output, final_output, state, state_path)
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

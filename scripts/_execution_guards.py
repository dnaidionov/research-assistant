#!/usr/bin/env python3

"""Isolation and integrity guards for run execution.

Stage agents run with broad filesystem access, so the runner snapshots the
inputs a stage must not modify and restores them if they changed, refreshes the
run manifest with real hashes after execution, and pins the brief/config
versions a run was scaffolded against.
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path

from _execution_plan import StageExecution
from _stage_contracts import is_structured_stage, stage_structured_output_path
from _workflow_lib import sha256_file, write_json
from _workflow_state import append_workflow_event
from run_workflow import RUN_STAGES


def ensure_job_input_snapshot(run_dir: Path, job_dir: Path) -> None:
    """Pin the brief and config versions this run was built against.

    The prompt packets embed the brief at scaffold time, so a changed brief makes
    the run incoherent: execution refuses to continue. Config drift is journaled
    as a warning; execution-relevant config drift is separately enforced by the
    execution-config snapshot guard.
    """
    snapshot_dir = run_dir / "job-inputs"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    for input_name in ("brief.md", "config.yaml"):
        current_path = job_dir / input_name
        snapshot_path = snapshot_dir / input_name
        current_bytes = current_path.read_bytes() if current_path.is_file() else b""
        if not snapshot_path.is_file():
            snapshot_path.write_bytes(current_bytes)
            append_workflow_event(run_dir, "job_input_snapshot_created", file=input_name)
            continue
        if snapshot_path.read_bytes() == current_bytes:
            continue
        if input_name == "brief.md":
            raise ValueError(
                f"brief.md changed since run {run_dir.name} was scaffolded; the run's prompt packets embed the original brief. "
                f"Start a new run for the updated brief, or restore it from {snapshot_path}."
            )
        append_workflow_event(run_dir, "job_input_drift_detected", file=input_name)
        print(
            f"Warning: {input_name} differs from the snapshot taken when run {run_dir.name} was scaffolded ({snapshot_path}).",
            file=sys.stderr,
        )


_MANIFEST_LOCK = threading.Lock()


def protected_stage_paths(stage: StageExecution, run_dir: Path, job_dir: Path) -> list[Path]:
    """Files a stage agent must not modify: job inputs and completed upstream artifacts."""
    paths = [job_dir / "brief.md", job_dir / "config.yaml"]
    stage_map = {str(candidate["id"]): candidate for candidate in RUN_STAGES}
    entry = stage_map.get(stage.stage_id)
    if entry is not None:
        for dependency_stage_id in entry.get("depends_on", []):
            dependency = stage_map[str(dependency_stage_id)]
            paths.append(run_dir / "stage-outputs" / str(dependency["output"]))
            if is_structured_stage(str(dependency_stage_id)):
                paths.append(stage_structured_output_path(run_dir, str(dependency_stage_id)))
    return [path for path in paths if path.is_file()]


def final_report_protected_paths(
    run_dir: Path,
    job_dir: Path,
    *,
    claim_register_path: Path | None = None,
    report_output_path: Path | None = None,
) -> list[Path]:
    """Files the final-report synthesis agent must not modify: job inputs, every
    completed stage artifact, the merged source registry, and the claim register.

    The report output itself (and its rejected-draft sibling) is excluded — the
    agent is allowed to write it.
    """
    paths = [job_dir / "brief.md", job_dir / "config.yaml", run_dir / "sources.json"]
    stage_outputs_dir = run_dir / "stage-outputs"
    if stage_outputs_dir.is_dir():
        paths.extend(sorted(stage_outputs_dir.iterdir()))
    if claim_register_path is not None:
        paths.append(claim_register_path)
    excluded: set[Path] = set()
    if report_output_path is not None:
        excluded.add(report_output_path)
        excluded.add(report_output_path.with_suffix(report_output_path.suffix + ".rejected.md"))
    return [path for path in paths if path.is_file() and path not in excluded]


def snapshot_protected_files(paths: list[Path]) -> dict[Path, bytes]:
    return {path: path.read_bytes() for path in paths}


def restore_protected_files(run_dir: Path, stage_id: str, snapshot: dict[Path, bytes]) -> list[str]:
    restored: list[str] = []
    for path, content in snapshot.items():
        try:
            current = path.read_bytes() if path.is_file() else None
        except OSError:
            current = None
        if current != content:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            restored.append(str(path))
    if restored:
        append_workflow_event(run_dir, "protected_artifacts_restored", stage_id=stage_id, paths=restored)
    return restored


def refresh_run_manifest(run_dir: Path) -> None:
    """Rebuild audit/manifest.json from the current run contents so the manifest reflects executed state, not just the scaffold."""
    manifest_path = run_dir / "audit" / "manifest.json"
    entries: list[dict[str, str]] = []
    for path in sorted(run_dir.rglob("*")):
        if not path.is_file() or path == manifest_path:
            continue
        try:
            digest = sha256_file(path)
        except OSError:
            continue
        entries.append({"path": str(path.relative_to(run_dir)), "sha256": digest})
    with _MANIFEST_LOCK:
        write_json(manifest_path, {"files": entries})

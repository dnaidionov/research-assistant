#!/usr/bin/env python3

"""Workflow-state load, status recomputation, and transition helpers for run execution."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Callable

from _execution_plan import STAGE_CLAIM_STAGE_IDS, stage_claim_output_path
from _workflow_lib import write_json
from _workflow_state import (
    append_workflow_event,
    derive_workflow_state_from_events,
    initial_stage_substeps,
)


def load_state(path: Path) -> dict[str, object]:
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return derive_workflow_state_from_events(path.parent)


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


def ensure_post_processing_state(
    state: dict[str, object],
    claim_output: Path,
    final_output: Path,
    report_output: Path | None = None,
) -> None:
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
    # The LLM-synthesized report is tracked separately from the deterministic
    # final artifact so a resumed run's state distinguishes "artifact written,
    # report still pending" from "both done" instead of conflating the two.
    if report_output is None:
        report_output = run_dir.parent.parent / "outputs" / f"final-report-{run_dir.name}.md"
    post_processing.setdefault("final_report", {"output_path": str(report_output), "status": "pending"})


def set_post_processing_status(state: dict[str, object], key: str, status: str) -> None:
    state["post_processing"][key]["status"] = status


def set_stage_claim_status(state: dict[str, object], stage_id: str, status: str) -> None:
    state["post_processing"]["stage_claims"][stage_id]["status"] = status


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

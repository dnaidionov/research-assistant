#!/usr/bin/env python3

from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from pathlib import Path

from _workflow_lib import write_json


STRUCTURED_STAGE_IDS = {"research-a", "research-b", "critique-a-on-b", "critique-b-on-a", "judge"}
STRUCTURED_SUBSTEPS = ("source-pass", "claim-pass", "render")
INTAKE_SUBSTEPS = ("source-pass", "fact-lineage", "normalization", "merge")
TERMINAL_STAGE_STATUSES = {"completed", "failed", "cancelled", "aborted"}
TERMINAL_POST_STATUSES = {"completed", "failed", "cancelled", "aborted"}


def workflow_events_path(run_dir: Path) -> Path:
    return run_dir / "events.jsonl"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def initial_stage_substeps(stage_id: str) -> dict[str, dict[str, str]]:
    if stage_id == "intake":
        return {substep: {"status": "pending"} for substep in INTAKE_SUBSTEPS}
    if stage_id in STRUCTURED_STAGE_IDS:
        return {substep: {"status": "pending"} for substep in STRUCTURED_SUBSTEPS}
    return {}


def append_workflow_event(run_dir: Path, event_type: str, **payload: object) -> dict[str, object]:
    event = {"event_type": event_type, "timestamp": utc_now_iso(), **payload}
    path = workflow_events_path(run_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, sort_keys=True) + "\n")
        handle.flush()
    return event


def read_workflow_events(run_dir: Path) -> list[dict[str, object]]:
    path = workflow_events_path(run_dir)
    if not path.is_file():
        return []
    events: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        events.append(json.loads(stripped))
    return events


def _ensure_stage_substeps(state: dict[str, object], stage_id: str) -> dict[str, dict[str, str]]:
    for stage in state.get("stages", []):
        if isinstance(stage, dict) and stage.get("id") == stage_id:
            substeps = stage.setdefault("substeps", {})
            if not isinstance(substeps, dict):
                substeps = {}
                stage["substeps"] = substeps
            for substep, default in initial_stage_substeps(stage_id).items():
                substeps.setdefault(substep, dict(default))
            return substeps  # type: ignore[return-value]
    raise KeyError(f"Unknown stage id: {stage_id}")


def _set_stage_status(state: dict[str, object], stage_id: str, status: str) -> None:
    for stage in state.get("stages", []):
        if isinstance(stage, dict) and stage.get("id") == stage_id:
            stage["status"] = status
            return
    raise KeyError(f"Unknown stage id: {stage_id}")


def _set_substep_status(state: dict[str, object], stage_id: str, substep: str, status: str) -> None:
    substeps = _ensure_stage_substeps(state, stage_id)
    substeps.setdefault(substep, {"status": "pending"})
    substeps[substep]["status"] = status


def _set_post_processing_status(state: dict[str, object], key: str, status: str, stage_id: str | None = None) -> None:
    post_processing = state.setdefault("post_processing", {})
    if key == "stage_claims":
        if stage_id is None:
            raise ValueError("stage_id is required for stage_claims status changes.")
        stage_claims = post_processing.setdefault("stage_claims", {})
        entry = stage_claims.setdefault(stage_id, {})
        entry["status"] = status
        return
    entry = post_processing.setdefault(key, {})
    if not isinstance(entry, dict):
        entry = {}
        post_processing[key] = entry
    entry["status"] = status


def _recompute_run_status(state: dict[str, object]) -> str:
    stage_statuses = [
        str(stage.get("status", "pending"))
        for stage in state.get("stages", [])
        if isinstance(stage, dict)
    ]
    post_statuses: list[str] = []
    post_processing = state.get("post_processing", {})
    if isinstance(post_processing, dict):
        for key, value in post_processing.items():
            if key == "stage_claims" and isinstance(value, dict):
                for item in value.values():
                    if isinstance(item, dict):
                        post_statuses.append(str(item.get("status", "pending")))
            elif isinstance(value, dict):
                post_statuses.append(str(value.get("status", "pending")))
    all_statuses = stage_statuses + post_statuses
    if any(status in {"failed", "cancelled", "aborted"} for status in all_statuses):
        return "failed"
    if any(status == "running" for status in all_statuses):
        return "running"
    if all_statuses and all(status == "completed" for status in all_statuses):
        return "completed"
    if any(status == "completed" for status in all_statuses):
        return "running"
    return "scaffolded"


def derive_workflow_state_from_events(run_dir: Path) -> dict[str, object]:
    events = read_workflow_events(run_dir)
    if not events:
        raise ValueError(f"No workflow events found for run: {run_dir}")
    first = events[0]
    if first.get("event_type") != "run_started" or not isinstance(first.get("initial_state"), dict):
        raise ValueError(f"Workflow events for {run_dir} do not start with a run_started initial_state event.")
    state = copy.deepcopy(first["initial_state"])

    def normalize_event_status(raw_status: str) -> str:
        return "running" if raw_status == "started" else raw_status

    for event in events[1:]:
        event_type = str(event.get("event_type") or "")
        if event_type == "state_checkpoint" and isinstance(event.get("state"), dict):
            state = copy.deepcopy(event["state"])
            continue
        if event_type.startswith("stage_"):
            stage_id = str(event.get("stage_id") or "")
            if stage_id:
                _set_stage_status(state, stage_id, normalize_event_status(event_type.removeprefix("stage_")))
            continue
        if event_type.startswith("substep_"):
            stage_id = str(event.get("stage_id") or "")
            substep = str(event.get("substep") or "")
            if stage_id and substep:
                _set_substep_status(state, stage_id, substep, normalize_event_status(event_type.removeprefix("substep_")))
            continue
        if event_type.startswith("post_processing_"):
            key = str(event.get("key") or "")
            stage_id = event.get("stage_id")
            if key:
                _set_post_processing_status(
                    state,
                    key,
                    normalize_event_status(event_type.removeprefix("post_processing_")),
                    str(stage_id) if isinstance(stage_id, str) else None,
                )
    state["status"] = _recompute_run_status(state)
    return state


def rebuild_workflow_state(run_dir: Path) -> dict[str, object]:
    state = derive_workflow_state_from_events(run_dir)
    write_json(run_dir / "workflow-state.json", state)
    return state

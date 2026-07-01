#!/usr/bin/env python3

"""Run-level disagreement register.

Critique stages raise unresolved disagreements with stable DIS-### ids
(assigned during normalization). The runner merges them into
runs/<run-id>/disagreements.json so disputes stay first-class run artifacts,
and records how the judge disposed of each one: kept unresolved, addressed in
the synthesis, or never mentioned.
"""

from __future__ import annotations

import json
from pathlib import Path

from _stage_contracts import DISAGREEMENT_ID_PATTERN
from _workflow_lib import write_json


def disagreement_register_path(run_dir: Path) -> Path:
    return run_dir / "disagreements.json"


def load_disagreement_register(run_dir: Path) -> dict[str, object]:
    register_path = disagreement_register_path(run_dir)
    if register_path.is_file():
        try:
            payload = json.loads(register_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict) and isinstance(payload.get("disagreements"), list):
                return payload
        except (json.JSONDecodeError, OSError):
            pass
    return {"disagreements": []}


def merge_stage_disagreements(run_dir: Path, stage_id: str, stage_payload: dict[str, object]) -> None:
    """Replace a critique stage's entries in the register with its current set.

    Replacement (not additive merge) keeps the register faithful to the stage
    artifact: a rerun critique that dropped a disagreement does not strand a
    stale open entry that the judge would then be falsely flagged for.
    """
    register = load_disagreement_register(run_dir)
    entries: list[dict[str, object]] = [
        entry
        for entry in register["disagreements"]
        if isinstance(entry, dict) and str(entry.get("raised_by")) != stage_id
    ]
    for item in stage_payload.get("unresolved_disagreements", []):
        if not isinstance(item, dict):
            continue
        dis_id = str(item.get("id") or "").strip()
        if not DISAGREEMENT_ID_PATTERN.match(dis_id):
            continue
        entries.append(
            {
                "id": dis_id,
                "raised_by": stage_id,
                "text": str(item.get("text") or "").strip(),
                "status": "open",
            }
        )
    write_json(disagreement_register_path(run_dir), {"disagreements": entries})


def apply_judge_dispositions(run_dir: Path, judge_payload: dict[str, object]) -> None:
    """Record how the judge disposed of each registered disagreement.

    An id listed in the judge's unresolved disagreements stays unresolved by
    adjudication; an id mentioned anywhere else in the judge payload counts as
    addressed; an id the judge never mentions is flagged unaddressed.
    """
    register = load_disagreement_register(run_dir)
    entries = [entry for entry in register["disagreements"] if isinstance(entry, dict)]
    if not entries:
        return
    unresolved_text = json.dumps(judge_payload.get("unresolved_disagreements", []))
    full_text = json.dumps(judge_payload)
    for entry in entries:
        dis_id = str(entry.get("id") or "")
        if dis_id in unresolved_text:
            entry["status"] = "unresolved_by_judge"
        elif dis_id in full_text:
            entry["status"] = "addressed"
        else:
            entry["status"] = "unaddressed"
    write_json(disagreement_register_path(run_dir), {"disagreements": entries})

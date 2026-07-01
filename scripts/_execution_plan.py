#!/usr/bin/env python3

"""Canonical execution plan and run-directory path layout for the automated workflow."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from run_workflow import RUN_STAGES

STAGE_CLAIM_STAGE_IDS = {"research-a", "research-b", "critique-a-on-b", "critique-b-on-a", "judge"}


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
EXECUTION_BY_STAGE_ID = {
    stage.stage_id: stage
    for group in EXECUTION_PLAN
    for stage in group
}


def stage_execution_for_id(stage_id: str) -> StageExecution:
    stage = EXECUTION_BY_STAGE_ID.get(stage_id)
    if stage is None:
        known = ", ".join(sorted(EXECUTION_BY_STAGE_ID))
        raise ValueError(f"Unknown stage '{stage_id}'. Known stages: {known}.")
    return stage


def expected_first_heading(stage_id: str) -> str | None:
    return {
        "research-a": "# Executive Summary",
        "research-b": "# Executive Summary",
        "critique-a-on-b": "# Claims That Survive Review",
        "critique-b-on-a": "# Claims That Survive Review",
        "judge": "# Supported Conclusions",
    }.get(stage_id)


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

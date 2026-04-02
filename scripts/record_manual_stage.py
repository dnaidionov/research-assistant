#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from types import SimpleNamespace

from _provider_runtime import apply_provider_runtime_policy, record_provider_stage_result
from _workflow_state import append_workflow_event
from execute_workflow import (
    STAGE_CLAIM_STAGE_IDS,
    append_manual_stage_usage_record,
    build_execution_snapshot,
    ensure_post_processing_state,
    execution_snapshot_path,
    is_stage_execution_complete,
    load_provider_catalog_from_job_config,
    load_state,
    load_execution_config,
    persist_execution_snapshot,
    resolve_provider_runtime_policy,
    resolve_stage_assignments,
    resolve_stage_required_provider_trust,
    resolve_stage_selection_override,
    save_state,
    set_stage_claim_status,
    set_stage_status,
    stage_execution_for_id,
    update_execution_snapshot_actual_assignment,
    utc_now_iso,
    StageAdapterSelection,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Record a manually executed stage attempt for an existing run.")
    parser.add_argument("--run-dir", required=True, help="Path to the existing run directory.")
    parser.add_argument("--stage", required=True, help="Stage id such as intake, research-a, or judge.")
    parser.add_argument("--status", required=True, choices=["started", "completed", "failed", "cancelled"])
    parser.add_argument("--provider-key", help="Provider key to record. If omitted, use the run's resolved stage provider.")
    parser.add_argument("--adapter", help="Adapter name to record. If omitted, use the run's resolved stage adapter.")
    parser.add_argument("--model", help="Model to record. If omitted, use the run's resolved stage model.")
    parser.add_argument("--failure-reason", help="Optional failure reason for failed or cancelled stage attempts.")
    return parser.parse_args()


def selection_from_snapshot(payload: dict[str, object], stage_id: str) -> StageAdapterSelection:
    assignments = payload.get("resolved_stage_assignments")
    if not isinstance(assignments, dict) or stage_id not in assignments:
        raise ValueError(f"Execution snapshot does not contain a resolved assignment for stage '{stage_id}'.")
    entry = assignments[stage_id]
    if not isinstance(entry, dict):
        raise ValueError(f"Invalid resolved stage assignment for '{stage_id}'.")
    provider_key = entry.get("provider_key")
    adapter = entry.get("adapter")
    model = entry.get("model")
    if not isinstance(provider_key, str) or not isinstance(adapter, str):
        raise ValueError(f"Invalid resolved stage assignment for '{stage_id}'.")
    return StageAdapterSelection(adapter_name=adapter, model=model if isinstance(model, str) else None, provider_name=provider_key)


def provider_catalog_from_snapshot(payload: dict[str, object]) -> dict[str, StageAdapterSelection]:
    catalog = payload.get("provider_catalog")
    if not isinstance(catalog, dict):
        return {}
    resolved: dict[str, StageAdapterSelection] = {}
    for provider_key, entry in catalog.items():
        if not isinstance(provider_key, str) or not isinstance(entry, dict):
            continue
        adapter = entry.get("adapter")
        model = entry.get("model")
        if not isinstance(adapter, str):
            continue
        resolved[provider_key] = StageAdapterSelection(
            adapter_name=adapter,
            model=model if isinstance(model, str) else None,
            provider_name=provider_key,
        )
    return resolved


def ensure_execution_snapshot_for_manual_run(run_dir: Path) -> dict[str, object]:
    snapshot_path = execution_snapshot_path(run_dir)
    if snapshot_path.is_file():
        return json.loads(snapshot_path.read_text(encoding="utf-8"))

    job_dir = run_dir.parent.parent
    fallback_args = SimpleNamespace(primary_adapter="codex", secondary_adapter="gemini")
    execution_config = load_execution_config(job_dir)
    configured_stage_assignments = resolve_stage_assignments(fallback_args, job_dir)
    provider_catalog = load_provider_catalog_from_job_config(job_dir) or {
        selection.provider_name or selection.adapter_name: selection
        for selection in configured_stage_assignments.values()
    }
    stage_required_trust = resolve_stage_required_provider_trust(job_dir)
    runtime_policy = resolve_provider_runtime_policy(job_dir)
    resolved_stage_assignments = apply_provider_runtime_policy(
        job_dir,
        configured_stage_assignments,
        provider_catalog,
        runtime_policy,
    )
    snapshot = build_execution_snapshot(
        job_dir=job_dir,
        run_dir=run_dir,
        args=fallback_args,
        execution_config=execution_config,
        provider_catalog=provider_catalog,
        configured_stage_assignments=configured_stage_assignments,
        resolved_stage_assignments=resolved_stage_assignments,
        stage_required_trust=stage_required_trust,
        runtime_policy=runtime_policy,
    )
    return persist_execution_snapshot(run_dir=run_dir, snapshot=snapshot)


def main() -> int:
    args = parse_args()
    run_dir = Path(args.run_dir).expanduser()
    if not run_dir.is_dir():
        print(f"Run directory does not exist: {run_dir}", file=sys.stderr)
        return 1
    if run_dir.parent.name != "runs":
        print(f"Run directory must be inside a job repo runs/ directory: {run_dir}", file=sys.stderr)
        return 1

    try:
        stage = stage_execution_for_id(args.stage)
        snapshot = ensure_execution_snapshot_for_manual_run(run_dir)
        base_selection = selection_from_snapshot(snapshot, stage.stage_id)
        provider_catalog = provider_catalog_from_snapshot(snapshot)
        actual_selection = resolve_stage_selection_override(
            base_selection=base_selection,
            provider_catalog=provider_catalog,
            provider_key_override=args.provider_key,
            adapter_override=args.adapter,
            model_override=args.model,
        )
        if args.status == "completed" and not is_stage_execution_complete(run_dir, stage):
            print(
                f"Stage {stage.stage_id} does not have a completed output artifact yet; "
                "manual completion can only be recorded after the expected stage artifact exists.",
                file=sys.stderr,
            )
            return 1
        state_path = run_dir / "workflow-state.json"
        state = load_state(state_path)
        claim_output = Path(str(state["post_processing"]["claim_extraction"]["output_path"])) if isinstance(state.get("post_processing"), dict) and isinstance(state["post_processing"].get("claim_extraction"), dict) else run_dir.parent.parent / "evidence" / f"claims-{run_dir.name}.json"
        final_output = Path(str(state["post_processing"]["final_artifact"]["output_path"])) if isinstance(state.get("post_processing"), dict) and isinstance(state["post_processing"].get("final_artifact"), dict) else run_dir.parent.parent / "outputs" / f"final-{run_dir.name}.md"
        ensure_post_processing_state(state, claim_output, final_output)
        state_status = "running" if args.status == "started" else args.status
        set_stage_status(state, stage.stage_id, state_status)
        if args.status in {"failed", "cancelled"} and stage.stage_id in STAGE_CLAIM_STAGE_IDS:
            set_stage_claim_status(state, stage.stage_id, args.status)
        save_state(state_path, state)
        append_workflow_event(run_dir, f"stage_{args.status}", stage_id=stage.stage_id, manual=True)
        update_execution_snapshot_actual_assignment(run_dir, stage.stage_id, actual_selection, args.status)
        append_manual_stage_usage_record(
            run_dir=run_dir,
            scope="stage",
            stage_id=stage.stage_id,
            status=args.status,
            provider_key=actual_selection.provider_name or actual_selection.adapter_name,
            adapter=actual_selection.adapter_name,
            model=actual_selection.model,
            started_at=utc_now_iso(),
            finished_at=utc_now_iso(),
            failure_reason=args.failure_reason,
        )
        if args.status in {"completed", "failed", "cancelled"}:
            record_provider_stage_result(
                run_dir.parent.parent,
                actual_selection.provider_name or actual_selection.adapter_name,
                stage.stage_id,
                args.status,
                run_id=run_dir.name,
                adapter_name=actual_selection.adapter_name,
                model=actual_selection.model,
            )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(f"Recorded {args.status} for {stage.stage_id} using {actual_selection.adapter_name}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

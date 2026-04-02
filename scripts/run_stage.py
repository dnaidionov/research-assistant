#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

from _provider_runtime import apply_provider_runtime_policy, record_provider_stage_result
from _repo_paths import load_repo_path_config, resolve_jobs_root
from _stage_contracts import is_structured_stage, source_registry_path, source_registry_placeholder
from _workflow_lib import write_json
from execute_workflow import (
    EXECUTION_PLAN,
    ProgressReporter,
    STAGE_CLAIM_STAGE_IDS,
    append_manual_stage_usage_record,
    build_adapter_bin_map,
    build_execution_snapshot,
    confirm_existing_run,
    ensure_post_processing_state,
    execution_snapshot_path,
    is_stage_execution_complete,
    load_execution_config,
    load_provider_catalog_from_job_config,
    load_state,
    persist_execution_snapshot,
    resolve_job_path,
    resolve_provider_runtime_policy,
    resolve_stage_assignments,
    resolve_stage_required_provider_trust,
    resolve_stage_selection_override,
    run_agent_stage,
    run_stage_claim_extraction,
    save_state,
    set_stage_claim_status,
    stage_execution_for_id,
    stage_output_path,
    transition_stage_status,
    update_execution_snapshot_actual_assignment,
    qualify_stage_adapters,
    merge_intake_sources_into_registry,
    merge_stage_sources_into_registry,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Execute a single workflow stage for an existing run.")
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--job-name")
    target.add_argument("--job-id")
    target.add_argument("--job-path")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--stage", required=True)
    parser.add_argument("--jobs-root", help="Optional override for the root directory containing job repositories.")
    parser.add_argument("--provider-key")
    parser.add_argument("--adapter")
    parser.add_argument("--model")
    parser.add_argument("--codex-bin", default="codex")
    parser.add_argument("--gemini-bin", default="gemini")
    parser.add_argument("--antigravity-bin", default="antigravity")
    parser.add_argument("--claude-bin", default="claude")
    parser.add_argument("--primary-adapter", default="codex")
    parser.add_argument("--secondary-adapter", default="gemini")
    return parser.parse_args()


def _snapshot_provider_catalog(snapshot: dict[str, object]) -> dict[str, object]:
    catalog = snapshot.get("provider_catalog")
    return catalog if isinstance(catalog, dict) else {}


def _dependency_stage_ids(stage_id: str) -> list[str]:
    for group in EXECUTION_PLAN:
        for stage in group:
            if stage.stage_id == stage_id:
                for spec in execute_run_stages():
                    if str(spec["id"]) == stage_id:
                        return list(spec.get("depends_on", []))
    return []


def execute_run_stages() -> list[dict[str, object]]:
    from run_workflow import RUN_STAGES

    return RUN_STAGES


def _resolved_assignments(args: argparse.Namespace, job_dir: Path) -> tuple[dict[str, object] | None, dict[str, object], dict[str, object] | None, dict[str, object], dict[str, object]]:
    execution_config = load_execution_config(job_dir)
    configured_stage_assignments = resolve_stage_assignments(args, job_dir)
    provider_catalog = load_provider_catalog_from_job_config(job_dir) or {
        selection.provider_name or selection.adapter_name: selection
        for selection in configured_stage_assignments.values()
    }
    runtime_policy = resolve_provider_runtime_policy(job_dir)
    stage_assignments = apply_provider_runtime_policy(job_dir, configured_stage_assignments, provider_catalog, runtime_policy)
    stage_required_trust = resolve_stage_required_provider_trust(job_dir)
    return execution_config, configured_stage_assignments, runtime_policy, provider_catalog, stage_assignments, stage_required_trust


def main() -> int:
    args = parse_args()
    reporter = ProgressReporter(sys.stdout)
    repo_root = Path(__file__).resolve().parents[1]
    try:
        repo_paths = load_repo_path_config(repo_root=repo_root)
        job_name, job_dir = resolve_job_path(
            job_name=args.job_name,
            job_id=args.job_id,
            job_path=args.job_path,
            jobs_root=resolve_jobs_root(repo_root=repo_root, cli_jobs_root=Path(args.jobs_root) if args.jobs_root else None),
            jobs_index_root=repo_paths.jobs_index_root,
        )
        stage = stage_execution_for_id(args.stage)
        run_dir = job_dir / "runs" / args.run_id
        if not run_dir.is_dir():
            raise ValueError(f"Run {args.run_id} does not exist at {run_dir}. Scaffold it first.")
        execution_config, configured_stage_assignments, runtime_policy, provider_catalog, stage_assignments, stage_required_trust = _resolved_assignments(args, job_dir)
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
        selected = resolve_stage_selection_override(
            base_selection=stage_assignments[stage.stage_id],
            provider_catalog=provider_catalog,
            provider_key_override=args.provider_key,
            adapter_override=args.adapter,
            model_override=args.model,
        )
        stage_assignments = dict(stage_assignments)
        stage_assignments[stage.stage_id] = selected
        qualify_stage_adapters(
            run_dir=run_dir,
            job_dir=job_dir,
            stage_assignments={stage.stage_id: selected},
            stage_required_trust={stage.stage_id: stage_required_trust.get(stage.stage_id, "structured_safe_smoke")},
            adapter_bins=build_adapter_bin_map(args),
        )
        for dependency_stage_id in _dependency_stage_ids(stage.stage_id):
            dependency_stage = stage_execution_for_id(str(dependency_stage_id))
            if not is_stage_execution_complete(run_dir, dependency_stage):
                raise ValueError(
                    f"Stage {stage.stage_id} depends on {dependency_stage.stage_id}, but that dependency does not have a completed output artifact yet."
                )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    state_path = run_dir / "workflow-state.json"
    state = load_state(state_path)
    claim_output = Path(str(state["post_processing"]["claim_extraction"]["output_path"]))
    final_output = Path(str(state["post_processing"]["final_artifact"]["output_path"]))
    ensure_post_processing_state(state, claim_output, final_output)
    save_state(state_path, state)
    state_lock = threading.RLock()
    source_path = source_registry_path(run_dir)
    if not source_path.exists():
        write_json(source_path, source_registry_placeholder(run_dir.name))

    try:
        transition_stage_status(run_dir, state, stage.stage_id, "started")
        save_state(state_path, state)
        update_execution_snapshot_actual_assignment(run_dir, stage.stage_id, selected, "started")
        stage_id, status = run_agent_stage(
            stage,
            run_dir,
            job_dir,
            state,
            state_path,
            state_lock,
            {stage.stage_id: selected},
            build_adapter_bin_map(args),
            reporter,
        )
        transition_stage_status(run_dir, state, stage_id, status)
        save_state(state_path, state)
        update_execution_snapshot_actual_assignment(run_dir, stage_id, selected, status)
        record_provider_stage_result(
            job_dir,
            selected.provider_name or selected.adapter_name,
            stage_id,
            status,
            run_id=run_dir.name,
            adapter_name=selected.adapter_name,
            model=selected.model,
        )
        if stage_id == "intake":
            merge_intake_sources_into_registry(run_dir)
        elif is_structured_stage(stage_id):
            merge_stage_sources_into_registry(stage_id, run_dir)
        run_stage_claim_extraction(stage_id, run_dir, job_dir, state, state_path, state_lock, reporter)
    except Exception as exc:
        transition_stage_status(run_dir, state, stage.stage_id, "failed")
        if stage.stage_id in STAGE_CLAIM_STAGE_IDS:
            set_stage_claim_status(state, stage.stage_id, "failed")
        save_state(state_path, state)
        update_execution_snapshot_actual_assignment(run_dir, stage.stage_id, selected, "failed")
        record_provider_stage_result(
            job_dir,
            selected.provider_name or selected.adapter_name,
            stage.stage_id,
            "failed",
            run_id=run_dir.name,
            adapter_name=selected.adapter_name,
            model=selected.model,
        )
        print(str(exc), file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

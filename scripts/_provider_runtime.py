#!/usr/bin/env python3

from __future__ import annotations

import json
from pathlib import Path

from _job_config import load_execution_config
from _workflow_lib import write_json


def provider_scorecard_path(job_dir: Path, provider_key: str) -> Path:
    safe = provider_key.replace("/", "-")
    return job_dir / "audit" / "provider-scorecards" / f"{safe}.json"


def list_provider_scorecard_paths(job_dir: Path) -> list[Path]:
    root = job_dir / "audit" / "provider-scorecards"
    if not root.is_dir():
        return []
    return sorted(path for path in root.glob("*.json") if path.is_file())


def _default_scorecard(provider_key: str) -> dict[str, object]:
    return {
        "provider_key": provider_key,
        "qualification_history": [],
        "live_drift": {"failed": 0, "completed": 0, "history": []},
        "stage_results": [],
        "repair": {"attempted": 0},
        "totals": {"completed": 0, "failed": 0, "cancelled": 0, "aborted": 0},
        "quarantined": False,
    }


def load_provider_scorecard(job_dir: Path, provider_key: str) -> dict[str, object]:
    path = provider_scorecard_path(job_dir, provider_key)
    if not path.is_file():
        return _default_scorecard(provider_key)
    return json.loads(path.read_text(encoding="utf-8"))


def save_provider_scorecard(job_dir: Path, provider_key: str, payload: dict[str, object]) -> Path:
    path = provider_scorecard_path(job_dir, provider_key)
    write_json(path, payload)
    return path


def should_quarantine_provider(scorecard: dict[str, object], policy: dict[str, object] | None) -> bool:
    if not policy:
        return False
    totals = scorecard.get("totals", {})
    live_drift = scorecard.get("live_drift", {})
    failure_threshold = int(policy.get("failure_threshold", 0) or 0)
    live_drift_threshold = int(policy.get("live_drift_failure_threshold", 0) or 0)
    if failure_threshold and int(totals.get("failed", 0) or 0) >= failure_threshold:
        return True
    if live_drift_threshold and int(live_drift.get("failed", 0) or 0) >= live_drift_threshold:
        return True
    return False


def record_provider_qualification(job_dir: Path, provider_key: str, report: dict[str, object], *, run_id: str | None = None) -> Path:
    payload = load_provider_scorecard(job_dir, provider_key)
    history = payload.setdefault("qualification_history", [])
    if isinstance(history, list):
        history.append(
            {
                "run_id": run_id,
                "adapter": report.get("adapter_name"),
                "trust_level": report.get("trust_level"),
                "classification": report.get("classification"),
                "profile": report.get("profile"),
                "probe_set_version": report.get("probe_set_version"),
                "adapter_version": report.get("adapter_version"),
            }
        )
    return save_provider_scorecard(job_dir, provider_key, payload)


def record_provider_stage_result(
    job_dir: Path,
    provider_key: str,
    stage_id: str,
    status: str,
    *,
    run_id: str | None = None,
    adapter_name: str | None = None,
    model: str | None = None,
) -> Path:
    payload = load_provider_scorecard(job_dir, provider_key)
    stage_results = payload.setdefault("stage_results", [])
    if isinstance(stage_results, list):
        stage_results.append(
            {
                "run_id": run_id,
                "stage_id": stage_id,
                "status": status,
                "adapter_name": adapter_name,
                "model": model,
            }
        )
    totals = payload.setdefault("totals", {})
    if isinstance(totals, dict):
        totals[status] = int(totals.get(status, 0) or 0) + 1
    return save_provider_scorecard(job_dir, provider_key, payload)


def record_live_drift_result(
    job_dir: Path,
    provider_key: str,
    status: str,
    *,
    family: str | None = None,
    adapter_name: str | None = None,
    model: str | None = None,
) -> Path:
    payload = load_provider_scorecard(job_dir, provider_key)
    live_drift = payload.setdefault("live_drift", {"failed": 0, "completed": 0, "history": []})
    if isinstance(live_drift, dict):
        live_drift[status] = int(live_drift.get(status, 0) or 0) + 1
        history = live_drift.setdefault("history", [])
        if isinstance(history, list):
            history.append({"status": status, "family": family, "adapter_name": adapter_name, "model": model})
    return save_provider_scorecard(job_dir, provider_key, payload)


def record_provider_repair_attempt(
    job_dir: Path,
    provider_key: str,
    *,
    stage_id: str,
    run_id: str | None = None,
) -> Path:
    payload = load_provider_scorecard(job_dir, provider_key)
    repair = payload.setdefault("repair", {"attempted": 0, "history": []})
    if isinstance(repair, dict):
        repair["attempted"] = int(repair.get("attempted", 0) or 0) + 1
        history = repair.setdefault("history", [])
        if isinstance(history, list):
            history.append({"run_id": run_id, "stage_id": stage_id})
    return save_provider_scorecard(job_dir, provider_key, payload)


def apply_provider_runtime_policy(
    job_dir: Path,
    stage_assignments: dict[str, object],
    provider_catalog: dict[str, object],
    runtime_policy: dict[str, object] | None,
) -> dict[str, object]:
    if not runtime_policy:
        return dict(stage_assignments)
    quarantine_policy = runtime_policy.get("quarantine")
    stage_fallbacks = runtime_policy.get("stage_provider_fallbacks", {})
    if stage_fallbacks is None:
        stage_fallbacks = {}
    updated = dict(stage_assignments)
    for stage_id, selection in stage_assignments.items():
        provider_key = getattr(selection, "provider_name", None) or getattr(selection, "adapter_name", None)
        if not isinstance(provider_key, str):
            continue
        scorecard = load_provider_scorecard(job_dir, provider_key)
        quarantined = should_quarantine_provider(scorecard, quarantine_policy if isinstance(quarantine_policy, dict) else None)
        scorecard["quarantined"] = quarantined
        save_provider_scorecard(job_dir, provider_key, scorecard)
        if not quarantined:
            continue
        fallback_provider = stage_fallbacks.get(stage_id) if isinstance(stage_fallbacks, dict) else None
        if fallback_provider is None:
            raise ValueError(f"Provider '{provider_key}' is quarantined and no fallback is configured for stage '{stage_id}'.")
        if fallback_provider not in provider_catalog:
            raise ValueError(f"Provider fallback '{fallback_provider}' for stage '{stage_id}' is not defined.")
        updated[stage_id] = provider_catalog[fallback_provider]
    return updated


def record_live_drift_for_providers(job_dir: Path, *, status: str, family: str | None = None) -> list[str]:
    execution = load_execution_config(job_dir)
    if not execution:
        return []
    providers = execution.get("providers")
    if not isinstance(providers, dict):
        return []
    updated: list[str] = []
    for provider_key, provider_config in providers.items():
        adapter_name = provider_config.get("adapter") if isinstance(provider_config, dict) else None
        model = provider_config.get("model") if isinstance(provider_config, dict) else None
        record_live_drift_result(
            job_dir,
            str(provider_key),
            status,
            family=family,
            adapter_name=str(adapter_name) if isinstance(adapter_name, str) else None,
            model=str(model) if isinstance(model, str) else None,
        )
        updated.append(str(provider_key))
    return sorted(updated)


def build_provider_scorecard_report(job_dir: Path) -> dict[str, object]:
    providers: list[dict[str, object]] = []
    for path in list_provider_scorecard_paths(job_dir):
        payload = json.loads(path.read_text(encoding="utf-8"))
        providers.append(payload)
    providers.sort(key=lambda item: str(item.get("provider_key") or ""))
    ok = all(not bool(item.get("quarantined")) and int(item.get("totals", {}).get("failed", 0) or 0) == 0 for item in providers)
    return {
        "job_dir": str(job_dir),
        "ok": ok,
        "providers": providers,
    }

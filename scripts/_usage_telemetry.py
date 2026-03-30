from __future__ import annotations

import json
import re
import threading
import time
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


_USAGE_LOCK = threading.RLock()


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def usage_records_path(run_dir: Path) -> Path:
    return run_dir / "audit" / "usage" / "usage-records.json"


def qualification_usage_records_path(run_dir: Path) -> Path:
    return run_dir / "audit" / "usage" / "qualification-usage-records.json"


def usage_summary_path(run_dir: Path) -> Path:
    return run_dir / "audit" / "usage" / "usage-summary.json"


def _load_records(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, list) else []


def _write_records(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")


def _usage_totals(records: list[dict[str, Any]]) -> dict[str, Any]:
    usage_status_counts = {"reported": 0, "estimated": 0, "unavailable": 0}
    status_counts: dict[str, int] = defaultdict(int)
    total_duration = 0
    total_prompt_bytes = 0
    total_stdout_bytes = 0
    total_stderr_bytes = 0
    reported_input_tokens = 0
    reported_output_tokens = 0
    reported_total_tokens = 0
    reported_token_records = 0

    for record in records:
        usage_status = str(record.get("usage_status", "unavailable"))
        if usage_status not in usage_status_counts:
            usage_status = "unavailable"
        usage_status_counts[usage_status] += 1
        status_counts[str(record.get("status", "unknown"))] += 1
        total_duration += int(record.get("duration_ms") or 0)
        total_prompt_bytes += int(record.get("prompt_bytes") or 0)
        total_stdout_bytes += int(record.get("stdout_bytes") or 0)
        total_stderr_bytes += int(record.get("stderr_bytes") or 0)
        if record.get("input_tokens") is not None:
            reported_input_tokens += int(record["input_tokens"])
            reported_token_records += 1
        if record.get("output_tokens") is not None:
            reported_output_tokens += int(record["output_tokens"])
        if record.get("total_tokens") is not None:
            reported_total_tokens += int(record["total_tokens"])

    return {
        "records": len(records),
        "reported_records": usage_status_counts["reported"],
        "estimated_records": usage_status_counts["estimated"],
        "unavailable_records": usage_status_counts["unavailable"],
        "reported_token_records": reported_token_records,
        "duration_ms": total_duration,
        "prompt_bytes": total_prompt_bytes,
        "stdout_bytes": total_stdout_bytes,
        "stderr_bytes": total_stderr_bytes,
        "input_tokens": reported_input_tokens if reported_token_records else None,
        "output_tokens": reported_output_tokens if reported_token_records else None,
        "total_tokens": reported_total_tokens if reported_token_records else None,
        "statuses": dict(status_counts),
    }


def _group_totals(records: list[dict[str, Any]], field: str) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        key = str(record.get(field) or "<none>")
        grouped[key].append(record)
    return {key: _usage_totals(items) for key, items in sorted(grouped.items())}


def _summary_for_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "totals": _usage_totals(records),
        "by_stage": _group_totals(records, "stage_id"),
        "by_provider": _group_totals(records, "provider_key"),
        "by_adapter": _group_totals(records, "adapter"),
        "by_model": _group_totals(records, "model"),
        "by_scope": _group_totals(records, "scope"),
    }


def refresh_usage_summary(run_dir: Path) -> None:
    execution_records = _load_records(usage_records_path(run_dir))
    qualification_records = _load_records(qualification_usage_records_path(run_dir))
    payload = {
        "execution": _summary_for_records(execution_records),
        "qualification": _summary_for_records(qualification_records),
    }
    path = usage_summary_path(run_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def append_usage_record(run_dir: Path, record: dict[str, Any], *, qualification: bool = False) -> None:
    path = qualification_usage_records_path(run_dir) if qualification else usage_records_path(run_dir)
    with _USAGE_LOCK:
        records = _load_records(path)
        records.append(record)
        _write_records(path, records)
        refresh_usage_summary(run_dir)


def extract_reported_token_counts(stdout: str, stderr: str) -> tuple[str, int | None, int | None, int | None]:
    combined = "\n".join(part for part in (stdout, stderr) if part)
    patterns = {
        "input_tokens": [
            r'"input_tokens"\s*:\s*(\d+)',
            r'"prompt_tokens"\s*:\s*(\d+)',
            r"\binput_tokens\s*=\s*(\d+)",
        ],
        "output_tokens": [
            r'"output_tokens"\s*:\s*(\d+)',
            r'"completion_tokens"\s*:\s*(\d+)',
            r"\boutput_tokens\s*=\s*(\d+)",
        ],
        "total_tokens": [
            r'"total_tokens"\s*:\s*(\d+)',
            r"\btotal_tokens\s*=\s*(\d+)",
        ],
    }
    values: dict[str, int | None] = {}
    for field, field_patterns in patterns.items():
        values[field] = None
        for pattern in field_patterns:
            match = re.search(pattern, combined, flags=re.IGNORECASE)
            if match:
                values[field] = int(match.group(1))
                break
    if values["input_tokens"] is not None and values["output_tokens"] is not None and values["total_tokens"] is None:
        values["total_tokens"] = values["input_tokens"] + values["output_tokens"]
    usage_status = "reported" if any(value is not None for value in values.values()) else "unavailable"
    return usage_status, values["input_tokens"], values["output_tokens"], values["total_tokens"]


def build_usage_record(
    *,
    scope: str,
    stage_id: str,
    status: str,
    provider_key: str,
    adapter: str,
    model: str | None,
    started_at: str,
    finished_at: str,
    duration_ms: int,
    prompt_text: str | None,
    stdout: str,
    stderr: str,
    attempt_index: int = 1,
    failure_reason: str | None = None,
    substep: str | None = None,
    probe_name: str | None = None,
    profile: str | None = None,
    usage_status: str | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    total_tokens: int | None = None,
) -> dict[str, Any]:
    derived_usage_status, derived_input, derived_output, derived_total = extract_reported_token_counts(stdout, stderr)
    final_usage_status = usage_status or derived_usage_status
    final_input_tokens = input_tokens if input_tokens is not None else derived_input
    final_output_tokens = output_tokens if output_tokens is not None else derived_output
    final_total_tokens = total_tokens if total_tokens is not None else derived_total
    prompt_bytes = len((prompt_text or "").encode("utf-8"))
    prompt_chars = len(prompt_text or "")
    return {
        "scope": scope,
        "stage_id": stage_id,
        "substep": substep,
        "probe_name": probe_name,
        "profile": profile,
        "provider_key": provider_key,
        "adapter": adapter,
        "model": model,
        "status": status,
        "usage_status": final_usage_status,
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_ms": duration_ms,
        "prompt_chars": prompt_chars,
        "prompt_bytes": prompt_bytes,
        "stdout_bytes": len(stdout.encode("utf-8")),
        "stderr_bytes": len(stderr.encode("utf-8")),
        "input_tokens": final_input_tokens,
        "output_tokens": final_output_tokens,
        "total_tokens": final_total_tokens,
        "estimated_input_tokens": None,
        "estimated_output_tokens": None,
        "estimated_total_tokens": None,
        "attempt_index": attempt_index,
        "failure_reason": failure_reason,
    }


def build_manual_usage_record(
    *,
    scope: str,
    stage_id: str,
    status: str,
    provider_key: str,
    adapter: str,
    model: str | None,
    started_at: str,
    finished_at: str,
    prompt_text: str | None = None,
    stdout: str = "",
    stderr: str = "",
    failure_reason: str | None = None,
    substep: str | None = None,
    attempt_index: int = 1,
) -> dict[str, Any]:
    started_dt = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
    finished_dt = datetime.fromisoformat(finished_at.replace("Z", "+00:00"))
    duration_ms = max(0, int((finished_dt - started_dt).total_seconds() * 1000))
    return build_usage_record(
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
        stdout=stdout,
        stderr=stderr,
        attempt_index=attempt_index,
        failure_reason=failure_reason,
        substep=substep,
        usage_status="unavailable",
    )


def timed_operation_bounds() -> tuple[float, str]:
    started = time.time()
    return started, utc_now_iso()


def finish_operation(started_monotonic: float) -> tuple[str, int]:
    finished_at = utc_now_iso()
    duration_ms = max(0, int((time.time() - started_monotonic) * 1000))
    return finished_at, duration_ms

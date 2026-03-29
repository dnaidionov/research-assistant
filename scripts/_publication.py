#!/usr/bin/env python3

from __future__ import annotations

from pathlib import Path

from _claim_model import claim_register_errors, extract_reference_ids
from _research_quality import quality_gate_errors
from _stage_contracts import normalize_source_record


def referenced_source_publication_errors(reference_ids: list[str], source_index: dict[str, dict[str, str]]) -> list[str]:
    errors: list[str] = []
    for reference_id in reference_ids:
        record = source_index.get(reference_id)
        if record is None:
            errors.append(f"Cannot generate final artifact: referenced source {reference_id} is unresolved.")
            continue
        source_class = record.get("source_class", "")
        policy_outcome = record.get("policy_outcome", "")
        policy_notes = record.get("policy_notes", [])
        if isinstance(policy_notes, str):
            policy_detail = policy_notes
        elif isinstance(policy_notes, list):
            policy_detail = "; ".join(str(note) for note in policy_notes if str(note).strip())
        else:
            policy_detail = ""
        if policy_outcome == "blocked":
            detail = f" {policy_detail}" if policy_detail else ""
            errors.append(f"Cannot generate final artifact: referenced source {reference_id} is blocked by source policy.{detail}")
            continue
        if source_class == "recovered_provisional":
            errors.append(f"Cannot generate final artifact: referenced source {reference_id} is provisional.")
        if source_class == "workflow_provenance":
            errors.append(f"Cannot generate final artifact: referenced source {reference_id} is workflow provenance, not user-facing evidence.")
    return errors


def claim_register_publication_errors(payload: dict[str, object]) -> list[str]:
    return claim_register_errors(payload)


def final_artifact_input_errors(judge_text: str, payload: dict[str, object]) -> list[str]:
    errors = claim_register_publication_errors(payload)
    if not judge_text.strip():
        errors.append("Cannot generate final artifact: judge artifact is empty.")
    return errors

def infer_job_dir_from_judge_path(judge_path: Path) -> Path | None:
    try:
        runs_dir = judge_path.parents[2]
        if runs_dir.name != "runs":
            return None
        return judge_path.parents[3]
    except IndexError:
        return None


def normalize_reference_record(reference_id: str, record: dict[str, object], judge_path: Path) -> dict[str, str]:
    normalized_source = normalize_source_record(record)
    title = str(normalized_source.get("title") or reference_id)
    source_type = str(normalized_source.get("type") or "").strip()
    authority = str(normalized_source.get("authority") or "").strip()
    locator = str(normalized_source.get("locator") or "").strip()
    source_class = str(normalized_source.get("source_class") or "").strip()
    job_dir = infer_job_dir_from_judge_path(judge_path)

    if source_class == "job_input" and job_dir is not None:
        lower_title = title.lower()
        lower_locator = locator.lower()
        candidate_path: Path | None = None
        if source_type == "project_brief" or "brief" in lower_title or lower_locator.endswith("brief.md") or "/prompt-packets/" in lower_locator:
            candidate_path = job_dir / "brief.md"
            title = "Job brief"
            authority = "Job input"
        elif "config" in lower_title or lower_locator.endswith("config.yaml"):
            candidate_path = job_dir / "config.yaml"
            title = "Job config"
            authority = "Job input"
        if candidate_path is not None and candidate_path.is_file():
            title = "Job brief"
            locator = str(candidate_path)
            if candidate_path.name == "config.yaml":
                title = "Job config"

    return {
        "id": reference_id,
        "title": title,
        "type": source_type,
        "authority": authority,
        "source_class": source_class,
        "locator": locator,
        "policy_outcome": str(normalized_source.get("policy_outcome") or ""),
        "policy_notes": normalized_source.get("policy_notes", []),
    }


def build_source_index(judge_structured_payload: dict[str, object] | None, judge_path: Path) -> dict[str, dict[str, str]]:
    if not judge_structured_payload:
        return {}
    index: dict[str, dict[str, str]] = {}
    for source in judge_structured_payload.get("sources", []):
        if not isinstance(source, dict):
            continue
        source_id = source.get("id")
        if not isinstance(source_id, str) or not source_id.strip():
            continue
        index[source_id] = normalize_reference_record(source_id, source, judge_path)
    return index


def publication_readiness_errors(
    judge_text: str,
    payload: dict[str, object],
    *,
    judge_structured_payload: dict[str, object] | None = None,
    judge_path: Path | None = None,
    quality_policy: dict[str, object] | None = None,
) -> list[str]:
    errors = final_artifact_input_errors(judge_text, payload)
    if judge_structured_payload is None or judge_path is None:
        return errors
    claims = payload.get("claims", [])
    if not isinstance(claims, list):
        return errors
    source_index = build_source_index(judge_structured_payload, judge_path)
    reference_ids = extract_reference_ids([claim for claim in claims if isinstance(claim, dict)])
    errors.extend(referenced_source_publication_errors(reference_ids, source_index))
    quality_errors = quality_gate_errors({"claims": [claim for claim in claims if isinstance(claim, dict)]}, source_index, quality_policy)
    errors.extend(quality_errors)
    return errors

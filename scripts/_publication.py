#!/usr/bin/env python3

from __future__ import annotations


def referenced_source_publication_errors(reference_ids: list[str], source_index: dict[str, dict[str, str]]) -> list[str]:
    errors: list[str] = []
    for reference_id in reference_ids:
        record = source_index.get(reference_id)
        if record is None:
            continue
        source_class = record.get("source_class", "")
        if source_class == "recovered_provisional":
            errors.append(f"Cannot generate final artifact: referenced source {reference_id} is provisional.")
        if source_class == "workflow_provenance":
            errors.append(f"Cannot generate final artifact: referenced source {reference_id} is workflow provenance, not user-facing evidence.")
    return errors


def claim_register_publication_errors(payload: dict[str, object]) -> list[str]:
    summary = payload.get("summary", {})
    if not isinstance(summary, dict):
        return ["Claim register summary is missing or invalid."]

    errors: list[str] = []
    if summary.get("uncited_fact_ids"):
        errors.append("Claim register contains uncited facts and is not ready for final artifact generation.")
    if summary.get("uncited_inference_ids"):
        errors.append("Claim register contains uncited inferences and is not ready for final artifact generation.")
    if summary.get("provenance_only_fact_ids"):
        errors.append("Claim register contains provenance-only supported facts and is not ready for final artifact generation.")
    if summary.get("claims_with_unclassified_markers"):
        errors.append("Claim register contains unclassified markers and is not ready for final artifact generation.")
    return errors


def final_artifact_input_errors(judge_text: str, payload: dict[str, object]) -> list[str]:
    errors = claim_register_publication_errors(payload)
    if not judge_text.strip():
        errors.append("Cannot generate final artifact: judge artifact is empty.")
    return errors

#!/usr/bin/env python3

from __future__ import annotations

import re
from collections import Counter


WORKFLOW_MARKER_PATTERN = re.compile(
    r"^(?:PASS|CRIT|JUDGE|INTAKE|RUN|STAGE|WORK[_-]?ORDER|ARTIFACT)(?:[-_][A-Z0-9]+)*$",
    re.IGNORECASE,
)

TRUTH_GATED_CLAIM_TYPES = {"fact", "inference", "decision", "recommendation"}


def _is_truth_gated(claim: dict[str, object]) -> bool:
    return str(claim.get("type") or "").strip() in TRUTH_GATED_CLAIM_TYPES


def _recommendation_is_supported(claim: dict[str, object]) -> bool:
    if str(claim.get("type") or "").strip() != "recommendation":
        return True
    evidence_sources = claim.get("evidence_sources")
    if not isinstance(evidence_sources, list) or not evidence_sources:
        return False
    rationale_fields = (
        claim.get("rationale"),
        claim.get("recommendation_basis"),
        claim.get("risk_accounting"),
        claim.get("unresolved_risks"),
        claim.get("claim_dependencies"),
    )
    for value in rationale_fields:
        if isinstance(value, str) and value.strip():
            return True
        if isinstance(value, list) and value:
            return True
    return False


def summarize_claims(claims: list[dict[str, object]]) -> dict[str, object]:
    claim_type_counts = Counter(str(claim["type"]) for claim in claims)
    truth_gated_claim_type_counts = Counter(
        str(claim["type"]) for claim in claims if _is_truth_gated(claim)
    )
    uncited_facts = [
        claim["id"]
        for claim in claims
        if claim["type"] == "fact" and not claim.get("evidence_sources")
    ]
    uncited_inferences = [
        claim["id"]
        for claim in claims
        if claim["type"] == "inference" and not claim.get("evidence_sources")
    ]
    provenance_only_facts = [
        claim["id"]
        for claim in claims
        if claim["type"] == "fact" and not claim.get("evidence_sources") and claim.get("provenance")
    ]
    claims_with_unclassified_markers = [
        claim["id"] for claim in claims if claim.get("unclassified_markers")
    ]
    uncited_truth_gated_ids = [
        claim["id"]
        for claim in claims
        if _is_truth_gated(claim) and not claim.get("evidence_sources")
    ]
    unsupported_recommendations = [
        claim["id"] for claim in claims if not _recommendation_is_supported(claim)
    ]
    return {
        "claim_type_counts": dict(sorted(claim_type_counts.items())),
        "truth_gated_claim_type_counts": dict(sorted(truth_gated_claim_type_counts.items())),
        "claims_with_unclassified_markers": claims_with_unclassified_markers,
        "assumption_count": claim_type_counts.get("assumption", 0),
        "fact_count": claim_type_counts.get("fact", 0),
        "inference_count": claim_type_counts.get("inference", 0),
        "provenance_only_fact_ids": provenance_only_facts,
        "uncited_fact_ids": uncited_facts,
        "uncited_inference_ids": uncited_inferences,
        "uncited_truth_gated_ids": uncited_truth_gated_ids,
        "unsupported_recommendation_ids": unsupported_recommendations,
    }


def build_claim_register(claims: list[dict[str, object]]) -> dict[str, object]:
    return {
        "claims": claims,
        "summary": summarize_claims(claims),
    }


def claim_register_errors(payload: dict[str, object]) -> list[str]:
    summary = payload.get("summary", {})
    if not isinstance(summary, dict):
        return ["Claim register summary is missing or invalid."]

    errors: list[str] = []
    if summary.get("uncited_fact_ids"):
        errors.append("Claim register contains uncited facts and is not ready for final artifact generation.")
    if summary.get("uncited_inference_ids"):
        errors.append("Claim register contains uncited inferences and is not ready for final artifact generation.")
    if summary.get("uncited_truth_gated_ids"):
        errors.append("Claim register contains uncited truth-gated claims and is not ready for final artifact generation.")
    if summary.get("provenance_only_fact_ids"):
        errors.append("Claim register contains provenance-only supported facts and is not ready for final artifact generation.")
    if summary.get("unsupported_recommendation_ids"):
        errors.append("Claim register contains unsupported recommendations and is not ready for final artifact generation.")
    if summary.get("claims_with_unclassified_markers"):
        errors.append("Claim register contains unclassified markers and is not ready for final artifact generation.")
    return errors


def extract_reference_ids(claims: list[dict[str, object]]) -> list[str]:
    seen: set[str] = set()
    refs: list[str] = []
    for claim in claims:
        for source in claim.get("evidence_sources", []):
            normalized = str(source)
            if not normalized or WORKFLOW_MARKER_PATTERN.match(normalized):
                continue
            if normalized not in seen:
                seen.add(normalized)
                refs.append(normalized)
    return refs

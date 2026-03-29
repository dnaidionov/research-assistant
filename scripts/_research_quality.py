#!/usr/bin/env python3

from __future__ import annotations


TRUTH_GATED_TYPES = {"fact", "inference", "decision", "recommendation"}
ADJUDICATION_TYPES = {"evaluation", "open_question", "evidence_gap"}


def quality_gate_errors(
    claim_register: dict[str, object],
    source_index: dict[str, dict[str, object]],
    policy: dict[str, object] | None = None,
) -> list[str]:
    if policy and policy.get("enabled") is False:
        return []
    claims = [claim for claim in claim_register.get("claims", []) if isinstance(claim, dict)]
    errors: list[str] = []

    if policy is None:
        policy = {}

    if policy.get("one_sided_source_selection"):
        evidence_sources: set[str] = set()
        for claim in claims:
            if str(claim.get("type") or "") not in TRUTH_GATED_TYPES:
                continue
            for source_id in claim.get("evidence_sources", []):
                if isinstance(source_id, str):
                    evidence_sources.add(source_id)
        if len(evidence_sources) <= 1 and evidence_sources:
            errors.append("Quality gate failed: research relies on a one-sided source base.")

    if policy.get("disfavored_recommendation_support"):
        for claim in claims:
            if str(claim.get("type") or "") != "recommendation":
                continue
            recommendation_sources = [
                source_index.get(source_id, {})
                for source_id in claim.get("evidence_sources", [])
                if isinstance(source_id, str)
            ]
            if recommendation_sources and all(str(source.get("policy_outcome") or "") == "disfavored" for source in recommendation_sources):
                errors.append(
                    f"Quality gate failed: recommendation {claim.get('id', '<unknown>')} is supported only by disfavored sources."
                )

    required_dimensions = policy.get("required_dimensions")
    if isinstance(required_dimensions, list) and required_dimensions:
        searchable_text = "\n".join(
            [
                str(claim.get("text") or "")
                + "\n"
                + str(claim.get("section") or "")
                for claim in claims
                if str(claim.get("type") or "") in TRUTH_GATED_TYPES
            ]
        ).lower()
        for dimension in required_dimensions:
            if not isinstance(dimension, str) or not dimension.strip():
                continue
            if dimension.strip().lower() not in searchable_text:
                errors.append(f"Quality gate failed: missing required comparison dimension '{dimension}'.")

    if policy.get("evidence_quality_mismatch"):
        for claim in claims:
            claim_type = str(claim.get("type") or "")
            if claim_type not in TRUTH_GATED_TYPES:
                continue
            evidence_source_ids = [source_id for source_id in claim.get("evidence_sources", []) if isinstance(source_id, str)]
            if not evidence_source_ids:
                continue
            evidence_sources = [source_index.get(source_id, {}) for source_id in evidence_source_ids]
            if evidence_sources and all(str(source.get("policy_outcome") or "") in {"allowed_with_warning", "disfavored"} for source in evidence_sources):
                errors.append(
                    f"Quality gate failed: evidence-quality mismatch for {claim_type} {claim.get('id', '<unknown>')}."
                )

    if policy.get("disagreement_collapse"):
        summary = claim_register.get("summary", {})
        source_conflict_count = 0
        disagreement_count = 0
        if isinstance(summary, dict):
            source_conflict_count = int(summary.get("source_conflict_count", 0) or 0)
            disagreement_count = int(summary.get("disagreement_count", 0) or 0)
        has_adjudication_claim = any(str(claim.get("type") or "") in ADJUDICATION_TYPES for claim in claims)
        if source_conflict_count > 0 and disagreement_count == 0 and not has_adjudication_claim:
            errors.append("Quality gate failed: disagreement collapse detected; source conflict is present but unresolved disagreement is not preserved.")
    return errors

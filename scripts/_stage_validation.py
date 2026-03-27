#!/usr/bin/env python3

from __future__ import annotations

import re
from dataclasses import dataclass

from _stage_contracts import (
    build_claim_map_from_stage_json,
    collect_numbered_items,
    collect_section_entries,
    extract_evidence_sources,
    normalize_stage_citations,
    parse_markdown_sections,
    render_stage_markdown_from_json,
    source_quality_warnings,
    validate_stage_json,
)


CONFIDENCE_LABEL_PATTERN = re.compile(r"\bconfidence\s*:\s*(low|medium|high)\b", re.IGNORECASE)


@dataclass(frozen=True)
class StageValidationResult:
    stage_id: str
    normalized_payload: dict[str, object]
    structured_errors: list[str]
    structured_warnings: list[str]
    markdown_errors: list[str]
    original_markdown_errors: list[str]
    canonical_markdown: str
    should_rewrite_markdown: bool
    claim_map: dict[str, object] | None


def has_evidence_marker(text: str) -> bool:
    return bool(extract_evidence_sources(text))


def validate_stage_markdown_contract(stage_id: str, markdown: str) -> list[str]:
    sections = parse_markdown_sections(markdown)
    errors: list[str] = []

    if stage_id in {"research-a", "research-b"}:
        facts = collect_numbered_items(sections.get("Facts", []))
        inferences = collect_numbered_items(sections.get("Inferences", []))
        for index, item in enumerate(facts, start=1):
            if not has_evidence_marker(item):
                errors.append(f"Facts item {index} lacks an external evidence citation.")
        for index, item in enumerate(inferences, start=1):
            if not has_evidence_marker(item):
                errors.append(f"Inferences item {index} lacks an external evidence citation.")
            if not CONFIDENCE_LABEL_PATTERN.search(item):
                errors.append(f"Inferences item {index} lacks an explicit confidence label.")
        return errors

    if stage_id == "judge":
        conclusions = collect_numbered_items(sections.get("Supported Conclusions", []))
        inferences = collect_numbered_items(sections.get("Inferences And Synthesis Judgments", []))
        for index, item in enumerate(conclusions, start=1):
            if not has_evidence_marker(item):
                errors.append(f"Supported Conclusions item {index} lacks an external evidence citation.")
        for index, item in enumerate(inferences, start=1):
            if not has_evidence_marker(item):
                errors.append(f"Inferences And Synthesis Judgments item {index} lacks an external evidence citation.")
            if not CONFIDENCE_LABEL_PATTERN.search(item):
                errors.append(f"Inferences And Synthesis Judgments item {index} lacks an explicit confidence label.")
        return errors

    if stage_id in {"critique-a-on-b", "critique-b-on-a"}:
        required_sections = [
            "Claims That Survive Review",
            "Unsupported Claims",
            "Weak Sources Or Citation Problems",
            "Omissions And Missing Alternatives",
            "Overreach And Overconfident Inference",
            "Unresolved Disagreements For Judge",
            "Overall Critique Summary",
        ]
        for section_name in required_sections:
            if section_name not in sections:
                errors.append(f"Missing required section: {section_name}.")
        summary_entries = collect_section_entries(sections.get("Overall Critique Summary", []))
        if not summary_entries:
            errors.append("Overall Critique Summary must contain at least one item.")
        else:
            for index, item in enumerate(summary_entries, start=1):
                if not CONFIDENCE_LABEL_PATTERN.search(item):
                    errors.append(f"Overall Critique Summary item {index} lacks an explicit confidence label.")
        return errors

    return errors


def validate_structured_stage_artifact(
    stage_id: str,
    payload: dict[str, object],
    source_registry: dict[str, object],
    markdown: str,
    dependency_payloads: list[dict[str, object]] | None = None,
) -> StageValidationResult:
    if dependency_payloads and stage_id in {"critique-a-on-b", "critique-b-on-a"}:
        target_claim_catalog: list[dict[str, object]] = []
        for dependency_payload in dependency_payloads:
            if not isinstance(dependency_payload, dict):
                continue
            for field_name in ("facts", "supported_conclusions"):
                for item in dependency_payload.get(field_name, []):
                    if not isinstance(item, dict):
                        continue
                    if isinstance(item.get("id"), str) and isinstance(item.get("evidence_sources"), list):
                        target_claim_catalog.append(
                            {
                                "id": item["id"],
                                "evidence_sources": [source for source in item["evidence_sources"] if isinstance(source, str)],
                            }
                        )
        if target_claim_catalog:
            payload = dict(payload)
            payload["target_claim_catalog"] = target_claim_catalog
    normalized_payload = normalize_stage_citations(stage_id, payload)
    structured_errors = validate_stage_json(stage_id, normalized_payload, source_registry)
    structured_warnings = source_quality_warnings(normalized_payload)
    original_markdown_errors = validate_stage_markdown_contract(stage_id, markdown)
    if structured_errors:
        return StageValidationResult(
            stage_id=stage_id,
            normalized_payload=normalized_payload,
            structured_errors=structured_errors,
            structured_warnings=structured_warnings,
            markdown_errors=original_markdown_errors,
            original_markdown_errors=original_markdown_errors,
            canonical_markdown=markdown,
            should_rewrite_markdown=False,
            claim_map=None,
        )

    canonical_markdown = markdown
    should_rewrite_markdown = False
    markdown_errors = original_markdown_errors
    if original_markdown_errors:
        canonical_markdown = render_stage_markdown_from_json(stage_id, normalized_payload)
        markdown_errors = validate_stage_markdown_contract(stage_id, canonical_markdown)
        should_rewrite_markdown = not markdown_errors and canonical_markdown != markdown

    claim_map = build_claim_map_from_stage_json(stage_id, normalized_payload)
    return StageValidationResult(
        stage_id=stage_id,
        normalized_payload=normalized_payload,
        structured_errors=[],
        structured_warnings=structured_warnings,
        markdown_errors=markdown_errors,
        original_markdown_errors=original_markdown_errors,
        canonical_markdown=canonical_markdown,
        should_rewrite_markdown=should_rewrite_markdown,
        claim_map=claim_map,
    )

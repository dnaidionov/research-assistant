#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from _job_config import load_quality_policy_from_path
from _publication import (
    build_source_index,
    extract_reference_ids,
    publication_readiness_errors,
    referenced_source_publication_errors,
)
from _workflow_lib import write_text


REQUIRED_SECTIONS = [
    "# Executive Summary",
    "# Options Comparison",
    "# Recommendation",
    "# Confidence And Uncertainty",
    "# References",
    "# Open Questions",
]
JUDGE_SECTION_PATTERN = re.compile(r"^#\s+(.+)$", re.MULTILINE)
PLACEHOLDER_PATTERN = re.compile(r"\{.+?\}|TODO|not started|placeholder", re.IGNORECASE)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a structured operator-reviewed final artifact from judge output and a claim register."
    )
    parser.add_argument("--judge-input", required=True, help="Path to the judge markdown artifact.")
    parser.add_argument("--judge-structured-input", help="Optional path to the structured judge JSON artifact.")
    parser.add_argument("--claim-register", required=True, help="Path to the JSON claim register.")
    parser.add_argument("--output", required=True, help="Path to write the final markdown artifact.")
    parser.add_argument("--config", help="Optional job config path.")
    return parser.parse_args()


def load_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def parse_markdown_sections(markdown: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for raw_line in markdown.splitlines():
        match = JUDGE_SECTION_PATTERN.match(raw_line)
        if match:
            current = match.group(1).strip()
            sections.setdefault(current, [])
            continue
        if current is not None:
            sections[current].append(raw_line)
    return sections


def normalize_lines(lines: list[str]) -> list[str]:
    normalized: list[str] = []
    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        line = re.sub(r"^(?:[-*+]\s+)+", "", line)
        line = re.sub(r"^\d+\.\s+", "", line)
        normalized.append(line.strip())
    return normalized


def format_citation_suffix(reference_ids: list[str]) -> str:
    if not reference_ids:
        return ""
    return f" [{', '.join(reference_ids)}]"


def text_from_entry(item: object) -> str:
    if isinstance(item, str):
        return item.strip()
    if isinstance(item, dict):
        for key in ("text", "summary", "topic", "point"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return str(item).strip()


def render_reference_lines(reference_ids: list[str], source_index: dict[str, dict[str, str]]) -> list[str]:
    lines: list[str] = []
    for reference_id in reference_ids:
        record = source_index.get(reference_id)
        if record is None:
            lines.append(f"- {reference_id}")
            continue
        parts = [f"{reference_id}: {record['title']}"]
        authority = record.get("authority")
        locator = record.get("locator")
        if authority:
            parts.append(authority)
        if locator:
            parts.append(locator)
        lines.append(f"- {' | '.join(parts)}")
    return lines


def render_structured_disagreement(item: dict[str, object]) -> str:
    def clean_sentence(value: str) -> str:
        return value.strip().rstrip(".")

    point = str(item.get("point", "")).strip()
    case_a = clean_sentence(str(item.get("case_a", "")))
    case_b = clean_sentence(str(item.get("case_b", "")))
    reason = clean_sentence(str(item.get("reason_unresolved", "")))
    parts = [clean_sentence(point)] if point else []
    if case_a:
        parts.append(f"Case A: {case_a}")
    if case_b:
        parts.append(f"Case B: {case_b}")
    if reason:
        parts.append(f"Unresolved because {reason}")
    return ". ".join(parts).strip()


def render_structured_confidence_lines(confidence_assessment: object) -> list[str]:
    if isinstance(confidence_assessment, dict):
        lines: list[str] = []
        summary = confidence_assessment.get("summary")
        if isinstance(summary, str) and summary.strip():
            lines.append(summary.strip())
        topics = confidence_assessment.get("topics")
        if isinstance(topics, list):
            for topic in topics:
                if isinstance(topic, dict):
                    topic_name = str(topic.get("topic", "")).strip()
                    confidence = str(topic.get("confidence", "")).strip()
                    rationale = str(topic.get("rationale", "")).strip()
                    parts = [topic_name] if topic_name else []
                    if confidence:
                        parts.append(f"Confidence: {confidence}")
                    if rationale:
                        parts.append(rationale)
                    if parts:
                        lines.append(". ".join(parts))
                elif isinstance(topic, str) and topic.strip():
                    lines.append(topic.strip())
        return lines
    if isinstance(confidence_assessment, str):
        return [confidence_assessment.strip()] if confidence_assessment.strip() else []
    if isinstance(confidence_assessment, list):
        return normalize_lines([text_from_entry(item) for item in confidence_assessment if text_from_entry(item)])
    return []


def render_brief_improvement_lines(brief_improvements: object) -> list[str]:
    if not isinstance(brief_improvements, list):
        return []
    lines: list[str] = []
    for item in brief_improvements:
        if not isinstance(item, dict):
            text = text_from_entry(item)
            if text:
                lines.append(text)
            continue
        missing_input = str(item.get("missing_input", "")).strip().rstrip(".")
        why_it_matters = str(item.get("why_it_matters", "")).strip().rstrip(".")
        expected_impact = str(item.get("expected_impact", "")).strip().rstrip(".")
        priority = str(item.get("priority", "")).strip().lower()
        parts: list[str] = []
        if missing_input:
            parts.append(f"Missing input: {missing_input}.")
        if why_it_matters:
            parts.append(f"Why it matters: {why_it_matters}.")
        if expected_impact:
            parts.append(f"Expected impact: {expected_impact}.")
        if priority:
            parts.append(f"Priority: {priority}")
        if parts:
            lines.append(" ".join(parts).strip())
    return lines


def validate_inputs(
    judge_text: str,
    payload: dict[str, object],
    *,
    judge_structured_payload: dict[str, object] | None = None,
    judge_path: Path | None = None,
    config_path: Path | None = None,
) -> None:
    errors = publication_readiness_errors(
        judge_text,
        payload,
        judge_structured_payload=judge_structured_payload,
        judge_path=judge_path,
        quality_policy=load_quality_policy_from_path(config_path),
    )
    if errors:
        normalized = errors[0]
        normalized = normalized.replace("Claim register contains ", "Cannot generate final artifact: ")
        normalized = normalized.replace(" and is not ready for final artifact generation.", "")
        normalized = normalized.replace("provenance-only supported facts", "provenance-only fact support")
        raise ValueError(normalized)


def choose_recommendation(claims: list[dict[str, object]], sections: dict[str, list[str]]) -> list[str]:
    recommendation_lines = normalize_lines(sections.get("Inferences And Synthesis Judgments", []))
    if recommendation_lines:
        return recommendation_lines[:2]
    fallback = [
        claim["text"]
        for claim in claims
        if claim.get("type") in {"decision", "inference", "evaluation"}
    ]
    if fallback:
        return fallback[:2]
    raise ValueError("Cannot generate final artifact: recommendation content is missing from judge synthesis.")


def render_artifact(
    judge_text: str,
    payload: dict[str, object],
    *,
    judge_path: Path,
    judge_structured_payload: dict[str, object] | None = None,
) -> str:
    claims = payload["claims"]
    sections = parse_markdown_sections(judge_text)
    source_index = build_source_index(judge_structured_payload, judge_path)
    used_reference_ids: list[str] = []
    seen_reference_ids: set[str] = set()

    def remember_references(reference_ids: list[str]) -> None:
        for reference_id in reference_ids:
            if reference_id not in seen_reference_ids:
                seen_reference_ids.add(reference_id)
                used_reference_ids.append(reference_id)

    if judge_structured_payload:
        executive_summary = []
        for item in judge_structured_payload.get("supported_conclusions", []):
            if not isinstance(item, dict):
                continue
            evidence_sources = [str(source) for source in item.get("evidence_sources", []) if isinstance(source, str)]
            executive_summary.append(f"{item['text']}{format_citation_suffix(evidence_sources)}")
            remember_references(evidence_sources)

        options_comparison = []
        for item in judge_structured_payload.get("unresolved_disagreements", []):
            if isinstance(item, dict):
                options_comparison.append(render_structured_disagreement(item))
            elif isinstance(item, str) and item.strip():
                options_comparison.append(item.strip())

        recommendation = []
        for item in judge_structured_payload.get("synthesis_judgments", []):
            if not isinstance(item, dict):
                continue
            evidence_sources = [str(source) for source in item.get("evidence_sources", []) if isinstance(source, str)]
            remember_references(evidence_sources)
            confidence_label = str(item.get("confidence", "")).strip()
            confidence_suffix = f" Confidence: {confidence_label}." if confidence_label else ""
            recommendation.append(f"{item['text']}{format_citation_suffix(evidence_sources)}{confidence_suffix}")

        confidence = render_structured_confidence_lines(judge_structured_payload.get("confidence_assessment"))
        open_questions = normalize_lines([text_from_entry(item) for item in judge_structured_payload.get("evidence_gaps", []) if text_from_entry(item)])
        brief_improvements = render_brief_improvement_lines(judge_structured_payload.get("brief_improvements"))
    else:
        executive_summary = normalize_lines(sections.get("Supported Conclusions", []))
        if not executive_summary:
            executive_summary = [
                claim["text"]
                for claim in claims
                if claim.get("type") == "fact" and claim.get("evidence_sources")
            ][:3]

        options_comparison = normalize_lines(sections.get("Unresolved Disagreements", []))
        if not options_comparison:
            options_comparison = [
                claim["text"]
                for claim in claims
                if claim.get("type") in {"inference", "evaluation"}
            ][:4]

        recommendation = choose_recommendation(claims, sections)
        confidence = normalize_lines(sections.get("Confidence Assessment", []))
        open_questions = normalize_lines(sections.get("Evidence Gaps", []))
        brief_improvements = normalize_lines(sections.get("Brief Improvement Recommendations", []))

    if not confidence:
        confidence = ["Confidence remains limited where source coverage is incomplete or evidence is mixed."]
    if not open_questions:
        open_questions = [
            claim["text"]
            for claim in claims
            if claim.get("type") in {"open_question", "evidence_gap"}
        ][:5]
    if not brief_improvements:
        brief_improvements = []

    references = used_reference_ids or extract_reference_ids(claims)
    if not references:
        raise ValueError("Cannot generate final artifact: no external references are available.")
    source_errors = referenced_source_publication_errors(references, source_index)
    if source_errors:
        raise ValueError(source_errors[0])
    reference_lines = render_reference_lines(references, source_index)

    parts = [
        "# Executive Summary",
        "",
        *[f"- {line}" for line in executive_summary],
        "",
        "# Options Comparison",
        "",
        *[f"- {line}" for line in options_comparison],
        "",
        "# Recommendation",
        "",
        *[f"- {line}" for line in recommendation],
        "",
        "# Confidence And Uncertainty",
        "",
        *[f"- {line}" for line in confidence],
        "",
    ]
    if brief_improvements:
        parts.extend(
            [
                "# Brief Improvement Recommendations",
                "",
                *[f"- {line}" for line in brief_improvements],
                "",
            ]
        )
    parts.extend(
        [
            "# References",
            "",
            *reference_lines,
            "",
            "# Open Questions",
            "",
            *[f"- {line}" for line in open_questions],
            "",
            "<!-- Workflow provenance remains in the audit artifacts and claim register, not in the user-facing references list. -->",
        ]
    )
    artifact = "\n".join(parts).rstrip() + "\n"
    if PLACEHOLDER_PATTERN.search(artifact):
        raise ValueError("Generated artifact contains unresolved placeholder or template residue.")
    for heading in REQUIRED_SECTIONS:
        if heading not in artifact:
            raise ValueError(f"Generated artifact is missing required section: {heading}")
    return artifact


def main() -> int:
    args = parse_args()
    judge_path = Path(args.judge_input).expanduser()
    judge_structured_path = (
        Path(args.judge_structured_input).expanduser()
        if args.judge_structured_input
        else judge_path.with_suffix(".json")
    )
    claims_path = Path(args.claim_register).expanduser()
    output_path = Path(args.output).expanduser()
    config_path = Path(args.config).expanduser() if args.config else None

    try:
        judge_text = judge_path.read_text(encoding="utf-8")
        judge_structured_payload = load_json(judge_structured_path) if judge_structured_path.is_file() else None
        payload = load_json(claims_path)
        validate_inputs(
            judge_text,
            payload,
            judge_structured_payload=judge_structured_payload,
            judge_path=judge_path,
            config_path=config_path,
        )
        artifact = render_artifact(
            judge_text,
            payload,
            judge_path=judge_path,
            judge_structured_payload=judge_structured_payload,
        )
        write_text(output_path, artifact)
    except FileNotFoundError as exc:
        print(f"Missing required input file: {exc.filename}", file=sys.stderr)
        return 1
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        print(f"Could not parse input artifact: {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"Final artifact generation failed: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

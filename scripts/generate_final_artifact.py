#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

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
WORKFLOW_MARKER_PATTERN = re.compile(
    r"^(?:PASS|CRIT|JUDGE|INTAKE|RUN|STAGE|WORK[_-]?ORDER|ARTIFACT)(?:[-_][A-Z0-9]+)*$",
    re.IGNORECASE,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a structured operator-reviewed final artifact from judge output and a claim register."
    )
    parser.add_argument("--judge-input", required=True, help="Path to the judge markdown artifact.")
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
    return [line.strip() for line in lines if line.strip()]


def extract_reference_ids(claims: list[dict[str, object]]) -> list[str]:
    seen: set[str] = set()
    refs: list[str] = []
    for claim in claims:
        for source in claim.get("evidence_sources", []):
            normalized = str(source)
            if normalized not in seen and not WORKFLOW_MARKER_PATTERN.match(normalized):
                seen.add(normalized)
                refs.append(normalized)
    return refs


def validate_inputs(judge_text: str, payload: dict[str, object]) -> None:
    summary = payload["summary"]
    if summary.get("uncited_fact_ids"):
        raise ValueError("Cannot generate final artifact: uncited facts remain in the claim register.")
    if summary.get("provenance_only_fact_ids"):
        raise ValueError("Cannot generate final artifact: provenance-only fact support remains in the claim register.")
    if summary.get("claims_with_unclassified_markers"):
        raise ValueError("Cannot generate final artifact: unclassified markers remain in the claim register.")
    if not judge_text.strip():
        raise ValueError("Cannot generate final artifact: judge artifact is empty.")


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


def render_artifact(judge_text: str, payload: dict[str, object]) -> str:
    claims = payload["claims"]
    sections = parse_markdown_sections(judge_text)

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
    if not confidence:
        confidence = ["Confidence remains limited where source coverage is incomplete or evidence is mixed."]

    open_questions = normalize_lines(sections.get("Evidence Gaps", []))
    if not open_questions:
        open_questions = [
            claim["text"]
            for claim in claims
            if claim.get("type") in {"open_question", "evidence_gap"}
        ][:5]

    references = extract_reference_ids(claims)
    if not references:
        raise ValueError("Cannot generate final artifact: no external references are available.")

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
        "# References",
        "",
        *[f"- {reference}" for reference in references],
        "",
        "# Open Questions",
        "",
        *[f"- {line}" for line in open_questions],
        "",
        "<!-- Workflow provenance remains in the audit artifacts and claim register, not in the user-facing references list. -->",
    ]
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
    claims_path = Path(args.claim_register).expanduser()
    output_path = Path(args.output).expanduser()

    try:
        judge_text = judge_path.read_text(encoding="utf-8")
        payload = load_json(claims_path)
        validate_inputs(judge_text, payload)
        artifact = render_artifact(judge_text, payload)
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

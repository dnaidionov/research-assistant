#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from _workflow_lib import write_json


CITATION_PATTERN = re.compile(r"\[([^\[\]]+)\]")
LIST_PREFIX_PATTERN = re.compile(r"^\s*(?:[-*]|\d+\.)\s+")
HEADING_PATTERN = re.compile(r"^\s{0,3}#{1,6}\s+(.*)$")


def normalize_claim_text(line: str) -> str:
    stripped = LIST_PREFIX_PATTERN.sub("", line.strip())
    return CITATION_PATTERN.sub("", stripped).strip()


def extract_citations(line: str) -> list[str]:
    citations: list[str] = []
    for block in CITATION_PATTERN.findall(line):
        for part in block.split(","):
            item = part.strip()
            if item:
                citations.append(item)
    return citations


def claim_type_for_heading(heading: str) -> str:
    lowered = heading.lower()
    if "inference" in lowered or "interpret" in lowered:
        return "inference"
    return "fact"


def iter_claim_lines(markdown: str) -> list[tuple[int, str, str]]:
    claims: list[tuple[int, str, str]] = []
    active_heading = "facts"
    for line_number, raw_line in enumerate(markdown.splitlines(), start=1):
        heading_match = HEADING_PATTERN.match(raw_line)
        if heading_match:
            active_heading = heading_match.group(1).strip()
            continue

        stripped = raw_line.strip()
        if not stripped:
            continue
        if stripped.startswith(">"):
            continue

        if LIST_PREFIX_PATTERN.match(raw_line) or active_heading.lower() in {"facts", "inferences", "fact", "inference"}:
            claims.append((line_number, active_heading, raw_line))
    return claims


def extract_claims(markdown: str) -> list[dict[str, object]]:
    claims: list[dict[str, object]] = []
    for index, (line_number, heading, raw_line) in enumerate(iter_claim_lines(markdown), start=1):
        claim_text = normalize_claim_text(raw_line)
        if not claim_text:
            continue
        claims.append(
            {
                "citations": extract_citations(raw_line),
                "id": f"CLM-{index:04d}",
                "line": line_number,
                "section": heading,
                "text": claim_text,
                "type": claim_type_for_heading(heading),
            }
        )
    return claims


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract atomic claims from markdown into JSON.")
    parser.add_argument("--input", required=True, help="Path to the markdown report.")
    parser.add_argument("--output", required=True, help="Path to the output JSON file.")
    parser.add_argument("--strict", action="store_true", help="Fail if a fact claim has no citations.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_path = Path(args.input).expanduser()
    output_path = Path(args.output).expanduser()

    markdown = input_path.read_text(encoding="utf-8")
    claims = extract_claims(markdown)
    uncited_facts = [claim["id"] for claim in claims if claim["type"] == "fact" and not claim["citations"]]

    payload = {
        "claims": claims,
        "summary": {
            "fact_count": sum(1 for claim in claims if claim["type"] == "fact"),
            "inference_count": sum(1 for claim in claims if claim["type"] == "inference"),
            "uncited_fact_ids": uncited_facts,
        },
    }
    write_json(output_path, payload)

    if args.strict and uncited_facts:
        print(
            "Uncited fact claims detected: " + ", ".join(uncited_facts),
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

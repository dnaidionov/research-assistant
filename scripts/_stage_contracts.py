#!/usr/bin/env python3

from __future__ import annotations

import json
import re
from copy import deepcopy
from pathlib import Path

from _workflow_lib import write_json


STRUCTURED_STAGE_IDS = {"research-a", "research-b", "judge"}
SOURCE_ID_PATTERN = re.compile(r"^(?:SRC|DOC)-[A-Z0-9._-]+$|^S[0-9]{1,6}$|^https?://\S+$", re.IGNORECASE)
SECTION_HEADING_PATTERN = re.compile(r"^#\s+(.+)$")
LIST_ITEM_PATTERN = re.compile(r"^\s*\d+[.)]\s+")
MARKDOWN_BULLET_PATTERN = re.compile(r"^\s*[-*+]\s+")
CITATION_BLOCK_PATTERN = re.compile(r"\[([^\[\]]+)\]")
CONFIDENCE_PATTERN = re.compile(r"\bconfidence\s*:\s*(low|medium|high)\b", re.IGNORECASE)
RECOVERED_SOURCE_AUTHORITY = "recovered-from-markdown"

STAGE_JSON_KEYS: dict[str, tuple[str, ...]] = {
    "research-a": (
        "stage",
        "summary",
        "facts",
        "inferences",
        "uncertainties",
        "evidence_gaps",
        "preliminary_disagreements",
        "source_evaluation",
        "sources",
    ),
    "research-b": (
        "stage",
        "summary",
        "facts",
        "inferences",
        "uncertainties",
        "evidence_gaps",
        "preliminary_disagreements",
        "source_evaluation",
        "sources",
    ),
    "judge": (
        "stage",
        "supported_conclusions",
        "synthesis_judgments",
        "unresolved_disagreements",
        "confidence_assessment",
        "evidence_gaps",
        "rationale",
        "recommended_artifact_structure",
        "sources",
    ),
}


def is_structured_stage(stage_id: str) -> bool:
    return stage_id in STRUCTURED_STAGE_IDS


def stage_structured_output_path(run_dir: Path, stage_id: str) -> Path:
    filename_by_stage = {
        "research-a": "02-research-a.json",
        "research-b": "03-research-b.json",
        "judge": "06-judge.json",
    }
    return run_dir / "stage-outputs" / filename_by_stage[stage_id]


def source_registry_path(run_dir: Path) -> Path:
    return run_dir / "sources.json"


def source_registry_placeholder(run_id: str) -> dict[str, object]:
    return {
        "run_id": run_id,
        "sources": [],
        "notes": "Populate this registry from authoritative stage JSON outputs. Recovered markdown-only entries are provisional.",
    }


def structured_output_placeholder(stage_id: str, markdown_path: Path, json_path: Path) -> dict[str, object]:
    return {
        "stage": stage_id,
        "status": "not_started",
        "expected_markdown_output": str(markdown_path),
        "expected_output_target": str(json_path),
        "notes": "Populate this structured stage artifact during execution. Facts and inferences must carry canonical external evidence source IDs.",
    }


def load_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def parse_markdown_sections(markdown: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for raw_line in markdown.splitlines():
        match = SECTION_HEADING_PATTERN.match(raw_line)
        if match:
            current = match.group(1).strip()
            sections.setdefault(current, [])
            continue
        if current is not None:
            sections[current].append(raw_line)
    return sections


def collect_numbered_items(lines: list[str]) -> list[str]:
    items: list[str] = []
    current: list[str] = []
    for raw_line in lines:
        if not raw_line.strip():
            continue
        if raw_line.startswith("# "):
            break
        if LIST_ITEM_PATTERN.match(raw_line):
            if current:
                items.append(" ".join(part.strip() for part in current))
            current = [LIST_ITEM_PATTERN.sub("", raw_line, count=1).strip()]
            continue
        if current:
            current.append(raw_line.strip())
    if current:
        items.append(" ".join(part.strip() for part in current))
    return items


def collect_section_entries(lines: list[str]) -> list[str]:
    entries: list[str] = []
    current: list[str] = []
    for raw_line in lines:
        stripped = raw_line.strip()
        if not stripped:
            if current:
                entries.append(" ".join(current).strip())
                current = []
            continue
        if raw_line.startswith("# "):
            break
        if MARKDOWN_BULLET_PATTERN.match(raw_line):
            if current:
                entries.append(" ".join(current).strip())
            current = [MARKDOWN_BULLET_PATTERN.sub("", raw_line, count=1).strip()]
            continue
        current.append(stripped)
    if current:
        entries.append(" ".join(current).strip())
    return [entry for entry in entries if entry]


def extract_evidence_sources(text: str) -> list[str]:
    sources: list[str] = []
    for block in CITATION_BLOCK_PATTERN.findall(text):
        for part in block.split(","):
            candidate = part.strip()
            if candidate and SOURCE_ID_PATTERN.match(candidate) and candidate not in sources:
                sources.append(candidate)
    return sources


def extract_confidence(text: str) -> str | None:
    match = CONFIDENCE_PATTERN.search(text)
    return match.group(1).lower() if match else None


def strip_citations_and_confidence(text: str) -> str:
    without_citations = CITATION_BLOCK_PATTERN.sub("", text)
    without_confidence = CONFIDENCE_PATTERN.sub("", without_citations)
    return re.sub(r"\s+", " ", without_confidence).strip(" ;,-")


def default_source_record(source_id: str, stage_id: str) -> dict[str, str]:
    return {
        "id": source_id,
        "title": f"Recovered source record for {source_id}",
        "type": "unknown",
        "authority": RECOVERED_SOURCE_AUTHORITY,
        "locator": f"urn:recovered:{stage_id}:{source_id}",
        "acquisition_provenance": "recovered_from_markdown",
    }


def _build_claim_items(stage_id: str, prefix: str, items: list[str], *, inference: bool) -> list[dict[str, object]]:
    payload: list[dict[str, object]] = []
    for index, item in enumerate(items, start=1):
        record: dict[str, object] = {
            "id": f"{stage_id}-{prefix}-{index:03d}",
            "text": strip_citations_and_confidence(item),
            "evidence_sources": extract_evidence_sources(item),
        }
        if inference:
            confidence = extract_confidence(item)
            if confidence is not None:
                record["confidence"] = confidence
        payload.append(record)
    return payload


def _build_text_entries(lines: list[str]) -> list[dict[str, object]]:
    return [
        {
            "text": strip_citations_and_confidence(entry),
            "evidence_sources": extract_evidence_sources(entry),
        }
        for entry in collect_section_entries(lines)
    ]


def _build_source_evaluation(lines: list[str]) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    for entry in collect_section_entries(lines):
        source_ids = extract_evidence_sources(entry)
        record: dict[str, object] = {"notes": strip_citations_and_confidence(entry)}
        if source_ids:
            record["source_id"] = source_ids[0]
        entries.append(record)
    return entries


def _collect_source_records(stage_id: str, payload: dict[str, object]) -> list[dict[str, str]]:
    source_ids: list[str] = []
    for key, value in payload.items():
        if key == "sources":
            continue
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    for source_id in item.get("evidence_sources", []):
                        if source_id not in source_ids:
                            source_ids.append(source_id)
                    source_id = item.get("source_id")
                    if isinstance(source_id, str) and source_id not in source_ids:
                        source_ids.append(source_id)
    return [default_source_record(source_id, stage_id) for source_id in source_ids]


def build_stage_json_from_markdown(stage_id: str, markdown: str) -> dict[str, object]:
    sections = parse_markdown_sections(markdown)
    if stage_id in {"research-a", "research-b"}:
        payload: dict[str, object] = {
            "stage": stage_id,
            "summary": _build_text_entries(sections.get("Executive Summary", [])),
            "facts": _build_claim_items(stage_id, "fact", collect_numbered_items(sections.get("Facts", [])), inference=False),
            "inferences": _build_claim_items(stage_id, "inference", collect_numbered_items(sections.get("Inferences", [])), inference=True),
            "uncertainties": _build_text_entries(sections.get("Uncertainty Register", [])),
            "evidence_gaps": _build_text_entries(sections.get("Evidence Gaps", [])),
            "preliminary_disagreements": _build_text_entries(sections.get("Preliminary Disagreements", [])),
            "source_evaluation": _build_source_evaluation(sections.get("Source Evaluation", [])),
        }
        payload["sources"] = _collect_source_records(stage_id, payload)
        return payload

    if stage_id == "judge":
        payload = {
            "stage": stage_id,
            "supported_conclusions": _build_claim_items(
                stage_id, "conclusion", collect_numbered_items(sections.get("Supported Conclusions", [])), inference=False
            ),
            "synthesis_judgments": _build_claim_items(
                stage_id,
                "judgment",
                collect_numbered_items(sections.get("Inferences And Synthesis Judgments", [])),
                inference=True,
            ),
            "unresolved_disagreements": _build_text_entries(sections.get("Unresolved Disagreements", [])),
            "confidence_assessment": _build_text_entries(sections.get("Confidence Assessment", [])),
            "evidence_gaps": _build_text_entries(sections.get("Evidence Gaps", [])),
            "rationale": _build_text_entries(sections.get("Rationale And Traceability", [])),
            "recommended_artifact_structure": [entry["text"] for entry in _build_text_entries(sections.get("Recommended Final Artifact Structure", []))],
        }
        payload["sources"] = _collect_source_records(stage_id, payload)
        return payload

    raise KeyError(f"Stage {stage_id} does not have a structured contract.")


def normalize_stage_citations(stage_id: str, payload: dict[str, object]) -> dict[str, object]:
    normalized = deepcopy(payload)
    supporting_sections = []
    if stage_id in {"research-a", "research-b"}:
        supporting_sections = ["facts"]
        target_sections = ["inferences"]
    elif stage_id == "judge":
        supporting_sections = ["supported_conclusions"]
        target_sections = ["synthesis_judgments"]
    else:
        return normalized

    local_reference_map: dict[str, list[str]] = {}
    for section in supporting_sections:
        for item in normalized.get(section, []):
            if not isinstance(item, dict):
                continue
            item_id = item.get("id")
            evidence_sources = item.get("evidence_sources")
            if isinstance(item_id, str) and isinstance(evidence_sources, list):
                local_reference_map[item_id] = [source for source in evidence_sources if isinstance(source, str)]

    for section in target_sections:
        for item in normalized.get(section, []):
            if not isinstance(item, dict):
                continue
            evidence_sources = item.get("evidence_sources")
            if not isinstance(evidence_sources, list):
                continue
            expanded: list[str] = []
            for source_id in evidence_sources:
                if isinstance(source_id, str) and source_id in local_reference_map:
                    for resolved_source_id in local_reference_map[source_id]:
                        if resolved_source_id not in expanded:
                            expanded.append(resolved_source_id)
                    continue
                if isinstance(source_id, str) and source_id not in expanded:
                    expanded.append(source_id)
            item["evidence_sources"] = expanded
    return normalized


def _format_evidence_sources(sources: list[str]) -> str:
    return f" [{', '.join(sources)}]" if sources else ""


def _entry_lines(items: object) -> list[str]:
    if isinstance(items, str):
        return [items]
    lines: list[str] = []
    if isinstance(items, list):
        for item in items:
            text = _entry_text(item)
            sources = _entry_sources(item)
            suffix = _format_evidence_sources(sources)
            lines.append(f"- {text}{suffix}".rstrip())
    return lines


def _judge_disagreement_lines(items: object) -> list[str]:
    if isinstance(items, str):
        return [f"- {items}"]
    lines: list[str] = []
    if isinstance(items, list):
        for index, item in enumerate(items, start=1):
            if isinstance(item, dict) and isinstance(item.get("point"), str) and item.get("point", "").strip():
                lines.append(f"{index}. {item['point']}")
                case_a = item.get("case_a")
                case_b = item.get("case_b")
                unresolved = item.get("reason_unresolved")
                if isinstance(case_a, str) and case_a.strip():
                    lines.append(f"   Case A: {case_a}")
                if isinstance(case_b, str) and case_b.strip():
                    lines.append(f"   Case B: {case_b}")
                if isinstance(unresolved, str) and unresolved.strip():
                    lines.append(f"   Why unresolved: {unresolved}")
                continue
            text = _entry_text(item)
            sources = _entry_sources(item)
            suffix = _format_evidence_sources(sources)
            lines.append(f"{index}. {text}{suffix}".rstrip())
    return lines


def _judge_confidence_lines(items: object) -> list[str]:
    if isinstance(items, dict):
        lines: list[str] = []
        summary = items.get("summary")
        if isinstance(summary, str) and summary.strip():
            lines.append(f"- {summary}")
        topics = items.get("topics")
        if isinstance(topics, list):
            for topic in topics:
                if isinstance(topic, dict):
                    parts = []
                    topic_name = topic.get("topic")
                    confidence = topic.get("confidence")
                    rationale = topic.get("rationale")
                    if isinstance(topic_name, str) and topic_name.strip():
                        parts.append(topic_name)
                    if isinstance(confidence, str) and confidence.strip():
                        parts.append(f"Confidence: {confidence}")
                    if isinstance(rationale, str) and rationale.strip():
                        parts.append(rationale)
                    if parts:
                        lines.append(f"- {'; '.join(parts)}")
                elif isinstance(topic, str) and topic.strip():
                    lines.append(f"- {topic}")
        return lines
    entry_lines = _entry_lines(items)
    return [line if line.startswith("- ") else f"- {line}" for line in entry_lines]


def _judge_recommended_structure_lines(items: object) -> list[str]:
    if isinstance(items, dict):
        sections = items.get("sections")
        if isinstance(sections, list):
            return [f"- {section}" for section in sections if isinstance(section, str) and section.strip()]
    entry_lines = _entry_lines(items)
    return [line if line.startswith("- ") else f"- {line}" for line in entry_lines]


def render_stage_markdown_from_json(stage_id: str, payload: dict[str, object]) -> str:
    payload = normalize_stage_citations(stage_id, payload)
    lines: list[str] = []

    if stage_id in {"research-a", "research-b"}:
        lines.extend(["# Executive Summary", ""])
        summary_items = payload.get("summary")
        if isinstance(summary_items, str):
            lines.append(summary_items)
        else:
            for item in summary_items or []:
                lines.append(_entry_text(item) + _format_evidence_sources(_entry_sources(item)))
        lines.extend(["", "# Facts", ""])
        for index, item in enumerate(payload.get("facts", []), start=1):
            lines.append(f"{index}. {item['text']}{_format_evidence_sources(list(item.get('evidence_sources', [])))}")
        lines.extend(["", "# Inferences", ""])
        for index, item in enumerate(payload.get("inferences", []), start=1):
            lines.append(
                f"{index}. {item['text']}{_format_evidence_sources(list(item.get('evidence_sources', [])))} Confidence: {item['confidence']}"
            )
        lines.extend(["", "# Uncertainty Register", ""])
        lines.extend(_entry_lines(payload.get("uncertainties")))
        lines.extend(["", "# Evidence Gaps", ""])
        lines.extend(_entry_lines(payload.get("evidence_gaps")))
        lines.extend(["", "# Preliminary Disagreements", ""])
        lines.extend(_entry_lines(payload.get("preliminary_disagreements")))
        lines.extend(["", "# Source Evaluation", ""])
        lines.extend(_entry_lines(payload.get("source_evaluation")))
        return "\n".join(lines).rstrip() + "\n"

    if stage_id == "judge":
        lines.extend(["# Supported Conclusions", ""])
        for index, item in enumerate(payload.get("supported_conclusions", []), start=1):
            lines.append(f"{index}. {item['text']}{_format_evidence_sources(list(item.get('evidence_sources', [])))}")
        lines.extend(["", "# Inferences And Synthesis Judgments", ""])
        for index, item in enumerate(payload.get("synthesis_judgments", []), start=1):
            lines.append(
                f"{index}. {item['text']}{_format_evidence_sources(list(item.get('evidence_sources', [])))} Confidence: {item['confidence']}"
            )
        lines.extend(["", "# Unresolved Disagreements", ""])
        lines.extend(_judge_disagreement_lines(payload.get("unresolved_disagreements")))
        lines.extend(["", "# Confidence Assessment", ""])
        lines.extend(_judge_confidence_lines(payload.get("confidence_assessment")))
        lines.extend(["", "# Evidence Gaps", ""])
        lines.extend(_entry_lines(payload.get("evidence_gaps")))
        lines.extend(["", "# Rationale And Traceability", ""])
        lines.extend(_entry_lines(payload.get("rationale")))
        lines.extend(["", "# Recommended Final Artifact Structure", ""])
        lines.extend(_judge_recommended_structure_lines(payload.get("recommended_artifact_structure")))
        return "\n".join(lines).rstrip() + "\n"

    raise KeyError(f"Stage {stage_id} does not have a structured markdown contract.")


def _require_string(value: object, field_name: str, errors: list[str]) -> None:
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{field_name} must be a non-empty string.")


def _validate_source_records(sources: object, errors: list[str]) -> dict[str, dict[str, str]]:
    if not isinstance(sources, list):
        errors.append("sources must be a list.")
        return {}
    index: dict[str, dict[str, str]] = {}
    for position, source in enumerate(sources, start=1):
        if not isinstance(source, dict):
            errors.append(f"sources[{position}] must be an object.")
            continue
        source_id = source.get("id")
        if not isinstance(source_id, str) or not SOURCE_ID_PATTERN.match(source_id):
            errors.append(f"sources[{position}].id must be a canonical external source ID.")
            continue
        for field in ("title", "type", "authority", "locator"):
            _require_string(source.get(field), f"sources[{position}].{field}", errors)
        index[source_id] = {key: str(value) for key, value in source.items() if isinstance(value, str)}
    return index


def _validate_claim_list(
    items: object,
    field_name: str,
    source_index: dict[str, dict[str, str]],
    errors: list[str],
    *,
    require_id: bool,
    require_confidence: bool,
) -> None:
    if not isinstance(items, list):
        errors.append(f"{field_name} must be a list.")
        return
    for position, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            errors.append(f"{field_name}[{position}] must be an object.")
            continue
        if require_id:
            _require_string(item.get("id"), f"{field_name}[{position}].id", errors)
        _require_string(item.get("text"), f"{field_name}[{position}].text", errors)
        evidence_sources = item.get("evidence_sources")
        if not isinstance(evidence_sources, list) or not evidence_sources:
            errors.append(f"{field_name}[{position}] must include at least one evidence source.")
        else:
            for source_id in evidence_sources:
                if not isinstance(source_id, str) or not SOURCE_ID_PATTERN.match(source_id):
                    errors.append(f"{field_name}[{position}] contains a non-canonical source ID.")
                    continue
                if source_id not in source_index:
                    errors.append(f"{field_name}[{position}] references unresolved source ID {source_id}.")
        if require_confidence:
            confidence = item.get("confidence")
            if confidence not in {"low", "medium", "high"}:
                errors.append(f"{field_name}[{position}].confidence must be low, medium, or high.")


def _validate_text_entry_list(items: object, field_name: str, errors: list[str]) -> None:
    if isinstance(items, str):
        if not items.strip():
            errors.append(f"{field_name} must not be empty.")
        return
    if not isinstance(items, list):
        errors.append(f"{field_name} must be a list.")
        return
    for position, item in enumerate(items, start=1):
        if isinstance(item, str):
            if not item.strip():
                errors.append(f"{field_name}[{position}] must not be empty.")
            continue
        if not isinstance(item, dict):
            errors.append(f"{field_name}[{position}] must be a string or object.")
            continue
        _require_string(item.get("text"), f"{field_name}[{position}].text", errors)


def _validate_judge_unresolved_disagreements(items: object, errors: list[str]) -> None:
    if isinstance(items, str):
        if not items.strip():
            errors.append("unresolved_disagreements must not be empty.")
        return
    if not isinstance(items, list):
        errors.append("unresolved_disagreements must be a list.")
        return
    for position, item in enumerate(items, start=1):
        if isinstance(item, str):
            if not item.strip():
                errors.append(f"unresolved_disagreements[{position}] must not be empty.")
            continue
        if not isinstance(item, dict):
            errors.append(f"unresolved_disagreements[{position}] must be a string or object.")
            continue
        if any(key in item for key in ("point", "case_a", "case_b", "reason_unresolved")):
            _require_string(item.get("point"), f"unresolved_disagreements[{position}].point", errors)
            _require_string(item.get("case_a"), f"unresolved_disagreements[{position}].case_a", errors)
            _require_string(item.get("case_b"), f"unresolved_disagreements[{position}].case_b", errors)
            _require_string(item.get("reason_unresolved"), f"unresolved_disagreements[{position}].reason_unresolved", errors)
            continue
        _require_string(item.get("text"), f"unresolved_disagreements[{position}].text", errors)


def _validate_confidence_assessment(items: object, errors: list[str]) -> None:
    if isinstance(items, dict):
        _require_string(items.get("summary"), "confidence_assessment.summary", errors)
        topics = items.get("topics")
        if topics is not None:
            if not isinstance(topics, list):
                errors.append("confidence_assessment.topics must be a list.")
            else:
                for position, topic in enumerate(topics, start=1):
                    if isinstance(topic, str):
                        if not topic.strip():
                            errors.append(f"confidence_assessment.topics[{position}] must not be empty.")
                        continue
                    if not isinstance(topic, dict):
                        errors.append(f"confidence_assessment.topics[{position}] must be a string or object.")
                        continue
                    _require_string(topic.get("topic"), f"confidence_assessment.topics[{position}].topic", errors)
                    confidence = topic.get("confidence")
                    if confidence is not None and confidence not in {"low", "medium", "high"}:
                        errors.append(f"confidence_assessment.topics[{position}].confidence must be low, medium, or high.")
                    _require_string(topic.get("rationale"), f"confidence_assessment.topics[{position}].rationale", errors)
        return
    _validate_text_entry_list(items, "confidence_assessment", errors)


def _validate_recommended_artifact_structure(items: object, errors: list[str]) -> None:
    if isinstance(items, dict):
        sections = items.get("sections")
        if not isinstance(sections, list):
            errors.append("recommended_artifact_structure.sections must be a list.")
            return
        for position, section in enumerate(sections, start=1):
            if not isinstance(section, str) or not section.strip():
                errors.append(f"recommended_artifact_structure.sections[{position}] must be a non-empty string.")
        return
    _validate_text_entry_list(items, "recommended_artifact_structure", errors)


def _validate_flexible_object_list(
    items: object,
    field_name: str,
    errors: list[str],
    *,
    accepted_text_keys: tuple[str, ...],
    accepted_source_keys: tuple[str, ...] = (),
) -> None:
    if isinstance(items, str):
        if not items.strip():
            errors.append(f"{field_name} must not be empty.")
        return
    if not isinstance(items, list):
        errors.append(f"{field_name} must be a list or string.")
        return
    for position, item in enumerate(items, start=1):
        if isinstance(item, str):
            if not item.strip():
                errors.append(f"{field_name}[{position}] must not be empty.")
            continue
        if not isinstance(item, dict):
            errors.append(f"{field_name}[{position}] must be a string or object.")
            continue
        if not any(isinstance(item.get(key), str) and item.get(key).strip() for key in accepted_text_keys):
            accepted = ", ".join(accepted_text_keys)
            errors.append(f"{field_name}[{position}] must include one of: {accepted}.")
        for key in accepted_source_keys:
            source_id = item.get(key)
            if source_id is not None and (not isinstance(source_id, str) or not SOURCE_ID_PATTERN.match(source_id)):
                errors.append(f"{field_name}[{position}].{key} must be a canonical external source ID.")


def _validate_source_evaluation(items: object, errors: list[str]) -> None:
    if isinstance(items, str):
        if not items.strip():
            errors.append("source_evaluation must not be empty.")
        return
    if not isinstance(items, list):
        errors.append("source_evaluation must be a list.")
        return
    for position, item in enumerate(items, start=1):
        if isinstance(item, str):
            if not item.strip():
                errors.append(f"source_evaluation[{position}] must not be empty.")
            continue
        if not isinstance(item, dict):
            errors.append(f"source_evaluation[{position}] must be a string or object.")
            continue
        if not any(isinstance(value, str) and value.strip() for value in item.values()):
            errors.append(f"source_evaluation[{position}] must include at least one non-empty string field.")
        for key in ("source_id",):
            source_id = item.get(key)
            if source_id is not None and (not isinstance(source_id, str) or not SOURCE_ID_PATTERN.match(source_id)):
                errors.append(f"source_evaluation[{position}].{key} must be a canonical external source ID.")


def validate_stage_json(stage_id: str, payload: dict[str, object], source_registry: dict[str, object]) -> list[str]:
    payload = normalize_stage_citations(stage_id, payload)
    errors: list[str] = []
    expected_keys = STAGE_JSON_KEYS.get(stage_id)
    if expected_keys is None:
        return [f"Stage {stage_id} does not have a structured contract."]

    if payload.get("stage") != stage_id:
        errors.append(f"stage must equal {stage_id}.")
    for key in expected_keys:
        if key not in payload:
            errors.append(f"Missing required key: {key}.")

    source_index = _validate_source_records(source_registry.get("sources", []), errors)
    stage_sources = payload.get("sources", [])
    stage_source_index = _validate_source_records(stage_sources, errors)
    source_index.update(stage_source_index)

    if stage_id in {"research-a", "research-b"}:
        _validate_text_entry_list(payload.get("summary"), "summary", errors)
        _validate_claim_list(payload.get("facts"), "facts", source_index, errors, require_id=True, require_confidence=False)
        _validate_claim_list(
            payload.get("inferences"), "inferences", source_index, errors, require_id=True, require_confidence=True
        )
        _validate_flexible_object_list(
            payload.get("uncertainties"),
            "uncertainties",
            errors,
            accepted_text_keys=("text", "issue", "reason", "impact", "reduction_strategy", "what_would_reduce_it"),
        )
        _validate_flexible_object_list(payload.get("evidence_gaps"), "evidence_gaps", errors, accepted_text_keys=("text",))
        _validate_flexible_object_list(
            payload.get("preliminary_disagreements"),
            "preliminary_disagreements",
            errors,
            accepted_text_keys=("text",),
        )
        _validate_source_evaluation(payload.get("source_evaluation"), errors)
        return errors

    _validate_claim_list(
        payload.get("supported_conclusions"),
        "supported_conclusions",
        source_index,
        errors,
        require_id=True,
        require_confidence=False,
    )
    _validate_claim_list(
        payload.get("synthesis_judgments"),
        "synthesis_judgments",
        source_index,
        errors,
        require_id=True,
        require_confidence=True,
    )
    _validate_judge_unresolved_disagreements(payload.get("unresolved_disagreements"), errors)
    _validate_confidence_assessment(payload.get("confidence_assessment"), errors)
    _validate_text_entry_list(payload.get("evidence_gaps"), "evidence_gaps", errors)
    _validate_text_entry_list(payload.get("rationale"), "rationale", errors)
    _validate_recommended_artifact_structure(payload.get("recommended_artifact_structure"), errors)
    return errors


def merge_source_registry(existing: dict[str, object], stage_sources: list[dict[str, object]]) -> dict[str, object]:
    merged = {"run_id": existing.get("run_id"), "notes": existing.get("notes", ""), "sources": []}
    existing_index = {
        source["id"]: dict(source)
        for source in existing.get("sources", [])
        if isinstance(source, dict) and isinstance(source.get("id"), str)
    }
    for source in stage_sources:
        if not isinstance(source, dict):
            continue
        source_id = source.get("id")
        if not isinstance(source_id, str):
            continue
        current = existing_index.get(source_id)
        candidate = dict(source)
        if current is None:
            existing_index[source_id] = candidate
            continue
        if current.get("authority") == RECOVERED_SOURCE_AUTHORITY and candidate.get("authority") != RECOVERED_SOURCE_AUTHORITY:
            upgraded = dict(current)
            upgraded.update(candidate)
            existing_index[source_id] = upgraded
            continue
        if candidate.get("authority") == RECOVERED_SOURCE_AUTHORITY and current.get("authority") != RECOVERED_SOURCE_AUTHORITY:
            continue
        if current.get("authority") == RECOVERED_SOURCE_AUTHORITY and candidate.get("authority") == RECOVERED_SOURCE_AUTHORITY:
            continue
        for field in ("title", "type", "authority", "locator"):
            left = current.get(field)
            right = candidate.get(field)
            if left and right and left != right:
                raise ValueError(f"Conflicting source registry definition for {source_id} field {field}.")
            if not left and right:
                current[field] = right
        if "acquisition_provenance" not in current and candidate.get("acquisition_provenance"):
            current["acquisition_provenance"] = candidate["acquisition_provenance"]
    merged["sources"] = sorted(existing_index.values(), key=lambda record: record["id"])
    return merged


def persist_source_registry(path: Path, payload: dict[str, object]) -> None:
    write_json(path, payload)


def _append_claim(
    claims: list[dict[str, object]],
    *,
    claim_id: str,
    text: str,
    claim_type: str,
    evidence_sources: list[str],
    confidence: str | None = None,
    section: str | None = None,
) -> None:
    record: dict[str, object] = {
        "id": claim_id,
        "text": text,
        "type": claim_type,
        "provenance": [],
        "evidence_sources": evidence_sources,
        "unclassified_markers": [],
    }
    if confidence is not None:
        record["confidence"] = confidence
    if section is not None:
        record["section"] = section
    claims.append(record)


def _entry_text(item: object) -> str:
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        for key in (
            "text",
            "point",
            "summary",
            "topic",
            "issue",
            "reason",
            "impact",
            "reduction_strategy",
            "what_would_reduce_it",
            "notes",
            "limitation",
            "quality",
            "source_name",
            "biases_or_freshness",
        ):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                return value
    raise TypeError("Unsupported entry type for claim-map conversion.")


def _entry_sources(item: object) -> list[str]:
    if isinstance(item, dict):
        if isinstance(item.get("evidence_sources"), list):
            return [source for source in item["evidence_sources"] if isinstance(source, str)]
        source_values = []
        for key in ("source_id", "id"):
            value = item.get(key)
            if isinstance(value, str) and SOURCE_ID_PATTERN.match(value):
                source_values.append(value)
        return source_values
    return []


def build_claim_map_from_stage_json(stage_id: str, payload: dict[str, object]) -> dict[str, object]:
    payload = normalize_stage_citations(stage_id, payload)
    claims: list[dict[str, object]] = []
    if stage_id in {"research-a", "research-b"}:
        for item in payload.get("facts", []):
            _append_claim(
                claims,
                claim_id=item["id"],
                text=item["text"],
                claim_type="fact",
                evidence_sources=list(item.get("evidence_sources", [])),
                section="Facts",
            )
        for item in payload.get("inferences", []):
            _append_claim(
                claims,
                claim_id=item["id"],
                text=item["text"],
                claim_type="inference",
                evidence_sources=list(item.get("evidence_sources", [])),
                confidence=item.get("confidence"),
                section="Inferences",
            )
        for index, item in enumerate(payload.get("evidence_gaps", []), start=1):
            _append_claim(
                claims,
                claim_id=f"{stage_id}-gap-{index:03d}",
                text=_entry_text(item),
                claim_type="evidence_gap",
                evidence_sources=_entry_sources(item),
                section="Evidence Gaps",
            )
    elif stage_id == "judge":
        for item in payload.get("supported_conclusions", []):
            _append_claim(
                claims,
                claim_id=item["id"],
                text=item["text"],
                claim_type="fact",
                evidence_sources=list(item.get("evidence_sources", [])),
                section="Supported Conclusions",
            )
        for item in payload.get("synthesis_judgments", []):
            _append_claim(
                claims,
                claim_id=item["id"],
                text=item["text"],
                claim_type="inference",
                evidence_sources=list(item.get("evidence_sources", [])),
                confidence=item.get("confidence"),
                section="Inferences And Synthesis Judgments",
            )
        for index, item in enumerate(payload.get("unresolved_disagreements", []), start=1):
            _append_claim(
                claims,
                claim_id=f"judge-disagreement-{index:03d}",
                text=_entry_text(item),
                claim_type="evaluation",
                evidence_sources=_entry_sources(item),
                section="Unresolved Disagreements",
            )
        confidence_assessment = payload.get("confidence_assessment", [])
        if isinstance(confidence_assessment, dict):
            summary = confidence_assessment.get("summary")
            if isinstance(summary, str) and summary.strip():
                _append_claim(
                    claims,
                    claim_id="judge-confidence-001",
                    text=summary,
                    claim_type="evaluation",
                    evidence_sources=[],
                    section="Confidence Assessment",
                )
            topics = confidence_assessment.get("topics")
            if isinstance(topics, list):
                for index, item in enumerate(topics, start=1):
                    _append_claim(
                        claims,
                        claim_id=f"judge-confidence-topic-{index:03d}",
                        text=_entry_text(item),
                        claim_type="evaluation",
                        evidence_sources=_entry_sources(item),
                        section="Confidence Assessment",
                    )
        else:
            confidence_items = [confidence_assessment] if isinstance(confidence_assessment, str) else confidence_assessment
            for index, item in enumerate(confidence_items, start=1):
                _append_claim(
                    claims,
                    claim_id=f"judge-confidence-{index:03d}",
                    text=_entry_text(item),
                    claim_type="evaluation",
                    evidence_sources=_entry_sources(item),
                    section="Confidence Assessment",
                )
        for index, item in enumerate(payload.get("evidence_gaps", []), start=1):
            _append_claim(
                claims,
                claim_id=f"judge-gap-{index:03d}",
                text=_entry_text(item),
                claim_type="evidence_gap",
                evidence_sources=_entry_sources(item),
                section="Evidence Gaps",
            )
        recommended_structure = payload.get("recommended_artifact_structure", [])
        if isinstance(recommended_structure, dict):
            structure_items = recommended_structure.get("sections", [])
        elif isinstance(recommended_structure, str):
            structure_items = [recommended_structure]
        else:
            structure_items = recommended_structure
        for index, item in enumerate(structure_items, start=1):
            text = _entry_text(item)
            _append_claim(
                claims,
                claim_id=f"judge-structure-{index:03d}",
                text=text,
                claim_type="report_structure",
                evidence_sources=[],
                section="Recommended Final Artifact Structure",
            )
    else:
        raise KeyError(f"Stage {stage_id} does not have a structured claim map.")

    summary = {
        "claim_type_counts": {},
        "claims_with_unclassified_markers": [],
        "fact_count": 0,
        "inference_count": 0,
        "provenance_only_fact_ids": [],
        "uncited_fact_ids": [],
        "uncited_inference_ids": [],
    }
    for claim in claims:
        claim_type = str(claim["type"])
        summary["claim_type_counts"][claim_type] = summary["claim_type_counts"].get(claim_type, 0) + 1
        if claim_type == "fact":
            summary["fact_count"] += 1
            if not claim["evidence_sources"]:
                summary["uncited_fact_ids"].append(claim["id"])
        if claim_type == "inference":
            summary["inference_count"] += 1
            if not claim["evidence_sources"]:
                summary["uncited_inference_ids"].append(claim["id"])
    return {"claims": claims, "summary": summary}

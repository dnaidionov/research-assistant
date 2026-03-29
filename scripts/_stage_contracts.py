#!/usr/bin/env python3

from __future__ import annotations

import json
import re
from copy import deepcopy
from pathlib import Path
from urllib.parse import urlparse

from _claim_model import build_claim_register
from _workflow_lib import write_json


STRUCTURED_STAGE_IDS = {"research-a", "research-b", "critique-a-on-b", "critique-b-on-a", "judge"}
SOURCE_ID_PATTERN = re.compile(r"^(?:SRC|DOC)-[A-Z0-9._-]+$|^S[0-9]{1,6}$|^https?://\S+$", re.IGNORECASE)
SECTION_HEADING_PATTERN = re.compile(r"^#\s+(.+)$")
LIST_ITEM_PATTERN = re.compile(r"^\s*\d+[.)]\s+")
MARKDOWN_BULLET_PATTERN = re.compile(r"^\s*[-*+]\s+")
CITATION_BLOCK_PATTERN = re.compile(r"\[([^\[\]]+)\]")
CONFIDENCE_PATTERN = re.compile(r"\bconfidence\s*:\s*(low|medium|high)\b", re.IGNORECASE)
RECOVERED_SOURCE_AUTHORITY = "recovered-from-markdown"
SOURCE_CLASSES = {"external_evidence", "job_input", "workflow_provenance", "recovered_provisional"}
SUPPORT_LINK_ROLES = {"evidence", "context", "challenge", "provenance"}
AUDITABLE_LOCATOR_PATTERN = re.compile(
    r"^(?:https?://\S+|file://\S+|app://\S+|urn:[^\s]+|(?:\.{0,2}/|/)\S+|[A-Za-z0-9._-]+\.[A-Za-z]{2,}(?:/\S*)?)$"
)
BARE_DOMAIN_PATTERN = re.compile(r"^[A-Za-z0-9._-]+\.[A-Za-z]{2,}$")

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
    "critique-a-on-b": (
        "stage",
        "supported_claims",
        "unsupported_claims",
        "weak_source_issues",
        "omissions",
        "overreach",
        "unresolved_disagreements",
        "summary",
        "sources",
    ),
    "critique-b-on-a": (
        "stage",
        "supported_claims",
        "unsupported_claims",
        "weak_source_issues",
        "omissions",
        "overreach",
        "unresolved_disagreements",
        "summary",
        "sources",
    ),
}

SOURCE_PASS_KEYS = ("stage", "sources")


def is_structured_stage(stage_id: str) -> bool:
    return stage_id in STRUCTURED_STAGE_IDS


def stage_claim_keys(stage_id: str) -> tuple[str, ...]:
    expected_keys = STAGE_JSON_KEYS.get(stage_id)
    if expected_keys is None:
        raise KeyError(f"Stage {stage_id} does not have a structured contract.")
    return tuple(key for key in expected_keys if key != "sources")


def stage_structured_output_path(run_dir: Path, stage_id: str) -> Path:
    filename_by_stage = {
        "research-a": "02-research-a.json",
        "research-b": "03-research-b.json",
        "critique-a-on-b": "04-critique-a-on-b.json",
        "critique-b-on-a": "05-critique-b-on-a.json",
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
        "source_class": "recovered_provisional",
        "locator": f"urn:recovered:{stage_id}:{source_id}",
        "acquisition_provenance": "recovered_from_markdown",
    }


def normalize_source_record(source: dict[str, object]) -> dict[str, object]:
    normalized = dict(source)
    source_class = normalized.get("source_class")
    explicit_source_class = isinstance(source_class, str) and bool(source_class.strip())

    source_type = str(normalized.get("type") or "").strip().lower()
    authority = str(normalized.get("authority") or "").strip()
    acquisition = str(normalized.get("acquisition_provenance") or "").strip().lower()
    locator = str(normalized.get("locator") or "").strip().lower()
    if isinstance(source_class, str) and source_class.strip():
        normalized_class = source_class.strip().lower()
        if normalized_class in {"primary", "input", "provided", "user_input"} and source_type in {
            "job_input",
            "project_brief",
            "job_config",
        }:
            normalized["source_class"] = "job_input"
            return normalized
        if normalized_class in {"workflow", "trace", "traceability"} and (
            source_type in {"workflow_artifact", "workflow_provenance"} or locator.startswith("urn:workflow:")
        ):
            normalized["source_class"] = "workflow_provenance"
            return normalized
        if normalized_class in {"recovered", "provisional"} and (
            authority == RECOVERED_SOURCE_AUTHORITY or acquisition == "recovered_from_markdown"
        ):
            normalized["source_class"] = "recovered_provisional"
        elif normalized_class in SOURCE_CLASSES:
            normalized["source_class"] = normalized_class

    if normalized.get("source_class") not in SOURCE_CLASSES and not explicit_source_class:
        if authority == RECOVERED_SOURCE_AUTHORITY or acquisition == "recovered_from_markdown":
            normalized["source_class"] = "recovered_provisional"
        elif source_type in {"project_brief", "job_input", "job_config"}:
            normalized["source_class"] = "job_input"
        elif source_type in {"workflow_artifact", "workflow_provenance"} or locator.startswith("urn:workflow:"):
            normalized["source_class"] = "workflow_provenance"
        else:
            normalized["source_class"] = "external_evidence"

    normalized.setdefault("evidence_kind", _infer_evidence_kind(normalized))
    normalized.setdefault("authority_tier", _infer_authority_tier(normalized))
    normalized.setdefault("freshness_status", _infer_freshness_status(normalized))
    if "publication_date" not in normalized and isinstance(normalized.get("freshness_date"), str):
        normalized["publication_date"] = normalized["freshness_date"]
    support_flags = _infer_support_flags(normalized)
    normalized.setdefault("supports_world_claims", support_flags["supports_world_claims"])
    normalized.setdefault("supports_process_claims", support_flags["supports_process_claims"])
    normalized.setdefault("policy_outcome", _infer_policy_outcome(normalized))
    normalized.setdefault("policy_notes", _infer_policy_notes(normalized))
    return normalized


def _infer_evidence_kind(source: dict[str, object]) -> str:
    source_class = str(source.get("source_class") or "").strip()
    source_type = str(source.get("type") or "").strip().lower()
    if source_class == "job_input":
        return "job_input"
    if source_class == "workflow_provenance":
        return "workflow_trace"
    if source_class == "recovered_provisional":
        return "recovered_artifact"
    if "marketing" in source_type:
        return "marketing"
    if any(token in source_type for token in ("official documentation", "datasheet", "specification", "spec sheet")):
        return "official_documentation"
    if any(token in source_type for token in ("technical note", "technical report", "benchmark", "paper", "report")):
        return "technical_report"
    return "external_report"


def _infer_authority_tier(source: dict[str, object]) -> str:
    source_class = str(source.get("source_class") or "").strip()
    evidence_kind = str(source.get("evidence_kind") or "").strip()
    authority = str(source.get("authority") or "").strip().lower()
    if source_class == "job_input":
        return "primary_input"
    if source_class == "workflow_provenance":
        return "workflow_only"
    if source_class == "recovered_provisional":
        return "provisional_recovery"
    if evidence_kind == "marketing":
        return "vendor_marketing"
    if evidence_kind == "official_documentation":
        return "primary_vendor"
    if evidence_kind == "technical_report" and authority == "vendor":
        return "secondary_vendor"
    return "unknown"


def _infer_freshness_status(source: dict[str, object]) -> str:
    freshness_status = str(source.get("freshness_status") or "").strip()
    if freshness_status:
        return freshness_status
    publication_date = str(source.get("publication_date") or source.get("freshness_date") or "").strip()
    return "undated" if publication_date else "unknown"


def _infer_support_flags(source: dict[str, object]) -> dict[str, bool]:
    source_class = str(source.get("source_class") or "").strip()
    evidence_kind = str(source.get("evidence_kind") or "").strip()
    if source_class == "workflow_provenance":
        return {"supports_world_claims": False, "supports_process_claims": True}
    if source_class == "recovered_provisional":
        return {"supports_world_claims": False, "supports_process_claims": False}
    if source_class == "job_input":
        return {"supports_world_claims": True, "supports_process_claims": False}
    if evidence_kind == "marketing":
        return {"supports_world_claims": True, "supports_process_claims": False}
    return {"supports_world_claims": True, "supports_process_claims": False}


def _infer_policy_outcome(source: dict[str, object]) -> str:
    source_class = str(source.get("source_class") or "").strip()
    evidence_kind = str(source.get("evidence_kind") or "").strip()
    freshness_status = str(source.get("freshness_status") or "").strip()
    explicit = str(source.get("policy_outcome") or "").strip()
    if explicit in {"allowed", "allowed_with_warning", "disfavored", "blocked"}:
        return explicit
    if source_class in {"workflow_provenance", "recovered_provisional"}:
        return "blocked"
    if evidence_kind == "marketing":
        return "disfavored"
    if freshness_status == "stale":
        return "allowed_with_warning"
    return "allowed"


def _infer_policy_notes(source: dict[str, object]) -> list[str]:
    explicit = source.get("policy_notes")
    if isinstance(explicit, list):
        return [str(note).strip() for note in explicit if str(note).strip()]
    if isinstance(explicit, str) and explicit.strip():
        return [explicit.strip()]
    source_class = str(source.get("source_class") or "").strip()
    evidence_kind = str(source.get("evidence_kind") or "").strip()
    freshness_status = str(source.get("freshness_status") or "").strip()
    if source_class == "workflow_provenance":
        return ["Workflow provenance is not user-facing evidence."]
    if source_class == "recovered_provisional":
        return ["Recovered provisional source is not publication-safe evidence."]
    if evidence_kind == "marketing":
        return ["Marketing-only source is disfavored for final publication."]
    if freshness_status == "stale":
        return ["Source is stale and should be corroborated by fresher evidence."]
    return []


def source_supports_world_claims(source_record: dict[str, str]) -> bool:
    if "supports_world_claims" in source_record:
        value = source_record.get("supports_world_claims")
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() == "true"
    return source_record.get("source_class") in {"external_evidence", "job_input"}


def auditable_locator(locator: object, source_class: str) -> bool:
    if not isinstance(locator, str) or not locator.strip():
        return False
    if source_class in {"job_input", "workflow_provenance", "recovered_provisional"}:
        return True
    return bool(AUDITABLE_LOCATOR_PATTERN.match(locator.strip()))


def source_quality_warnings(payload: dict[str, object]) -> list[str]:
    warnings: list[str] = []
    sources = payload.get("sources", [])
    if not isinstance(sources, list):
        return warnings
    seen_external_locators: dict[str, str] = {}
    for position, source in enumerate(sources, start=1):
        if not isinstance(source, dict):
            continue
        normalized_source = normalize_source_record(source)
        source_class = str(normalized_source.get("source_class") or "")
        locator = str(normalized_source.get("locator") or "").strip()
        source_id = str(normalized_source.get("id") or "").strip()
        if source_class == "external_evidence" and BARE_DOMAIN_PATTERN.match(locator):
            warnings.append(f"sources[{position}].locator uses a bare domain; prefer a specific page URL when available.")
        if source_class == "external_evidence" and external_locator_lacks_exact_location(locator):
            warnings.append(
                f"sources[{position}].locator does not retain the exact location used; prefer the specific page or file locator instead of a root or degraded locator."
            )
        if source_class == "external_evidence" and locator:
            previous_source_id = seen_external_locators.get(locator)
            if previous_source_id and previous_source_id != source_id:
                warnings.append(
                    f"sources[{position}].locator duplicates external locator {locator} already used by {previous_source_id}; prefer one canonical source ID per locator."
                )
            elif source_id:
                seen_external_locators[locator] = source_id
        if source_class == "job_input" and ("/prompt-packets/" in locator or locator == "__PROMPT_PACKET__"):
            warnings.append(
                f"sources[{position}].locator points to a prompt packet; prefer the canonical job artifact such as brief.md or config.yaml."
            )
    return warnings


def external_locator_lacks_exact_location(locator: str) -> bool:
    stripped = locator.strip()
    if not stripped:
        return False
    if BARE_DOMAIN_PATTERN.match(stripped):
        return True
    if not stripped.lower().startswith(("http://", "https://")):
        return False
    parsed = urlparse(stripped)
    if not parsed.netloc:
        return False
    path = parsed.path or ""
    if path in {"", "/"} and not parsed.query and not parsed.fragment:
        return True
    return False


def _locator_specificity(locator: str) -> tuple[int, int]:
    stripped = locator.strip()
    if not stripped:
        return (0, 0)
    if BARE_DOMAIN_PATTERN.match(stripped):
        return (1, len(stripped))
    lowered = stripped.lower()
    if lowered.startswith(("http://", "https://")):
        parsed = urlparse(stripped)
        if parsed.netloc and (parsed.path in {"", "/"} and not parsed.query and not parsed.fragment):
            return (2, len(stripped))
        return (5, len(stripped))
    if lowered.startswith(("file://", "app://", "urn:")) or stripped.startswith(("/", "./", "../")):
        return (5, len(stripped))
    return (3, len(stripped))


def _prefer_more_specific_locator(current: str, candidate: str) -> str | None:
    if not current or not candidate or current == candidate:
        return None
    current_rank = _locator_specificity(current)
    candidate_rank = _locator_specificity(candidate)
    if candidate_rank > current_rank:
        return candidate
    if current_rank > candidate_rank:
        return current
    return None


def normalize_support_links(
    item: dict[str, object],
    source_index: dict[str, dict[str, str]],
    local_reference_map: dict[str, list[str]] | None = None,
) -> list[dict[str, str]]:
    links = item.get("support_links")
    normalized_links: list[dict[str, str]] = []
    if isinstance(links, list):
        for link in links:
            if not isinstance(link, dict):
                continue
            source_id = link.get("source_id")
            role = link.get("role")
            if not isinstance(source_id, str):
                continue
            if not isinstance(role, str) or role not in SUPPORT_LINK_ROLES:
                continue
            if local_reference_map and source_id in local_reference_map:
                for resolved_source_id in local_reference_map[source_id]:
                    normalized_link = {"source_id": resolved_source_id, "role": role}
                    if normalized_link not in normalized_links:
                        normalized_links.append(normalized_link)
                continue
            if not SOURCE_ID_PATTERN.match(source_id):
                continue
            normalized_links.append({"source_id": source_id, "role": role})
        if normalized_links:
            return normalized_links

    evidence_sources = item.get("evidence_sources")
    if isinstance(evidence_sources, list):
        for source_id in evidence_sources:
            if not isinstance(source_id, str):
                continue
            source_record = source_index.get(source_id, {})
            role = "evidence" if source_supports_world_claims(source_record) else "provenance"
            normalized_links.append({"source_id": source_id, "role": role})
    return normalized_links


def semantic_evidence_sources(
    item: dict[str, object],
    source_index: dict[str, dict[str, str]],
    local_reference_map: dict[str, list[str]] | None = None,
) -> list[str]:
    sources: list[str] = []
    for link in normalize_support_links(item, source_index, local_reference_map):
        source_record = source_index.get(link["source_id"], {})
        if link["role"] in {"evidence", "context"} and source_supports_world_claims(source_record):
            if link["source_id"] not in sources:
                sources.append(link["source_id"])
    return sources


def semantic_provenance_sources(
    item: dict[str, object],
    source_index: dict[str, dict[str, str]],
    local_reference_map: dict[str, list[str]] | None = None,
) -> list[str]:
    provenance: list[str] = []
    for link in normalize_support_links(item, source_index, local_reference_map):
        source_record = source_index.get(link["source_id"], {})
        is_provenance = link["role"] == "provenance" or source_record.get("source_class") == "workflow_provenance"
        if is_provenance and link["source_id"] not in provenance:
            provenance.append(link["source_id"])
    return provenance


def semantic_world_support_sources(
    item: dict[str, object],
    source_index: dict[str, dict[str, str]],
    local_reference_map: dict[str, list[str]] | None = None,
) -> list[str]:
    sources: list[str] = []
    for link in normalize_support_links(item, source_index, local_reference_map):
        source_record = source_index.get(link["source_id"], {})
        if link["role"] == "evidence" and source_supports_world_claims(source_record):
            if link["source_id"] not in sources:
                sources.append(link["source_id"])
    return sources


def claim_dependencies(item: dict[str, object], local_reference_map: dict[str, list[str]] | None = None) -> list[str]:
    dependencies: list[str] = []
    for dependency in item.get("claim_dependencies", []):
        if isinstance(dependency, str) and dependency not in dependencies:
            dependencies.append(dependency)
    if not local_reference_map:
        return dependencies
    for source_id in item.get("evidence_sources", []):
        if isinstance(source_id, str) and source_id in local_reference_map and source_id not in dependencies:
            dependencies.append(source_id)
    for link in item.get("support_links", []) if isinstance(item.get("support_links"), list) else []:
        if not isinstance(link, dict):
            continue
        source_id = link.get("source_id")
        if isinstance(source_id, str) and source_id in local_reference_map and source_id not in dependencies:
            dependencies.append(source_id)
    return dependencies


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


def _build_summary_payload(lines: list[str]) -> object:
    entries = collect_section_entries(lines)
    if not entries:
        return []
    records: list[dict[str, object]] = []
    for entry in entries:
        confidence = extract_confidence(entry)
        record: dict[str, object] = {
            "text": strip_citations_and_confidence(entry),
            "evidence_sources": extract_evidence_sources(entry),
        }
        if confidence is not None:
            record["confidence"] = confidence
        records.append(record)
    return records[0] if len(records) == 1 else records


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

    if stage_id in {"critique-a-on-b", "critique-b-on-a"}:
        payload = {
            "stage": stage_id,
            "supported_claims": _build_text_entries(sections.get("Claims That Survive Review", [])),
            "unsupported_claims": _build_text_entries(sections.get("Unsupported Claims", [])),
            "weak_source_issues": _build_text_entries(sections.get("Weak Sources Or Citation Problems", [])),
            "omissions": _build_text_entries(sections.get("Omissions And Missing Alternatives", [])),
            "overreach": _build_text_entries(sections.get("Overreach And Overconfident Inference", [])),
            "unresolved_disagreements": _build_text_entries(sections.get("Unresolved Disagreements For Judge", [])),
            "summary": _build_summary_payload(sections.get("Overall Critique Summary", [])),
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
    elif stage_id in {"critique-a-on-b", "critique-b-on-a"}:
        supporting_sections = []
        target_sections = [
            "supported_claims",
            "unsupported_claims",
            "weak_source_issues",
            "omissions",
            "overreach",
            "unresolved_disagreements",
        ]
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
    target_claim_catalog = normalized.get("target_claim_catalog")
    if isinstance(target_claim_catalog, list):
        for item in target_claim_catalog:
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
            original_support_links = item.get("support_links")
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
            dependencies = claim_dependencies(item, local_reference_map)
            if dependencies:
                item["claim_dependencies"] = dependencies
            if isinstance(original_support_links, list):
                normalized_links = normalize_support_links({"support_links": original_support_links}, {}, local_reference_map)
                if normalized_links:
                    item["support_links"] = normalized_links
                else:
                    item.pop("support_links", None)
            elif "support_links" in item:
                item.pop("support_links", None)
            if not isinstance(original_support_links, list) and dependencies:
                normalized_links = []
                for dependency in dependencies:
                    for resolved_source_id in local_reference_map.get(dependency, []):
                        candidate = {"source_id": resolved_source_id, "role": "evidence"}
                        if candidate not in normalized_links:
                            normalized_links.append(candidate)
                if normalized_links:
                    item["support_links"] = normalized_links
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


def _critique_summary_lines(items: object) -> list[str]:
    if isinstance(items, dict):
        text = _entry_text(items)
        confidence = items.get("confidence")
        suffix = f" Confidence: {confidence}" if isinstance(confidence, str) and confidence.strip() else ""
        return [f"- {text}{suffix}".rstrip()]
    entry_lines = _entry_lines(items)
    return [line if line.startswith("- ") else f"- {line}" for line in entry_lines]


def _format_unsupported_claim(item: object) -> str:
    if isinstance(item, dict) and any(key in item for key in ("target_claim", "reason", "needed_evidence")):
        parts: list[str] = []
        target_claim = item.get("target_claim")
        reason = item.get("reason")
        needed_evidence = item.get("needed_evidence")
        if isinstance(target_claim, str) and target_claim.strip():
            parts.append(f"Target claim: {target_claim}")
        if isinstance(reason, str) and reason.strip():
            parts.append(f"Why unsupported: {reason}")
        if isinstance(needed_evidence, str) and needed_evidence.strip():
            parts.append(f"Needed evidence: {needed_evidence}")
        suffix = _format_evidence_sources(_entry_sources(item))
        return f"- {'. '.join(parts)}{suffix}".rstrip()
    text = _entry_text(item)
    suffix = _format_evidence_sources(_entry_sources(item))
    return f"- {text}{suffix}".rstrip()


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

    if stage_id in {"critique-a-on-b", "critique-b-on-a"}:
        lines.extend(["# Claims That Survive Review", ""])
        lines.extend(_entry_lines(payload.get("supported_claims")))
        lines.extend(["", "# Unsupported Claims", ""])
        for item in payload.get("unsupported_claims", []):
            lines.append(_format_unsupported_claim(item))
        lines.extend(["", "# Weak Sources Or Citation Problems", ""])
        lines.extend(_entry_lines(payload.get("weak_source_issues")))
        lines.extend(["", "# Omissions And Missing Alternatives", ""])
        lines.extend(_entry_lines(payload.get("omissions")))
        lines.extend(["", "# Overreach And Overconfident Inference", ""])
        lines.extend(_entry_lines(payload.get("overreach")))
        lines.extend(["", "# Unresolved Disagreements For Judge", ""])
        lines.extend(_entry_lines(payload.get("unresolved_disagreements")))
        lines.extend(["", "# Overall Critique Summary", ""])
        lines.extend(_critique_summary_lines(payload.get("summary")))
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
        normalized_source = normalize_source_record(source)
        source_id = normalized_source.get("id")
        if not isinstance(source_id, str) or not SOURCE_ID_PATTERN.match(source_id):
            errors.append(f"sources[{position}].id must be a canonical external source ID.")
            continue
        if source_id in index:
            errors.append(f"sources[{position}].id duplicates source ID {source_id}.")
            continue
        for field in ("title", "type", "authority", "locator"):
            _require_string(normalized_source.get(field), f"sources[{position}].{field}", errors)
        source_class = normalized_source.get("source_class")
        if not isinstance(source_class, str) or source_class not in SOURCE_CLASSES:
            errors.append(f"sources[{position}].source_class must be one of {sorted(SOURCE_CLASSES)}.")
        elif not auditable_locator(normalized_source.get("locator"), source_class):
            errors.append(f"sources[{position}].locator must be an auditable locator for source_class {source_class}.")
        index[source_id] = {key: str(value) for key, value in normalized_source.items() if isinstance(value, str)}
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
        claim_deps = item.get("claim_dependencies")
        if claim_deps is not None:
            if not isinstance(claim_deps, list) or not all(isinstance(dep, str) and dep.strip() for dep in claim_deps):
                errors.append(f"{field_name}[{position}].claim_dependencies must be a list of non-empty claim IDs when present.")
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
        _validate_semantic_links(
            item,
            field_name=field_name,
            position=position,
            source_index=source_index,
            errors=errors,
            allowed_support_roles={"evidence"},
        )
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


def _validate_critique_summary(items: object, errors: list[str]) -> None:
    if isinstance(items, dict):
        text = items.get("text", items.get("summary"))
        _require_string(text, "summary.text", errors)
        confidence = items.get("confidence")
        if confidence is not None and confidence not in {"low", "medium", "high"}:
            errors.append("summary.confidence must be low, medium, or high.")
        return
    _validate_text_entry_list(items, "summary", errors)


def _validate_unsupported_claims(items: object, errors: list[str]) -> None:
    if not isinstance(items, list):
        errors.append("unsupported_claims must be a list.")
        return
    for position, item in enumerate(items, start=1):
        if isinstance(item, str):
            if not item.strip():
                errors.append(f"unsupported_claims[{position}] must not be empty.")
            continue
        if not isinstance(item, dict):
            errors.append(f"unsupported_claims[{position}] must be a string or object.")
            continue
        if any(key in item for key in ("target_claim", "reason", "needed_evidence")):
            _require_string(item.get("target_claim"), f"unsupported_claims[{position}].target_claim", errors)
            _require_string(item.get("reason"), f"unsupported_claims[{position}].reason", errors)
            _require_string(item.get("needed_evidence"), f"unsupported_claims[{position}].needed_evidence", errors)
            continue
        _require_string(item.get("text"), f"unsupported_claims[{position}].text", errors)


def _validate_semantic_links(
    item: dict[str, object],
    *,
    field_name: str,
    position: int,
    source_index: dict[str, dict[str, str]],
    errors: list[str],
    allowed_support_roles: set[str] | None = None,
) -> None:
    support_links = item.get("support_links")
    if support_links is None:
        return
    if not isinstance(support_links, list) or not support_links:
        errors.append(f"{field_name}[{position}].support_links must be a non-empty list when present.")
        return
    for link_position, link in enumerate(support_links, start=1):
        if not isinstance(link, dict):
            errors.append(f"{field_name}[{position}].support_links[{link_position}] must be an object.")
            continue
        source_id = link.get("source_id")
        role = link.get("role")
        if not isinstance(source_id, str) or not SOURCE_ID_PATTERN.match(source_id):
            errors.append(f"{field_name}[{position}].support_links[{link_position}].source_id must be a canonical source ID.")
            continue
        if source_id not in source_index:
            errors.append(f"{field_name}[{position}].support_links[{link_position}] references unresolved source ID {source_id}.")
        if not isinstance(role, str) or role not in SUPPORT_LINK_ROLES:
            errors.append(f"{field_name}[{position}].support_links[{link_position}].role must be one of {sorted(SUPPORT_LINK_ROLES)}.")
    allowed_sources = semantic_evidence_sources(item, source_index)
    if allowed_support_roles is not None:
        allowed_sources = []
        for link in normalize_support_links(item, source_index):
            source_record = source_index.get(link["source_id"], {})
            if link["role"] in allowed_support_roles and source_supports_world_claims(source_record):
                if link["source_id"] not in allowed_sources:
                    allowed_sources.append(link["source_id"])
    if not allowed_sources:
        errors.append(
            f"{field_name}[{position}] must include at least one semantic evidence link that supports world claims; nearby citations do not count."
        )


def _validate_flexible_object_list(
    items: object,
    field_name: str,
    errors: list[str],
    source_index: dict[str, dict[str, str]] | None = None,
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
        claim_deps = item.get("claim_dependencies")
        if claim_deps is not None:
            if not isinstance(claim_deps, list) or not all(isinstance(dep, str) and dep.strip() for dep in claim_deps):
                errors.append(f"{field_name}[{position}].claim_dependencies must be a list of non-empty claim IDs when present.")
        for key in accepted_source_keys:
            source_id = item.get(key)
            if source_id is not None and (not isinstance(source_id, str) or not SOURCE_ID_PATTERN.match(source_id)):
                errors.append(f"{field_name}[{position}].{key} must be a canonical external source ID.")
        if source_index is not None:
            evidence_sources = item.get("evidence_sources")
            if evidence_sources is not None:
                if not isinstance(evidence_sources, list) or not evidence_sources:
                    errors.append(f"{field_name}[{position}].evidence_sources must be a non-empty list when present.")
                else:
                    for source_id in evidence_sources:
                        if not isinstance(source_id, str) or not SOURCE_ID_PATTERN.match(source_id):
                            errors.append(f"{field_name}[{position}] contains a non-canonical source ID.")
                            continue
                        if source_id not in source_index:
                            errors.append(f"{field_name}[{position}] references unresolved source ID {source_id}.")
            _validate_semantic_links(
                item,
                field_name=field_name,
                position=position,
                source_index=source_index,
                errors=errors,
                allowed_support_roles={"evidence", "challenge"},
            )


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
            source_index,
            accepted_text_keys=("text", "issue", "reason", "impact", "reduction_strategy", "what_would_reduce_it"),
        )
        _validate_flexible_object_list(payload.get("evidence_gaps"), "evidence_gaps", errors, source_index, accepted_text_keys=("text",))
        _validate_flexible_object_list(
            payload.get("preliminary_disagreements"),
            "preliminary_disagreements",
            errors,
            source_index,
            accepted_text_keys=("text",),
        )
        _validate_source_evaluation(payload.get("source_evaluation"), errors)
        return errors

    if stage_id in {"critique-a-on-b", "critique-b-on-a"}:
        _validate_flexible_object_list(payload.get("supported_claims"), "supported_claims", errors, source_index, accepted_text_keys=("text",))
        _validate_unsupported_claims(payload.get("unsupported_claims"), errors)
        _validate_flexible_object_list(payload.get("weak_source_issues"), "weak_source_issues", errors, source_index, accepted_text_keys=("text",))
        _validate_flexible_object_list(payload.get("omissions"), "omissions", errors, source_index, accepted_text_keys=("text",))
        _validate_flexible_object_list(payload.get("overreach"), "overreach", errors, source_index, accepted_text_keys=("text",))
        _validate_flexible_object_list(payload.get("unresolved_disagreements"), "unresolved_disagreements", errors, source_index, accepted_text_keys=("text",))
        _validate_critique_summary(payload.get("summary"), errors)
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


def validate_source_pass_payload(stage_id: str, payload: dict[str, object]) -> list[str]:
    errors: list[str] = []
    if payload.get("stage") != stage_id:
        errors.append(f"stage must equal {stage_id}.")
    if "sources" not in payload:
        errors.append("Missing required key: sources.")
        return errors
    extra_keys = sorted(key for key in payload.keys() if key not in SOURCE_PASS_KEYS)
    if extra_keys:
        errors.append(f"source-pass payload may only include {list(SOURCE_PASS_KEYS)}; found extra keys: {', '.join(extra_keys)}.")
    _validate_source_records(payload.get("sources"), errors)
    return errors


def sanitize_claim_pass_payload(stage_id: str, payload: dict[str, object]) -> dict[str, object]:
    sanitized = deepcopy(payload)
    sanitized["stage"] = stage_id
    sanitized.pop("sources", None)
    return sanitized


def validate_claim_pass_payload(stage_id: str, payload: dict[str, object]) -> list[str]:
    errors: list[str] = []
    if payload.get("stage") != stage_id:
        errors.append(f"stage must equal {stage_id}.")
    expected_keys = set(stage_claim_keys(stage_id))
    if "sources" in payload:
        errors.append("claim-pass payload must not include sources.")
    extra_keys = sorted(key for key in payload.keys() if key not in expected_keys and key != "sources")
    if extra_keys:
        errors.append(f"claim-pass payload contains unexpected keys: {', '.join(extra_keys)}.")
    missing_keys = sorted(key for key in expected_keys if key not in payload)
    for key in missing_keys:
        errors.append(f"Missing required key: {key}.")
    return errors


def merge_stage_substep_payloads(
    stage_id: str,
    source_payload: dict[str, object],
    claim_payload: dict[str, object],
) -> dict[str, object]:
    merged = sanitize_claim_pass_payload(stage_id, claim_payload)
    merged["sources"] = deepcopy(source_payload.get("sources", []))
    return merged


def merge_source_registry(existing: dict[str, object], stage_sources: list[dict[str, object]]) -> dict[str, object]:
    merged = {"run_id": existing.get("run_id"), "notes": existing.get("notes", ""), "sources": []}
    existing_index = {
        normalize_source_record(source)["id"]: dict(normalize_source_record(source))
        for source in existing.get("sources", [])
        if isinstance(source, dict) and isinstance(normalize_source_record(source).get("id"), str)
    }
    for source in stage_sources:
        if not isinstance(source, dict):
            continue
        candidate = normalize_source_record(source)
        source_id = candidate.get("id")
        if not isinstance(source_id, str):
            continue
        current = existing_index.get(source_id)
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
        for field in ("title", "type", "authority", "locator", "source_class"):
            left = current.get(field)
            right = candidate.get(field)
            if left and right and left != right:
                if field == "locator":
                    preferred = _prefer_more_specific_locator(str(left), str(right))
                    if preferred == right:
                        current[field] = right
                        continue
                    if preferred == left:
                        continue
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
    provenance: list[str] | None = None,
    support_links: list[dict[str, str]] | None = None,
    claim_dependencies: list[str] | None = None,
    confidence: str | None = None,
    section: str | None = None,
) -> None:
    record: dict[str, object] = {
        "id": claim_id,
        "text": text,
        "type": claim_type,
        "provenance": provenance or [],
        "evidence_sources": evidence_sources,
        "unclassified_markers": [],
    }
    if support_links:
        record["support_links"] = support_links
    if claim_dependencies:
        record["claim_dependencies"] = claim_dependencies
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
            "target_claim",
            "needed_evidence",
            "summary",
            "point",
            "topic",
            "issue",
            "reason",
            "impact",
            "reduction_strategy",
            "what_would_reduce_it",
            "notes",
            "assessment",
            "limitation",
            "quality",
            "title",
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


def _claim_type(item: dict[str, object], default_type: str) -> str:
    candidate = item.get("claim_class", item.get("type"))
    if isinstance(candidate, str) and candidate.strip():
        return candidate.strip()
    return default_type


def _append_semantic_claim(
    claims: list[dict[str, object]],
    *,
    claim_id: str,
    text: str,
    claim_type: str,
    item: dict[str, object],
    source_index: dict[str, dict[str, str]],
    local_reference_map: dict[str, list[str]] | None = None,
    confidence: str | None = None,
    section: str | None = None,
) -> None:
    _append_claim(
        claims,
        claim_id=claim_id,
        text=text,
        claim_type=claim_type,
        evidence_sources=semantic_evidence_sources(item, source_index, local_reference_map),
        provenance=semantic_provenance_sources(item, source_index, local_reference_map),
        support_links=normalize_support_links(item, source_index, local_reference_map),
        claim_dependencies=claim_dependencies(item, local_reference_map),
        confidence=confidence,
        section=section,
    )


def build_claim_map_from_stage_json(stage_id: str, payload: dict[str, object]) -> dict[str, object]:
    payload = normalize_stage_citations(stage_id, payload)
    source_index = {
        source["id"]: normalize_source_record(source)
        for source in payload.get("sources", [])
        if isinstance(source, dict) and isinstance(source.get("id"), str)
    }
    local_reference_map: dict[str, list[str]] = {}
    if stage_id in {"research-a", "research-b"}:
        for item in payload.get("facts", []):
            if isinstance(item, dict) and isinstance(item.get("id"), str) and isinstance(item.get("evidence_sources"), list):
                local_reference_map[item["id"]] = [source for source in item["evidence_sources"] if isinstance(source, str)]
    if stage_id in {"critique-a-on-b", "critique-b-on-a"}:
        for item in payload.get("target_claim_catalog", []):
            if isinstance(item, dict) and isinstance(item.get("id"), str) and isinstance(item.get("evidence_sources"), list):
                local_reference_map[item["id"]] = [source for source in item["evidence_sources"] if isinstance(source, str)]
    elif stage_id == "judge":
        for item in payload.get("supported_conclusions", []):
            if isinstance(item, dict) and isinstance(item.get("id"), str) and isinstance(item.get("evidence_sources"), list):
                local_reference_map[item["id"]] = [source for source in item["evidence_sources"] if isinstance(source, str)]
    claims: list[dict[str, object]] = []
    if stage_id in {"research-a", "research-b"}:
        for item in payload.get("facts", []):
            _append_semantic_claim(
                claims,
                claim_id=item["id"],
                text=item["text"],
                claim_type=_claim_type(item, "fact"),
                item=item,
                source_index=source_index,
                local_reference_map=local_reference_map,
                section="Facts",
            )
        for item in payload.get("inferences", []):
            _append_semantic_claim(
                claims,
                claim_id=item["id"],
                text=item["text"],
                claim_type=_claim_type(item, "inference"),
                item=item,
                source_index=source_index,
                local_reference_map=local_reference_map,
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
    elif stage_id in {"critique-a-on-b", "critique-b-on-a"}:
        section_map = (
            ("supported_claims", "Claims That Survive Review"),
            ("unsupported_claims", "Unsupported Claims"),
            ("weak_source_issues", "Weak Sources Or Citation Problems"),
            ("omissions", "Omissions And Missing Alternatives"),
            ("overreach", "Overreach And Overconfident Inference"),
            ("unresolved_disagreements", "Unresolved Disagreements For Judge"),
        )
        for field_name, section_name in section_map:
            for index, item in enumerate(payload.get(field_name, []), start=1):
                normalized_item = item if isinstance(item, dict) else {"text": _entry_text(item), "evidence_sources": _entry_sources(item)}
                _append_semantic_claim(
                    claims,
                    claim_id=f"{stage_id}-{field_name}-{index:03d}",
                    text=_entry_text(item),
                    claim_type=_claim_type(normalized_item, "evaluation"),
                    item=normalized_item,
                    source_index=source_index,
                    local_reference_map=local_reference_map,
                    section=section_name,
                )
        summary = payload.get("summary")
        if isinstance(summary, list):
            for index, item in enumerate(summary, start=1):
                normalized_item = item if isinstance(item, dict) else {"text": _entry_text(item), "evidence_sources": _entry_sources(item)}
                _append_semantic_claim(
                    claims,
                    claim_id=f"{stage_id}-summary-{index:03d}",
                    text=_entry_text(item),
                    claim_type=_claim_type(normalized_item, "evaluation"),
                    item=normalized_item,
                    source_index=source_index,
                    local_reference_map=local_reference_map,
                    confidence=item.get("confidence") if isinstance(item, dict) else None,
                    section="Overall Critique Summary",
                )
        elif summary:
            normalized_item = summary if isinstance(summary, dict) else {"text": _entry_text(summary), "evidence_sources": _entry_sources(summary)}
            _append_semantic_claim(
                claims,
                claim_id=f"{stage_id}-summary-001",
                text=_entry_text(summary),
                claim_type=_claim_type(normalized_item, "evaluation"),
                item=normalized_item,
                source_index=source_index,
                local_reference_map=local_reference_map,
                confidence=summary.get("confidence") if isinstance(summary, dict) else None,
                section="Overall Critique Summary",
            )
    elif stage_id == "judge":
        for item in payload.get("supported_conclusions", []):
            _append_semantic_claim(
                claims,
                claim_id=item["id"],
                text=item["text"],
                claim_type=_claim_type(item, "fact"),
                item=item,
                source_index=source_index,
                local_reference_map=local_reference_map,
                section="Supported Conclusions",
            )
        for item in payload.get("synthesis_judgments", []):
            _append_semantic_claim(
                claims,
                claim_id=item["id"],
                text=item["text"],
                claim_type=_claim_type(item, "inference"),
                item=item,
                source_index=source_index,
                local_reference_map=local_reference_map,
                confidence=item.get("confidence"),
                section="Inferences And Synthesis Judgments",
            )
        for index, item in enumerate(payload.get("unresolved_disagreements", []), start=1):
            normalized_item = item if isinstance(item, dict) else {"text": _entry_text(item), "evidence_sources": _entry_sources(item)}
            _append_semantic_claim(
                claims,
                claim_id=f"judge-disagreement-{index:03d}",
                text=_entry_text(item),
                claim_type=_claim_type(normalized_item, "evaluation"),
                item=normalized_item,
                source_index=source_index,
                local_reference_map=local_reference_map,
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
                    normalized_item = item if isinstance(item, dict) else {"text": _entry_text(item), "evidence_sources": _entry_sources(item)}
                    _append_semantic_claim(
                        claims,
                        claim_id=f"judge-confidence-topic-{index:03d}",
                        text=_entry_text(item),
                        claim_type="evaluation",
                        item=normalized_item,
                        source_index=source_index,
                        local_reference_map=local_reference_map,
                        section="Confidence Assessment",
                    )
        else:
            confidence_items = [confidence_assessment] if isinstance(confidence_assessment, str) else confidence_assessment
            for index, item in enumerate(confidence_items, start=1):
                normalized_item = item if isinstance(item, dict) else {"text": _entry_text(item), "evidence_sources": _entry_sources(item)}
                _append_semantic_claim(
                    claims,
                    claim_id=f"judge-confidence-{index:03d}",
                    text=_entry_text(item),
                    claim_type="evaluation",
                    item=normalized_item,
                    source_index=source_index,
                    local_reference_map=local_reference_map,
                    section="Confidence Assessment",
                )
        for index, item in enumerate(payload.get("evidence_gaps", []), start=1):
            normalized_item = item if isinstance(item, dict) else {"text": _entry_text(item), "evidence_sources": _entry_sources(item)}
            _append_semantic_claim(
                claims,
                claim_id=f"judge-gap-{index:03d}",
                text=_entry_text(item),
                claim_type="evidence_gap",
                item=normalized_item,
                source_index=source_index,
                local_reference_map=local_reference_map,
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

    return build_claim_register(claims)

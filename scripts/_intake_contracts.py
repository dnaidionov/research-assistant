#!/usr/bin/env python3

from __future__ import annotations

import re

from _stage_contracts import SOURCE_CLASSES, SOURCE_ID_PATTERN, auditable_locator, normalize_source_record


INTAKE_KEYS = (
    "question",
    "scope",
    "constraints",
    "assumptions",
    "missing_information",
    "required_artifacts",
    "notes_for_researchers",
    "known_facts",
    "working_inferences",
    "uncertainty_notes",
    "sources",
)

SOURCE_ANCHOR_PATTERN = re.compile(r"^[^#\s]+#.+$")
INTAKE_SOURCE_PASS_KEYS = {"stage", "sources"}
INTAKE_FACT_LINEAGE_KEYS = {"stage", "known_facts"}
INTAKE_NORMALIZATION_KEYS = {
    "stage",
    "question",
    "scope",
    "constraints",
    "assumptions",
    "missing_information",
    "required_artifacts",
    "notes_for_researchers",
    "working_inferences",
    "uncertainty_notes",
}


def _require_string(value: object, field_name: str, errors: list[str]) -> None:
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{field_name} must be a non-empty string.")


def _require_string_list(value: object, field_name: str, errors: list[str]) -> None:
    if not isinstance(value, list):
        errors.append(f"{field_name} must be a list.")
        return
    for index, item in enumerate(value, start=1):
        if not isinstance(item, str) or not item.strip():
            errors.append(f"{field_name}[{index}] must be a non-empty string.")


def _validate_only_allowed_keys(payload: dict[str, object], allowed: set[str], label: str, errors: list[str]) -> None:
    extra = sorted(set(payload.keys()) - allowed)
    if extra:
        errors.append(f"{label} may only include {sorted(allowed)}; unexpected keys: {extra}.")


def _normalize_intake_sources(
    sources: object,
    *,
    field_prefix: str = "sources",
) -> tuple[dict[str, dict[str, str]], list[str]]:
    errors: list[str] = []
    source_index: dict[str, dict[str, str]] = {}
    if not isinstance(sources, list):
        errors.append(f"{field_prefix} must be a list.")
        return source_index, errors
    for index, item in enumerate(sources, start=1):
        if not isinstance(item, dict):
            errors.append(f"{field_prefix}[{index}] must be an object.")
            continue
        normalized = normalize_source_record(item)
        _require_string(normalized.get("id"), f"{field_prefix}[{index}].id", errors)
        _require_string(normalized.get("title"), f"{field_prefix}[{index}].title", errors)
        _require_string(normalized.get("type"), f"{field_prefix}[{index}].type", errors)
        _require_string(normalized.get("authority"), f"{field_prefix}[{index}].authority", errors)
        _require_string(normalized.get("locator"), f"{field_prefix}[{index}].locator", errors)
        source_id = normalized.get("id")
        if isinstance(source_id, str) and not SOURCE_ID_PATTERN.match(source_id):
            errors.append(f"{field_prefix}[{index}].id must be a canonical source ID.")
        source_class = normalized.get("source_class")
        if not isinstance(source_class, str) or source_class not in SOURCE_CLASSES:
            errors.append(f"{field_prefix}[{index}].source_class must be one of {sorted(SOURCE_CLASSES)}.")
        elif not auditable_locator(normalized.get("locator"), source_class):
            errors.append(f"{field_prefix}[{index}].locator must be an auditable locator for source_class {source_class}.")
        if isinstance(source_id, str):
            source_index[source_id] = {key: str(value) for key, value in normalized.items() if isinstance(value, str)}
    return source_index, errors


def _validate_known_facts(
    known_facts: object,
    source_index: dict[str, dict[str, str]],
    *,
    field_prefix: str = "known_facts",
) -> tuple[set[str], list[str]]:
    errors: list[str] = []
    known_fact_statements: set[str] = set()
    if not isinstance(known_facts, list):
        errors.append(f"{field_prefix} must be a list.")
        return known_fact_statements, errors
    for index, item in enumerate(known_facts, start=1):
        if not isinstance(item, dict):
            errors.append(f"{field_prefix}[{index}] must be an object.")
            continue
        _require_string(item.get("id"), f"{field_prefix}[{index}].id", errors)
        _require_string(item.get("statement"), f"{field_prefix}[{index}].statement", errors)
        _require_string(item.get("source_excerpt"), f"{field_prefix}[{index}].source_excerpt", errors)
        _require_string(item.get("source_anchor"), f"{field_prefix}[{index}].source_anchor", errors)
        source_anchor = item.get("source_anchor")
        if isinstance(source_anchor, str) and source_anchor.strip() and not SOURCE_ANCHOR_PATTERN.match(source_anchor.strip()):
            errors.append(f"{field_prefix}[{index}].source_anchor must include a document reference such as brief.md#Question.")
        statement = str(item.get("statement") or "").strip().lower()
        if statement:
            known_fact_statements.add(statement)
        source_ids = item.get("source_ids")
        if not isinstance(source_ids, list) or not source_ids:
            errors.append(f"{field_prefix}[{index}].source_ids must be a non-empty list.")
        else:
            for source_id in source_ids:
                if not isinstance(source_id, str) or not SOURCE_ID_PATTERN.match(source_id):
                    errors.append(f"{field_prefix}[{index}].source_ids contains a non-canonical source ID.")
                    continue
                if source_id not in source_index:
                    errors.append(f"{field_prefix}[{index}] references undefined source ID {source_id}.")
                    continue
                if source_index[source_id].get("source_class") != "job_input":
                    errors.append(f"{field_prefix}[{index}] may only reference job_input sources; {source_id} is not job_input.")
    return known_fact_statements, errors


def _validate_working_inferences(
    working_inferences: object,
    known_fact_statements: set[str],
    *,
    field_prefix: str = "working_inferences",
) -> list[str]:
    errors: list[str] = []
    if not isinstance(working_inferences, list):
        errors.append(f"{field_prefix} must be a list.")
        return errors
    for index, item in enumerate(working_inferences, start=1):
        if not isinstance(item, dict):
            errors.append(f"{field_prefix}[{index}] must be an object.")
            continue
        _require_string(item.get("statement"), f"{field_prefix}[{index}].statement", errors)
        _require_string(item.get("why_it_is_inference"), f"{field_prefix}[{index}].why_it_is_inference", errors)
        statement = str(item.get("statement") or "").strip().lower()
        if statement and statement in known_fact_statements:
            errors.append(f"{field_prefix}[{index}].statement duplicates known_facts and must remain separated from direct facts.")
    return errors


def validate_intake_sources_payload(payload: dict[str, object]) -> list[str]:
    errors: list[str] = []
    _validate_only_allowed_keys(payload, INTAKE_SOURCE_PASS_KEYS, "intake source pass", errors)
    if payload.get("stage") != "intake":
        errors.append("intake source pass must declare stage=intake.")
    _source_index, source_errors = _normalize_intake_sources(payload.get("sources"))
    errors.extend(source_errors)
    return errors


def sanitize_intake_sources_payload(payload: dict[str, object]) -> dict[str, object]:
    return {
        "stage": "intake",
        "sources": payload.get("sources", []),
    }


def validate_intake_fact_lineage_payload(
    payload: dict[str, object],
    sources_payload: dict[str, object],
) -> list[str]:
    errors: list[str] = []
    _validate_only_allowed_keys(payload, INTAKE_FACT_LINEAGE_KEYS, "intake fact-lineage pass", errors)
    if payload.get("stage") != "intake":
        errors.append("intake fact-lineage pass must declare stage=intake.")
    source_index, source_errors = _normalize_intake_sources(sources_payload.get("sources"))
    errors.extend(source_errors)
    _known_fact_statements, fact_errors = _validate_known_facts(payload.get("known_facts"), source_index)
    errors.extend(fact_errors)
    return errors


def sanitize_intake_fact_lineage_payload(payload: dict[str, object]) -> dict[str, object]:
    return {
        "stage": "intake",
        "known_facts": payload.get("known_facts", []),
    }


def validate_intake_normalization_payload(
    payload: dict[str, object],
    fact_payload: dict[str, object],
) -> list[str]:
    errors: list[str] = []
    _validate_only_allowed_keys(payload, INTAKE_NORMALIZATION_KEYS, "intake normalization pass", errors)
    if payload.get("stage") != "intake":
        errors.append("intake normalization pass must declare stage=intake.")
    _require_string(payload.get("question"), "question", errors)
    for key in (
        "scope",
        "constraints",
        "assumptions",
        "missing_information",
        "required_artifacts",
        "notes_for_researchers",
        "uncertainty_notes",
    ):
        _require_string_list(payload.get(key), key, errors)
    known_fact_statements, fact_errors = _validate_known_facts(fact_payload.get("known_facts"), {})
    errors.extend(error for error in fact_errors if "undefined source ID" not in error and "not job_input" not in error)
    errors.extend(_validate_working_inferences(payload.get("working_inferences"), known_fact_statements))
    return errors


def sanitize_intake_normalization_payload(payload: dict[str, object]) -> dict[str, object]:
    return {
        "stage": "intake",
        "question": payload.get("question"),
        "scope": payload.get("scope", []),
        "constraints": payload.get("constraints", []),
        "assumptions": payload.get("assumptions", []),
        "missing_information": payload.get("missing_information", []),
        "required_artifacts": payload.get("required_artifacts", []),
        "notes_for_researchers": payload.get("notes_for_researchers", []),
        "working_inferences": payload.get("working_inferences", []),
        "uncertainty_notes": payload.get("uncertainty_notes", []),
    }


def merge_intake_substep_payloads(
    sources_payload: dict[str, object],
    fact_payload: dict[str, object],
    normalization_payload: dict[str, object],
) -> dict[str, object]:
    return {
        "question": normalization_payload.get("question"),
        "scope": normalization_payload.get("scope"),
        "constraints": normalization_payload.get("constraints"),
        "assumptions": normalization_payload.get("assumptions"),
        "missing_information": normalization_payload.get("missing_information"),
        "required_artifacts": normalization_payload.get("required_artifacts"),
        "notes_for_researchers": normalization_payload.get("notes_for_researchers"),
        "known_facts": fact_payload.get("known_facts"),
        "working_inferences": normalization_payload.get("working_inferences"),
        "uncertainty_notes": normalization_payload.get("uncertainty_notes"),
        "sources": sources_payload.get("sources"),
    }


def validate_intake_payload(payload: dict[str, object]) -> list[str]:
    errors: list[str] = []
    for key in INTAKE_KEYS:
        if key not in payload:
            errors.append(f"Missing required key: {key}.")

    _require_string(payload.get("question"), "question", errors)
    for key in (
        "scope",
        "constraints",
        "assumptions",
        "missing_information",
        "required_artifacts",
        "notes_for_researchers",
        "uncertainty_notes",
    ):
        _require_string_list(payload.get(key), key, errors)

    source_index, source_errors = _normalize_intake_sources(payload.get("sources"))
    errors.extend(source_errors)
    known_fact_statements, fact_errors = _validate_known_facts(payload.get("known_facts"), source_index)
    errors.extend(fact_errors)
    errors.extend(_validate_working_inferences(payload.get("working_inferences"), known_fact_statements))

    return errors

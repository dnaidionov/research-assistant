#!/usr/bin/env python3

from __future__ import annotations

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

    source_index: dict[str, dict[str, str]] = {}
    sources = payload.get("sources")
    if not isinstance(sources, list):
        errors.append("sources must be a list.")
    else:
        for index, item in enumerate(sources, start=1):
            if not isinstance(item, dict):
                errors.append(f"sources[{index}] must be an object.")
                continue
            normalized = normalize_source_record(item)
            _require_string(normalized.get("id"), f"sources[{index}].id", errors)
            _require_string(normalized.get("title"), f"sources[{index}].title", errors)
            _require_string(normalized.get("type"), f"sources[{index}].type", errors)
            _require_string(normalized.get("authority"), f"sources[{index}].authority", errors)
            _require_string(normalized.get("locator"), f"sources[{index}].locator", errors)
            source_id = normalized.get("id")
            if isinstance(source_id, str) and not SOURCE_ID_PATTERN.match(source_id):
                errors.append(f"sources[{index}].id must be a canonical source ID.")
            source_class = normalized.get("source_class")
            if not isinstance(source_class, str) or source_class not in SOURCE_CLASSES:
                errors.append(f"sources[{index}].source_class must be one of {sorted(SOURCE_CLASSES)}.")
            elif not auditable_locator(normalized.get("locator"), source_class):
                errors.append(f"sources[{index}].locator must be an auditable locator for source_class {source_class}.")
            if isinstance(source_id, str):
                source_index[source_id] = {key: str(value) for key, value in normalized.items() if isinstance(value, str)}

    known_facts = payload.get("known_facts")
    if not isinstance(known_facts, list):
        errors.append("known_facts must be a list.")
    else:
        for index, item in enumerate(known_facts, start=1):
            if not isinstance(item, dict):
                errors.append(f"known_facts[{index}] must be an object.")
                continue
            _require_string(item.get("id"), f"known_facts[{index}].id", errors)
            _require_string(item.get("statement"), f"known_facts[{index}].statement", errors)
            _require_string(item.get("source_excerpt"), f"known_facts[{index}].source_excerpt", errors)
            _require_string(item.get("source_anchor"), f"known_facts[{index}].source_anchor", errors)
            source_ids = item.get("source_ids")
            if not isinstance(source_ids, list) or not source_ids:
                errors.append(f"known_facts[{index}].source_ids must be a non-empty list.")
            else:
                for source_id in source_ids:
                    if not isinstance(source_id, str) or not SOURCE_ID_PATTERN.match(source_id):
                        errors.append(f"known_facts[{index}].source_ids contains a non-canonical source ID.")
                        continue
                    if source_id not in source_index:
                        errors.append(f"known_facts[{index}] references undefined source ID {source_id}.")

    working_inferences = payload.get("working_inferences")
    if not isinstance(working_inferences, list):
        errors.append("working_inferences must be a list.")
    else:
        for index, item in enumerate(working_inferences, start=1):
            if not isinstance(item, dict):
                errors.append(f"working_inferences[{index}] must be an object.")
                continue
            _require_string(item.get("statement"), f"working_inferences[{index}].statement", errors)
            _require_string(item.get("why_it_is_inference"), f"working_inferences[{index}].why_it_is_inference", errors)

    return errors

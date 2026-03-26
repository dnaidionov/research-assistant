#!/usr/bin/env python3

from __future__ import annotations


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

    known_facts = payload.get("known_facts")
    if not isinstance(known_facts, list):
        errors.append("known_facts must be a list.")
    else:
        for index, item in enumerate(known_facts, start=1):
            if not isinstance(item, dict):
                errors.append(f"known_facts[{index}] must be an object.")
                continue
            _require_string(item.get("statement"), f"known_facts[{index}].statement", errors)
            _require_string(item.get("source_basis"), f"known_facts[{index}].source_basis", errors)

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

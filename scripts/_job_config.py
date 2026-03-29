#!/usr/bin/env python3

from __future__ import annotations

import re
from pathlib import Path


def parse_yaml_scalar(raw: str) -> object:
    value = raw.strip()
    if not value:
        return ""
    lowered = value.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if re.fullmatch(r"-?\d+", value):
        return int(value)
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        return value[1:-1]
    return value


def load_yaml_document(path: Path) -> dict[str, object]:
    lines: list[tuple[int, str]] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        lines.append((indent, raw_line.strip()))

    def parse_block(index: int, indent: int) -> tuple[object, int]:
        if index >= len(lines):
            return {}, index
        current_indent, current_text = lines[index]
        if current_indent < indent:
            return {}, index
        if current_text.startswith("- "):
            items: list[object] = []
            while index < len(lines):
                line_indent, text = lines[index]
                if line_indent < indent:
                    break
                if line_indent != indent or not text.startswith("- "):
                    raise ValueError(f"Unsupported YAML structure in {path}: {text}")
                item_value = text[2:].strip()
                if item_value:
                    items.append(parse_yaml_scalar(item_value))
                    index += 1
                    continue
                nested, index = parse_block(index + 1, indent + 2)
                items.append(nested)
            return items, index

        mapping: dict[str, object] = {}
        while index < len(lines):
            line_indent, text = lines[index]
            if line_indent < indent:
                break
            if line_indent != indent or ":" not in text:
                raise ValueError(f"Unsupported YAML structure in {path}: {text}")
            key, remainder = text.split(":", 1)
            key = key.strip()
            remainder = remainder.strip()
            if remainder:
                mapping[key] = parse_yaml_scalar(remainder)
                index += 1
                continue
            if index + 1 >= len(lines) or lines[index + 1][0] <= indent:
                mapping[key] = {}
                index += 1
                continue
            nested, index = parse_block(index + 1, indent + 2)
            mapping[key] = nested
        return mapping, index

    if not lines:
        return {}
    document, _ = parse_block(0, lines[0][0])
    if not isinstance(document, dict):
        raise ValueError(f"Expected YAML document root to be a mapping in {path}.")
    return document


def load_job_config(job_dir: Path) -> dict[str, object]:
    config_path = job_dir / "config.yaml"
    if not config_path.is_file():
        return {}
    return load_yaml_document(config_path)


def load_quality_policy_from_path(config_path: Path | None) -> dict[str, object] | None:
    if config_path is None or not config_path.is_file():
        return None
    document = load_yaml_document(config_path)
    quality_policy = document.get("quality_policy")
    return quality_policy if isinstance(quality_policy, dict) else None


def load_execution_config(job_dir: Path) -> dict[str, object] | None:
    document = load_job_config(job_dir)
    workflow = document.get("workflow")
    if not isinstance(workflow, dict):
        return None
    execution = workflow.get("execution")
    if not isinstance(execution, dict):
        return None
    return execution


def load_quality_policy(job_dir: Path) -> dict[str, object] | None:
    return load_quality_policy_from_path(job_dir / "config.yaml")

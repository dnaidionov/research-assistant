#!/usr/bin/env python3

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from _repo_paths import load_repo_path_config

REPO_ROOT = Path(__file__).resolve().parents[1]
ASSISTANT_REPO_NAME = "research-assistant"
DEFAULT_JOB_ROOT = load_repo_path_config(repo_root=REPO_ROOT).jobs_root

STAGES: list[dict[str, object]] = [
    {
        "id": "intake",
        "packet": "01-intake.md",
        "template": "intake-template.md",
        "output": "01-intake.json",
        "format": "json",
        "depends_on": [],
        "description": "Normalize the brief, identify gaps, and restate the assignment without adding facts.",
    },
    {
        "id": "research_pass_a",
        "packet": "02-research-pass-a.md",
        "template": "research-template.md",
        "output": "02-research-pass-a.md",
        "format": "markdown",
        "depends_on": ["intake"],
        "description": "Produce independent research pass A with explicit citations and separated facts and inferences.",
        "researcher_label": "Research Pass A",
    },
    {
        "id": "research_pass_b",
        "packet": "03-research-pass-b.md",
        "template": "research-template.md",
        "output": "03-research-pass-b.md",
        "format": "markdown",
        "depends_on": ["intake"],
        "description": "Produce independent research pass B with explicit citations and separated facts and inferences.",
        "researcher_label": "Research Pass B",
    },
    {
        "id": "critique_a_by_b",
        "packet": "04-critique-a-by-b.md",
        "template": "critique-template.md",
        "output": "04-critique-a-by-b.md",
        "format": "markdown",
        "depends_on": ["research_pass_a", "research_pass_b"],
        "description": "Critique research pass A from the perspective of B without rewriting or erasing disagreements.",
        "critic_label": "Research Pass B",
        "target_label": "Research Pass A",
    },
    {
        "id": "critique_b_by_a",
        "packet": "05-critique-b-by-a.md",
        "template": "critique-template.md",
        "output": "05-critique-b-by-a.md",
        "format": "markdown",
        "depends_on": ["research_pass_a", "research_pass_b"],
        "description": "Critique research pass B from the perspective of A without rewriting or erasing disagreements.",
        "critic_label": "Research Pass A",
        "target_label": "Research Pass B",
    },
    {
        "id": "judge_synthesis",
        "packet": "06-judge-synthesis.md",
        "template": "judge-template.md",
        "output": "06-judge-synthesis.md",
        "format": "markdown",
        "depends_on": ["critique_a_by_b", "critique_b_by_a"],
        "description": "Synthesize both passes, preserve unresolved disagreements, and distinguish supported conclusions from open questions.",
    },
    {
        "id": "claim_extraction",
        "packet": "07-claim-extraction.md",
        "template": "claim-extraction-template.md",
        "output": "07-claims.json",
        "format": "json",
        "depends_on": ["judge_synthesis"],
        "description": "Extract atomic claims with IDs, citations, and fact or inference typing from the synthesized report.",
    },
    {
        "id": "artifact_writing",
        "packet": "08-artifact-writing.md",
        "template": "artifact-writing-template.md",
        "output": "08-final-artifact.md",
        "format": "markdown",
        "depends_on": ["judge_synthesis", "claim_extraction"],
        "description": "Produce the final job artifact using only cited claims and preserving a visible disagreement log.",
    },
]

STAGE_BY_ID = {stage["id"]: stage for stage in STAGES}

REQUIRED_JOB_FILES = ["brief.md", "config.yaml"]
REQUIRED_JOB_DIRS = ["outputs", "evidence", "audit", "logs", "runs"]
PROMPT_TEMPLATE_DIR = REPO_ROOT / "shared" / "prompts"


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    errors: list[str]
    warnings: list[str]


def ensure_job_is_external(job_dir: Path) -> None:
    resolved = job_dir.resolve()
    try:
        resolved.relative_to(REPO_ROOT.resolve())
    except ValueError:
        return
    raise ValueError(
        f"Job directory must not live inside the assistant repo: {resolved}. "
        "The assistant repo must contain framework code only."
    )


def validate_job_dir(job_dir: Path) -> ValidationResult:
    errors: list[str] = []
    warnings: list[str] = []
    resolved = job_dir.resolve()

    if not resolved.exists():
        errors.append(f"Job directory does not exist: {resolved}")
        return ValidationResult(ok=False, errors=errors, warnings=warnings)

    if not resolved.is_dir():
        errors.append(f"Job path is not a directory: {resolved}")
        return ValidationResult(ok=False, errors=errors, warnings=warnings)

    if not ((resolved / ".git").exists()):
        errors.append("Missing .git directory or file. Each job must be an independent repo.")

    for name in REQUIRED_JOB_FILES:
        if not (resolved / name).is_file():
            errors.append(f"Missing required file: {name}")

    for name in REQUIRED_JOB_DIRS:
        if not (resolved / name).is_dir():
            errors.append(f"Missing required directory: {name}")

    if DEFAULT_JOB_ROOT.exists():
        try:
            resolved.relative_to(DEFAULT_JOB_ROOT.resolve())
        except ValueError:
            warnings.append(
                f"Job directory is outside the standard jobs root {DEFAULT_JOB_ROOT}; "
                "this is allowed for tests but not recommended for real runs."
            )

    return ValidationResult(ok=not errors, errors=sorted(errors), warnings=sorted(warnings))


def load_template(name: str) -> str:
    return (PROMPT_TEMPLATE_DIR / name).read_text(encoding="utf-8")


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = content.rstrip() + "\n"
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(normalized)
        handle.flush()
        os.fsync(handle.fileno())
        temp_path = Path(handle.name)
    temp_path.replace(path)


def write_json(path: Path, payload: object) -> None:
    write_text(path, json.dumps(payload, indent=2, sort_keys=True))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def build_manifest(paths: Iterable[Path], root: Path) -> list[dict[str, str]]:
    manifest: list[dict[str, str]] = []
    for path in sorted(paths):
        manifest.append(
            {
                "path": str(path.relative_to(root)),
                "sha256": sha256_file(path),
            }
        )
    return manifest


def slugify(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return normalized or "job"

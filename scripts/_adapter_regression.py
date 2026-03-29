#!/usr/bin/env python3

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Iterable

from _workflow_lib import REPO_ROOT


WATCHED_PREFIXES: tuple[str, ...] = (
    "fixtures/adapter-qualification/",
    "fixtures/reference-job/",
    "shared/prompts/",
    "schemas/",
    "scripts/",
)

WATCHED_EXACT_FILES: tuple[str, ...] = (
    "config.yaml",
)


def path_requires_adapter_regression(path: str) -> bool:
    normalized = path.strip().replace("\\", "/")
    if not normalized:
        return False
    if normalized in WATCHED_EXACT_FILES or normalized.endswith("/config.yaml"):
        return True
    return normalized.startswith(WATCHED_PREFIXES)


def watched_repo_files(repo_root: Path) -> list[Path]:
    files: list[Path] = []
    for prefix in WATCHED_PREFIXES:
        root = repo_root / prefix
        if not root.exists():
            continue
        files.extend(path for path in root.rglob("*") if path.is_file())
    return sorted(set(files))


def qualification_inputs_fingerprint(repo_root: Path, job_dir: Path | None = None) -> str:
    digest = hashlib.sha256()
    for path in watched_repo_files(repo_root):
        relative = path.relative_to(repo_root).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    if job_dir is not None:
        config_path = job_dir / "config.yaml"
        digest.update(b"job-config\0")
        if config_path.is_file():
            digest.update(config_path.read_bytes())
        else:
            digest.update(b"<missing>")
        digest.update(b"\0")
    return digest.hexdigest()


def report_is_stale_for_current_inputs(
    report: dict[str, object],
    *,
    repo_root: Path,
    job_dir: Path | None,
    expected_profile: str,
    expected_probe_set_version: str,
) -> bool:
    if report.get("profile") != expected_profile:
        return True
    if report.get("probe_set_version") != expected_probe_set_version:
        return True
    current_fingerprint = qualification_inputs_fingerprint(repo_root, job_dir)
    return report.get("qualification_inputs_fingerprint") != current_fingerprint

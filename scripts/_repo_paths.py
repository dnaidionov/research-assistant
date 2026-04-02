#!/usr/bin/env python3

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from _job_config import load_yaml_document


DEFAULT_ASSISTANT_ROOT = Path("~/Projects/research-hub/research-assistant").expanduser()
DEFAULT_JOBS_ROOT = Path("~/Projects/research-hub/jobs").expanduser()


@dataclass(frozen=True)
class RepoPathConfig:
    repo_root: Path
    assistant_root: Path
    jobs_root: Path
    jobs_index_root: Path
    config_path: Path
    source: str


def assistant_repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def repo_paths_config_path(repo_root: Path | None = None) -> Path:
    root = (repo_root or assistant_repo_root()).resolve()
    return root / "config" / "paths.yaml"


def _expand_path(value: object, default: Path) -> Path:
    if not isinstance(value, str) or not value.strip():
        return default
    return Path(value).expanduser()


def load_repo_path_config(*, repo_root: Path | None = None) -> RepoPathConfig:
    root = (repo_root or assistant_repo_root()).resolve()
    config_path = repo_paths_config_path(root)
    document: dict[str, object] = {}
    source = "defaults"
    if config_path.is_file():
        document = load_yaml_document(config_path)
        source = "config"

    assistant_root = _expand_path(document.get("assistant_root"), DEFAULT_ASSISTANT_ROOT)
    jobs_root = _expand_path(document.get("jobs_root"), DEFAULT_JOBS_ROOT)
    if assistant_root.resolve() != root:
        raise ValueError(
            f"Configured assistant_root {assistant_root} does not match the actual assistant repo path {root}. "
            "Update config/paths.yaml or move the repo so the documented assistant root matches reality."
        )
    return RepoPathConfig(
        repo_root=root,
        assistant_root=assistant_root.resolve(),
        jobs_root=jobs_root,
        jobs_index_root=root / "jobs-index",
        config_path=config_path,
        source=source,
    )


def resolve_jobs_root(*, repo_root: Path | None = None, cli_jobs_root: Path | None = None) -> Path:
    if cli_jobs_root is not None:
        return cli_jobs_root.expanduser()
    return load_repo_path_config(repo_root=repo_root).jobs_root

#!/usr/bin/env python3

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

DEFAULT_CODEX_BIN = "codex"
DEFAULT_GEMINI_BIN = "gemini"
DEFAULT_ANTIGRAVITY_BIN = "antigravity"
DEFAULT_CLAUDE_BIN = "claude"
DEFAULT_GEMINI_MODEL = "pro"


@dataclass(frozen=True)
class CLIAdapter:
    name: str
    command_builder: Callable[[str, Path, str, str | None], list[str]]
    stdout_materialization: set[str] = field(default_factory=set)
    supports_model_selection: bool = False


def build_codex_command(binary: str, job_dir: Path, prompt: str, model: str | None = None) -> list[str]:
    return [binary, "exec", "--full-auto", "-C", str(job_dir), prompt]


def build_gemini_command(binary: str, job_dir: Path, prompt: str, model: str | None = None) -> list[str]:
    return [binary, "--model", model or DEFAULT_GEMINI_MODEL, "-p", prompt, "-y", "--output-format", "text"]


def build_antigravity_command(binary: str, job_dir: Path, prompt: str, model: str | None = None) -> list[str]:
    command = [binary, "chat", "--mode", "agent", "--yes"]
    if model:
        command.extend(["--model", model])
    command.append(prompt)
    return command


def build_claude_command(binary: str, job_dir: Path, prompt: str, model: str | None = None) -> list[str]:
    command = [binary]
    if model:
        command.extend(["--model", model])
    command.extend(["-p", "--output-format", "text", "--permission-mode", "bypassPermissions", prompt])
    return command


CLI_ADAPTERS: dict[str, CLIAdapter] = {
    "codex": CLIAdapter(name="codex", command_builder=build_codex_command),
    "gemini": CLIAdapter(
        name="gemini",
        command_builder=build_gemini_command,
        stdout_materialization={"markdown", "structured_json"},
        supports_model_selection=True,
    ),
    "antigravity": CLIAdapter(
        name="antigravity",
        command_builder=build_antigravity_command,
        stdout_materialization={"markdown", "structured_json"},
        supports_model_selection=True,
    ),
    "claude": CLIAdapter(
        name="claude",
        command_builder=build_claude_command,
        stdout_materialization={"markdown", "structured_json"},
        supports_model_selection=True,
    ),
}


def build_adapter_command(adapter_name: str, binary: str, job_dir: Path, prompt: str, model: str | None = None) -> list[str]:
    adapter = CLI_ADAPTERS.get(adapter_name)
    if adapter is None:
        raise ValueError(f"Unknown adapter: {adapter_name}")
    return adapter.command_builder(binary, job_dir, prompt, model)

#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from _adapter_qualification import DEFAULT_FIXTURE_FAMILY
from _provider_runtime import build_provider_scorecard_report, record_live_drift_for_providers
from _workflow_lib import REPO_ROOT, write_json


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a live provider drift check against the stable sanitized reference job."
    )
    parser.add_argument(
        "--fixture-dir",
        help="Optional explicit path to a stable sanitized reference-job fixture.",
    )
    parser.add_argument(
        "--fixture-family",
        default=DEFAULT_FIXTURE_FAMILY,
        help="Named reference-job fixture family to use when --fixture-dir is omitted.",
    )
    parser.add_argument(
        "--work-root",
        help="Optional parent directory for the copied live-drift worktree. Defaults to a temporary directory.",
    )
    parser.add_argument("--primary-adapter", default="codex")
    parser.add_argument("--secondary-adapter", default="gemini")
    parser.add_argument("--codex-bin", default="codex")
    parser.add_argument("--gemini-bin", default="gemini")
    parser.add_argument("--antigravity-bin", default="antigravity")
    parser.add_argument("--claude-bin", default="claude")
    return parser.parse_args()


def resolve_reference_job_fixture_dir(family: str = DEFAULT_FIXTURE_FAMILY) -> Path:
    fixture_dir = REPO_ROOT / "fixtures" / "reference-job" / "families" / family
    if not fixture_dir.is_dir():
        raise ValueError(f"Reference-job fixture family does not exist: {family}")
    return fixture_dir


def prepare_reference_job_copy(fixture_dir: Path, destination_root: Path) -> Path:
    fixture_dir = fixture_dir.expanduser().resolve()
    if not fixture_dir.is_dir():
        raise ValueError(f"Reference fixture directory does not exist: {fixture_dir}")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    job_dir = destination_root / f"adapter-live-drift-{timestamp}"
    shutil.copytree(fixture_dir, job_dir)
    for directory in ("outputs", "evidence", "audit", "logs", "runs"):
        (job_dir / directory).mkdir(exist_ok=True)
    return job_dir


def build_live_drift_command(args: argparse.Namespace, job_dir: Path) -> list[str]:
    return [
        sys.executable,
        str(REPO_ROOT / "scripts" / "execute_workflow.py"),
        "--job-path",
        str(job_dir),
        "--primary-adapter",
        args.primary_adapter,
        "--secondary-adapter",
        args.secondary_adapter,
        "--codex-bin",
        args.codex_bin,
        "--gemini-bin",
        args.gemini_bin,
        "--antigravity-bin",
        args.antigravity_bin,
        "--claude-bin",
        args.claude_bin,
    ]


def main() -> int:
    args = parse_args()
    if args.work_root:
        destination_root = Path(args.work_root).expanduser().resolve()
        destination_root.mkdir(parents=True, exist_ok=True)
    else:
        destination_root = Path(tempfile.mkdtemp(prefix="adapter-live-drift-"))

    fixture_dir = Path(args.fixture_dir).expanduser() if args.fixture_dir else resolve_reference_job_fixture_dir(args.fixture_family)
    job_dir = prepare_reference_job_copy(fixture_dir, destination_root)
    command = build_live_drift_command(args, job_dir)
    completed = subprocess.run(command, cwd=REPO_ROOT, capture_output=True, text=True)
    run_dir = job_dir / "runs" / "run-001"
    state_path = run_dir / "workflow-state.json"
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.is_file() else {}
    report = {
        "fixture_dir": str(fixture_dir.resolve()),
        "fixture_family": args.fixture_family if not args.fixture_dir else None,
        "job_dir": str(job_dir),
        "run_dir": str(run_dir),
        "command": command,
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "workflow_status": state.get("status"),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    drift_status = "completed" if completed.returncode == 0 and state.get("status") == "completed" else "failed"
    updated_providers = record_live_drift_for_providers(
        job_dir,
        status=drift_status,
        family=args.fixture_family,
        run_id=run_dir.name,
    )
    report["updated_provider_scorecards"] = updated_providers
    report["provider_scorecard_report"] = build_provider_scorecard_report(job_dir)
    if run_dir.is_dir():
        report_path = run_dir / "audit" / "live-drift-report.json"
        write_json(report_path, report)
        report["report_path"] = str(report_path)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if completed.returncode == 0 and state.get("status") == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())

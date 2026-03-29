#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from _adapter_qualification import (
    PROBE_SET_VERSIONS,
    STRUCTURED_TRUST_LEVELS,
    classify_adapter_qualification,
    persist_adapter_qualification,
    qualification_report_path,
    trust_satisfies,
)
from _adapter_regression import report_is_stale_for_current_inputs
from _workflow_lib import REPO_ROOT


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Qualify a CLI adapter for deterministic workflow artifact contracts.")
    parser.add_argument("--adapter", required=True, help="Adapter name such as codex, gemini, claude, or antigravity.")
    parser.add_argument("--adapter-bin", required=True, help="Path to the adapter binary.")
    parser.add_argument("--job-dir", required=True, help="Path to the target job directory.")
    parser.add_argument("--run-dir", help="Optional run directory. When provided, write the qualification report into audit/adapter-qualification.")
    parser.add_argument("--provider-key", help="Optional provider key used to name the persisted qualification report.")
    parser.add_argument(
        "--profile",
        choices=sorted(PROBE_SET_VERSIONS.keys()),
        default="smoke",
        help="Qualification profile to run.",
    )
    parser.add_argument(
        "--only-if-stale",
        action="store_true",
        help="Reuse an existing persisted report unless the watched prompts, schemas, scripts, or job config have changed.",
    )
    parser.add_argument(
        "--min-trust",
        choices=list(STRUCTURED_TRUST_LEVELS),
        help="Optional minimum trust level required for a zero exit code.",
    )
    return parser.parse_args()


def qualification_exit_code(payload: dict[str, object], min_trust: str | None) -> int:
    if min_trust:
        return 0 if trust_satisfies(str(payload.get("trust_level", "unsupported")), min_trust) else 1
    return 0 if payload["classification"] in {"structured_safe", "markdown_only"} else 1


def main() -> int:
    args = parse_args()
    job_dir = Path(args.job_dir).expanduser()
    report_path: Path | None = None
    if args.run_dir:
        report_path = qualification_report_path(
            Path(args.run_dir).expanduser(),
            args.provider_key or args.adapter,
            args.adapter,
            args.profile,
        )
    if args.only_if_stale and report_path is not None and report_path.is_file():
        existing_payload = json.loads(report_path.read_text(encoding="utf-8"))
        if not report_is_stale_for_current_inputs(
            existing_payload,
            repo_root=REPO_ROOT,
            job_dir=job_dir,
            expected_profile=args.profile,
            expected_probe_set_version=PROBE_SET_VERSIONS[args.profile],
        ):
            print(json.dumps({**existing_payload, "skipped": True}, indent=2, sort_keys=True))
            return qualification_exit_code(existing_payload, args.min_trust)
    payload = classify_adapter_qualification(
        adapter_name=args.adapter,
        adapter_bin=Path(args.adapter_bin).expanduser(),
        job_dir=job_dir,
        profile=args.profile,
    )
    if args.run_dir:
        persist_adapter_qualification(
            Path(args.run_dir).expanduser(),
            args.provider_key or args.adapter,
            args.adapter,
            payload,
            profile=args.profile,
        )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return qualification_exit_code(payload, args.min_trust)


if __name__ == "__main__":
    raise SystemExit(main())

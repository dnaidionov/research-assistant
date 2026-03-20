#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from pathlib import Path

from _workflow_lib import validate_job_dir


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate a research job repository.")
    parser.add_argument("--job-dir", required=True, help="Path to the job repository.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    job_dir = Path(args.job_dir).expanduser()
    result = validate_job_dir(job_dir)
    payload = {
        "errors": result.errors,
        "job_dir": str(job_dir.resolve()),
        "ok": result.ok,
        "warnings": result.warnings,
    }

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"Job: {payload['job_dir']}")
        print(f"OK: {payload['ok']}")
        if payload["warnings"]:
            print("Warnings:")
            for warning in payload["warnings"]:
                print(f"- {warning}")
        if payload["errors"]:
            print("Errors:")
            for error in payload["errors"]:
                print(f"- {error}")

    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

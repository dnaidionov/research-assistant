#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from pathlib import Path

from _provider_runtime import build_provider_scorecard_report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize provider runtime scorecards for a job.")
    parser.add_argument("--job-dir", required=True, help="Path to the job directory.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_provider_scorecard_report(Path(args.job_dir).expanduser())
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if bool(report.get("ok")) else 1


if __name__ == "__main__":
    raise SystemExit(main())

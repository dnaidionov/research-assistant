#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from _workflow_state import rebuild_workflow_state


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Rebuild workflow-state.json from a run's append-only events.jsonl journal.")
    parser.add_argument("--run-dir", required=True, help="Path to the workflow run directory.")
    parser.add_argument("--json", action="store_true", help="Emit the rebuilt state as JSON to stdout.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    run_dir = Path(args.run_dir).expanduser()
    try:
        state = rebuild_workflow_state(run_dir)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(state, indent=2, sort_keys=True))
    else:
        print(run_dir / "workflow-state.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from pathlib import Path

from _research_quality import quality_gate_errors
from _workflow_lib import REPO_ROOT


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run research-quality benchmark fixtures.")
    parser.add_argument("--family", default="neutral", help="Benchmark family to evaluate.")
    parser.add_argument("--fixture-dir", help="Optional explicit benchmark fixture directory.")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of text.")
    return parser.parse_args()


def resolve_benchmark_family_dir(family: str) -> Path:
    family_dir = REPO_ROOT / "fixtures" / "benchmarks" / "families" / family
    if not family_dir.is_dir():
        raise ValueError(f"Benchmark family does not exist: {family}")
    return family_dir


def load_fixture_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def evaluate_benchmark_fixture(fixture_dir: Path) -> dict[str, object]:
    fixture_dir = fixture_dir.expanduser().resolve()
    claim_register = load_fixture_json(fixture_dir / "claim-register.json")
    source_index = load_fixture_json(fixture_dir / "sources.json")
    policy = load_fixture_json(fixture_dir / "policy.json")
    expected = load_fixture_json(fixture_dir / "expected.json")
    actual_errors = quality_gate_errors(claim_register, source_index, policy)
    expected_errors = [str(error) for error in expected.get("errors", []) if isinstance(error, str)]
    return {
        "fixture": fixture_dir.name,
        "family": fixture_dir.parent.name,
        "actual_errors": actual_errors,
        "expected_errors": expected_errors,
        "ok": sorted(actual_errors) == sorted(expected_errors),
    }


def evaluate_benchmark_family(family_dir: Path) -> dict[str, object]:
    fixtures = [path for path in sorted(family_dir.iterdir()) if path.is_dir()]
    results = [evaluate_benchmark_fixture(path) for path in fixtures]
    return {
        "family": family_dir.name,
        "ok": all(bool(result["ok"]) for result in results),
        "results": results,
    }


def main() -> int:
    args = parse_args()
    if args.fixture_dir:
        report = evaluate_benchmark_fixture(Path(args.fixture_dir))
    else:
        report = evaluate_benchmark_family(resolve_benchmark_family_dir(args.family))
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if bool(report.get("ok")) else 1


if __name__ == "__main__":
    raise SystemExit(main())

import json
import tempfile
import unittest
from pathlib import Path

import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from run_quality_benchmarks import evaluate_benchmark_fixture, resolve_benchmark_family_dir


class QualityBenchmarkTests(unittest.TestCase):
    def test_resolve_benchmark_family_dir_supports_neutral_family(self) -> None:
        family_dir = resolve_benchmark_family_dir("neutral")

        self.assertTrue(family_dir.is_dir())
        self.assertTrue((family_dir / "balanced-evidence").is_dir())

    def test_evaluate_benchmark_fixture_reports_expected_errors(self) -> None:
        fixture_dir = resolve_benchmark_family_dir("neutral") / "one-sided-recommendation"
        result = evaluate_benchmark_fixture(fixture_dir)

        self.assertTrue(result["ok"])
        self.assertTrue(any("one-sided" in error.lower() for error in result["actual_errors"]))
        self.assertEqual(sorted(result["actual_errors"]), sorted(result["expected_errors"]))

    def test_evaluate_benchmark_fixture_passes_when_no_errors_expected(self) -> None:
        fixture_dir = resolve_benchmark_family_dir("neutral") / "balanced-evidence"
        result = evaluate_benchmark_fixture(fixture_dir)

        self.assertTrue(result["ok"])
        self.assertEqual(result["actual_errors"], [])
        self.assertEqual(result["expected_errors"], [])


if __name__ == "__main__":
    unittest.main()

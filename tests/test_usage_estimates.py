import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from _usage_telemetry import _usage_totals, build_usage_record  # noqa: E402


def make_record(**overrides: object) -> dict[str, object]:
    base = dict(
        scope="stage",
        stage_id="research-a",
        status="completed",
        provider_key="codex",
        adapter="codex",
        model=None,
        started_at="2026-06-12T00:00:00Z",
        finished_at="2026-06-12T00:01:00Z",
        duration_ms=60000,
        prompt_text="p" * 400,
        stdout="o" * 200,
        stderr="",
    )
    base.update(overrides)
    return build_usage_record(**base)


class UsageEstimateTests(unittest.TestCase):
    def test_unreported_tokens_fall_back_to_byte_estimates(self) -> None:
        record = make_record()
        self.assertEqual(record["usage_status"], "estimated")
        self.assertEqual(record["estimated_input_tokens"], 100)
        self.assertEqual(record["estimated_output_tokens"], 50)
        self.assertEqual(record["estimated_total_tokens"], 150)
        self.assertIsNone(record["input_tokens"])

    def test_reported_tokens_suppress_estimates(self) -> None:
        record = make_record(stdout='{"input_tokens": 123, "output_tokens": 45}')
        self.assertEqual(record["usage_status"], "reported")
        self.assertEqual(record["input_tokens"], 123)
        self.assertIsNone(record["estimated_input_tokens"])

    def test_empty_interaction_stays_unavailable(self) -> None:
        record = make_record(prompt_text=None, stdout="")
        self.assertEqual(record["usage_status"], "unavailable")
        self.assertIsNone(record["estimated_total_tokens"])

    def test_totals_aggregate_estimates_separately_from_reported(self) -> None:
        records = [make_record(), make_record(stdout='{"input_tokens": 10, "output_tokens": 5}')]
        totals = _usage_totals(records)
        self.assertEqual(totals["estimated_token_records"], 1)
        self.assertEqual(totals["estimated_total_tokens"], 150)
        self.assertEqual(totals["input_tokens"], 10)


if __name__ == "__main__":
    unittest.main()

import json
import tempfile
import unittest
from pathlib import Path

import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from _provider_runtime import (
    apply_provider_runtime_policy,
    build_provider_scorecard_report,
    record_provider_qualification,
    record_live_drift_for_providers,
    record_live_drift_result,
    record_provider_repair_attempt,
    provider_scorecard_path,
    record_provider_stage_result,
    should_quarantine_provider,
)
from execute_workflow import StageAdapterSelection


class ProviderRuntimeTests(unittest.TestCase):
    def test_provider_scorecard_records_stage_results(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            job_dir = Path(tmpdir)
            record_provider_stage_result(job_dir, "gemini-research", "research-b", "failed", run_id="run-001")
            record_provider_stage_result(job_dir, "gemini-research", "judge", "completed", run_id="run-002")

            payload = json.loads(provider_scorecard_path(job_dir, "gemini-research").read_text(encoding="utf-8"))
            self.assertEqual(payload["totals"]["failed"], 1)
            self.assertEqual(payload["totals"]["completed"], 1)
            self.assertEqual(payload["stage_results"][0]["stage_id"], "research-b")

    def test_should_quarantine_provider_when_failure_threshold_is_met(self) -> None:
        scorecard = {
            "provider_key": "gemini-research",
            "totals": {"failed": 3, "completed": 0, "cancelled": 0, "aborted": 0},
            "live_drift": {"failed": 1, "completed": 0},
        }

        self.assertTrue(
            should_quarantine_provider(
                scorecard,
                {
                    "failure_threshold": 2,
                    "live_drift_failure_threshold": 1,
                },
            )
        )

    def test_runtime_policy_reroutes_quarantined_provider_to_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            job_dir = Path(tmpdir)
            provider_scorecard_path(job_dir, "secondary").parent.mkdir(parents=True, exist_ok=True)
            provider_scorecard_path(job_dir, "secondary").write_text(
                json.dumps(
                    {
                        "provider_key": "secondary",
                        "totals": {"failed": 3, "completed": 0, "cancelled": 0, "aborted": 0},
                        "live_drift": {"failed": 0, "completed": 0},
                    }
                ),
                encoding="utf-8",
            )
            assignments = {
                "research-b": StageAdapterSelection(adapter_name="gemini", provider_name="secondary"),
                "judge": StageAdapterSelection(adapter_name="gemini", provider_name="judge"),
            }
            provider_catalog = {
                "secondary-fallback": StageAdapterSelection(adapter_name="claude", provider_name="secondary-fallback"),
                "judge": StageAdapterSelection(adapter_name="gemini", provider_name="judge"),
            }

            updated = apply_provider_runtime_policy(
                job_dir,
                assignments,
                provider_catalog,
                {
                    "quarantine": {"failure_threshold": 2},
                    "stage_provider_fallbacks": {"research-b": "secondary-fallback"},
                },
            )

            self.assertEqual(updated["research-b"].adapter_name, "claude")
            self.assertEqual(updated["judge"].adapter_name, "gemini")

    def test_provider_scorecard_records_live_drift_and_repair_activity(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            job_dir = Path(tmpdir)
            record_live_drift_result(job_dir, "gemini-research", "failed", family="neutral")
            record_provider_repair_attempt(job_dir, "gemini-research", stage_id="research-b", run_id="run-001")

            payload = json.loads(provider_scorecard_path(job_dir, "gemini-research").read_text(encoding="utf-8"))
            self.assertEqual(payload["live_drift"]["failed"], 1)
            self.assertEqual(payload["live_drift"]["history"][0]["family"], "neutral")
            self.assertEqual(payload["repair"]["attempted"], 1)
            self.assertEqual(payload["repair"]["history"][0]["stage_id"], "research-b")

    def test_record_live_drift_for_providers_uses_only_observed_run_providers(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            job_dir = Path(tmpdir)
            (job_dir / "config.yaml").write_text(
                """
workflow:
  execution:
    providers:
      research_claude:
        adapter: claude
      judge_gemini:
        adapter: gemini
      fallback_unused:
        adapter: codex
""".strip()
                + "\n",
                encoding="utf-8",
            )
            report = {
                "adapter_name": "claude",
                "trust_level": "structured_safe_smoke",
                "classification": "structured_safe",
                "profile": "smoke",
                "probe_set_version": "test",
                "adapter_version": "test",
            }
            record_provider_qualification(job_dir, "research_claude", report, run_id="run-001")
            record_provider_stage_result(job_dir, "judge_gemini", "judge", "completed", run_id="run-001")

            updated = record_live_drift_for_providers(job_dir, status="completed", family="neutral", run_id="run-001")

            self.assertEqual(sorted(updated), ["judge_gemini", "research_claude"])
            judge_payload = json.loads(provider_scorecard_path(job_dir, "judge_gemini").read_text(encoding="utf-8"))
            self.assertEqual(judge_payload["live_drift"]["completed"], 1)
            self.assertFalse(provider_scorecard_path(job_dir, "fallback_unused").exists())

    def test_build_provider_scorecard_report_summarizes_trust_and_failures(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            job_dir = Path(tmpdir)
            record_provider_stage_result(job_dir, "gemini-research", "research-b", "failed", run_id="run-001")
            record_live_drift_result(job_dir, "gemini-research", "failed", family="neutral")
            report = build_provider_scorecard_report(job_dir)

            self.assertFalse(report["ok"])
            self.assertEqual(report["providers"][0]["provider_key"], "gemini-research")
            self.assertEqual(report["providers"][0]["totals"]["failed"], 1)


if __name__ == "__main__":
    unittest.main()

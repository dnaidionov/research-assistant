import json
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
RUN_WORKFLOW = REPO_ROOT / "scripts" / "run_workflow.py"
RECORD_MANUAL_STAGE = REPO_ROOT / "scripts" / "record_manual_stage.py"


class RecordManualStageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)
        self.job_dir = self.root / "jobs" / "manual-job"
        self.job_dir.mkdir(parents=True)
        (self.job_dir / ".git").mkdir()
        (self.job_dir / "brief.md").write_text("# Brief\n", encoding="utf-8")
        (self.job_dir / "config.yaml").write_text(
            textwrap.dedent(
                """\
                topic: manual-job
                workflow:
                  execution:
                    providers:
                      codex_primary:
                        adapter: codex
                      claude_secondary:
                        adapter: claude
                        model: claude-sonnet-4-6
                    stage_providers:
                      intake: codex_primary
                      research-a: codex_primary
                      research-b: claude_secondary
                      critique-a-on-b: codex_primary
                      critique-b-on-a: claude_secondary
                      judge: claude_secondary
                """
            ),
            encoding="utf-8",
        )
        for directory in ("outputs", "evidence", "audit", "logs", "runs"):
            (self.job_dir / directory).mkdir()

        scaffolded = subprocess.run(
            ["python3", str(RUN_WORKFLOW), "--job-path", str(self.job_dir), "--run-id", "run-manual"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(scaffolded.returncode, 0, scaffolded.stderr)
        self.run_dir = self.job_dir / "runs" / "run-manual"

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_started_records_attempted_provider_model(self) -> None:
        result = subprocess.run(
            [
                "python3",
                str(RECORD_MANUAL_STAGE),
                "--run-dir",
                str(self.run_dir),
                "--stage",
                "research-b",
                "--status",
                "started",
                "--adapter",
                "claude",
                "--model",
                "claude-sonnet-4-6",
                "--provider-key",
                "claude_secondary",
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        snapshot = json.loads((self.run_dir / "audit" / "execution-config.json").read_text(encoding="utf-8"))
        self.assertEqual(
            snapshot["actual_stage_assignments"]["research-b"],
            {
                "adapter": "claude",
                "model": "claude-sonnet-4-6",
                "provider_key": "claude_secondary",
                "status": "started",
            },
        )

    def test_completed_requires_expected_output_artifact(self) -> None:
        result = subprocess.run(
            [
                "python3",
                str(RECORD_MANUAL_STAGE),
                "--run-dir",
                str(self.run_dir),
                "--stage",
                "research-a",
                "--status",
                "completed",
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("completed output artifact", result.stderr.lower())

    def test_failed_records_attempted_provider_even_without_output(self) -> None:
        result = subprocess.run(
            [
                "python3",
                str(RECORD_MANUAL_STAGE),
                "--run-dir",
                str(self.run_dir),
                "--stage",
                "judge",
                "--status",
                "failed",
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        snapshot = json.loads((self.run_dir / "audit" / "execution-config.json").read_text(encoding="utf-8"))
        self.assertEqual(
            snapshot["actual_stage_assignments"]["judge"],
            {
                "adapter": "claude",
                "model": "claude-sonnet-4-6",
                "provider_key": "claude_secondary",
                "status": "failed",
            },
        )
        usage_records = json.loads((self.run_dir / "audit" / "usage" / "usage-records.json").read_text(encoding="utf-8"))
        self.assertTrue(
            any(
                record["stage_id"] == "judge"
                and record["status"] == "failed"
                and record["provider_key"] == "claude_secondary"
                and record["adapter"] == "claude"
                for record in usage_records
            )
        )


if __name__ == "__main__":
    unittest.main()

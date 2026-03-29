import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
import sys

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from run_live_drift_check import (
    build_live_drift_command,
    prepare_reference_job_copy,
    resolve_reference_job_fixture_dir,
)


class LiveDriftCheckTests(unittest.TestCase):
    def test_prepare_reference_job_copy_copies_fixture_and_bootstraps_job_dirs(self) -> None:
        fixture_dir = resolve_reference_job_fixture_dir("neutral")
        with tempfile.TemporaryDirectory() as tmpdir:
            job_dir = prepare_reference_job_copy(fixture_dir, Path(tmpdir))

            self.assertTrue((job_dir / "brief.md").is_file())
            self.assertTrue((job_dir / "config.yaml").is_file())
            self.assertTrue((job_dir / "runs").is_dir())
            self.assertIn("structured_safe_realistic", (job_dir / "config.yaml").read_text(encoding="utf-8"))
            self.assertIn("neutral", (job_dir / "brief.md").read_text(encoding="utf-8").lower())

    def test_resolve_reference_job_fixture_dir_supports_named_family(self) -> None:
        fixture_dir = resolve_reference_job_fixture_dir("hardware-tradeoff")

        self.assertTrue(fixture_dir.is_dir())
        self.assertTrue((fixture_dir / "brief.md").is_file())
        self.assertTrue((fixture_dir / "config.yaml").is_file())

    def test_build_live_drift_command_targets_execute_workflow(self) -> None:
        class Args:
            fixture_dir = ""
            work_root = ""
            primary_adapter = "codex"
            secondary_adapter = "gemini"
            codex_bin = "codex"
            gemini_bin = "gemini"
            antigravity_bin = "antigravity"
            claude_bin = "claude"

        job_dir = Path("/tmp/reference-job")
        command = build_live_drift_command(Args(), job_dir)

        self.assertEqual(command[0], sys.executable)
        self.assertEqual(command[1], str(REPO_ROOT / "scripts" / "execute_workflow.py"))
        self.assertIn("--job-path", command)
        self.assertIn(str(job_dir), command)
        self.assertIn("--primary-adapter", command)
        self.assertIn("--secondary-adapter", command)


if __name__ == "__main__":
    unittest.main()

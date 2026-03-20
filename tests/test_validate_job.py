import json
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
VALIDATE_JOB = REPO_ROOT / "scripts" / "validate_job.py"


class ValidateJobTests(unittest.TestCase):
    def _make_job(self, root: Path) -> Path:
        job_dir = root / "my-project-1"
        job_dir.mkdir()
        (job_dir / ".git").mkdir()
        (job_dir / "brief.md").write_text("# Research Brief\n", encoding="utf-8")
        (job_dir / "config.yaml").write_text("topic: my-project-1\n", encoding="utf-8")
        for directory in ("outputs", "evidence", "audit", "logs", "runs"):
            (job_dir / directory).mkdir()
        return job_dir

    def test_valid_job_repo_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            job_dir = self._make_job(Path(tmpdir))
            result = subprocess.run(
                ["python3", str(VALIDATE_JOB), "--job-dir", str(job_dir), "--json"],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["errors"], [])

    def test_missing_git_and_required_directories_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            job_dir = Path(tmpdir) / "my-project-1"
            job_dir.mkdir()
            (job_dir / "brief.md").write_text("# Research Brief\n", encoding="utf-8")

            result = subprocess.run(
                ["python3", str(VALIDATE_JOB), "--job-dir", str(job_dir), "--json"],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
            )

            self.assertNotEqual(result.returncode, 0)
            payload = json.loads(result.stdout)
            self.assertFalse(payload["ok"])
            self.assertTrue(any(".git" in error for error in payload["errors"]))
            self.assertTrue(any("config.yaml" in error for error in payload["errors"]))


if __name__ == "__main__":
    unittest.main()

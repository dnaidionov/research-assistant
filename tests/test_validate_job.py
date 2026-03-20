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
            self.assertIn("checks", payload)
            self.assertTrue(payload["checks"]["template_docs_consistent"])

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

    def test_rejects_job_inside_assistant_repo(self) -> None:
        nested_job = REPO_ROOT / "tmp-validate-job"
        nested_job.mkdir(exist_ok=True)
        try:
            (nested_job / ".git").mkdir(exist_ok=True)
            (nested_job / "brief.md").write_text("# Research Brief\n", encoding="utf-8")
            (nested_job / "config.yaml").write_text("topic: nested\n", encoding="utf-8")
            for directory in ("outputs", "evidence", "audit", "logs", "runs"):
                (nested_job / directory).mkdir(exist_ok=True)

            result = subprocess.run(
                ["python3", str(VALIDATE_JOB), "--job-dir", str(nested_job), "--json"],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
            )
        finally:
            if nested_job.exists():
                for child in sorted(nested_job.rglob("*"), reverse=True):
                    if child.is_file():
                        child.unlink()
                    else:
                        child.rmdir()
                nested_job.rmdir()

        self.assertNotEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertTrue(any("assistant repo" in error.lower() for error in payload["errors"]))

    def test_invalid_runs_path_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            job_dir = self._make_job(Path(tmpdir))
            (job_dir / "runs").rmdir()
            (job_dir / "runs").write_text("not-a-directory\n", encoding="utf-8")

            result = subprocess.run(
                ["python3", str(VALIDATE_JOB), "--job-dir", str(job_dir), "--json"],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
            )

            self.assertNotEqual(result.returncode, 0)
            payload = json.loads(result.stdout)
            self.assertTrue(any("runs" in error.lower() for error in payload["errors"]))

    def test_unreadable_key_file_reports_clear_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            job_dir = self._make_job(Path(tmpdir))
            (job_dir / "config.yaml").unlink()

            result = subprocess.run(
                ["python3", str(VALIDATE_JOB), "--job-dir", str(job_dir), "--json"],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
            )

            self.assertNotEqual(result.returncode, 0)
            payload = json.loads(result.stdout)
            self.assertTrue(any("config.yaml" in error for error in payload["errors"]))
            self.assertEqual(payload["exit_code"], 2)


if __name__ == "__main__":
    unittest.main()

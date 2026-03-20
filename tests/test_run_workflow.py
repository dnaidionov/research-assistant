import json
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
RUN_WORKFLOW = REPO_ROOT / "scripts" / "run_workflow.py"


class RunWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.job_dir = Path(self.tmpdir.name) / "my-project-1"
        self.job_dir.mkdir(parents=True)
        (self.job_dir / ".git").mkdir()
        (self.job_dir / "brief.md").write_text(
            "# Research Brief\n\n## Question\nHow should the framework scaffold a research run?\n",
            encoding="utf-8",
        )
        (self.job_dir / "config.yaml").write_text(
            "topic: my-project-1\nrequirements:\n  require_citations: true\n",
            encoding="utf-8",
        )
        for directory in ("outputs", "evidence", "audit", "logs", "runs"):
            (self.job_dir / directory).mkdir()

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_creates_full_run_scaffold_and_audit_files(self) -> None:
        result = subprocess.run(
            [
                "python3",
                str(RUN_WORKFLOW),
                "--job-dir",
                str(self.job_dir),
                "--run-id",
                "run-001",
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)

        run_dir = self.job_dir / "runs" / "run-001"
        self.assertTrue(run_dir.exists())
        self.assertTrue((run_dir / "WORK_ORDER.md").exists())
        self.assertTrue((run_dir / "workflow-state.json").exists())
        self.assertTrue((run_dir / "prompt-packets").is_dir())
        self.assertTrue((run_dir / "stage-outputs").is_dir())
        self.assertTrue((run_dir / "audit").is_dir())

        state = json.loads((run_dir / "workflow-state.json").read_text(encoding="utf-8"))
        self.assertEqual(
            [stage["id"] for stage in state["stages"]],
            [
                "intake",
                "research_pass_a",
                "research_pass_b",
                "critique_a_by_b",
                "critique_b_by_a",
                "judge_synthesis",
                "claim_extraction",
                "artifact_writing",
            ],
        )
        self.assertEqual(state["job_dir"], str(self.job_dir))
        self.assertEqual(state["run_id"], "run-001")

        work_order = (run_dir / "WORK_ORDER.md").read_text(encoding="utf-8")
        self.assertIn("critique_a_by_b", work_order)
        self.assertIn("claim_extraction", work_order)

        packet_names = sorted(path.name for path in (run_dir / "prompt-packets").glob("*.md"))
        self.assertEqual(
            packet_names,
            [
                "01-intake.md",
                "02-research-pass-a.md",
                "03-research-pass-b.md",
                "04-critique-a-by-b.md",
                "05-critique-b-by-a.md",
                "06-judge-synthesis.md",
                "07-claim-extraction.md",
                "08-artifact-writing.md",
            ],
        )

    def test_rejects_job_inside_assistant_repo(self) -> None:
        nested_job = REPO_ROOT / "tmp-job-forbidden"
        nested_job.mkdir(exist_ok=True)
        try:
            result = subprocess.run(
                [
                    "python3",
                    str(RUN_WORKFLOW),
                    "--job-dir",
                    str(nested_job),
                    "--run-id",
                    "run-001",
                ],
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
        self.assertIn("assistant repo", result.stderr.lower())


if __name__ == "__main__":
    unittest.main()

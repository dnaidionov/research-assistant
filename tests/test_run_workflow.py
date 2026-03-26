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
        self.temp_root = Path(self.tmpdir.name)
        self.job_dir = self.temp_root / "jobs" / "my-project-1"
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
        self.jobs_index_root = self.temp_root / "jobs-index"
        (self.jobs_index_root / "active").mkdir(parents=True)
        (self.jobs_index_root / "active" / "my-project-1.yaml").write_text(
            "\n".join(
                [
                    "job_id: my-project-1",
                    "display_name: Example Research Project",
                    "local_path: ../../jobs/my-project-1",
                    "status: active",
                ]
            ),
            encoding="utf-8",
        )
        (self.jobs_index_root / "active" / "example-project.yaml").write_text(
            "\n".join(
                [
                    "job_id: alpha-001",
                    "display_name: Example Research Project",
                    "local_path: ../../jobs/my-project-1",
                    "status: active",
                ]
            ),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_creates_full_run_scaffold_and_audit_files(self) -> None:
        result = subprocess.run(
            [
                "python3",
                str(RUN_WORKFLOW),
                "--job-path",
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
        self.assertTrue((run_dir / "stage-claims").is_dir())
        self.assertTrue((run_dir / "sources.json").is_file())
        self.assertTrue((run_dir / "audit").is_dir())

        state = json.loads((run_dir / "workflow-state.json").read_text(encoding="utf-8"))
        self.assertEqual(
            [stage["id"] for stage in state["stages"]],
            [
                "intake",
                "research-a",
                "research-b",
                "critique-a-on-b",
                "critique-b-on-a",
                "judge",
            ],
        )
        self.assertEqual(state["job_dir"], str(self.job_dir))
        self.assertEqual(state["run_id"], "run-001")

        work_order = (run_dir / "WORK_ORDER.md").read_text(encoding="utf-8")
        self.assertIn("critique-a-on-b", work_order)
        self.assertIn("expected output target", work_order.lower())
        self.assertIn("upstream stage artifacts", work_order.lower())
        self.assertIn("stage-outputs/01-intake.json", work_order)

        packet_names = sorted(path.name for path in (run_dir / "prompt-packets").glob("*.md"))
        self.assertEqual(
            packet_names,
            [
                "01-intake.md",
                "02-research-a.md",
                "03-research-b.md",
                "04-critique-a-on-b.md",
                "05-critique-b-on-a.md",
                "06-judge.md",
            ],
        )
        output_names = sorted(path.name for path in (run_dir / "stage-outputs").iterdir())
        self.assertEqual(
            output_names,
            [
                "01-intake.json",
                "02-research-a.json",
                "02-research-a.md",
                "03-research-b.json",
                "03-research-b.md",
                "04-critique-a-on-b.json",
                "04-critique-a-on-b.md",
                "05-critique-b-on-a.json",
                "05-critique-b-on-a.md",
                "06-judge.json",
                "06-judge.md",
            ],
        )
        claim_names = sorted(path.name for path in (run_dir / "stage-claims").iterdir())
        self.assertEqual(
            claim_names,
            [
                "02-research-a.claims.json",
                "03-research-b.claims.json",
                "04-critique-a-on-b.claims.json",
                "05-critique-b-on-a.claims.json",
                "06-judge.claims.json",
            ],
        )
        manifest = json.loads((run_dir / "audit" / "manifest.json").read_text(encoding="utf-8"))
        manifest_paths = {entry["path"] for entry in manifest["files"]}
        self.assertIn("prompt-packets/01-intake.md", manifest_paths)
        self.assertIn("workflow-state.json", manifest_paths)
        self.assertIn("sources.json", manifest_paths)
        self.assertIn("stage-outputs/02-research-a.json", manifest_paths)
        self.assertIn("stage-outputs/04-critique-a-on-b.json", manifest_paths)
        self.assertIn("stage-claims/02-research-a.claims.json", manifest_paths)

        research_a_packet = (run_dir / "prompt-packets" / "02-research-a.md").read_text(encoding="utf-8")
        self.assertIn("Upstream Stage Artifacts", research_a_packet)
        self.assertIn("01-intake.json", research_a_packet)
        self.assertIn("Use the output artifact from the dependency stage", research_a_packet)
        self.assertIn("Expected Structured Output", research_a_packet)
        self.assertIn("Run Source Registry", research_a_packet)

        critique_packet = (run_dir / "prompt-packets" / "04-critique-a-on-b.md").read_text(encoding="utf-8")
        self.assertIn("02-research-a.md", critique_packet)
        self.assertIn("03-research-b.md", critique_packet)

        judge_packet = (run_dir / "prompt-packets" / "06-judge.md").read_text(encoding="utf-8")
        self.assertIn("04-critique-a-on-b.md", judge_packet)
        self.assertIn("05-critique-b-on-a.md", judge_packet)

    def test_resolves_job_name_via_jobs_index(self) -> None:
        result = subprocess.run(
            [
                "python3",
                str(RUN_WORKFLOW),
                "--job-name",
                "my-project-1",
                "--jobs-index-root",
                str(self.jobs_index_root),
                "--jobs-root",
                str(self.temp_root / "jobs"),
                "--run-id",
                "run-lookup",
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        run_dir = self.job_dir / "runs" / "run-lookup"
        self.assertTrue(run_dir.exists())
        state = json.loads((run_dir / "workflow-state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["job_name"], "my-project-1")

    def test_resolves_job_id_via_jobs_index_metadata(self) -> None:
        result = subprocess.run(
            [
                "python3",
                str(RUN_WORKFLOW),
                "--job-id",
                "alpha-001",
                "--jobs-index-root",
                str(self.jobs_index_root),
                "--jobs-root",
                str(self.temp_root / "jobs"),
                "--run-id",
                "run-by-id",
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        run_dir = self.job_dir / "runs" / "run-by-id"
        self.assertTrue(run_dir.exists())
        state = json.loads((run_dir / "workflow-state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["job_name"], "my-project-1")

    def test_rejects_job_inside_assistant_repo(self) -> None:
        nested_job = REPO_ROOT / "tmp-job-forbidden"
        nested_job.mkdir(exist_ok=True)
        try:
            result = subprocess.run(
                [
                    "python3",
                    str(RUN_WORKFLOW),
                    "--job-path",
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

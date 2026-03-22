import json
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
EXECUTE_WORKFLOW = REPO_ROOT / "scripts" / "execute_workflow.py"


class ExecuteWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)
        self.job_dir = self.root / "jobs" / "my-project-1"
        self.job_dir.mkdir(parents=True)
        (self.job_dir / ".git").mkdir()
        (self.job_dir / "brief.md").write_text(
            "# Research Brief\n\n## Question\nWhich option is better?\n",
            encoding="utf-8",
        )
        (self.job_dir / "config.yaml").write_text(
            "topic: my-project-1\nrequirements:\n  require_citations: true\n",
            encoding="utf-8",
        )
        for directory in ("outputs", "evidence", "audit", "logs", "runs"):
            (self.job_dir / directory).mkdir()

        self.bin_dir = self.root / "bin"
        self.bin_dir.mkdir()
        self.codex_bin = self.bin_dir / "codex"
        self.antigravity_bin = self.bin_dir / "antigravity"
        self._write_fake_executor(self.codex_bin, "codex")
        self._write_fake_executor(self.antigravity_bin, "antigravity")
        self.jobs_index_root = self.root / "jobs-index"
        (self.jobs_index_root / "active").mkdir(parents=True)
        (self.jobs_index_root / "active" / "example-project.yaml").write_text(
            textwrap.dedent(
                """\
                job_id: alpha-001
                display_name: Example Research Project
                local_path: ../../jobs/my-project-1
                status: active
                """
            ),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def _write_fake_executor(self, path: Path, agent_name: str) -> None:
        path.write_text(
            textwrap.dedent(
                f"""\
                #!/usr/bin/env python3
                import json
                import re
                import sys
                from pathlib import Path

                prompt = " ".join(sys.argv[1:])
                output_match = re.search(r"OUTPUT_PATH=(.+)", prompt)
                stage_match = re.search(r"STAGE_ID=([a-z0-9-]+)", prompt)
                if not output_match or not stage_match:
                    print("missing stage metadata", file=sys.stderr)
                    sys.exit(2)

                output_path = Path(output_match.group(1).strip())
                output_path.parent.mkdir(parents=True, exist_ok=True)
                stage = stage_match.group(1)
                log_path = output_path.parent.parent / "logs" / f"{{stage}}.{agent_name}.log"
                log_path.parent.mkdir(parents=True, exist_ok=True)
                log_path.write_text(prompt + "\\n", encoding="utf-8")

                if stage == "intake":
                    output_path.write_text(
                        json.dumps({{
                            "question": "Which option is better?",
                            "scope": ["Compare option A and option B"],
                            "constraints": ["Require citations"],
                            "assumptions": [],
                            "missing_information": [],
                            "required_artifacts": ["judge report"],
                            "notes_for_researchers": ["Use cited evidence only"],
                            "known_facts": [{{"statement": "The brief asks for an option comparison.", "source_basis": "brief.md"}}],
                            "working_inferences": [],
                            "uncertainty_notes": []
                        }}, indent=2),
                        encoding="utf-8",
                    )
                elif stage in {{"research-a", "research-b"}}:
                    option = "A" if stage.endswith("a") else "B"
                    output_path.write_text(
                        f"# Executive Summary\\n\\n- Research {{option}} summary. [SRC-00{{1 if option == 'A' else 2}}]\\n\\n"
                        f"# Facts\\n\\n1. Option {{option}} has evidence behind it. [SRC-00{{1 if option == 'A' else 2}}]\\n\\n"
                        "# Inferences\\n\\n1. Option "
                        f"{{option}} may be viable. [SRC-00{{1 if option == 'A' else 2}}] Confidence: medium\\n\\n"
                        "# Uncertainty Register\\n\\n- Coverage is incomplete. [SRC-003]\\n\\n"
                        "# Evidence Gaps\\n\\n- Benchmarking is incomplete. [SRC-004]\\n\\n"
                        "# Preliminary Disagreements\\n\\n- The other option may be stronger on another axis. [SRC-005]\\n\\n"
                        "# Source Evaluation\\n\\n- Sources are limited but relevant. [SRC-006]\\n",
                        encoding="utf-8",
                    )
                elif stage in {{"critique-a-on-b", "critique-b-on-a"}}:
                    output_path.write_text(
                        "# Claims That Survive Review\\n\\n- One claim survives review. [SRC-010]\\n\\n"
                        "# Unsupported Claims\\n\\n- Some claims need stronger support. [SRC-011]\\n\\n"
                        "# Weak Sources Or Citation Problems\\n\\n- One citation is indirect. [SRC-012]\\n\\n"
                        "# Omissions And Missing Alternatives\\n\\n- Missing alternative analysis. [SRC-013]\\n\\n"
                        "# Overreach And Overconfident Inference\\n\\n- One conclusion is too strong. [SRC-014]\\n\\n"
                        "# Unresolved Disagreements For Judge\\n\\n- Option A vs B remains disputed. [SRC-015]\\n\\n"
                        "# Overall Critique Summary\\n\\n- Reliability is mixed. Confidence: medium\\n",
                        encoding="utf-8",
                    )
                elif stage == "judge":
                    output_path.write_text(
                        "# Supported Conclusions\\n\\n1. Option A has lower implementation risk. [SRC-001]\\n\\n"
                        "# Inferences And Synthesis Judgments\\n\\n1. Inference: Option A is the safer near-term choice. [SRC-001, SRC-002] Confidence: medium\\n\\n"
                        "# Unresolved Disagreements\\n\\n- Option B may still have better upside under some conditions. [SRC-003]\\n\\n"
                        "# Confidence Assessment\\n\\n- Confidence is medium because evidence is incomplete. [SRC-004]\\n\\n"
                        "# Evidence Gaps\\n\\n- No direct benchmark compares both options in this environment. [SRC-005]\\n\\n"
                        "# Rationale And Traceability\\n\\n- Research A favored Option A; critique B-on-A preserved upside concerns. [PASS-A, CRIT-B-A]\\n\\n"
                        "# Recommended Final Artifact Structure\\n\\n- Summary, comparison, recommendation, uncertainty, references, open questions.\\n",
                        encoding="utf-8",
                    )
                else:
                    print(f"unexpected stage: {{stage}}", file=sys.stderr)
                    sys.exit(2)
                """
            ),
            encoding="utf-8",
        )
        path.chmod(0o755)

    def test_executes_full_cross_tool_workflow_and_generates_outputs(self) -> None:
        result = subprocess.run(
            [
                "python3",
                str(EXECUTE_WORKFLOW),
                "--job-path",
                str(self.job_dir),
                "--run-id",
                "run-001",
                "--codex-bin",
                str(self.codex_bin),
                "--antigravity-bin",
                str(self.antigravity_bin),
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)

        run_dir = self.job_dir / "runs" / "run-001"
        self.assertTrue((run_dir / "stage-outputs" / "01-intake.json").is_file())
        self.assertTrue((run_dir / "stage-outputs" / "02-research-a.md").is_file())
        self.assertTrue((run_dir / "stage-outputs" / "03-research-b.md").is_file())
        self.assertTrue((run_dir / "stage-outputs" / "04-critique-a-on-b.md").is_file())
        self.assertTrue((run_dir / "stage-outputs" / "05-critique-b-on-a.md").is_file())
        self.assertTrue((run_dir / "stage-outputs" / "06-judge.md").is_file())

        claim_register = self.job_dir / "evidence" / "claims-run-001.json"
        final_artifact = self.job_dir / "outputs" / "final-run-001.md"
        self.assertTrue(claim_register.is_file())
        self.assertTrue(final_artifact.is_file())

        payload = json.loads(claim_register.read_text(encoding="utf-8"))
        self.assertEqual(payload["summary"]["uncited_fact_ids"], [])

        artifact = final_artifact.read_text(encoding="utf-8")
        self.assertIn("# Executive Summary", artifact)
        self.assertIn("# Recommendation", artifact)
        self.assertIn("# References", artifact)
        self.assertIn("SRC-001", artifact)

        state = json.loads((run_dir / "workflow-state.json").read_text(encoding="utf-8"))
        statuses = {stage["id"]: stage["status"] for stage in state["stages"]}
        self.assertEqual(statuses["intake"], "completed")
        self.assertEqual(statuses["judge"], "completed")
        self.assertEqual(state["post_processing"]["claim_extraction"]["status"], "completed")
        self.assertEqual(state["post_processing"]["final_artifact"]["status"], "completed")

    def test_resume_skips_completed_stages(self) -> None:
        first = subprocess.run(
            [
                "python3",
                str(EXECUTE_WORKFLOW),
                "--job-path",
                str(self.job_dir),
                "--run-id",
                "run-002",
                "--codex-bin",
                str(self.codex_bin),
                "--antigravity-bin",
                str(self.antigravity_bin),
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(first.returncode, 0, first.stderr)

        second = subprocess.run(
            [
                "python3",
                str(EXECUTE_WORKFLOW),
                "--job-path",
                str(self.job_dir),
                "--run-id",
                "run-002",
                "--codex-bin",
                str(self.codex_bin),
                "--antigravity-bin",
                str(self.antigravity_bin),
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertIn("already complete", second.stdout.lower())

    def test_resolves_job_id_via_jobs_index(self) -> None:
        result = subprocess.run(
            [
                "python3",
                str(EXECUTE_WORKFLOW),
                "--job-id",
                "alpha-001",
                "--jobs-index-root",
                str(self.jobs_index_root),
                "--jobs-root",
                str(self.root / "jobs"),
                "--run-id",
                "run-by-id",
                "--codex-bin",
                str(self.codex_bin),
                "--antigravity-bin",
                str(self.antigravity_bin),
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


if __name__ == "__main__":
    unittest.main()

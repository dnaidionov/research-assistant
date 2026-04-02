import json
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
RUN_WORKFLOW = REPO_ROOT / "scripts" / "run_workflow.py"
RUN_STAGE = REPO_ROOT / "scripts" / "run_stage.py"


class RunStageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)
        self.job_dir = self.root / "jobs" / "stage-job"
        self.job_dir.mkdir(parents=True)
        (self.job_dir / ".git").mkdir()
        (self.job_dir / "brief.md").write_text("# Brief\n", encoding="utf-8")
        (self.job_dir / "config.yaml").write_text(
            textwrap.dedent(
                """\
                topic: stage-job
                workflow:
                  execution:
                    providers:
                      codex_primary:
                        adapter: codex
                      gemini_secondary:
                        adapter: gemini
                        model: gemini-3.1-pro-preview
                    stage_providers:
                      intake: codex_primary
                      research-a: codex_primary
                      research-b: gemini_secondary
                      critique-a-on-b: codex_primary
                      critique-b-on-a: gemini_secondary
                      judge: gemini_secondary
                """
            ),
            encoding="utf-8",
        )
        for directory in ("outputs", "evidence", "audit", "logs", "runs"):
            (self.job_dir / directory).mkdir()

        self.bin_dir = self.root / "bin"
        self.bin_dir.mkdir()
        self.codex_bin = self.bin_dir / "codex"
        self.gemini_bin = self.bin_dir / "gemini"
        self.claude_bin = self.bin_dir / "claude"
        self.antigravity_bin = self.bin_dir / "antigravity"
        self._write_fake_executor(self.codex_bin, "codex")
        self._write_fake_executor(self.gemini_bin, "gemini")
        self._write_fake_executor(self.claude_bin, "claude")
        self._write_fake_executor(self.antigravity_bin, "antigravity")

        scaffolded = subprocess.run(
            ["python3", str(RUN_WORKFLOW), "--job-path", str(self.job_dir), "--run-id", "run-stage"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(scaffolded.returncode, 0, scaffolded.stderr)
        self.run_dir = self.job_dir / "runs" / "run-stage"
        (self.run_dir / "stage-outputs" / "01-intake.json").write_text(
            json.dumps(
                {
                    "stage": "intake",
                    "question": "Which option is better?",
                    "scope": [],
                    "constraints": [],
                    "assumptions": [],
                    "missing_information": [],
                    "required_artifacts": [],
                    "notes_for_researchers": [],
                    "working_inferences": [],
                    "uncertainty_notes": [],
                    "known_facts": [],
                    "sources": [],
                },
                indent=2,
            )
            + "\n",
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
                json_match = re.search(r"OUTPUT_JSON_PATH=(.+)", prompt)
                stage_match = re.search(r"STAGE_ID=([a-z0-9-]+)", prompt)
                substep_match = re.search(r"SUBSTEP=([a-z-]+)", prompt)
                if not output_match or not stage_match:
                    print("missing stage metadata", file=sys.stderr)
                    sys.exit(2)
                output_path = Path(output_match.group(1).strip())
                json_path = Path(json_match.group(1).strip()) if json_match else None
                output_path.parent.mkdir(parents=True, exist_ok=True)
                if json_path is not None and json_path.name != "not_applicable":
                    json_path.parent.mkdir(parents=True, exist_ok=True)
                stage = stage_match.group(1)
                substep = substep_match.group(1) if substep_match else "single-pass"
                if "ADAPTER_QUALIFICATION=1" in prompt:
                    if output_path.suffix.lower() == ".json":
                        output_path.write_text(json.dumps({{"stage": "adapter-qualification", "status": "ok"}}, indent=2) + "\\n", encoding="utf-8")
                    else:
                        output_path.write_text("# Adapter qualification markdown\\n", encoding="utf-8")
                    if json_path is not None and json_path.name != "not_applicable":
                        json_path.write_text(json.dumps({{"stage": "adapter-qualification", "status": "ok"}}, indent=2) + "\\n", encoding="utf-8")
                    sys.exit(0)
                if substep == "source-pass":
                    payload = {{
                        "stage": stage,
                        "sources": [{{"id": "SRC-001", "title": "Canonical source", "type": "report", "authority": "test fixture", "locator": "https://example.com/src-001"}}],
                    }}
                    json_path.write_text(json.dumps(payload, indent=2) + "\\n", encoding="utf-8")
                elif substep == "claim-pass":
                    payload = {{
                        "stage": stage,
                        "summary": [{{"text": "Research summary.", "evidence_sources": ["SRC-001"]}}],
                        "facts": [{{"id": f"{{stage}}-fact-1", "text": "Option has evidence.", "evidence_sources": ["SRC-001"]}}],
                        "inferences": [{{"id": f"{{stage}}-inf-1", "text": "Option may be viable.", "evidence_sources": ["SRC-001"], "confidence": "medium"}}],
                        "uncertainties": [{{"text": "Coverage is incomplete."}}],
                        "evidence_gaps": [{{"text": "Benchmarking is incomplete."}}],
                        "preliminary_disagreements": [{{"text": "Another option may still be stronger."}}],
                        "source_evaluation": [{{"source_id": "SRC-001", "notes": "Source is limited but relevant."}}],
                    }}
                    json_path.write_text(json.dumps(payload, indent=2) + "\\n", encoding="utf-8")
                else:
                    output_path.write_text("# Executive Summary\\n\\nExecuted by {agent_name}.\\n", encoding="utf-8")
                    if json_path is not None and json_path.name != "not_applicable":
                        payload = {{
                            "stage": stage,
                            "summary": [{{"text": "Research summary.", "evidence_sources": ["SRC-001"]}}],
                            "facts": [{{"id": f"{{stage}}-fact-1", "text": "Option has evidence.", "evidence_sources": ["SRC-001"]}}],
                            "inferences": [{{"id": f"{{stage}}-inf-1", "text": "Option may be viable.", "evidence_sources": ["SRC-001"], "confidence": "medium"}}],
                            "uncertainties": [{{"text": "Coverage is incomplete."}}],
                            "evidence_gaps": [{{"text": "Benchmarking is incomplete."}}],
                            "preliminary_disagreements": [{{"text": "Another option may still be stronger."}}],
                            "source_evaluation": [{{"source_id": "SRC-001", "notes": "Source is limited but relevant."}}],
                            "sources": [{{"id": "SRC-001", "title": "Canonical source", "type": "report", "authority": "test fixture", "locator": "https://example.com/src-001"}}],
                        }}
                        json_path.write_text(json.dumps(payload, indent=2) + "\\n", encoding="utf-8")
                print("ok")
                """
            ),
            encoding="utf-8",
        )
        path.chmod(0o755)

    def _run_stage(self, *extra: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                "python3",
                str(RUN_STAGE),
                "--job-path",
                str(self.job_dir),
                "--run-id",
                "run-stage",
                "--codex-bin",
                str(self.codex_bin),
                "--gemini-bin",
                str(self.gemini_bin),
                "--claude-bin",
                str(self.claude_bin),
                "--antigravity-bin",
                str(self.antigravity_bin),
                *extra,
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )

    def test_run_stage_uses_configured_provider_when_no_override_given(self) -> None:
        result = self._run_stage("--stage", "research-b")

        self.assertEqual(result.returncode, 0, result.stderr)
        snapshot = json.loads((self.run_dir / "audit" / "execution-config.json").read_text(encoding="utf-8"))
        self.assertEqual(
            snapshot["actual_stage_assignments"]["research-b"],
            {
                "adapter": "gemini",
                "model": "gemini-3.1-pro-preview",
                "provider_key": "gemini_secondary",
                "status": "completed",
            },
        )
        self.assertEqual(
            snapshot["resolved_stage_assignments"]["research-b"],
            {
                "adapter": "gemini",
                "model": "gemini-3.1-pro-preview",
                "provider_key": "gemini_secondary",
            },
        )

    def test_run_stage_uses_override_without_mutating_configured_assignment(self) -> None:
        result = self._run_stage(
            "--stage",
            "research-b",
            "--adapter",
            "claude",
            "--model",
            "claude-sonnet-4-6",
            "--provider-key",
            "manual_claude_override",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        snapshot = json.loads((self.run_dir / "audit" / "execution-config.json").read_text(encoding="utf-8"))
        self.assertEqual(
            snapshot["actual_stage_assignments"]["research-b"],
            {
                "adapter": "claude",
                "model": "claude-sonnet-4-6",
                "provider_key": "manual_claude_override",
                "status": "completed",
            },
        )
        self.assertEqual(
            snapshot["resolved_stage_assignments"]["research-b"],
            {
                "adapter": "gemini",
                "model": "gemini-3.1-pro-preview",
                "provider_key": "gemini_secondary",
            },
        )


if __name__ == "__main__":
    unittest.main()

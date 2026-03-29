import json
import io
import subprocess
import tempfile
import threading
import textwrap
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
EXECUTE_WORKFLOW = REPO_ROOT / "scripts" / "execute_workflow.py"
REBUILD_WORKFLOW_STATE = REPO_ROOT / "scripts" / "rebuild_workflow_state.py"
import sys

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from _adapter_qualification import (
    build_qualification_prompt,
    classify_adapter_qualification,
    list_fixture_families,
    qualification_report_path,
    render_reference_prompt_packet,
    trust_satisfies,
)
from execute_workflow import (
    CommandResult,
    ProgressReporter,
    StageAdapterSelection,
    StageExecution,
    StageProcessController,
    apply_state_update,
    build_adapter_executor,
    build_claude_command,
    build_gemini_command,
    next_incremental_run_id,
    run_structured_stage,
    run_stage_group,
)
from _stage_validation import validate_stage_markdown_contract


class FakeTTYStream:
    def __init__(self) -> None:
        self.parts: list[str] = []

    def write(self, value: str) -> None:
        self.parts.append(value)

    def flush(self) -> None:
        return None

    def isatty(self) -> bool:
        return True

    def rendered(self) -> str:
        return "".join(self.parts)


class FakeRunningProcess:
    def __init__(self, pid: int) -> None:
        self.pid = pid

    def poll(self) -> None:
        return None

    def wait(self, timeout: float | None = None) -> int:
        return 0


class ExecuteWorkflowTests(unittest.TestCase):
    def test_next_incremental_run_id_starts_at_run_001(self) -> None:
        self.assertEqual(next_incremental_run_id(self.job_dir), "run-001")

    def test_next_incremental_run_id_ignores_non_incremental_runs_and_increments_max(self) -> None:
        runs_dir = self.job_dir / "runs"
        (runs_dir / "run-001").mkdir()
        (runs_dir / "run-009").mkdir()
        (runs_dir / "run-manual").mkdir()
        (runs_dir / "draft").mkdir()

        self.assertEqual(next_incremental_run_id(self.job_dir), "run-010")

    def test_build_claude_command_uses_default_model_when_unspecified(self) -> None:
        cmd = build_claude_command("claude", Path("/tmp/job"), "prompt text")

        self.assertEqual(
            cmd,
            ["claude", "-p", "--output-format", "text", "--permission-mode", "bypassPermissions", "prompt text"],
        )

    def test_build_claude_command_includes_model_override(self) -> None:
        cmd = build_claude_command("claude", Path("/tmp/job"), "prompt text", model="claude-sonnet-4-6")

        self.assertEqual(
            cmd,
            [
                "claude",
                "--model",
                "claude-sonnet-4-6",
                "-p",
                "--output-format",
                "text",
                "--permission-mode",
                "bypassPermissions",
                "prompt text",
            ],
        )

    def test_build_gemini_command_pins_model(self) -> None:
        cmd = build_gemini_command("gemini", Path("/tmp/job"), "prompt text")

        self.assertEqual(
            cmd,
            ["gemini", "--model", "gemini-3.1-pro-preview", "-p", "prompt text", "-y"],
        )

    def test_build_adapter_executor_rejects_unknown_artifact_kind(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unsupported artifact kind"):
            build_adapter_executor("gemini", Path("/tmp/job"), "xml")

    def test_apply_state_update_serializes_concurrent_checkpoints(self) -> None:
        state = {"run_dir": str(self.job_dir / "runs" / "run-lock"), "stages": [{"id": "research-a", "status": "pending"}]}
        state_path = self.job_dir / "runs" / "run-lock" / "workflow-state.json"
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_lock = threading.RLock()
        overlap_detected = []
        active = 0
        start_gate = threading.Barrier(2)

        def slow_save(_path: Path, _payload: dict[str, object]) -> None:
            nonlocal active
            active += 1
            if active > 1:
                overlap_detected.append(True)
            time.sleep(0.02)
            active -= 1

        def worker() -> None:
            start_gate.wait()
            apply_state_update(
                state_lock,
                state_path,
                state,
                lambda: state["stages"][0].update({"status": "running"}),
            )

        with patch("execute_workflow.save_state", side_effect=slow_save):
            first = threading.Thread(target=worker)
            second = threading.Thread(target=worker)
            first.start()
            second.start()
            first.join()
            second.join()

        self.assertEqual(overlap_detected, [])

    def test_classify_adapter_qualification_reports_structured_safe_for_fake_executor(self) -> None:
        result = classify_adapter_qualification(
            adapter_name="gemini",
            adapter_bin=self.gemini_bin,
            job_dir=self.job_dir,
        )

        self.assertEqual(result["classification"], "structured_safe")
        self.assertTrue(result["markdown"]["ok"])
        self.assertTrue(result["structured_json"]["ok"])
        self.assertEqual(
            sorted(result["probes"].keys()),
            [
                "claim_pass_structured_json",
                "intake_structured_json",
                "markdown_render",
                "source_pass_structured_json",
            ],
        )
        self.assertEqual(result["profile"], "smoke")
        self.assertIn("probe_set_version", result)
        self.assertIn("adapter_version", result)

    def test_classify_adapter_qualification_rejects_adapter_that_fails_claim_pass_probe(self) -> None:
        self.gemini_bin.write_text(
            textwrap.dedent(
                """\
                #!/usr/bin/env python3
                import json
                import re
                import sys
                from pathlib import Path

                prompt = " ".join(sys.argv[1:])
                output_match = re.search(r"OUTPUT_PATH=(.+)", prompt)
                if not output_match:
                    print("missing output path", file=sys.stderr)
                    sys.exit(2)
                output_path = Path(output_match.group(1).strip())
                output_path.parent.mkdir(parents=True, exist_ok=True)

                if "ADAPTER_QUALIFICATION=1" in prompt and "SUBSTEP=claim-pass" in prompt:
                    print("claim-pass qualification failed", file=sys.stderr)
                    sys.exit(7)

                if "ADAPTER_QUALIFICATION=1" in prompt:
                    if output_path.suffix.lower() == ".json":
                        output_path.write_text(
                            json.dumps({"stage": "adapter-qualification", "status": "ok"}, indent=2),
                            encoding="utf-8",
                        )
                    else:
                        output_path.write_text("# Adapter qualification markdown\\n", encoding="utf-8")
                    sys.exit(0)

                print("unexpected non-qualification call", file=sys.stderr)
                sys.exit(9)
                """
            ),
            encoding="utf-8",
        )
        self.gemini_bin.chmod(0o755)

        result = classify_adapter_qualification(
            adapter_name="gemini",
            adapter_bin=self.gemini_bin,
            job_dir=self.job_dir,
        )

        self.assertEqual(result["classification"], "markdown_only")
        self.assertFalse(result["structured_json"]["ok"])
        self.assertFalse(result["probes"]["claim_pass_structured_json"]["ok"])
        self.assertIn("claim-pass qualification failed", result["probes"]["claim_pass_structured_json"]["error"])

    def test_classify_adapter_qualification_supports_regression_profile(self) -> None:
        result = classify_adapter_qualification(
            adapter_name="gemini",
            adapter_bin=self.gemini_bin,
            job_dir=self.job_dir,
            profile="workflow-regression",
        )

        self.assertEqual(result["classification"], "structured_safe")
        self.assertEqual(result["profile"], "workflow-regression")
        self.assertEqual(
            sorted(result["probes"].keys()),
            [
                "claim_pass_structured_json",
                "critique_claim_pass_structured_json",
                "intake_structured_json",
                "judge_claim_pass_structured_json",
                "markdown_render",
                "source_pass_structured_json",
            ],
        )
        self.assertTrue(result["probes"]["critique_claim_pass_structured_json"]["ok"])
        self.assertTrue(result["probes"]["judge_claim_pass_structured_json"]["ok"])
        self.assertEqual(result["trust_level"], "structured_safe_regression")

    def test_classify_adapter_qualification_supports_realistic_regression_profile(self) -> None:
        result = classify_adapter_qualification(
            adapter_name="gemini",
            adapter_bin=self.gemini_bin,
            job_dir=self.job_dir,
            profile="workflow-regression-realistic",
        )

        self.assertEqual(result["classification"], "structured_safe")
        self.assertEqual(result["profile"], "workflow-regression-realistic")
        self.assertEqual(result["trust_level"], "structured_safe_realistic")

    def test_render_reference_prompt_packet_realistic_profile_uses_frozen_fixture(self) -> None:
        packet = render_reference_prompt_packet(
            "judge",
            self.job_dir,
            profile="workflow-regression-realistic",
        )

        self.assertIn("# Judge Synthesis Prompt", packet)
        self.assertIn("Fixture Family: neutral", packet)
        self.assertIn("Run ID: `qualification-fixture`", packet)

    def test_fixture_family_listing_exposes_multiple_extensible_families(self) -> None:
        families = list_fixture_families()

        self.assertIn("neutral", families)
        self.assertIn("hardware-tradeoff", families)
        self.assertIn("policy-analysis", families)

    def test_trust_satisfies_requires_ordered_structured_levels(self) -> None:
        self.assertTrue(trust_satisfies("structured_safe_realistic", "structured_safe_regression"))
        self.assertTrue(trust_satisfies("structured_safe_regression", "structured_safe_smoke"))
        self.assertFalse(trust_satisfies("structured_safe_smoke", "structured_safe_regression"))
        self.assertFalse(trust_satisfies("markdown_only", "structured_safe_smoke"))

    def test_classify_adapter_qualification_regression_profile_requires_judge_probe(self) -> None:
        self.gemini_bin.write_text(
            textwrap.dedent(
                """\
                #!/usr/bin/env python3
                import json
                import re
                import sys
                from pathlib import Path

                prompt = " ".join(sys.argv[1:])
                output_match = re.search(r"OUTPUT_PATH=(.+)", prompt)
                if not output_match:
                    print("missing output path", file=sys.stderr)
                    sys.exit(2)
                output_path = Path(output_match.group(1).strip())
                output_path.parent.mkdir(parents=True, exist_ok=True)

                if "ADAPTER_QUALIFICATION=1" in prompt and "STAGE_ID=judge" in prompt and "SUBSTEP=claim-pass" in prompt:
                    print("judge claim-pass qualification failed", file=sys.stderr)
                    sys.exit(8)

                if "ADAPTER_QUALIFICATION=1" in prompt:
                    if output_path.suffix.lower() == ".json":
                        output_path.write_text(
                            json.dumps({"stage": "adapter-qualification", "status": "ok"}, indent=2),
                            encoding="utf-8",
                        )
                    else:
                        output_path.write_text("# Adapter qualification markdown\\n", encoding="utf-8")
                    sys.exit(0)

                print("unexpected non-qualification call", file=sys.stderr)
                sys.exit(9)
                """
            ),
            encoding="utf-8",
        )
        self.gemini_bin.chmod(0o755)

        result = classify_adapter_qualification(
            adapter_name="gemini",
            adapter_bin=self.gemini_bin,
            job_dir=self.job_dir,
            profile="workflow-regression",
        )

        self.assertEqual(result["classification"], "markdown_only")
        self.assertFalse(result["structured_json"]["ok"])
        self.assertFalse(result["probes"]["judge_claim_pass_structured_json"]["ok"])
        self.assertIn(
            "judge claim-pass qualification failed",
            result["probes"]["judge_claim_pass_structured_json"]["error"],
        )

    def test_render_reference_prompt_packet_uses_real_stage_template_content(self) -> None:
        packet = render_reference_prompt_packet("research-a", self.job_dir)

        self.assertIn("# Research Stage Prompt", packet)
        self.assertIn("Role: `Research Pass A`", packet)
        self.assertIn("Which option is better?", packet)
        self.assertIn("Use the output artifact from the dependency stage", packet)

    def test_build_qualification_prompt_embeds_reference_packet_for_regression(self) -> None:
        prompt = build_qualification_prompt(
            "judge_claim_pass_structured_json",
            "structured_json",
            self.job_dir / "probe.json",
            stage_id="judge",
            substep="claim-pass",
            qualification_profile="workflow-regression",
            reference_packet="# Judge Synthesis Prompt\n\nStage ID: `judge`\n",
        )

        self.assertIn("QUALIFICATION_PROFILE=workflow-regression", prompt)
        self.assertIn("REFERENCE_PROMPT_PACKET_BEGIN", prompt)
        self.assertIn("# Judge Synthesis Prompt", prompt)
        self.assertIn("REFERENCE_PROMPT_PACKET_END", prompt)
        self.assertIn("Do not answer it. Obey the qualification artifact instruction only.", prompt)

    def test_stage_process_controller_ignores_permission_error_when_cancelling_sibling(self) -> None:
        import execute_workflow as execute_workflow_module

        original_killpg = execute_workflow_module.os.killpg
        controller = StageProcessController()
        try:
            controller.register("research-a", FakeRunningProcess(12345))
            controller.register("research-b", FakeRunningProcess(23456))

            def raising_killpg(pid: int, sig: int) -> None:
                raise PermissionError(1, "operation not permitted")

            execute_workflow_module.os.killpg = raising_killpg
            controller.cancel_others("research-a")
            self.assertTrue(controller.is_cancelled("research-b"))
        finally:
            execute_workflow_module.os.killpg = original_killpg

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
        self.gemini_bin = self.bin_dir / "gemini"
        self.antigravity_bin = self.bin_dir / "antigravity"
        self.claude_bin = self.bin_dir / "claude"
        self._write_fake_executor(self.codex_bin, "codex")
        self._write_fake_executor(self.gemini_bin, "gemini")
        self._write_failing_executor(self.antigravity_bin, "antigravity should not be called by default")
        self._write_failing_executor(self.claude_bin, "claude should not be called by default")
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
            ).replace("\n                ", "\n").lstrip(),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def _workflow_command(self, run_id: str, *extra: str) -> list[str]:
        return [
            "python3",
            str(EXECUTE_WORKFLOW),
            "--job-path",
            str(self.job_dir),
            "--run-id",
            run_id,
            "--codex-bin",
            str(self.codex_bin),
            "--gemini-bin",
            str(self.gemini_bin),
            "--antigravity-bin",
            str(self.antigravity_bin),
            "--claude-bin",
            str(self.claude_bin),
            *extra,
        ]

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
                source_match = re.search(r"SOURCE_REGISTRY_PATH=(.+)", prompt)
                stage_match = re.search(r"STAGE_ID=([a-z0-9-]+)", prompt)
                substep_match = re.search(r"SUBSTEP=([a-z-]+)", prompt)
                if not output_match or not stage_match:
                    print("missing stage metadata", file=sys.stderr)
                    sys.exit(2)

                output_path = Path(output_match.group(1).strip())
                json_path = Path(json_match.group(1).strip()) if json_match else None
                source_registry_path = Path(source_match.group(1).strip()) if source_match else None
                output_path.parent.mkdir(parents=True, exist_ok=True)
                if json_path is not None:
                    json_path.parent.mkdir(parents=True, exist_ok=True)
                stage = stage_match.group(1)
                substep = substep_match.group(1) if substep_match else "single-pass"
                log_path = output_path.parent.parent / "logs" / f"{{stage}}.{agent_name}.log"
                log_path.parent.mkdir(parents=True, exist_ok=True)
                log_path.write_text(prompt + "\\n", encoding="utf-8")

                if "ADAPTER_QUALIFICATION=1" in prompt:
                    if output_path.suffix.lower() == ".json":
                        output_path.write_text(
                            json.dumps({{"stage": "adapter-qualification", "status": "ok"}}, indent=2),
                            encoding="utf-8",
                        )
                    else:
                        output_path.write_text("# Adapter qualification markdown\\n", encoding="utf-8")
                    sys.exit(0)

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
                            "known_facts": [{{"id": "KF-001", "statement": "The brief asks for an option comparison.", "source_ids": ["DOC-BRIEF"], "source_excerpt": "Which option is better?", "source_anchor": "brief.md#Question"}}],
                            "working_inferences": [],
                            "uncertainty_notes": [],
                            "sources": [
                                {{
                                    "id": "DOC-BRIEF",
                                    "title": "Job brief",
                                    "type": "project_brief",
                                    "authority": "job input",
                                    "locator": "brief.md",
                                    "source_class": "job_input"
                                }},
                                {{
                                    "id": "DOC-CONFIG",
                                    "title": "Job config",
                                    "type": "job_config",
                                    "authority": "job input",
                                    "locator": "config.yaml",
                                    "source_class": "job_input"
                                }}
                            ]
                        }}, indent=2),
                        encoding="utf-8",
                    )
                elif stage in {{"research-a", "research-b"}} and substep == "source-pass":
                    option = "A" if stage.endswith("a") else "B"
                    source_id = f"SRC-00{{1 if option == 'A' else 2}}"
                    if json_path is not None:
                        json_path.write_text(
                            json.dumps({{
                                "stage": stage,
                                "sources": [{{"id": source_id, "title": f"Canonical source {{source_id}}", "type": "report", "authority": "test fixture", "locator": f"https://example.com/{{source_id.lower()}}"}}],
                            }}, indent=2),
                            encoding="utf-8",
                        )
                elif stage in {{"research-a", "research-b"}} and substep == "claim-pass":
                    option = "A" if stage.endswith("a") else "B"
                    source_id = f"SRC-00{{1 if option == 'A' else 2}}"
                    if json_path is not None:
                        json_path.write_text(
                            json.dumps({{
                                "stage": stage,
                                "summary": [{{"text": f"Research {{option}} summary.", "evidence_sources": [source_id]}}],
                                "facts": [{{"id": f"{{stage}}-fact-1", "text": f"Option {{option}} has evidence behind it.", "evidence_sources": [source_id]}}],
                                "inferences": [{{"id": f"{{stage}}-inf-1", "text": f"Option {{option}} may be viable.", "evidence_sources": [source_id], "confidence": "medium"}}],
                                "uncertainties": [{{"text": "Coverage is incomplete."}}],
                                "evidence_gaps": [{{"text": "Benchmarking is incomplete."}}],
                                "preliminary_disagreements": [{{"text": "The other option may be stronger on another axis."}}],
                                "source_evaluation": [{{"source_id": source_id, "notes": "Sources are limited but relevant."}}],
                            }}, indent=2),
                            encoding="utf-8",
                        )
                elif stage in {{"critique-a-on-b", "critique-b-on-a"}} and substep == "source-pass":
                    if json_path is not None:
                        json_path.write_text(
                            json.dumps({{
                                "stage": stage,
                                "sources": [
                                    {{"id": "SRC-010", "title": "Canonical source SRC-010", "type": "report", "authority": "test fixture", "locator": "https://example.com/src-010"}},
                                    {{"id": "SRC-011", "title": "Canonical source SRC-011", "type": "report", "authority": "test fixture", "locator": "https://example.com/src-011"}},
                                    {{"id": "SRC-012", "title": "Canonical source SRC-012", "type": "report", "authority": "test fixture", "locator": "https://example.com/src-012"}},
                                    {{"id": "SRC-013", "title": "Canonical source SRC-013", "type": "report", "authority": "test fixture", "locator": "https://example.com/src-013"}},
                                    {{"id": "SRC-014", "title": "Canonical source SRC-014", "type": "report", "authority": "test fixture", "locator": "https://example.com/src-014"}},
                                    {{"id": "SRC-015", "title": "Canonical source SRC-015", "type": "report", "authority": "test fixture", "locator": "https://example.com/src-015"}}
                                ]
                            }}, indent=2),
                            encoding="utf-8",
                        )
                elif stage in {{"critique-a-on-b", "critique-b-on-a"}} and substep == "claim-pass":
                    if json_path is not None:
                        json_path.write_text(
                            json.dumps({{
                                "stage": stage,
                                "supported_claims": [{{"text": "One claim survives review.", "evidence_sources": ["SRC-010"]}}],
                                "unsupported_claims": [
                                    {{
                                        "target_claim": "Some claims need stronger support.",
                                        "reason": "Support is incomplete.",
                                        "needed_evidence": "Direct benchmark evidence.",
                                        "evidence_sources": ["SRC-011"]
                                    }}
                                ],
                                "weak_source_issues": [{{"text": "One citation is indirect.", "evidence_sources": ["SRC-012"]}}],
                                "omissions": [{{"text": "Missing alternative analysis.", "evidence_sources": ["SRC-013"]}}],
                                "overreach": [{{"text": "One conclusion is too strong.", "evidence_sources": ["SRC-014"]}}],
                                "unresolved_disagreements": [{{"text": "Option A vs B remains disputed.", "evidence_sources": ["SRC-015"]}}],
                                "summary": {{"text": "Reliability is mixed.", "confidence": "medium"}},
                            }}, indent=2),
                            encoding="utf-8",
                        )
                elif stage == "judge" and substep == "source-pass":
                    if json_path is not None:
                        json_path.write_text(
                            json.dumps({{
                                "stage": "judge",
                                "sources": [
                                    {{"id": "SRC-001", "title": "Canonical source SRC-001", "type": "report", "authority": "test fixture", "locator": "https://example.com/src-001"}},
                                    {{"id": "SRC-002", "title": "Canonical source SRC-002", "type": "report", "authority": "test fixture", "locator": "https://example.com/src-002"}},
                                    {{"id": "SRC-004", "title": "Canonical source SRC-004", "type": "report", "authority": "test fixture", "locator": "https://example.com/src-004"}}
                                ]
                            }}, indent=2),
                            encoding="utf-8",
                        )
                elif stage == "judge" and substep == "claim-pass":
                    if json_path is not None:
                        json_path.write_text(
                            json.dumps({{
                                "stage": "judge",
                                "supported_conclusions": [{{"id": "judge-conclusion-1", "text": "Option A has lower implementation risk.", "evidence_sources": ["SRC-001"]}}],
                                "synthesis_judgments": [{{"id": "judge-inference-1", "text": "Option A is the safer near-term choice.", "evidence_sources": ["SRC-001", "SRC-002"], "confidence": "medium"}}],
                                "unresolved_disagreements": [{{"text": "Hardware selection trade-off remains unresolved because interface data is missing."}}],
                                "confidence_assessment": [{{"text": "Medium confidence because benchmark coverage is limited.", "evidence_sources": ["SRC-004"]}}],
                                "evidence_gaps": [{{"text": "No direct benchmark compares both options in this environment."}}],
                                "rationale": [{{"text": "Research A favored Option A and critique B-on-A preserved upside concerns."}}],
                                "recommended_artifact_structure": ["Summary", "Comparison", "Recommendation", "Uncertainty", "References", "Open Questions"],
                            }}, indent=2),
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

    def _write_failing_executor(self, path: Path, message: str) -> None:
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
                if "ADAPTER_QUALIFICATION=1" in prompt and output_match:
                    output_path = Path(output_match.group(1).strip())
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    if output_path.suffix.lower() == ".json":
                        output_path.write_text(
                            json.dumps({{"stage": "adapter-qualification", "status": "ok"}}, indent=2),
                            encoding="utf-8",
                        )
                    else:
                        output_path.write_text("# Adapter qualification markdown\\n", encoding="utf-8")
                    sys.exit(0)

                print({message!r}, file=sys.stderr)
                sys.exit(23)
                """
            ),
            encoding="utf-8",
        )
        path.chmod(0o755)

    def _write_noop_executor(self, path: Path, message: str) -> None:
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
                if "ADAPTER_QUALIFICATION=1" in prompt and output_match:
                    output_path = Path(output_match.group(1).strip())
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    if output_path.suffix.lower() == ".json":
                        output_path.write_text(
                            json.dumps({{"stage": "adapter-qualification", "status": "ok"}}, indent=2),
                            encoding="utf-8",
                        )
                    else:
                        output_path.write_text("# Adapter qualification markdown\\n", encoding="utf-8")
                    sys.exit(0)

                print({message!r}, file=sys.stderr)
                sys.exit(0)
                """
            ),
            encoding="utf-8",
        )
        path.chmod(0o755)

    def _write_stdout_only_executor(self, path: Path, markdown: str, json_payload: str | None = None) -> None:
        path.write_text(
            textwrap.dedent(
                f"""\
                #!/usr/bin/env python3
                import json
                import re
                import sys
                
                prompt = " ".join(sys.argv[1:])
                substep_match = re.search(r"SUBSTEP=([a-z-]+)", prompt)
                substep = substep_match.group(1) if substep_match else "single-pass"
                payload = {json_payload!r}
                markdown = {markdown!r}

                if "ADAPTER_QUALIFICATION=1" in prompt:
                    print("# Adapter qualification markdown")
                    sys.exit(0)

                if payload is None:
                    print(markdown)
                    sys.exit(0)

                parsed = json.loads(payload)
                if substep == "source-pass":
                    source_payload = {{"stage": parsed["stage"], "sources": parsed.get("sources", [])}}
                    print(f"```json\\n{{json.dumps(source_payload, indent=2)}}\\n```")
                elif substep == "claim-pass":
                    parsed.pop("sources", None)
                    print(markdown + "\\n\\n```json\\n" + json.dumps(parsed, indent=2) + "\\n```")
                else:
                    print(markdown + "\\n\\n```json\\n" + json.dumps(parsed, indent=2) + "\\n```")
                sys.exit(0)
                """
            ),
            encoding="utf-8",
        )
        path.chmod(0o755)

    def _write_repairing_executor(self, path: Path, agent_name: str, *, repair_succeeds: bool = True) -> None:
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
                repair_match = re.search(r"REPAIR_ATTEMPT=(\\d+)", prompt)
                if not output_match or not stage_match:
                    print("missing stage metadata", file=sys.stderr)
                    sys.exit(2)

                output_path = Path(output_match.group(1).strip())
                json_path = Path(json_match.group(1).strip()) if json_match else None
                output_path.parent.mkdir(parents=True, exist_ok=True)
                if json_path is not None:
                    json_path.parent.mkdir(parents=True, exist_ok=True)
                stage = stage_match.group(1)
                substep = substep_match.group(1) if substep_match else "single-pass"
                repair_attempt = int(repair_match.group(1)) if repair_match else 0

                if "ADAPTER_QUALIFICATION=1" in prompt:
                    if output_path.suffix.lower() == ".json":
                        output_path.write_text(
                            json.dumps({{"stage": "adapter-qualification", "status": "ok"}}, indent=2),
                            encoding="utf-8",
                        )
                    else:
                        output_path.write_text("# Adapter qualification markdown\\n", encoding="utf-8")
                    sys.exit(0)

                if stage == "research-b" and substep == "source-pass":
                    json_path.write_text(
                        json.dumps(
                            {{
                                "stage": "research-b",
                                "sources": [
                                    {{"id": "SRC-001", "title": "Canonical source SRC-001", "type": "report", "authority": "test fixture", "locator": "https://example.com/src-001"}},
                                    {{"id": "SRC-002", "title": "Canonical source SRC-002", "type": "report", "authority": "test fixture", "locator": "https://example.com/src-002"}}
                                ],
                            }},
                            indent=2,
                        ),
                        encoding="utf-8",
                    )
                elif stage == "research-b" and substep == "claim-pass" and (repair_attempt == 0 or not {repair_succeeds!r}):
                    json_path.write_text(
                        json.dumps(
                            {{
                                "stage": "research-b",
                                "summary": [{{"text": "Summary.", "evidence_sources": ["SRC-001"]}}],
                                "facts": [{{"id": "F-001", "text": "Fact.", "evidence_sources": ["SRC-001"], "support_links": [{{"source_id": "SRC-001", "role": "evidence"}}]}}],
                                "inferences": [{{"id": "I-001", "text": "Inference without explicit evidence.", "evidence_sources": ["SRC-001"], "support_links": [{{"source_id": "SRC-WF", "role": "provenance"}}], "confidence": "high"}}],
                                "uncertainties": [{{"text": "Gap."}}],
                                "evidence_gaps": [{{"text": "More data."}}],
                                "preliminary_disagreements": [{{"text": "Trade-off remains.", "evidence_sources": ["SRC-002"]}}],
                                "source_evaluation": [{{"notes": "Source note.", "source_id": "SRC-001"}}],
                            }},
                            indent=2,
                        ),
                        encoding="utf-8",
                    )
                elif stage == "research-b" and substep == "claim-pass":
                    json_path.write_text(
                        json.dumps(
                            {{
                                "stage": "research-b",
                                "summary": [{{"text": "Summary.", "evidence_sources": ["SRC-001"]}}],
                                "facts": [{{"id": "F-001", "text": "Fact.", "evidence_sources": ["SRC-001"], "support_links": [{{"source_id": "SRC-001", "role": "evidence"}}]}}],
                                "inferences": [{{"id": "I-001", "text": "Inference with explicit evidence.", "evidence_sources": ["SRC-001"], "support_links": [{{"source_id": "SRC-001", "role": "evidence"}}], "confidence": "high"}}],
                                "uncertainties": [{{"text": "Gap."}}],
                                "evidence_gaps": [{{"text": "More data."}}],
                                "preliminary_disagreements": [{{"text": "Trade-off remains.", "evidence_sources": ["SRC-002"]}}],
                                "source_evaluation": [{{"notes": "Source note.", "source_id": "SRC-001"}}],
                            }},
                            indent=2,
                        ),
                        encoding="utf-8",
                    )
                elif stage == "critique-b-on-a" and substep == "source-pass":
                    json_path.write_text(
                        json.dumps(
                            {{
                                "stage": "critique-b-on-a",
                                "sources": [
                                    {{"id": "SRC-010", "title": "Canonical source SRC-010", "type": "report", "authority": "test fixture", "locator": "https://example.com/src-010"}},
                                    {{"id": "SRC-011", "title": "Canonical source SRC-011", "type": "report", "authority": "test fixture", "locator": "https://example.com/src-011"}},
                                    {{"id": "SRC-012", "title": "Canonical source SRC-012", "type": "report", "authority": "test fixture", "locator": "https://example.com/src-012"}},
                                    {{"id": "SRC-013", "title": "Canonical source SRC-013", "type": "report", "authority": "test fixture", "locator": "https://example.com/src-013"}},
                                    {{"id": "SRC-014", "title": "Canonical source SRC-014", "type": "report", "authority": "test fixture", "locator": "https://example.com/src-014"}},
                                    {{"id": "SRC-015", "title": "Canonical source SRC-015", "type": "report", "authority": "test fixture", "locator": "https://example.com/src-015"}}
                                ],
                            }},
                            indent=2,
                        ),
                        encoding="utf-8",
                    )
                elif stage == "critique-b-on-a" and substep == "claim-pass":
                    json_path.write_text(
                        json.dumps(
                            {{
                                "stage": "critique-b-on-a",
                                "supported_claims": [{{"text": "One claim survives review.", "evidence_sources": ["SRC-010"]}}],
                                "unsupported_claims": [{{"target_claim": "Some claims need stronger support.", "reason": "Support is incomplete.", "needed_evidence": "Direct benchmark evidence.", "evidence_sources": ["SRC-011"]}}],
                                "weak_source_issues": [{{"text": "One citation is indirect.", "evidence_sources": ["SRC-012"]}}],
                                "omissions": [{{"text": "Missing alternative analysis.", "evidence_sources": ["SRC-013"]}}],
                                "overreach": [{{"text": "One conclusion is too strong.", "evidence_sources": ["SRC-014"]}}],
                                "unresolved_disagreements": [{{"text": "Option A vs B remains disputed.", "evidence_sources": ["SRC-015"]}}],
                                "summary": {{"text": "Reliability is mixed.", "confidence": "medium"}},
                            }},
                            indent=2,
                        ),
                        encoding="utf-8",
                    )
                elif stage == "judge" and substep == "source-pass":
                    json_path.write_text(
                        json.dumps(
                            {{
                                "stage": "judge",
                                "sources": [{{"id": "SRC-001", "title": "Canonical source SRC-001", "type": "report", "authority": "test fixture", "locator": "https://example.com/src-001"}}],
                            }},
                            indent=2,
                        ),
                        encoding="utf-8",
                    )
                elif stage == "judge" and substep == "claim-pass":
                    json_path.write_text(
                        json.dumps(
                            {{
                                "stage": "judge",
                                "supported_conclusions": [{{"id": "C-001", "text": "Option A has lower implementation risk.", "evidence_sources": ["SRC-001"]}}],
                                "synthesis_judgments": [{{"id": "J-001", "text": "Option A is the safer near-term choice.", "evidence_sources": ["SRC-001"], "confidence": "medium"}}],
                                "unresolved_disagreements": ["Trade-off remains unresolved."],
                                "confidence_assessment": ["Medium confidence because evidence is incomplete."],
                                "evidence_gaps": ["Comparative benchmark is still missing."],
                                "rationale": ["Research preserved the strongest cited inference."],
                                "recommended_artifact_structure": ["Summary, evidence, recommendation, uncertainty, references."],
                            }},
                            indent=2,
                        ),
                        encoding="utf-8",
                    )
                else:
                    print("unexpected stage", file=sys.stderr)
                    sys.exit(2)
                sys.exit(0)
                """
            ),
            encoding="utf-8",
        )
        path.chmod(0o755)

    def _write_sleeping_executor(self, path: Path, agent_name: str) -> None:
        path.write_text(
            textwrap.dedent(
                f"""\
                #!/usr/bin/env python3
                import json
                import re
                import signal
                import sys
                import time
                from pathlib import Path

                cancelled = False

                def handle_term(signum, frame):
                    global cancelled
                    cancelled = True

                signal.signal(signal.SIGTERM, handle_term)

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
                if json_path is not None:
                    json_path.parent.mkdir(parents=True, exist_ok=True)
                stage = stage_match.group(1)

                if "ADAPTER_QUALIFICATION=1" in prompt:
                    if output_path.suffix.lower() == ".json":
                        output_path.write_text(
                            json.dumps({{"stage": "adapter-qualification", "status": "ok"}}, indent=2),
                            encoding="utf-8",
                        )
                    else:
                        output_path.write_text("# Adapter qualification markdown\\n", encoding="utf-8")
                    sys.exit(0)

                if stage not in {{"research-b", "critique-b-on-a", "judge"}}:
                    print("unexpected stage", file=sys.stderr)
                    sys.exit(2)

                for _ in range(100):
                    if cancelled:
                        print("cancelled_due_to_parallel_stage_failure", file=sys.stderr)
                        sys.exit(143)
                    time.sleep(0.05)

                output_path.write_text("# never reached\\n", encoding="utf-8")
                if json_path is not None:
                    json_path.write_text(json.dumps({{"stage": stage}}), encoding="utf-8")
                sys.exit(0)
                """
            ),
            encoding="utf-8",
        )
        path.chmod(0o755)

    def _write_research_a_failure_executor(self, path: Path) -> None:
        path.write_text(
            textwrap.dedent(
                """\
                #!/usr/bin/env python3
                import json
                import re
                import sys
                from pathlib import Path

                prompt = " ".join(sys.argv[1:])
                output_match = re.search(r"OUTPUT_PATH=(.+)", prompt)
                json_match = re.search(r"OUTPUT_JSON_PATH=(.+)", prompt)
                stage_match = re.search(r"STAGE_ID=([a-z0-9-]+)", prompt)
                if not output_match or not stage_match:
                    print("missing stage metadata", file=sys.stderr)
                    sys.exit(2)

                output_path = Path(output_match.group(1).strip())
                json_path = Path(json_match.group(1).strip()) if json_match else None
                output_path.parent.mkdir(parents=True, exist_ok=True)
                if json_path is not None:
                    json_path.parent.mkdir(parents=True, exist_ok=True)
                stage = stage_match.group(1)

                if "ADAPTER_QUALIFICATION=1" in prompt:
                    if output_path.suffix.lower() == ".json":
                        output_path.write_text(
                            json.dumps({"stage": "adapter-qualification", "status": "ok"}, indent=2),
                            encoding="utf-8",
                        )
                    else:
                        output_path.write_text("# Adapter qualification markdown\\n", encoding="utf-8")
                    sys.exit(0)

                if stage == "intake":
                    output_path.write_text(
                        json.dumps(
                            {
                                "question": "Which option is better?",
                                "scope": ["Compare option A and option B"],
                                "constraints": ["Require citations"],
                                "assumptions": [],
                                "missing_information": [],
                                "required_artifacts": ["judge report"],
                                "notes_for_researchers": ["Use cited evidence only"],
                                "known_facts": [
                                    {
                                        "id": "KF-001",
                                        "statement": "The brief asks for an option comparison.",
                                        "source_ids": ["DOC-BRIEF"],
                                        "source_excerpt": "Which option is better?",
                                        "source_anchor": "brief.md#Question",
                                    }
                                ],
                                "working_inferences": [],
                                "uncertainty_notes": [],
                                "sources": [
                                    {
                                        "id": "DOC-BRIEF",
                                        "title": "Job brief",
                                        "type": "project_brief",
                                        "authority": "job input",
                                        "locator": "brief.md",
                                        "source_class": "job_input",
                                    },
                                    {
                                        "id": "DOC-CONFIG",
                                        "title": "Job config",
                                        "type": "job_config",
                                        "authority": "job input",
                                        "locator": "config.yaml",
                                        "source_class": "job_input",
                                    },
                                ],
                            },
                            indent=2,
                        ),
                        encoding="utf-8",
                    )
                    sys.exit(0)

                if stage == "research-a":
                    output_path.write_text(
                        "# Executive Summary\\n\\nSummary. [SRC-001]\\n\\n# Facts\\n\\n1. Fact. [SRC-001]\\n\\n# Inferences\\n\\n1. Inference. [SRC-001] Confidence: high\\n\\n# Uncertainty Register\\n\\n- Gap.\\n\\n# Evidence Gaps\\n\\n- More data.\\n\\n# Preliminary Disagreements\\n\\n- Trade-off. [SRC-002]\\n\\n# Source Evaluation\\n\\n- Source note. [SRC-001]\\n",
                        encoding="utf-8",
                    )
                    if json_path is None:
                        print("missing structured output path", file=sys.stderr)
                        sys.exit(2)
                    json_path.write_text(
                        json.dumps(
                            {
                                "stage": "research-a",
                                "summary": [{"text": "Summary.", "evidence_sources": ["SRC-001"]}],
                                "facts": [
                                    {
                                        "id": "F-001",
                                        "text": "Fact.",
                                        "evidence_sources": ["SRC-001"],
                                        "support_links": [{"source_id": "SRC-001", "role": "evidence"}],
                                    }
                                ],
                                "inferences": [
                                    {
                                        "id": "I-001",
                                        "text": "Inference.",
                                        "evidence_sources": ["SRC-001"],
                                        "support_links": [{"source_id": "SRC-WF", "role": "provenance"}],
                                        "confidence": "high",
                                    }
                                ],
                                "uncertainties": [{"text": "Gap."}],
                                "evidence_gaps": [{"text": "More data."}],
                                "preliminary_disagreements": [{"text": "Trade-off.", "evidence_sources": ["SRC-002"]}],
                                "source_evaluation": [{"notes": "Source note.", "source_id": "SRC-001"}],
                                "sources": [
                                    {
                                        "id": "SRC-001",
                                        "title": "Source 1",
                                        "type": "report",
                                        "authority": "fixture",
                                        "locator": "https://example.com/src-001",
                                    },
                                    {
                                        "id": "SRC-002",
                                        "title": "Source 2",
                                        "type": "report",
                                        "authority": "fixture",
                                        "locator": "https://example.com/src-002",
                                    },
                                    {
                                        "id": "SRC-WF",
                                        "title": "Workflow artifact",
                                        "type": "workflow_artifact",
                                        "authority": "runner",
                                        "locator": "urn:workflow:research-a",
                                        "source_class": "workflow_provenance",
                                    },
                                ],
                            },
                            indent=2,
                        ),
                        encoding="utf-8",
                    )
                    sys.exit(0)

                print("unexpected stage", file=sys.stderr)
                sys.exit(2)
                """
            ).replace("\n                ", "\n").lstrip(),
            encoding="utf-8",
        )
        path.chmod(0o755)

    def _write_counting_resume_executor(self, path: Path) -> None:
        count_path = self.root / "substep-counts.json"
        path.write_text(
            textwrap.dedent(
                f"""\
                #!/usr/bin/env python3
                import json
                import re
                import sys
                from pathlib import Path

                count_path = Path({str(count_path)!r})
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
                stage = stage_match.group(1)
                substep = substep_match.group(1) if substep_match else "single-pass"
                output_path.parent.mkdir(parents=True, exist_ok=True)
                if json_path is not None:
                    json_path.parent.mkdir(parents=True, exist_ok=True)

                if "ADAPTER_QUALIFICATION=1" in prompt:
                    if output_path.suffix.lower() == ".json":
                        output_path.write_text(
                            json.dumps({{"stage": "adapter-qualification", "status": "ok"}}, indent=2),
                            encoding="utf-8",
                        )
                    else:
                        output_path.write_text("# Adapter qualification markdown\\n", encoding="utf-8")
                    sys.exit(0)

                if count_path.is_file():
                    raw_counts = count_path.read_text(encoding="utf-8").strip()
                    counts = json.loads(raw_counts) if raw_counts else {{}}
                else:
                    counts = {{}}
                key = f"{{stage}}:{{substep}}"
                counts[key] = counts.get(key, 0) + 1
                count_path.write_text(json.dumps(counts, indent=2), encoding="utf-8")

                if stage == "intake":
                    output_path.write_text(json.dumps({{
                        "question": "Which option is better?",
                        "scope": ["Compare option A and option B"],
                        "constraints": ["Require citations"],
                        "assumptions": [],
                        "missing_information": [],
                        "required_artifacts": ["judge report"],
                        "notes_for_researchers": ["Use cited evidence only"],
                        "known_facts": [{{"id": "KF-001", "statement": "The brief asks for an option comparison.", "source_ids": ["DOC-BRIEF"], "source_excerpt": "Which option is better?", "source_anchor": "brief.md#Question"}}],
                        "working_inferences": [],
                        "uncertainty_notes": [],
                        "sources": [
                            {{"id": "DOC-BRIEF", "title": "Job brief", "type": "project_brief", "authority": "job input", "locator": "brief.md", "source_class": "job_input"}},
                            {{"id": "DOC-CONFIG", "title": "Job config", "type": "job_config", "authority": "job input", "locator": "config.yaml", "source_class": "job_input"}}
                        ]
                    }}, indent=2), encoding="utf-8")
                    sys.exit(0)

                if stage in {{"research-a", "research-b", "critique-a-on-b", "critique-b-on-a", "judge"}} and substep == "source-pass":
                    json_path.write_text(
                        json.dumps(
                            {{
                                "stage": stage,
                                "sources": [
                                    {{"id": "SRC-001", "title": "Canonical source SRC-001", "type": "report", "authority": "test fixture", "locator": "https://example.com/src-001"}},
                                    {{"id": "SRC-002", "title": "Canonical source SRC-002", "type": "report", "authority": "test fixture", "locator": "https://example.com/src-002"}}
                                ],
                            }},
                            indent=2,
                        ),
                        encoding="utf-8",
                    )
                    sys.exit(0)

                if stage == "research-b" and substep == "claim-pass":
                    json_path.write_text(
                        json.dumps(
                            {{
                                "stage": "research-b",
                                "summary": [{{"text": "Summary.", "evidence_sources": ["SRC-001"]}}],
                                "facts": [{{"id": "F-001", "text": "Fact.", "evidence_sources": ["SRC-001"]}}],
                                "inferences": [{{"id": "I-001", "text": "Inference.", "evidence_sources": ["SRC-001"], "confidence": "high"}}],
                                "uncertainties": [],
                                "evidence_gaps": [],
                                "preliminary_disagreements": [],
                                "source_evaluation": [],
                            }},
                            indent=2,
                        ),
                        encoding="utf-8",
                    )
                    sys.exit(0)

                if stage == "research-a" and substep == "claim-pass":
                    json_path.write_text(
                        json.dumps(
                            {{
                                "stage": "research-a",
                                "summary": [{{"text": "Summary.", "evidence_sources": ["SRC-001"]}}],
                                "facts": [{{"id": "F-001", "text": "Fact.", "evidence_sources": ["SRC-001"]}}],
                                "inferences": [{{"id": "I-001", "text": "Inference.", "evidence_sources": ["SRC-001"], "confidence": "high"}}],
                                "uncertainties": [],
                                "evidence_gaps": [],
                                "preliminary_disagreements": [],
                                "source_evaluation": [],
                            }},
                            indent=2,
                        ),
                        encoding="utf-8",
                    )
                    sys.exit(0)

                if stage in {{"critique-a-on-b", "critique-b-on-a"}} and substep == "claim-pass":
                    json_path.write_text(
                        json.dumps(
                            {{
                                "stage": stage,
                                "supported_claims": [{{"text": "One claim survives review.", "evidence_sources": ["SRC-001"]}}],
                                "unsupported_claims": [],
                                "weak_source_issues": [],
                                "omissions": [],
                                "overreach": [],
                                "unresolved_disagreements": [],
                                "summary": {{"text": "Mostly sound.", "confidence": "medium"}},
                            }},
                            indent=2,
                        ),
                        encoding="utf-8",
                    )
                    sys.exit(0)

                if stage == "judge" and substep == "claim-pass":
                    json_path.write_text(
                        json.dumps(
                            {{
                                "stage": "judge",
                                "supported_conclusions": [{{"id": "C-001", "text": "Conclusion.", "evidence_sources": ["SRC-001"]}}],
                                "synthesis_judgments": [{{"id": "J-001", "text": "Judgment.", "evidence_sources": ["SRC-001"], "confidence": "medium"}}],
                                "unresolved_disagreements": [],
                                "confidence_assessment": [],
                                "evidence_gaps": [],
                                "rationale": [],
                                "recommended_artifact_structure": ["Summary"],
                            }},
                            indent=2,
                        ),
                        encoding="utf-8",
                    )
                    sys.exit(0)

                print("unexpected stage/substep", file=sys.stderr)
                sys.exit(2)
                """
            ),
            encoding="utf-8",
        )
        path.chmod(0o755)

    def _write_research_b_stdout_executor(self, path: Path, markdown: str, json_payload: str | None = None) -> None:
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
                if json_path is not None:
                    json_path.parent.mkdir(parents=True, exist_ok=True)
                stage = stage_match.group(1)
                substep = substep_match.group(1) if substep_match else "single-pass"

                if "ADAPTER_QUALIFICATION=1" in prompt:
                    if output_path.suffix.lower() == ".json":
                        output_path.write_text(
                            json.dumps({{"stage": "adapter-qualification", "status": "ok"}}, indent=2),
                            encoding="utf-8",
                        )
                    else:
                        output_path.write_text("# Adapter qualification markdown\\n", encoding="utf-8")
                    sys.exit(0)

                if stage == "research-b" and substep == "source-pass":
                    if json_path is not None:
                        json_path.write_text(
                            json.dumps({{
                                "stage": "research-b",
                                "sources": [
                                    {{"id": "SRC-002", "title": "Canonical source SRC-002", "type": "report", "authority": "test fixture", "locator": "https://example.com/src-002"}},
                                    {{"id": "SRC-003", "title": "Canonical source SRC-003", "type": "report", "authority": "test fixture", "locator": "https://example.com/src-003"}},
                                    {{"id": "SRC-004", "title": "Canonical source SRC-004", "type": "report", "authority": "test fixture", "locator": "https://example.com/src-004"}},
                                    {{"id": "SRC-005", "title": "Canonical source SRC-005", "type": "report", "authority": "test fixture", "locator": "https://example.com/src-005"}},
                                    {{"id": "SRC-006", "title": "Canonical source SRC-006", "type": "report", "authority": "test fixture", "locator": "https://example.com/src-006"}}
                                ]
                            }}, indent=2),
                            encoding="utf-8",
                        )
                    sys.exit(0)

                if stage == "research-b" and substep == "claim-pass":
                    payload = {json_payload!r}
                    if payload is None:
                        print({markdown!r})
                    else:
                        parsed = json.loads(payload)
                        parsed.pop("sources", None)
                        print({markdown!r} + "\\n\\n```json\\n" + json.dumps(parsed, indent=2) + "\\n```")
                    sys.exit(0)

                if stage == "critique-b-on-a" and substep == "source-pass":
                    if json_path is not None:
                        json_path.write_text(
                            json.dumps({{
                                "stage": "critique-b-on-a",
                                "sources": [
                                    {{"id": "SRC-010", "title": "Canonical source SRC-010", "type": "report", "authority": "test fixture", "locator": "https://example.com/src-010"}},
                                    {{"id": "SRC-011", "title": "Canonical source SRC-011", "type": "report", "authority": "test fixture", "locator": "https://example.com/src-011"}},
                                    {{"id": "SRC-012", "title": "Canonical source SRC-012", "type": "report", "authority": "test fixture", "locator": "https://example.com/src-012"}},
                                    {{"id": "SRC-013", "title": "Canonical source SRC-013", "type": "report", "authority": "test fixture", "locator": "https://example.com/src-013"}},
                                    {{"id": "SRC-014", "title": "Canonical source SRC-014", "type": "report", "authority": "test fixture", "locator": "https://example.com/src-014"}},
                                    {{"id": "SRC-015", "title": "Canonical source SRC-015", "type": "report", "authority": "test fixture", "locator": "https://example.com/src-015"}}
                                ]
                            }}, indent=2),
                            encoding="utf-8",
                        )
                    sys.exit(0)

                if stage == "critique-b-on-a" and substep == "claim-pass":
                    if json_path is not None:
                        json_path.write_text(
                            json.dumps({{
                                "stage": "critique-b-on-a",
                                "supported_claims": [{{"text": "One claim survives review.", "evidence_sources": ["SRC-010"]}}],
                                "unsupported_claims": [
                                    {{
                                        "target_claim": "Some claims need stronger support.",
                                        "reason": "Support is incomplete.",
                                        "needed_evidence": "Direct benchmark evidence.",
                                        "evidence_sources": ["SRC-011"]
                                    }}
                                ],
                                "weak_source_issues": [{{"text": "One citation is indirect.", "evidence_sources": ["SRC-012"]}}],
                                "omissions": [{{"text": "Missing alternative analysis.", "evidence_sources": ["SRC-013"]}}],
                                "overreach": [{{"text": "One conclusion is too strong.", "evidence_sources": ["SRC-014"]}}],
                                "unresolved_disagreements": [{{"text": "Option A vs B remains disputed.", "evidence_sources": ["SRC-015"]}}],
                                "summary": {{"text": "Reliability is mixed.", "confidence": "medium"}}
                            }}, indent=2),
                            encoding="utf-8",
                        )
                    sys.exit(0)

                if stage == "judge" and substep == "source-pass":
                    if json_path is not None:
                        json_path.write_text(
                            json.dumps(
                                {{
                                    "stage": "judge",
                                    "sources": [
                                        {{"id": "SRC-001", "title": "Canonical source SRC-001", "type": "report", "authority": "test fixture", "locator": "https://example.com/src-001"}},
                                        {{"id": "SRC-002", "title": "Canonical source SRC-002", "type": "report", "authority": "test fixture", "locator": "https://example.com/src-002"}}
                                    ],
                                }},
                                indent=2,
                            ),
                            encoding="utf-8",
                        )
                    sys.exit(0)

                if stage == "judge" and substep == "claim-pass":
                    if json_path is not None:
                        json_path.write_text(
                            json.dumps(
                                {{
                                    "stage": "judge",
                                    "supported_conclusions": [{{"id": "judge-conclusion-1", "text": "Option A has lower implementation risk.", "evidence_sources": ["SRC-001"]}}],
                                    "synthesis_judgments": [{{"id": "judge-inference-1", "text": "Option A is the safer near-term choice.", "evidence_sources": ["SRC-001", "SRC-002"], "confidence": "medium"}}],
                                    "unresolved_disagreements": ["Hardware selection remains unresolved because interface data is missing."],
                                    "confidence_assessment": ["Medium confidence: evidence is incomplete and benchmark coverage is limited."],
                                    "evidence_gaps": ["No direct benchmark compares both options in this environment."],
                                    "rationale": ["Research A favored Option A and critique B-on-A preserved upside concerns."],
                                    "recommended_artifact_structure": ["Summary", "Comparison", "Recommendation", "Uncertainty", "References", "Open Questions"],
                                }},
                                indent=2,
                            ),
                            encoding="utf-8",
                        )
                    sys.exit(0)

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
                "--gemini-bin",
                str(self.gemini_bin),
                "--antigravity-bin",
                str(self.antigravity_bin),
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("codex: intake started", result.stdout.lower())
        self.assertIn("codex: intake completed", result.stdout.lower())
        self.assertIn("codex: research-a started", result.stdout.lower())
        self.assertIn("gemini: research-b started", result.stdout.lower())
        self.assertIn("codex: critique-a-on-b completed", result.stdout.lower())
        self.assertIn("gemini: judge completed", result.stdout.lower())
        self.assertIn("system: claim-extraction started", result.stdout.lower())
        self.assertIn("system: final-artifact completed", result.stdout.lower())

        run_dir = self.job_dir / "runs" / "run-001"
        self.assertTrue((run_dir / "stage-outputs" / "01-intake.json").is_file())
        self.assertTrue((run_dir / "sources.json").is_file())
        self.assertTrue((run_dir / "stage-outputs" / "02-research-a.json").is_file())
        self.assertTrue((run_dir / "stage-outputs" / "02-research-a.md").is_file())
        self.assertTrue((run_dir / "stage-outputs" / "03-research-b.json").is_file())
        self.assertTrue((run_dir / "stage-outputs" / "03-research-b.md").is_file())
        self.assertTrue((run_dir / "stage-outputs" / "04-critique-a-on-b.md").is_file())
        self.assertTrue((run_dir / "stage-outputs" / "05-critique-b-on-a.md").is_file())
        self.assertTrue((run_dir / "stage-outputs" / "06-judge.json").is_file())
        self.assertTrue((run_dir / "stage-outputs" / "06-judge.md").is_file())

        claim_register = self.job_dir / "evidence" / "claims-run-001.json"
        final_artifact = self.job_dir / "outputs" / "final-run-001.md"
        self.assertTrue(claim_register.is_file())
        self.assertTrue(final_artifact.is_file())
        self.assertTrue((run_dir / "stage-claims" / "02-research-a.claims.json").is_file())
        self.assertTrue((run_dir / "stage-claims" / "03-research-b.claims.json").is_file())
        self.assertTrue((run_dir / "stage-claims" / "04-critique-a-on-b.claims.json").is_file())
        self.assertTrue((run_dir / "stage-claims" / "05-critique-b-on-a.claims.json").is_file())
        self.assertTrue((run_dir / "stage-claims" / "06-judge.claims.json").is_file())

        payload = json.loads(claim_register.read_text(encoding="utf-8"))
        self.assertEqual(payload["summary"]["uncited_fact_ids"], [])

        artifact = final_artifact.read_text(encoding="utf-8")
        self.assertIn("# Executive Summary", artifact)
        self.assertIn("# Recommendation", artifact)
        self.assertIn("# References", artifact)
        self.assertIn("SRC-001", artifact)

        source_registry = json.loads((run_dir / "sources.json").read_text(encoding="utf-8"))
        source_ids = {source["id"] for source in source_registry["sources"]}
        self.assertIn("DOC-BRIEF", source_ids)
        self.assertIn("DOC-CONFIG", source_ids)

        state = json.loads((run_dir / "workflow-state.json").read_text(encoding="utf-8"))
        statuses = {stage["id"]: stage["status"] for stage in state["stages"]}
        self.assertEqual(statuses["intake"], "completed")
        self.assertEqual(statuses["judge"], "completed")
        intake_state = next(stage for stage in state["stages"] if stage["id"] == "intake")
        self.assertEqual(intake_state["substeps"]["source-pass"]["status"], "completed")
        self.assertEqual(intake_state["substeps"]["fact-lineage"]["status"], "completed")
        self.assertEqual(intake_state["substeps"]["normalization"]["status"], "completed")
        self.assertEqual(intake_state["substeps"]["merge"]["status"], "completed")
        self.assertEqual(state["post_processing"]["stage_claims"]["research-a"]["status"], "completed")
        self.assertEqual(state["post_processing"]["stage_claims"]["research-b"]["status"], "completed")
        self.assertEqual(state["post_processing"]["stage_claims"]["judge"]["status"], "completed")
        self.assertEqual(state["post_processing"]["claim_extraction"]["status"], "completed")
        self.assertEqual(state["post_processing"]["final_artifact"]["status"], "completed")

    def test_persists_append_only_workflow_events(self) -> None:
        result = subprocess.run(
            self._workflow_command("run-events"),
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            input="yes\n",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        events_path = self.job_dir / "runs" / "run-events" / "events.jsonl"
        self.assertTrue(events_path.is_file())
        events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        event_types = [event["event_type"] for event in events]
        self.assertIn("run_started", event_types)
        self.assertIn("stage_started", event_types)
        self.assertIn("stage_completed", event_types)
        self.assertIn("substep_started", event_types)
        self.assertIn("substep_completed", event_types)
        self.assertIn("post_processing_completed", event_types)
        self.assertTrue(
            any(
                event["event_type"] == "substep_started"
                and event.get("stage_id") == "research-a"
                and event.get("substep") == "source-pass"
                for event in events
            )
        )

    def test_can_rebuild_workflow_state_from_events(self) -> None:
        result = subprocess.run(
            self._workflow_command("run-rebuild"),
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            input="yes\n",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        run_dir = self.job_dir / "runs" / "run-rebuild"
        state_path = run_dir / "workflow-state.json"
        original_state = json.loads(state_path.read_text(encoding="utf-8"))
        state_path.unlink()

        rebuild = subprocess.run(
            ["python3", str(REBUILD_WORKFLOW_STATE), "--run-dir", str(run_dir)],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )

        self.assertEqual(rebuild.returncode, 0, rebuild.stderr)
        rebuilt_state = json.loads(state_path.read_text(encoding="utf-8"))
        self.assertEqual(rebuilt_state["status"], original_state["status"])
        self.assertEqual(
            {stage["id"]: stage["status"] for stage in rebuilt_state["stages"]},
            {stage["id"]: stage["status"] for stage in original_state["stages"]},
        )
        self.assertEqual(
            rebuilt_state["post_processing"]["final_artifact"]["status"],
            original_state["post_processing"]["final_artifact"]["status"],
        )

    def test_event_replay_restores_running_status_for_started_events(self) -> None:
        run_dir = self.job_dir / "runs" / "run-replay-running"
        run_dir.mkdir(parents=True, exist_ok=True)
        initial_state = {
            "run_id": "run-replay-running",
            "run_dir": str(run_dir),
            "status": "scaffolded",
            "stages": [
                {"id": "intake", "status": "pending", "substeps": {"source-pass": {"status": "pending"}}},
            ],
            "post_processing": {
                "claim_extraction": {"status": "pending"},
                "final_artifact": {"status": "pending"},
                "stage_claims": {},
            },
        }
        from _workflow_state import append_workflow_event, derive_workflow_state_from_events

        append_workflow_event(run_dir, "run_started", initial_state=initial_state)
        append_workflow_event(run_dir, "stage_started", stage_id="intake")
        append_workflow_event(run_dir, "substep_started", stage_id="intake", substep="source-pass")
        append_workflow_event(run_dir, "post_processing_started", key="claim_extraction")

        rebuilt_state = derive_workflow_state_from_events(run_dir)

        self.assertEqual(rebuilt_state["status"], "running")
        self.assertEqual(rebuilt_state["stages"][0]["status"], "running")
        self.assertEqual(rebuilt_state["stages"][0]["substeps"]["source-pass"]["status"], "running")
        self.assertEqual(rebuilt_state["post_processing"]["claim_extraction"]["status"], "running")

    def test_execute_workflow_defaults_run_id_to_next_incremental_value(self) -> None:
        result = subprocess.run(
            [
                "python3",
                str(EXECUTE_WORKFLOW),
                "--job-path",
                str(self.job_dir),
                "--codex-bin",
                str(self.codex_bin),
                "--gemini-bin",
                str(self.gemini_bin),
                "--antigravity-bin",
                str(self.antigravity_bin),
                "--claude-bin",
                str(self.claude_bin),
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.job_dir / "runs" / "run-001").is_dir())
        self.assertIn(str(self.job_dir / "runs" / "run-001"), result.stdout)

    def test_execute_workflow_picks_next_available_incremental_run_id(self) -> None:
        (self.job_dir / "runs" / "run-001").mkdir()
        (self.job_dir / "runs" / "run-002").mkdir()
        (self.job_dir / "runs" / "run-manual").mkdir()

        result = subprocess.run(
            [
                "python3",
                str(EXECUTE_WORKFLOW),
                "--job-path",
                str(self.job_dir),
                "--codex-bin",
                str(self.codex_bin),
                "--gemini-bin",
                str(self.gemini_bin),
                "--antigravity-bin",
                str(self.antigravity_bin),
                "--claude-bin",
                str(self.claude_bin),
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.job_dir / "runs" / "run-003").is_dir())
        self.assertIn(str(self.job_dir / "runs" / "run-003"), result.stdout)

    def test_explicit_existing_run_id_prompts_and_continues_on_yes(self) -> None:
        result = subprocess.run(
            self._workflow_command("run-001"),
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            input="yes\n",
        )
        resume = subprocess.run(
            self._workflow_command("run-001"),
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            input="yes\n",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(resume.returncode, 0, resume.stderr)
        self.assertIn("already exists", resume.stdout.lower())
        self.assertIn("workflow already complete for run run-001", resume.stdout.lower())

    def test_explicit_existing_run_id_stops_on_no(self) -> None:
        result = subprocess.run(
            self._workflow_command("run-001"),
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            input="yes\n",
        )
        declined = subprocess.run(
            self._workflow_command("run-001"),
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            input="no\n",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotEqual(declined.returncode, 0)
        self.assertIn("already exists", declined.stdout.lower())
        self.assertIn("aborted by user", declined.stderr.lower())

    def test_explicit_existing_run_id_stops_when_confirmation_is_missing(self) -> None:
        result = subprocess.run(
            self._workflow_command("run-001"),
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            input="yes\n",
        )
        missing_confirmation = subprocess.run(
            self._workflow_command("run-001"),
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotEqual(missing_confirmation.returncode, 0)
        self.assertIn("confirmation required", missing_confirmation.stderr.lower())

    def test_fails_when_structured_stage_output_cites_undefined_source(self) -> None:
        self.gemini_bin.write_text(
            textwrap.dedent(
                """\
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
                if json_path is not None:
                    json_path.parent.mkdir(parents=True, exist_ok=True)
                stage = stage_match.group(1)
                substep = substep_match.group(1) if substep_match else "single-pass"

                if "ADAPTER_QUALIFICATION=1" in prompt:
                    if output_path.suffix.lower() == ".json":
                        output_path.write_text(
                            json.dumps({"stage": "adapter-qualification", "status": "ok"}, indent=2),
                            encoding="utf-8",
                        )
                    else:
                        output_path.write_text("# Adapter qualification markdown\\n", encoding="utf-8")
                    sys.exit(0)

                if stage == "research-b" and substep == "source-pass":
                    json_path.write_text(
                        json.dumps(
                            {
                                "stage": "research-b",
                                "sources": []
                            },
                            indent=2,
                        ),
                        encoding="utf-8",
                    )
                    sys.exit(0)

                if stage == "research-b" and substep == "claim-pass":
                    json_path.write_text(
                        json.dumps(
                            {
                                "stage": "research-b",
                                "summary": [{"text": "Research B summary.", "evidence_sources": ["SRC-999"]}],
                                "facts": [{"id": "research-b-fact-1", "text": "Option B has evidence behind it.", "evidence_sources": ["SRC-999"]}],
                                "inferences": [{"id": "research-b-inf-1", "text": "Option B may be viable.", "evidence_sources": ["SRC-999"], "confidence": "medium"}],
                                "uncertainties": [{"text": "Coverage is incomplete."}],
                                "evidence_gaps": [{"text": "Benchmarking is incomplete."}],
                                "preliminary_disagreements": [{"text": "The other option may be stronger on another axis."}],
                                "source_evaluation": [{"source_id": "SRC-999", "notes": "Sources are limited but relevant."}],
                            },
                            indent=2,
                        ),
                        encoding="utf-8",
                    )
                    sys.exit(0)

                if stage == "critique-b-on-a":
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
                    if json_path is not None:
                        json_path.write_text(
                            json.dumps(
                                {
                                    "stage": "critique-b-on-a",
                                    "supported_claims": [{"text": "One claim survives review.", "evidence_sources": ["SRC-010"]}],
                                    "unsupported_claims": [
                                        {
                                            "target_claim": "Some claims need stronger support.",
                                            "reason": "Support is incomplete.",
                                            "needed_evidence": "Direct benchmark evidence.",
                                            "evidence_sources": ["SRC-011"],
                                        }
                                    ],
                                    "weak_source_issues": [{"text": "One citation is indirect.", "evidence_sources": ["SRC-012"]}],
                                    "omissions": [{"text": "Missing alternative analysis.", "evidence_sources": ["SRC-013"]}],
                                    "overreach": [{"text": "One conclusion is too strong.", "evidence_sources": ["SRC-014"]}],
                                    "unresolved_disagreements": [{"text": "Option A vs B remains disputed.", "evidence_sources": ["SRC-015"]}],
                                    "summary": {"text": "Reliability is mixed.", "confidence": "medium"},
                                    "sources": [
                                        {"id": "SRC-010", "title": "Canonical source SRC-010", "type": "report", "authority": "fixture", "locator": "https://example.com/src-010"},
                                        {"id": "SRC-011", "title": "Canonical source SRC-011", "type": "report", "authority": "fixture", "locator": "https://example.com/src-011"},
                                        {"id": "SRC-012", "title": "Canonical source SRC-012", "type": "report", "authority": "fixture", "locator": "https://example.com/src-012"},
                                        {"id": "SRC-013", "title": "Canonical source SRC-013", "type": "report", "authority": "fixture", "locator": "https://example.com/src-013"},
                                        {"id": "SRC-014", "title": "Canonical source SRC-014", "type": "report", "authority": "fixture", "locator": "https://example.com/src-014"},
                                        {"id": "SRC-015", "title": "Canonical source SRC-015", "type": "report", "authority": "fixture", "locator": "https://example.com/src-015"},
                                    ],
                                },
                                indent=2,
                            ),
                            encoding="utf-8",
                        )
                    sys.exit(0)

                if stage == "judge":
                    output_path.write_text(
                        "# Supported Conclusions\\n\\n1. Option A has lower implementation risk. [SRC-001]\\n\\n"
                        "# Inferences And Synthesis Judgments\\n\\n1. Inference: Option A is the safer near-term choice. [SRC-001, SRC-002] Confidence: medium\\n\\n"
                        "# Unresolved Disagreements\\n\\n1. Hardware Selection remains unresolved because interface data is missing. [SRC-003]\\n\\n"
                        "# Confidence Assessment\\n\\n- Medium confidence: evidence is incomplete and benchmark coverage is limited. [SRC-004]\\n\\n"
                        "# Evidence Gaps\\n\\n- No direct benchmark compares both options in this environment. [SRC-005]\\n\\n"
                        "# Rationale And Traceability\\n\\n- Research A favored Option A and critique B-on-A preserved upside concerns.\\n\\n"
                        "# Recommended Final Artifact Structure\\n\\n- Summary, comparison, recommendation, uncertainty, references, open questions.\\n",
                        encoding="utf-8",
                    )
                    if json_path is not None:
                        json_path.write_text(
                            json.dumps(
                                {
                                    "stage": "judge",
                                    "supported_conclusions": [{"id": "judge-conclusion-1", "text": "Option A has lower implementation risk.", "evidence_sources": ["SRC-001"]}],
                                    "synthesis_judgments": [{"id": "judge-inference-1", "text": "Option A is the safer near-term choice.", "evidence_sources": ["SRC-001", "SRC-002"], "confidence": "medium"}],
                                    "unresolved_disagreements": ["Hardware selection remains unresolved because interface data is missing."],
                                    "confidence_assessment": ["Medium confidence: evidence is incomplete and benchmark coverage is limited."],
                                    "evidence_gaps": ["No direct benchmark compares both options in this environment."],
                                    "rationale": ["Research A favored Option A and critique B-on-A preserved upside concerns."],
                                    "recommended_artifact_structure": ["Summary", "Comparison", "Recommendation", "Uncertainty", "References", "Open Questions"],
                                    "sources": [
                                        {"id": "SRC-001", "title": "Canonical source SRC-001", "type": "report", "authority": "fixture", "locator": "https://example.com/src-001"},
                                        {"id": "SRC-002", "title": "Canonical source SRC-002", "type": "report", "authority": "fixture", "locator": "https://example.com/src-002"}
                                    ],
                                },
                                indent=2,
                            ),
                            encoding="utf-8",
                        )
                    sys.exit(0)

                print("fallback", file=sys.stderr)
                sys.exit(0)
                """
            ),
            encoding="utf-8",
        )
        self.gemini_bin.chmod(0o755)

        result = subprocess.run(
            [
                "python3",
                str(EXECUTE_WORKFLOW),
                "--job-path",
                str(self.job_dir),
                "--run-id",
                "run-bad-source-registry",
                "--codex-bin",
                str(self.codex_bin),
                "--gemini-bin",
                str(self.gemini_bin),
                "--antigravity-bin",
                str(self.antigravity_bin),
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unresolved source", result.stderr.lower())

    def test_runner_ignores_direct_model_edits_to_shared_source_registry(self) -> None:
        self.gemini_bin.write_text(
            textwrap.dedent(
                """\
                #!/usr/bin/env python3
                import json
                import re
                import sys
                from pathlib import Path

                prompt = " ".join(sys.argv[1:])
                output_match = re.search(r"OUTPUT_PATH=(.+)", prompt)
                json_match = re.search(r"OUTPUT_JSON_PATH=(.+)", prompt)
                source_match = re.search(r"SOURCE_REGISTRY_PATH=(.+)", prompt)
                stage_match = re.search(r"STAGE_ID=([a-z0-9-]+)", prompt)
                substep_match = re.search(r"SUBSTEP=([a-z-]+)", prompt)
                if not output_match or not stage_match:
                    print("missing stage metadata", file=sys.stderr)
                    sys.exit(2)

                output_path = Path(output_match.group(1).strip())
                json_path = Path(json_match.group(1).strip()) if json_match else None
                source_path = Path(source_match.group(1).strip()) if source_match else None
                output_path.parent.mkdir(parents=True, exist_ok=True)
                if json_path is not None:
                    json_path.parent.mkdir(parents=True, exist_ok=True)
                stage = stage_match.group(1)
                substep = substep_match.group(1) if substep_match else "single-pass"

                if "ADAPTER_QUALIFICATION=1" in prompt:
                    if output_path.suffix.lower() == ".json":
                        output_path.write_text(
                            json.dumps({"stage": "adapter-qualification", "status": "ok"}, indent=2),
                            encoding="utf-8",
                        )
                    else:
                        output_path.write_text("# Adapter qualification markdown\\n", encoding="utf-8")
                    sys.exit(0)

                if stage == "research-b" and substep == "source-pass":
                    json_path.write_text(
                        json.dumps(
                            {
                                "stage": "research-b",
                                "sources": [
                                    {
                                        "id": "SRC-200",
                                        "title": "Canonical stage source",
                                        "type": "report",
                                        "authority": "fixture",
                                        "locator": "https://example.com/src-200",
                                    }
                                ],
                            },
                            indent=2,
                        ),
                        encoding="utf-8",
                    )
                    source_path.write_text(
                        json.dumps(
                            {
                                "run_id": "run-registry-guard",
                                "sources": [
                                    {
                                        "id": "SRC-INJECTED",
                                        "title": "Injected by model",
                                        "type": "report",
                                        "authority": "bad write",
                                        "locator": "https://example.com/injected",
                                    }
                                ],
                            },
                            indent=2,
                        ),
                        encoding="utf-8",
                    )
                    sys.exit(0)

                if stage == "research-b" and substep == "claim-pass":
                    json_path.write_text(
                        json.dumps(
                            {
                                "stage": "research-b",
                                "summary": "Research B summary.",
                                "facts": [{"id": "F-200", "text": "Fact.", "evidence_sources": ["SRC-200"]}],
                                "inferences": [{"id": "I-200", "text": "Inference.", "evidence_sources": ["SRC-200"], "confidence": "high"}],
                                "uncertainties": ["Gap."],
                                "evidence_gaps": ["More data."],
                                "preliminary_disagreements": ["Trade-off remains."],
                                "source_evaluation": ["Source quality note."],
                            },
                            indent=2,
                        ),
                        encoding="utf-8",
                    )
                    sys.exit(0)

                if stage == "critique-b-on-a" and substep == "source-pass":
                    if json_path is not None:
                        json_path.write_text(
                            json.dumps(
                                {
                                    "stage": "critique-b-on-a",
                                    "sources": [
                                        {"id": "SRC-010", "title": "Canonical source SRC-010", "type": "report", "authority": "test fixture", "locator": "https://example.com/src-010"},
                                        {"id": "SRC-011", "title": "Canonical source SRC-011", "type": "report", "authority": "test fixture", "locator": "https://example.com/src-011"},
                                        {"id": "SRC-012", "title": "Canonical source SRC-012", "type": "report", "authority": "test fixture", "locator": "https://example.com/src-012"},
                                        {"id": "SRC-013", "title": "Canonical source SRC-013", "type": "report", "authority": "test fixture", "locator": "https://example.com/src-013"},
                                        {"id": "SRC-014", "title": "Canonical source SRC-014", "type": "report", "authority": "test fixture", "locator": "https://example.com/src-014"},
                                        {"id": "SRC-015", "title": "Canonical source SRC-015", "type": "report", "authority": "test fixture", "locator": "https://example.com/src-015"},
                                    ],
                                },
                                indent=2,
                            ),
                            encoding="utf-8",
                        )
                    sys.exit(0)

                if stage == "critique-b-on-a" and substep == "claim-pass":
                    if json_path is not None:
                        json_path.write_text(
                            json.dumps(
                                {
                                    "stage": "critique-b-on-a",
                                    "supported_claims": [{"text": "One claim survives review.", "evidence_sources": ["SRC-010"]}],
                                    "unsupported_claims": [
                                        {
                                            "target_claim": "Some claims need stronger support.",
                                            "reason": "Support is incomplete.",
                                            "needed_evidence": "Direct benchmark evidence.",
                                            "evidence_sources": ["SRC-011"],
                                        }
                                    ],
                                    "weak_source_issues": [{"text": "One citation is indirect.", "evidence_sources": ["SRC-012"]}],
                                    "omissions": [{"text": "Missing alternative analysis.", "evidence_sources": ["SRC-013"]}],
                                    "overreach": [{"text": "One conclusion is too strong.", "evidence_sources": ["SRC-014"]}],
                                    "unresolved_disagreements": [{"text": "Option A vs B remains disputed.", "evidence_sources": ["SRC-015"]}],
                                    "summary": {"text": "Reliability is mixed.", "confidence": "medium"},
                                },
                                indent=2,
                            ),
                            encoding="utf-8",
                        )
                    sys.exit(0)

                if stage == "judge" and substep == "source-pass":
                    if json_path is not None:
                        json_path.write_text(
                            json.dumps(
                                {
                                    "stage": "judge",
                                    "sources": [
                                        {"id": "SRC-001", "title": "Canonical source SRC-001", "type": "report", "authority": "test fixture", "locator": "https://example.com/src-001"},
                                        {"id": "SRC-002", "title": "Canonical source SRC-002", "type": "report", "authority": "test fixture", "locator": "https://example.com/src-002"}
                                    ],
                                },
                                indent=2,
                            ),
                            encoding="utf-8",
                        )
                    sys.exit(0)

                if stage == "judge" and substep == "claim-pass":
                    if json_path is not None:
                        json_path.write_text(
                            json.dumps(
                                {
                                    "stage": "judge",
                                    "supported_conclusions": [{"id": "judge-conclusion-1", "text": "Option A has lower implementation risk.", "evidence_sources": ["SRC-001"]}],
                                    "synthesis_judgments": [{"id": "judge-inference-1", "text": "Option A is the safer near-term choice.", "evidence_sources": ["SRC-001", "SRC-002"], "confidence": "medium"}],
                                    "unresolved_disagreements": ["Hardware selection remains unresolved because interface data is missing."],
                                    "confidence_assessment": ["Medium confidence: evidence is incomplete and benchmark coverage is limited."],
                                    "evidence_gaps": ["No direct benchmark compares both options in this environment."],
                                    "rationale": ["Research A favored Option A and critique B-on-A preserved upside concerns."],
                                    "recommended_artifact_structure": ["Summary", "Comparison", "Recommendation", "Uncertainty", "References", "Open Questions"],
                                },
                                indent=2,
                            ),
                            encoding="utf-8",
                        )
                    sys.exit(0)

                print("fallback", file=sys.stderr)
                sys.exit(0)
                """
            ),
            encoding="utf-8",
        )
        self.gemini_bin.chmod(0o755)

        result = subprocess.run(
            [
                "python3",
                str(EXECUTE_WORKFLOW),
                "--job-path",
                str(self.job_dir),
                "--run-id",
                "run-registry-guard",
                "--codex-bin",
                str(self.codex_bin),
                "--gemini-bin",
                str(self.gemini_bin),
                "--antigravity-bin",
                str(self.antigravity_bin),
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        sources_payload = json.loads(
            (self.job_dir / "runs" / "run-registry-guard" / "sources.json").read_text(encoding="utf-8")
        )
        source_ids = {source["id"] for source in sources_payload["sources"]}
        self.assertIn("SRC-200", source_ids)
        self.assertNotIn("SRC-INJECTED", source_ids)

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
                "--gemini-bin",
                str(self.gemini_bin),
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
                "--gemini-bin",
                str(self.gemini_bin),
                "--antigravity-bin",
                str(self.antigravity_bin),
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            input="yes\n",
        )
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertIn("already complete", second.stdout.lower())

    def test_resuming_completed_run_does_not_double_count_provider_stage_results(self) -> None:
        first = subprocess.run(
            [
                "python3",
                str(EXECUTE_WORKFLOW),
                "--job-path",
                str(self.job_dir),
                "--run-id",
                "run-scorecard-resume",
                "--codex-bin",
                str(self.codex_bin),
                "--gemini-bin",
                str(self.gemini_bin),
                "--antigravity-bin",
                str(self.antigravity_bin),
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(first.returncode, 0, first.stderr)

        scorecard_dir = self.job_dir / "audit" / "provider-scorecards"
        before_payloads = {
            path.name: json.loads(path.read_text(encoding="utf-8"))
            for path in scorecard_dir.glob("*.json")
        }
        self.assertTrue(before_payloads)

        second = subprocess.run(
            [
                "python3",
                str(EXECUTE_WORKFLOW),
                "--job-path",
                str(self.job_dir),
                "--run-id",
                "run-scorecard-resume",
                "--codex-bin",
                str(self.codex_bin),
                "--gemini-bin",
                str(self.gemini_bin),
                "--antigravity-bin",
                str(self.antigravity_bin),
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            input="yes\n",
        )
        self.assertEqual(second.returncode, 0, second.stderr)

        after_payloads = {
            path.name: json.loads(path.read_text(encoding="utf-8"))
            for path in scorecard_dir.glob("*.json")
        }
        self.assertEqual(set(after_payloads), set(before_payloads))
        for name, before in before_payloads.items():
            after = after_payloads[name]
            self.assertEqual(after["totals"], before["totals"])
            self.assertEqual(len(after["stage_results"]), len(before["stage_results"]))

    def test_run_stage_group_does_not_double_record_provider_result_when_claim_extraction_fails(self) -> None:
        run_dir = self.job_dir / "runs" / "run-claim-extraction-fails"
        run_dir.mkdir(parents=True, exist_ok=True)
        state_path = run_dir / "workflow-state.json"
        state = {
            "run_dir": str(run_dir),
            "status": "running",
            "stages": [{"id": "research-a", "status": "pending", "substeps": {}}],
            "post_processing": {
                "stage_claims": {"research-a": {"status": "pending", "output_path": str(run_dir / "stage-claims" / "02-research-a.claims.json")}},
                "claim_extraction": {"status": "pending", "output_path": str(self.job_dir / "evidence" / "claims-run-x.json")},
                "final_artifact": {"status": "pending", "output_path": str(self.job_dir / "outputs" / "final-run-x.md")},
            },
        }
        reporter = ProgressReporter(io.StringIO())
        calls: list[tuple[str, str]] = []

        with (
            patch("execute_workflow.run_agent_stage", return_value=("research-a", "completed")),
            patch("execute_workflow.run_stage_claim_extraction", side_effect=RuntimeError("claim extraction failed")),
            patch("execute_workflow.merge_stage_sources_into_registry", return_value=None),
            patch("execute_workflow.record_provider_stage_result", side_effect=lambda job_dir, provider_key, stage_id, status, **_: calls.append((stage_id, status))),
        ):
            with self.assertRaisesRegex(RuntimeError, "claim extraction failed"):
                run_stage_group(
                    [StageExecution("research-a", "primary", "02-research-a.md", "02-research-a.md")],
                    run_dir,
                    self.job_dir,
                    state_path,
                    state,
                    {"research-a": StageAdapterSelection(adapter_name="codex")},
                    {"codex": str(self.codex_bin), "gemini": str(self.gemini_bin), "antigravity": str(self.antigravity_bin), "claude": str(self.claude_bin)},
                    reporter,
                )

        self.assertEqual(calls, [("research-a", "completed")])

    def test_reports_skipped_stages_when_resuming_partial_run(self) -> None:
        partial_run = subprocess.run(
            [
                "python3",
                str(EXECUTE_WORKFLOW),
                "--job-path",
                str(self.job_dir),
                "--run-id",
                "run-partial",
                "--codex-bin",
                str(self.codex_bin),
                "--gemini-bin",
                str(self.gemini_bin),
                "--antigravity-bin",
                str(self.antigravity_bin),
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(partial_run.returncode, 0, partial_run.stderr)

        run_dir = self.job_dir / "runs" / "run-partial"
        (run_dir / "stage-outputs" / "03-research-b.md").unlink()
        (self.job_dir / "evidence" / "claims-run-partial.json").unlink()
        (self.job_dir / "outputs" / "final-run-partial.md").unlink()

        resumed = subprocess.run(
            [
                "python3",
                str(EXECUTE_WORKFLOW),
                "--job-path",
                str(self.job_dir),
                "--run-id",
                "run-partial",
                "--codex-bin",
                str(self.codex_bin),
                "--gemini-bin",
                str(self.gemini_bin),
                "--antigravity-bin",
                str(self.antigravity_bin),
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            input="yes\n",
        )
        self.assertEqual(resumed.returncode, 0, resumed.stderr)
        self.assertIn("codex: intake completed", resumed.stdout.lower())
        self.assertIn("gemini: research-b started", resumed.stdout.lower())
        self.assertIn("system: claim-extraction started", resumed.stdout.lower())

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
                "--gemini-bin",
                str(self.gemini_bin),
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

    def test_supports_switching_secondary_adapter_to_antigravity(self) -> None:
        self._write_fake_executor(self.antigravity_bin, "antigravity")
        result = subprocess.run(
            [
                "python3",
                str(EXECUTE_WORKFLOW),
                "--job-path",
                str(self.job_dir),
                "--run-id",
                "run-antigravity",
                "--codex-bin",
                str(self.codex_bin),
                "--gemini-bin",
                str(self.gemini_bin),
                "--antigravity-bin",
                str(self.antigravity_bin),
                "--secondary-adapter",
                "antigravity",
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("antigravity: research-b started", result.stdout.lower())
        self.assertNotIn("gemini: research-b started", result.stdout.lower())
        report = json.loads(
            qualification_report_path(self.job_dir / "runs" / "run-antigravity", "secondary", "antigravity").read_text(encoding="utf-8")
        )
        self.assertEqual(report["classification"], "structured_safe")

    def test_rejects_structured_stage_adapter_when_qualification_is_not_structured_safe(self) -> None:
        self._write_stdout_only_executor(self.antigravity_bin, "# markdown only qualification")
        result = subprocess.run(
            [
                "python3",
                str(EXECUTE_WORKFLOW),
                "--job-path",
                str(self.job_dir),
                "--run-id",
                "run-unqualified-secondary",
                "--codex-bin",
                str(self.codex_bin),
                "--gemini-bin",
                str(self.gemini_bin),
                "--antigravity-bin",
                str(self.antigravity_bin),
                "--secondary-adapter",
                "antigravity",
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not qualified for structured stage execution", result.stderr.lower())

    def test_rejects_stage_when_job_requires_realistic_provider_trust(self) -> None:
        self.gemini_bin.write_text(
            textwrap.dedent(
                """\
                #!/usr/bin/env python3
                import json
                import re
                import sys
                from pathlib import Path

                prompt = " ".join(sys.argv[1:])
                output_match = re.search(r"OUTPUT_PATH=(.+)", prompt)
                if not output_match:
                    print("missing output path", file=sys.stderr)
                    sys.exit(2)
                output_path = Path(output_match.group(1).strip())
                output_path.parent.mkdir(parents=True, exist_ok=True)

                if "ADAPTER_QUALIFICATION=1" in prompt and "QUALIFICATION_PROFILE=workflow-regression-realistic" in prompt:
                    print("realistic qualification failed", file=sys.stderr)
                    sys.exit(6)

                if "ADAPTER_QUALIFICATION=1" in prompt:
                    if output_path.suffix.lower() == ".json":
                        output_path.write_text(
                            json.dumps({"stage": "adapter-qualification", "status": "ok"}, indent=2),
                            encoding="utf-8",
                        )
                    else:
                        output_path.write_text("# Adapter qualification markdown\\n", encoding="utf-8")
                    sys.exit(0)

                print("unexpected non-qualification call", file=sys.stderr)
                sys.exit(9)
                """
            ),
            encoding="utf-8",
        )
        self.gemini_bin.chmod(0o755)
        (self.job_dir / "config.yaml").write_text(
            textwrap.dedent(
                """\
                topic: my-project-1
                requirements:
                  require_citations: true
                workflow:
                  execution:
                    required_provider_trust: structured_safe_realistic
                """
            ),
            encoding="utf-8",
        )
        result = subprocess.run(
            self._workflow_command("run-realistic-trust-required"),
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("structured_safe_realistic", result.stderr)
        self.assertIn("trust_level=unsupported", result.stderr)

    def test_uses_job_execution_provider_config_for_per_stage_routing(self) -> None:
        self._write_fake_executor(self.claude_bin, "claude")
        (self.job_dir / "config.yaml").write_text(
            textwrap.dedent(
                """\
                topic: my-project-1
                requirements:
                  require_citations: true
                workflow:
                  execution:
                    providers:
                      codex_primary:
                        adapter: codex
                      claude_research:
                        adapter: claude
                      gemini_judge:
                        adapter: gemini
                        model: gemini-3.1-pro-preview
                    stage_providers:
                      intake: codex_primary
                      research-a: codex_primary
                      research-b: claude_research
                      critique-a-on-b: codex_primary
                      critique-b-on-a: claude_research
                      judge: gemini_judge
                """
            ),
            encoding="utf-8",
        )
        result = subprocess.run(
            self._workflow_command("run-config-stage-routing"),
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("claude: research-b started", result.stdout.lower())
        self.assertIn("claude: critique-b-on-a started", result.stdout.lower())
        self.assertIn("gemini: judge started", result.stdout.lower())
        self.assertNotIn("gemini: research-b started", result.stdout.lower())
        research_b_log = (
            self.job_dir / "runs" / "run-config-stage-routing" / "logs" / "research-b.claude.driver.log"
        ).read_text(encoding="utf-8")
        judge_log = (
            self.job_dir / "runs" / "run-config-stage-routing" / "logs" / "judge.gemini.driver.log"
        ).read_text(encoding="utf-8")
        self.assertIn("SOURCE_PASS_COMMAND:\n" + str(self.claude_bin), research_b_log)
        self.assertIn("CLAIM_PASS_COMMAND:\n" + str(self.claude_bin), research_b_log)
        self.assertIn("--model gemini-3.1-pro-preview", judge_log)

    def test_rejects_model_override_for_adapter_without_model_support(self) -> None:
        (self.job_dir / "config.yaml").write_text(
            textwrap.dedent(
                """\
                topic: my-project-1
                requirements:
                  require_citations: true
                workflow:
                  execution:
                    providers:
                      codex_primary:
                        adapter: codex
                        model: gpt-5
                    stage_providers:
                      intake: codex_primary
                      research-a: codex_primary
                      research-b: codex_primary
                      critique-a-on-b: codex_primary
                      critique-b-on-a: codex_primary
                      judge: codex_primary
                """
            ),
            encoding="utf-8",
        )
        result = subprocess.run(
            self._workflow_command("run-invalid-model-config"),
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("does not support explicit model selection", result.stderr.lower())

    def test_marks_stage_failed_and_logs_output_status_when_adapter_leaves_placeholder(self) -> None:
        self._write_noop_executor(self.antigravity_bin, "warning: accepted command but did not write output")
        result = subprocess.run(
            [
                "python3",
                str(EXECUTE_WORKFLOW),
                "--job-path",
                str(self.job_dir),
                "--run-id",
                "run-noop-antigravity",
                "--codex-bin",
                str(self.codex_bin),
                "--gemini-bin",
                str(self.gemini_bin),
                "--antigravity-bin",
                str(self.antigravity_bin),
                "--secondary-adapter",
                "antigravity",
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("did not produce a completed output artifact", result.stderr.lower())

        run_dir = self.job_dir / "runs" / "run-noop-antigravity"
        state = json.loads((run_dir / "workflow-state.json").read_text(encoding="utf-8"))
        statuses = {stage["id"]: stage["status"] for stage in state["stages"]}
        self.assertEqual(statuses["research-b"], "failed")

        driver_log = (run_dir / "logs" / "research-b.antigravity.driver.log").read_text(encoding="utf-8")
        self.assertIn("RETURN_CODE:\n0", driver_log)
        self.assertIn("OUTPUT_EXISTS:\nTrue", driver_log)
        self.assertIn("OUTPUT_COMPLETE:\nFalse", driver_log)
        self.assertIn("Status: not started", driver_log)

    def test_fails_when_intake_output_breaks_contract(self) -> None:
        self.codex_bin.write_text(
            textwrap.dedent(
                """\
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

                if "ADAPTER_QUALIFICATION=1" in prompt:
                    output_path.write_text(
                        json.dumps({"stage": "adapter-qualification", "status": "ok"}, indent=2),
                        encoding="utf-8",
                    )
                    sys.exit(0)

                if stage == "intake":
                    output_path.write_text(json.dumps({"question": "", "scope": "invalid"}, indent=2), encoding="utf-8")
                    sys.exit(0)

                print("unexpected stage", file=sys.stderr)
                sys.exit(2)
                """
            ).lstrip(),
            encoding="utf-8",
        )
        self.codex_bin.chmod(0o755)

        result = subprocess.run(
            [
                "python3",
                str(EXECUTE_WORKFLOW),
                "--job-path",
                str(self.job_dir),
                "--run-id",
                "run-bad-intake",
                "--codex-bin",
                str(self.codex_bin),
                "--gemini-bin",
                str(self.gemini_bin),
                "--antigravity-bin",
                str(self.antigravity_bin),
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("validation", result.stderr.lower())
        state = json.loads((self.job_dir / "runs" / "run-bad-intake" / "workflow-state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["status"], "failed")

    def test_structured_stage_rejects_stdout_json_recovery_when_file_is_not_written(self) -> None:
        self._write_research_b_stdout_executor(
            self.gemini_bin,
            "\n".join(
                [
                    "I will first inspect the prompt packet.",
                    "# Executive Summary",
                    "",
                    "- Research B summary. [SRC-002]",
                    "",
                    "# Facts",
                    "",
                    "1. Option B has evidence behind it. [SRC-002]",
                    "",
                    "# Inferences",
                    "",
                    "1. Option B may be viable. [SRC-002] Confidence: medium",
                    "",
                    "# Uncertainty Register",
                    "",
                    "- Coverage is incomplete. [SRC-003]",
                    "",
                    "# Evidence Gaps",
                    "",
                    "- Benchmarking is incomplete. [SRC-004]",
                    "",
                    "# Preliminary Disagreements",
                    "",
                    "- The other option may be stronger on another axis. [SRC-005]",
                    "",
                    "# Source Evaluation",
                    "",
                    "- Sources are limited but relevant. [SRC-006]",
                ]
            ),
            json_payload="""{
  "stage": "research-b",
  "summary": [{"text": "Research B summary.", "evidence_sources": ["SRC-002"]}],
  "facts": [{"id": "F-001", "text": "Option B has evidence behind it.", "evidence_sources": ["SRC-002"]}],
  "inferences": [{"id": "I-001", "text": "Option B may be viable.", "evidence_sources": ["SRC-002"], "confidence": "medium"}],
  "uncertainties": [{"text": "Coverage is incomplete.", "evidence_sources": ["SRC-003"]}],
  "evidence_gaps": [{"text": "Benchmarking is incomplete.", "evidence_sources": ["SRC-004"]}],
  "preliminary_disagreements": [{"text": "The other option may be stronger on another axis.", "evidence_sources": ["SRC-005"]}],
  "source_evaluation": [{"notes": "Sources are limited but relevant.", "source_id": "SRC-006"}],
  "sources": [
    {"id": "SRC-002", "title": "Canonical source SRC-002", "type": "report", "authority": "test fixture", "locator": "https://example.com/src-002"},
    {"id": "SRC-003", "title": "Canonical source SRC-003", "type": "report", "authority": "test fixture", "locator": "https://example.com/src-003"},
    {"id": "SRC-004", "title": "Canonical source SRC-004", "type": "report", "authority": "test fixture", "locator": "https://example.com/src-004"},
    {"id": "SRC-005", "title": "Canonical source SRC-005", "type": "report", "authority": "test fixture", "locator": "https://example.com/src-005"},
    {"id": "SRC-006", "title": "Canonical source SRC-006", "type": "report", "authority": "test fixture", "locator": "https://example.com/src-006"}
  ]
}""",
        )

        result = subprocess.run(
            [
                "python3",
                str(EXECUTE_WORKFLOW),
                "--job-path",
                str(self.job_dir),
                "--run-id",
                "run-stdout-gemini",
                "--codex-bin",
                str(self.codex_bin),
                "--gemini-bin",
                str(self.gemini_bin),
                "--antigravity-bin",
                str(self.antigravity_bin),
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("completed structured output artifact", result.stderr.lower())
        state = json.loads((self.job_dir / "runs" / "run-stdout-gemini" / "workflow-state.json").read_text(encoding="utf-8"))
        statuses = {stage["id"]: stage["status"] for stage in state["stages"]}
        self.assertEqual(statuses["research-b"], "failed")
        self.assertEqual(state["status"], "failed")
        driver_log = (self.job_dir / "runs" / "run-stdout-gemini" / "logs" / "research-b.gemini.driver.log").read_text(encoding="utf-8")
        self.assertNotIn("OUTPUT_RECOVERED_FROM_STDOUT", driver_log)

    def test_structured_stage_fails_when_adapter_only_returns_markdown_without_json_artifact(self) -> None:
        self._write_research_b_stdout_executor(
            self.gemini_bin,
            "\n".join(
                [
                    "I will first inspect the prompt packet.",
                    "# Executive Summary",
                    "",
                    "- Research B summary. [SRC-002]",
                    "",
                    "# Facts",
                    "",
                    "1. Option B has evidence behind it. [SRC-002]",
                    "",
                    "# Inferences",
                    "",
                    "1. Option B may be viable. [SRC-002] Confidence: medium",
                    "",
                    "# Uncertainty Register",
                    "",
                    "- Coverage is incomplete. [SRC-003]",
                    "",
                    "# Evidence Gaps",
                    "",
                    "- Benchmarking is incomplete. [SRC-004]",
                    "",
                    "# Preliminary Disagreements",
                    "",
                    "- The other option may be stronger on another axis. [SRC-005]",
                    "",
                    "# Source Evaluation",
                    "",
                    "- Sources are limited but relevant. [SRC-006]",
                ]
            ),
        )

        result = subprocess.run(
            [
                "python3",
                str(EXECUTE_WORKFLOW),
                "--job-path",
                str(self.job_dir),
                "--run-id",
                "run-missing-structured-json",
                "--codex-bin",
                str(self.codex_bin),
                "--gemini-bin",
                str(self.gemini_bin),
                "--antigravity-bin",
                str(self.antigravity_bin),
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("completed structured output artifact", result.stderr.lower())
        driver_log = (self.job_dir / "runs" / "run-missing-structured-json" / "logs" / "research-b.gemini.driver.log").read_text(encoding="utf-8")
        self.assertIn("REPAIR_ATTEMPTED:\nFalse", driver_log)
        state = json.loads((self.job_dir / "runs" / "run-missing-structured-json" / "workflow-state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["status"], "failed")

    def test_markdown_materialization_requires_exact_stdout_or_written_file(self) -> None:
        self.claude_bin.write_text(
            textwrap.dedent(
                """\
                #!/usr/bin/env python3
                print("returned markdown to stdout only")
                """
            ),
            encoding="utf-8",
        )
        self.claude_bin.chmod(0o755)
        executor = build_adapter_executor("claude", self.claude_bin, "markdown")
        output_path = self.root / "artifact.md"

        result = executor(
            [str(self.claude_bin), "-p", "prompt text"],
            job_dir=self.job_dir,
            output_path=output_path,
            stage_id="manual-markdown",
        )

        self.assertEqual(result.returncode, 0)
        self.assertTrue(output_path.is_file())
        self.assertEqual(output_path.read_text(encoding="utf-8"), "returned markdown to stdout only\n")

    def test_fails_fast_when_research_sidecar_contains_uncited_inference(self) -> None:
        self.gemini_bin.write_text(
            textwrap.dedent(
                """\
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
                if json_path is not None:
                    json_path.parent.mkdir(parents=True, exist_ok=True)
                stage = stage_match.group(1)
                substep = substep_match.group(1) if substep_match else "single-pass"

                if "ADAPTER_QUALIFICATION=1" in prompt:
                    if output_path.suffix.lower() == ".json":
                        output_path.write_text(
                            json.dumps({"stage": "adapter-qualification", "status": "ok"}, indent=2),
                            encoding="utf-8",
                        )
                    else:
                        output_path.write_text("# Adapter qualification markdown\\n", encoding="utf-8")
                    sys.exit(0)

                if stage == "research-b" and substep == "source-pass":
                    json_path.write_text(
                        json.dumps(
                            {
                                "stage": "research-b",
                                "sources": [
                                    {"id": "SRC-002", "title": "Canonical source SRC-002", "type": "report", "authority": "test fixture", "locator": "https://example.com/src-002"},
                                    {"id": "SRC-003", "title": "Canonical source SRC-003", "type": "report", "authority": "test fixture", "locator": "https://example.com/src-003"},
                                    {"id": "SRC-004", "title": "Canonical source SRC-004", "type": "report", "authority": "test fixture", "locator": "https://example.com/src-004"},
                                    {"id": "SRC-005", "title": "Canonical source SRC-005", "type": "report", "authority": "test fixture", "locator": "https://example.com/src-005"},
                                    {"id": "SRC-006", "title": "Canonical source SRC-006", "type": "report", "authority": "test fixture", "locator": "https://example.com/src-006"}
                                ]
                            },
                            indent=2,
                        ),
                        encoding="utf-8",
                    )
                    sys.exit(0)

                if stage == "research-b" and substep == "claim-pass":
                    json_path.write_text(
                        json.dumps(
                            {
                                "stage": "research-b",
                                "summary": [{"text": "Research B summary.", "evidence_sources": ["SRC-002"]}],
                                "facts": [{"id": "F-001", "text": "Option B has evidence behind it.", "evidence_sources": ["SRC-002"]}],
                                "inferences": [{"id": "I-001", "text": "Option B may be viable.", "evidence_sources": [], "confidence": "medium"}],
                                "uncertainties": [{"text": "Coverage is incomplete.", "evidence_sources": ["SRC-003"]}],
                                "evidence_gaps": [{"text": "Benchmarking is incomplete.", "evidence_sources": ["SRC-004"]}],
                                "preliminary_disagreements": [{"text": "The other option may be stronger on another axis.", "evidence_sources": ["SRC-005"]}],
                                "source_evaluation": [{"notes": "Sources are limited but relevant.", "source_id": "SRC-006"}],
                            },
                            indent=2,
                        ),
                        encoding="utf-8",
                    )
                    sys.exit(0)

                print("unexpected stage", file=sys.stderr)
                sys.exit(2)
                """
            ).lstrip(),
            encoding="utf-8",
        )
        self.gemini_bin.chmod(0o755)

        result = subprocess.run(
            [
                "python3",
                str(EXECUTE_WORKFLOW),
                "--job-path",
                str(self.job_dir),
                "--run-id",
                "run-uncited-inference",
                "--codex-bin",
                str(self.codex_bin),
                "--gemini-bin",
                str(self.gemini_bin),
                "--antigravity-bin",
                str(self.antigravity_bin),
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("uncited inference", result.stderr.lower())
        run_dir = self.job_dir / "runs" / "run-uncited-inference"
        state = json.loads((run_dir / "workflow-state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["stages"][2]["status"], "failed")
        self.assertEqual(state["post_processing"]["stage_claims"]["research-b"]["status"], "failed")
        self.assertNotEqual(state["stages"][1]["status"], "running")
        self.assertEqual(state["status"], "failed")

    def test_failed_structured_substep_does_not_overwrite_final_markdown_artifact(self) -> None:
        self._write_noop_executor(self.antigravity_bin, "warning: accepted command but did not write output")

        result = subprocess.run(
            [
                "python3",
                str(EXECUTE_WORKFLOW),
                "--job-path",
                str(self.job_dir),
                "--run-id",
                "run-scratch-markdown",
                "--codex-bin",
                str(self.codex_bin),
                "--gemini-bin",
                str(self.gemini_bin),
                "--antigravity-bin",
                str(self.antigravity_bin),
                "--secondary-adapter",
                "antigravity",
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )

        self.assertNotEqual(result.returncode, 0)
        final_markdown = (self.job_dir / "runs" / "run-scratch-markdown" / "stage-outputs" / "03-research-b.md").read_text(encoding="utf-8")
        self.assertIn("Stage Output Placeholder: research-b", final_markdown)

    def test_resumes_structured_stage_from_claim_pass_when_source_pass_is_already_valid(self) -> None:
        self._write_counting_resume_executor(self.codex_bin)
        self._write_counting_resume_executor(self.gemini_bin)
        count_path = self.root / "substep-counts.json"

        first = subprocess.run(
            self._workflow_command("run-substep-resume"),
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(first.returncode, 0, first.stderr)

        run_dir = self.job_dir / "runs" / "run-substep-resume"
        (run_dir / "stage-outputs" / "03-research-b.md").unlink()
        (run_dir / "stage-outputs" / "03-research-b.json").unlink()
        (run_dir / "audit" / "substeps" / "research-b.claim-pass.json").unlink()
        (self.job_dir / "evidence" / "claims-run-substep-resume.json").unlink()
        (self.job_dir / "outputs" / "final-run-substep-resume.md").unlink()

        before_counts = json.loads(count_path.read_text(encoding="utf-8"))
        resumed = subprocess.run(
            self._workflow_command("run-substep-resume"),
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            input="yes\n",
        )
        self.assertEqual(resumed.returncode, 0, resumed.stderr)

        after_counts = json.loads(count_path.read_text(encoding="utf-8"))
        self.assertEqual(
            after_counts.get("research-b:source-pass", 0),
            before_counts.get("research-b:source-pass", 0),
        )
        self.assertGreater(
            after_counts.get("research-b:claim-pass", 0),
            before_counts.get("research-b:claim-pass", 0),
        )
        self.assertTrue((run_dir / "stage-outputs" / "03-research-b.md").is_file())
        self.assertTrue((run_dir / "stage-outputs" / "03-research-b.json").is_file())

    def test_rewrites_structured_stage_markdown_from_valid_json_when_markdown_citations_are_missing(self) -> None:
        self.gemini_bin.write_text(
            textwrap.dedent(
                """\
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
                if json_path is not None:
                    json_path.parent.mkdir(parents=True, exist_ok=True)
                stage = stage_match.group(1)
                substep = substep_match.group(1) if substep_match else "single-pass"

                if "ADAPTER_QUALIFICATION=1" in prompt:
                    if output_path.suffix.lower() == ".json":
                        output_path.write_text(
                            json.dumps({"stage": "adapter-qualification", "status": "ok"}, indent=2),
                            encoding="utf-8",
                        )
                    else:
                        output_path.write_text("# Adapter qualification markdown\\n", encoding="utf-8")
                    sys.exit(0)

                if stage == "research-b" and substep == "source-pass":
                    json_path.write_text(
                        json.dumps(
                            {
                                "stage": "research-b",
                                "sources": [
                                    {
                                        "id": "SRC-200",
                                        "title": "Canonical stage source",
                                        "type": "report",
                                        "authority": "fixture",
                                        "locator": "https://example.com/src-200",
                                    }
                                ],
                            },
                            indent=2,
                        ),
                        encoding="utf-8",
                    )
                    sys.exit(0)

                if stage == "research-b" and substep == "claim-pass":
                    output_path.write_text(
                        "# Executive Summary\\n\\nResearch B summary.\\n\\n"
                        "# Facts\\n\\n1. Fact. [SRC-200]\\n\\n"
                        "# Inferences\\n\\n1. Inference without markdown citation. Confidence: high\\n\\n"
                        "# Uncertainty Register\\n\\n- Gap.\\n\\n"
                        "# Evidence Gaps\\n\\n- More data.\\n\\n"
                        "# Preliminary Disagreements\\n\\n- Trade-off remains.\\n\\n"
                        "# Source Evaluation\\n\\n- Source quality note.\\n",
                        encoding="utf-8",
                    )
                    json_path.write_text(
                        json.dumps(
                            {
                                "stage": "research-b",
                                "summary": "Research B summary.",
                                "facts": [{"id": "F-200", "text": "Fact.", "evidence_sources": ["SRC-200"]}],
                                "inferences": [{"id": "I-200", "text": "Inference from valid JSON.", "evidence_sources": ["SRC-200"], "confidence": "high"}],
                                "uncertainties": ["Gap."],
                                "evidence_gaps": ["More data."],
                                "preliminary_disagreements": ["Trade-off remains."],
                                "source_evaluation": ["Source quality note."],
                            },
                            indent=2,
                        ),
                        encoding="utf-8",
                    )
                    sys.exit(0)

                if stage == "critique-b-on-a" and substep == "source-pass":
                    json_path.write_text(
                        json.dumps(
                            {
                                "stage": "critique-b-on-a",
                                "sources": [
                                    {"id": "SRC-210", "title": "Canonical source SRC-210", "type": "report", "authority": "fixture", "locator": "https://example.com/src-210"},
                                    {"id": "SRC-211", "title": "Canonical source SRC-211", "type": "report", "authority": "fixture", "locator": "https://example.com/src-211"},
                                    {"id": "SRC-212", "title": "Canonical source SRC-212", "type": "report", "authority": "fixture", "locator": "https://example.com/src-212"},
                                    {"id": "SRC-213", "title": "Canonical source SRC-213", "type": "report", "authority": "fixture", "locator": "https://example.com/src-213"},
                                    {"id": "SRC-214", "title": "Canonical source SRC-214", "type": "report", "authority": "fixture", "locator": "https://example.com/src-214"},
                                    {"id": "SRC-215", "title": "Canonical source SRC-215", "type": "report", "authority": "fixture", "locator": "https://example.com/src-215"},
                                ],
                            },
                            indent=2,
                        ),
                        encoding="utf-8",
                    )
                    sys.exit(0)

                if stage == "critique-b-on-a" and substep == "claim-pass":
                    json_path.write_text(
                        json.dumps(
                            {
                                "stage": "critique-b-on-a",
                                "supported_claims": [{"text": "One claim survives review.", "evidence_sources": ["SRC-210"]}],
                                "unsupported_claims": [
                                    {
                                        "target_claim": "Some claims need stronger support.",
                                        "reason": "Support is incomplete.",
                                        "needed_evidence": "Direct benchmark evidence.",
                                        "evidence_sources": ["SRC-211"],
                                    }
                                ],
                                "weak_source_issues": [{"text": "One citation is indirect.", "evidence_sources": ["SRC-212"]}],
                                "omissions": [{"text": "Missing alternative analysis.", "evidence_sources": ["SRC-213"]}],
                                "overreach": [{"text": "One conclusion is too strong.", "evidence_sources": ["SRC-214"]}],
                                "unresolved_disagreements": [{"text": "Option A vs B remains disputed.", "evidence_sources": ["SRC-215"]}],
                                "summary": {"text": "Reliability is mixed.", "confidence": "medium"},
                            },
                            indent=2,
                        ),
                        encoding="utf-8",
                    )
                    sys.exit(0)

                if stage == "judge" and substep == "source-pass":
                    json_path.write_text(
                        json.dumps(
                            {
                                "stage": "judge",
                                "sources": [
                                    {
                                        "id": "SRC-200",
                                        "title": "Canonical stage source",
                                        "type": "report",
                                        "authority": "fixture",
                                        "locator": "https://example.com/src-200",
                                    }
                                ],
                            },
                            indent=2,
                        ),
                        encoding="utf-8",
                    )
                    sys.exit(0)

                if stage == "judge" and substep == "claim-pass":
                    json_path.write_text(
                        json.dumps(
                            {
                                "stage": "judge",
                                "supported_conclusions": [
                                    {"id": "C-200", "text": "Option A has lower implementation risk.", "evidence_sources": ["SRC-200"]}
                                ],
                                "synthesis_judgments": [
                                    {"id": "J-200", "text": "Option A is the safer near-term choice.", "evidence_sources": ["SRC-200"], "confidence": "medium"}
                                ],
                                "unresolved_disagreements": ["Trade-off remains unresolved."],
                                "confidence_assessment": ["Medium confidence because evidence is incomplete."],
                                "evidence_gaps": ["Comparative benchmark is still missing."],
                                "rationale": ["Research B preserved the strongest cited inference."],
                                "recommended_artifact_structure": ["Summary, evidence, recommendation, uncertainty, references."],
                            },
                            indent=2,
                        ),
                        encoding="utf-8",
                    )
                    sys.exit(0)

                print("fallback", file=sys.stderr)
                sys.exit(0)
                """
            ),
            encoding="utf-8",
        )
        self.gemini_bin.chmod(0o755)

        result = subprocess.run(
            [
                "python3",
                str(EXECUTE_WORKFLOW),
                "--job-path",
                str(self.job_dir),
                "--run-id",
                "run-markdown-rewrite",
                "--codex-bin",
                str(self.codex_bin),
                "--gemini-bin",
                str(self.gemini_bin),
                "--antigravity-bin",
                str(self.antigravity_bin),
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        rewritten_markdown = (self.job_dir / "runs" / "run-markdown-rewrite" / "stage-outputs" / "03-research-b.md").read_text(encoding="utf-8")
        self.assertIn("[SRC-200]", rewritten_markdown)
        self.assertIn("Confidence: high", rewritten_markdown)

    def test_repairs_structured_stage_once_after_validation_failure(self) -> None:
        self._write_repairing_executor(self.gemini_bin, "gemini")

        result = subprocess.run(
            [
                "python3",
                str(EXECUTE_WORKFLOW),
                "--job-path",
                str(self.job_dir),
                "--run-id",
                "run-repair-once",
                "--codex-bin",
                str(self.codex_bin),
                "--gemini-bin",
                str(self.gemini_bin),
                "--antigravity-bin",
                str(self.antigravity_bin),
                "--claude-bin",
                str(self.claude_bin),
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        driver_log = (self.job_dir / "runs" / "run-repair-once" / "logs" / "research-b.gemini.driver.log").read_text(encoding="utf-8")
        self.assertIn("REPAIR_ATTEMPTED:\nTrue", driver_log)
        self.assertIn("REPAIR_RETURN_CODE:\n0", driver_log)
        repaired_json = json.loads((self.job_dir / "runs" / "run-repair-once" / "stage-outputs" / "03-research-b.json").read_text(encoding="utf-8"))
        self.assertEqual(repaired_json["inferences"][0]["support_links"][0]["role"], "evidence")

    def test_fails_after_single_repair_attempt_when_structured_stage_remains_invalid(self) -> None:
        self._write_repairing_executor(self.gemini_bin, "gemini", repair_succeeds=False)

        result = subprocess.run(
            [
                "python3",
                str(EXECUTE_WORKFLOW),
                "--job-path",
                str(self.job_dir),
                "--run-id",
                "run-repair-fails",
                "--codex-bin",
                str(self.codex_bin),
                "--gemini-bin",
                str(self.gemini_bin),
                "--antigravity-bin",
                str(self.antigravity_bin),
                "--claude-bin",
                str(self.claude_bin),
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("failed structured validation", result.stderr.lower())

    def test_structured_stage_repair_missing_claim_artifact_fails_hard(self) -> None:
        run_dir = self.job_dir / "runs" / "run-repair-missing-claim"
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "logs").mkdir(parents=True, exist_ok=True)
        (run_dir / "stage-outputs").mkdir(parents=True, exist_ok=True)
        state_path = run_dir / "workflow-state.json"
        state = {
            "run_dir": str(run_dir),
            "status": "running",
            "stages": [{"id": "research-a", "status": "running", "substeps": {}}],
            "post_processing": {
                "stage_claims": {"research-a": {"status": "pending", "output_path": str(run_dir / "stage-claims" / "02-research-a.claims.json")}},
                "claim_extraction": {"status": "pending", "output_path": str(self.job_dir / "evidence" / "claims-run-x.json")},
                "final_artifact": {"status": "pending", "output_path": str(self.job_dir / "outputs" / "final-run-x.md")},
            },
        }
        reporter = ProgressReporter(io.StringIO())
        state_lock = threading.RLock()
        stage = StageExecution("research-a", "primary", "02-research-a.md", "02-research-a.md")
        source_output_path = run_dir / "audit" / "substeps" / "research-a.source-pass.json"
        claim_output_path = run_dir / "audit" / "substeps" / "research-a.claim-pass.json"

        def fake_execute_json_substep(**kwargs: object) -> tuple[CommandResult, dict[str, object], bool, CommandResult | None, list[str]]:
            substep = kwargs["substep"]
            output_json_path = kwargs["output_json_path"]
            if substep == "source-pass":
                payload = {
                    "stage": "research-a",
                    "sources": [
                        {
                            "id": "SRC-200",
                            "title": "Test Source",
                            "type": "webpage",
                            "authority": "example",
                            "locator": "https://example.com/source",
                            "source_class": "external_evidence",
                        }
                    ],
                }
            else:
                payload = {
                    "stage": "research-a",
                    "facts": [],
                    "inferences": [
                        {
                            "id": "I-001",
                            "text": "Inference text",
                            "kind": "inference",
                            "support_links": [{"role": "evidence", "source_id": "SRC-200"}],
                        }
                    ],
                }
            output_json_path.parent.mkdir(parents=True, exist_ok=True)
            output_json_path.write_text(json.dumps(payload), encoding="utf-8")
            return CommandResult(0, "", ""), payload, False, None, []

        def fake_repair(*_args: object, **_kwargs: object) -> CommandResult:
            if claim_output_path.exists():
                claim_output_path.unlink()
            return CommandResult(0, "", "")

        failing_validation = SimpleNamespace(
            structured_errors=["repair me"],
            structured_warnings=[],
            markdown_errors=[],
            normalized_payload={"stage": "research-a", "sources": [], "facts": [], "inferences": []},
            canonical_markdown="# Research A\n",
        )

        with (
            patch("execute_workflow.execute_json_substep", side_effect=fake_execute_json_substep),
            patch("execute_workflow.execute_adapter_command", side_effect=fake_repair),
            patch("execute_workflow.validate_structured_stage_artifact", return_value=failing_validation),
            patch("execute_workflow.render_stage_markdown_from_json", return_value="# Research A\n"),
            patch("execute_workflow.record_provider_repair_attempt", return_value=None),
            patch("execute_workflow.dependency_structured_payloads", return_value={}),
        ):
            with self.assertRaisesRegex(RuntimeError, "did not produce a completed structured output artifact"):
                run_structured_stage(
                    stage,
                    run_dir,
                    self.job_dir,
                    state,
                    state_path,
                    state_lock,
                    StageAdapterSelection(adapter_name="codex"),
                    build_adapter_executor.__globals__["CLI_ADAPTERS"]["codex"],
                    str(self.codex_bin),
                    reporter,
                    None,
                )

    def test_cancels_parallel_sibling_stage_after_first_fatal_failure(self) -> None:
        self.gemini_bin = self.bin_dir / "gemini-cancel"
        self._write_sleeping_executor(self.gemini_bin, "gemini")
        self._write_research_a_failure_executor(self.codex_bin)

        result = subprocess.run(
            [
                "python3",
                str(EXECUTE_WORKFLOW),
                "--job-path",
                str(self.job_dir),
                "--run-id",
                "run-cancel-sibling",
                "--codex-bin",
                str(self.codex_bin),
                "--gemini-bin",
                str(self.gemini_bin),
                "--antigravity-bin",
                str(self.antigravity_bin),
                "--claude-bin",
                str(self.claude_bin),
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )

        self.assertNotEqual(result.returncode, 0)
        run_dir = self.job_dir / "runs" / "run-cancel-sibling"
        state = json.loads((run_dir / "workflow-state.json").read_text(encoding="utf-8"))
        statuses = {stage["id"]: stage["status"] for stage in state["stages"]}
        self.assertEqual(statuses["research-a"], "failed")
        self.assertEqual(statuses["research-b"], "cancelled")
        driver_log = (run_dir / "logs" / "research-b.gemini.driver.log").read_text(encoding="utf-8")
        self.assertIn("cancelled_due_to_parallel_stage_failure", driver_log)

    def test_rejects_unknown_adapter_name(self) -> None:
        result = subprocess.run(
            [
                "python3",
                str(EXECUTE_WORKFLOW),
                "--job-path",
                str(self.job_dir),
                "--run-id",
                "run-invalid-adapter",
                "--secondary-adapter",
                "unknown-cli",
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unknown adapter", result.stderr.lower())

    def test_progress_reporter_colors_only_status_indicator_on_tty(self) -> None:
        stream = FakeTTYStream()
        reporter = ProgressReporter(stream)

        reporter.start("codex", "intake")
        reporter.complete("codex", "intake")
        reporter.fail("gemini", "judge")

        rendered = stream.rendered()
        self.assertIn("codex: intake \x1b[32mcompleted\x1b[0m", rendered)
        self.assertIn("gemini: judge \x1b[31mfailed\x1b[0m", rendered)
        self.assertNotIn("\x1b[32mcodex", rendered)
        self.assertNotIn("\x1b[31mgemini", rendered)

    def test_progress_reporter_does_not_duplicate_completed_stage_on_tty(self) -> None:
        stream = FakeTTYStream()
        reporter = ProgressReporter(stream)

        reporter.start("codex", "research-a")
        reporter.complete("codex", "research-a")

        lines = [line for line in stream.rendered().splitlines() if "research-a" in line]
        completed_lines = [line for line in lines if "completed" in line]
        self.assertEqual(len(completed_lines), 1, completed_lines)

    def test_stage_markdown_validator_allows_summary_citations_at_end_of_paragraph(self) -> None:
        markdown = "\n".join(
            [
                "# Executive Summary",
                "",
                "Fully on-device processing appears feasible. The evidence supports a hybrid upgrade. [DOC-001] [SRC-002]",
                "",
                "# Facts",
                "",
                "1. The current system uses an FPGA and an external laptop. [DOC-001]",
                "",
                "# Inferences",
                "",
                "1. The strongest near-term architecture is hybrid. That preserves the current radar knowledge while removing the laptop. [DOC-001] [SRC-002] Confidence: high",
                "",
                "# Uncertainty Register",
                "",
                "- Data format remains unclear.",
                "",
                "# Evidence Gaps",
                "",
                "- Missing current model details.",
                "",
                "# Preliminary Disagreements",
                "",
                "- Hybrid versus end-to-end remains disputed. [SRC-002]",
                "",
                "# Source Evaluation",
                "",
                "- [DOC-001] Internal project packet.",
            ]
        )

        errors = validate_stage_markdown_contract("research-a", markdown)
        self.assertEqual(errors, [], errors)

    def test_stage_markdown_validator_allows_unindented_numbered_item_continuations(self) -> None:
        markdown = "\n".join(
            [
                "# Executive Summary",
                "",
                "Summary text. [DOC-001]",
                "",
                "# Facts",
                "",
                "1. Fact line one.",
                "Continuation line with citation at the end. [DOC-001]",
                "",
                "# Inferences",
                "",
                "1. Inference first sentence.",
                "Continuation line with supporting citation and confidence. [SRC-001] Confidence: medium",
                "",
                "# Uncertainty Register",
                "",
                "- Gap remains.",
                "",
                "# Evidence Gaps",
                "",
                "- More data needed.",
                "",
                "# Preliminary Disagreements",
                "",
                "- One disagreement exists. [SRC-002]",
                "",
                "# Source Evaluation",
                "",
                "- [DOC-001] Packet source.",
            ]
        )

        errors = validate_stage_markdown_contract("research-a", markdown)
        self.assertEqual(errors, [], errors)

if __name__ == "__main__":
    unittest.main()

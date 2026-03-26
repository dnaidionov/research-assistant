import json
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
EXECUTE_WORKFLOW = REPO_ROOT / "scripts" / "execute_workflow.py"
import sys

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from execute_workflow import (
    ProgressReporter,
    extract_markdown_artifact,
    extract_structured_json_artifact,
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
        self.gemini_bin = self.bin_dir / "gemini"
        self.antigravity_bin = self.bin_dir / "antigravity"
        self._write_fake_executor(self.codex_bin, "codex")
        self._write_fake_executor(self.gemini_bin, "gemini")
        self._write_failing_executor(self.antigravity_bin, "antigravity should not be called by default")
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
                json_match = re.search(r"OUTPUT_JSON_PATH=(.+)", prompt)
                source_match = re.search(r"SOURCE_REGISTRY_PATH=(.+)", prompt)
                stage_match = re.search(r"STAGE_ID=([a-z0-9-]+)", prompt)
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
                    source_id = f"SRC-00{{1 if option == 'A' else 2}}"
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
                                "sources": [{{"id": source_id, "title": f"Canonical source {{source_id}}", "type": "report", "authority": "test fixture", "locator": f"https://example.com/{{source_id.lower()}}"}}],
                            }}, indent=2),
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
                elif stage == "judge":
                    output_path.write_text(
                        "# Supported Conclusions\\n\\n1. Option A has lower implementation risk. [SRC-001]\\n\\n"
                        "# Inferences And Synthesis Judgments\\n\\n1. Inference: Option A is the safer near-term choice. [SRC-001, SRC-002] Confidence: medium\\n\\n"
                        "# Unresolved Disagreements\\n\\n1. Hardware Selection (NVIDIA vs. Xilinx/TI): Trade-off remains unresolved because interface data is missing. [SRC-003]\\n\\n"
                        "# Confidence Assessment\\n\\n- Medium confidence: evidence is incomplete and benchmark coverage is limited. [SRC-004]\\n\\n"
                        "# Evidence Gaps\\n\\n- No direct benchmark compares both options in this environment. [SRC-005]\\n\\n"
                        "# Rationale And Traceability\\n\\n- Research A favored Option A and critique B-on-A preserved upside concerns.\\n\\n"
                        "# Recommended Final Artifact Structure\\n\\n- Summary, comparison, recommendation, uncertainty, references, open questions.\\n",
                        encoding="utf-8",
                    )
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
                                "sources": [
                                    {{"id": "SRC-001", "title": "Canonical source SRC-001", "type": "report", "authority": "test fixture", "locator": "https://example.com/src-001"}},
                                    {{"id": "SRC-002", "title": "Canonical source SRC-002", "type": "report", "authority": "test fixture", "locator": "https://example.com/src-002"}},
                                    {{"id": "SRC-004", "title": "Canonical source SRC-004", "type": "report", "authority": "test fixture", "locator": "https://example.com/src-004"}}
                                ]
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
                import sys
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
                import sys
                print({message!r}, file=sys.stderr)
                sys.exit(0)
                """
            ),
            encoding="utf-8",
        )
        path.chmod(0o755)

    def _write_stdout_only_executor(self, path: Path, markdown: str, json_payload: str | None = None) -> None:
        stdout = markdown if json_payload is None else f"{markdown}\n\n```json\n{json_payload}\n```"
        path.write_text(
            textwrap.dedent(
                f"""\
                #!/usr/bin/env python3
                import sys
                print({stdout!r})
                sys.exit(0)
                """
            ),
            encoding="utf-8",
        )
        path.chmod(0o755)

    def _write_research_b_stdout_executor(self, path: Path, markdown: str, json_payload: str | None = None) -> None:
        stdout = markdown if json_payload is None else f"{markdown}\n\n```json\n{json_payload}\n```"
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
                if not output_match or not stage_match:
                    print("missing stage metadata", file=sys.stderr)
                    sys.exit(2)

                output_path = Path(output_match.group(1).strip())
                json_path = Path(json_match.group(1).strip()) if json_match else None
                output_path.parent.mkdir(parents=True, exist_ok=True)
                if json_path is not None:
                    json_path.parent.mkdir(parents=True, exist_ok=True)
                stage = stage_match.group(1)

                if stage == "research-b":
                    print({stdout!r})
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
                                "summary": {{"text": "Reliability is mixed.", "confidence": "medium"}},
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

                if stage == "judge":
                    output_path.write_text(
                        "# Supported Conclusions\\n\\n1. Option A has lower implementation risk. [SRC-001]\\n\\n"
                        "# Inferences And Synthesis Judgments\\n\\n1. Inference: Option A is the safer near-term choice. [SRC-001, SRC-002] Confidence: medium\\n\\n"
                        "# Unresolved Disagreements\\n\\n1. Hardware Selection (NVIDIA vs. Xilinx/TI): Trade-off remains unresolved because interface data is missing. [SRC-003]\\n\\n"
                        "# Confidence Assessment\\n\\n- Medium confidence: evidence is incomplete and benchmark coverage is limited. [SRC-004]\\n\\n"
                        "# Evidence Gaps\\n\\n- No direct benchmark compares both options in this environment. [SRC-005]\\n\\n"
                        "# Rationale And Traceability\\n\\n- Research A favored Option A and critique B-on-A preserved upside concerns.\\n\\n"
                        "# Recommended Final Artifact Structure\\n\\n- Summary, comparison, recommendation, uncertainty, references, open questions.\\n",
                        encoding="utf-8",
                    )
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

        state = json.loads((run_dir / "workflow-state.json").read_text(encoding="utf-8"))
        statuses = {stage["id"]: stage["status"] for stage in state["stages"]}
        self.assertEqual(statuses["intake"], "completed")
        self.assertEqual(statuses["judge"], "completed")
        self.assertEqual(state["post_processing"]["stage_claims"]["research-a"]["status"], "completed")
        self.assertEqual(state["post_processing"]["stage_claims"]["research-b"]["status"], "completed")
        self.assertEqual(state["post_processing"]["stage_claims"]["judge"]["status"], "completed")
        self.assertEqual(state["post_processing"]["claim_extraction"]["status"], "completed")
        self.assertEqual(state["post_processing"]["final_artifact"]["status"], "completed")

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
                if not output_match or not stage_match:
                    print("missing stage metadata", file=sys.stderr)
                    sys.exit(2)

                output_path = Path(output_match.group(1).strip())
                json_path = Path(json_match.group(1).strip()) if json_match else None
                output_path.parent.mkdir(parents=True, exist_ok=True)
                if json_path is not None:
                    json_path.parent.mkdir(parents=True, exist_ok=True)
                stage = stage_match.group(1)

                if stage == "research-b":
                    output_path.write_text(
                        "# Executive Summary\\n\\n- Research B summary. [SRC-999]\\n\\n"
                        "# Facts\\n\\n1. Option B has evidence behind it. [SRC-999]\\n\\n"
                        "# Inferences\\n\\n1. Option B may be viable. [SRC-999] Confidence: medium\\n\\n"
                        "# Uncertainty Register\\n\\n- Coverage is incomplete.\\n\\n"
                        "# Evidence Gaps\\n\\n- Benchmarking is incomplete.\\n\\n"
                        "# Preliminary Disagreements\\n\\n- The other option may be stronger on another axis.\\n\\n"
                        "# Source Evaluation\\n\\n- Sources are limited but relevant.\\n",
                        encoding="utf-8",
                    )
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
                                "sources": []
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

                if stage == "research-b":
                    output_path.write_text(
                        "# Executive Summary\\n\\nResearch B summary. [SRC-200]\\n\\n"
                        "# Facts\\n\\n1. Fact. [SRC-200]\\n\\n"
                        "# Inferences\\n\\n1. Inference. [SRC-200] Confidence: high\\n\\n"
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
                                "inferences": [{"id": "I-200", "text": "Inference.", "evidence_sources": ["SRC-200"], "confidence": "high"}],
                                "uncertainties": ["Gap."],
                                "evidence_gaps": ["More data."],
                                "preliminary_disagreements": ["Trade-off remains."],
                                "source_evaluation": ["Source quality note."],
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
                                        {"id": "SRC-001", "title": "Canonical source SRC-001", "type": "report", "authority": "test fixture", "locator": "https://example.com/src-001"},
                                        {"id": "SRC-002", "title": "Canonical source SRC-002", "type": "report", "authority": "test fixture", "locator": "https://example.com/src-002"}
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
        )
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertIn("already complete", second.stdout.lower())

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

                if stage == "intake":
                    output_path.write_text(json.dumps({"question": "", "scope": "invalid"}, indent=2), encoding="utf-8")
                    sys.exit(0)

                print("unexpected stage", file=sys.stderr)
                sys.exit(2)
                """
            ),
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
        self.assertIn("intake validation", result.stderr.lower())
        state = json.loads((self.job_dir / "runs" / "run-bad-intake" / "workflow-state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["status"], "failed")

    def test_wraps_gemini_stdout_into_stage_output_when_file_is_not_written(self) -> None:
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

        self.assertEqual(result.returncode, 0, result.stderr)
        run_dir = self.job_dir / "runs" / "run-stdout-gemini"
        research_b = (run_dir / "stage-outputs" / "03-research-b.md").read_text(encoding="utf-8")
        self.assertTrue(research_b.startswith("# Executive Summary"))
        self.assertNotIn("I will first inspect", research_b)

        state = json.loads((run_dir / "workflow-state.json").read_text(encoding="utf-8"))
        statuses = {stage["id"]: stage["status"] for stage in state["stages"]}
        self.assertEqual(statuses["research-b"], "completed")
        self.assertEqual(state["status"], "completed")

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
        state = json.loads((self.job_dir / "runs" / "run-missing-structured-json" / "workflow-state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["status"], "failed")

    def test_fails_fast_when_research_sidecar_contains_uncited_inference(self) -> None:
        self._write_stdout_only_executor(
            self.gemini_bin,
            "\n".join(
                [
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
                    "1. Option B may be viable. Confidence: medium",
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
  "inferences": [{"id": "I-001", "text": "Option B may be viable.", "evidence_sources": [], "confidence": "medium"}],
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
        judge_sidecar = json.loads((run_dir / "stage-claims" / "06-judge.claims.json").read_text(encoding="utf-8"))
        self.assertEqual(judge_sidecar["status"], "not_started")

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
                if not output_match or not stage_match:
                    print("missing stage metadata", file=sys.stderr)
                    sys.exit(2)

                output_path = Path(output_match.group(1).strip())
                json_path = Path(json_match.group(1).strip()) if json_match else None
                output_path.parent.mkdir(parents=True, exist_ok=True)
                if json_path is not None:
                    json_path.parent.mkdir(parents=True, exist_ok=True)
                stage = stage_match.group(1)

                if stage == "research-b":
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

                if stage == "critique-b-on-a":
                    output_path.write_text(
                        "# Claims That Survive Review\\n\\n- One claim survives review. [SRC-210]\\n\\n"
                        "# Unsupported Claims\\n\\n- Some claims need stronger support. [SRC-211]\\n\\n"
                        "# Weak Sources Or Citation Problems\\n\\n- One citation is indirect. [SRC-212]\\n\\n"
                        "# Omissions And Missing Alternatives\\n\\n- Missing alternative analysis. [SRC-213]\\n\\n"
                        "# Overreach And Overconfident Inference\\n\\n- One conclusion is too strong. [SRC-214]\\n\\n"
                        "# Unresolved Disagreements For Judge\\n\\n- Option A vs B remains disputed. [SRC-215]\\n\\n"
                        "# Overall Critique Summary\\n\\n- Reliability is mixed. Confidence: medium\\n",
                        encoding="utf-8",
                    )
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

                if stage == "judge":
                    output_path.write_text(
                        "# Supported Conclusions\\n\\n1. Option A has lower implementation risk. [SRC-200]\\n\\n"
                        "# Inferences And Synthesis Judgments\\n\\n1. Option A is the safer near-term choice. [SRC-200] Confidence: medium\\n\\n"
                        "# Unresolved Disagreements\\n\\n- Trade-off remains unresolved. [SRC-215]\\n\\n"
                        "# Confidence Assessment\\n\\n- Medium confidence because evidence is incomplete. [SRC-200]\\n\\n"
                        "# Evidence Gaps\\n\\n- Comparative benchmark is still missing. [SRC-216]\\n\\n"
                        "# Rationale And Traceability\\n\\n- Research B preserved the strongest cited inference.\\n\\n"
                        "# Recommended Final Artifact Structure\\n\\n- Summary, evidence, recommendation, uncertainty, references.\\n",
                        encoding="utf-8",
                    )
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

    def test_stdout_artifact_extraction_prefers_expected_heading_or_fenced_markdown(self) -> None:
        stdout = "\n".join(
            [
                "# Notes",
                "",
                "I will now write the artifact.",
                "",
                "```markdown",
                "# Executive Summary",
                "",
                "- Summary. [SRC-001]",
                "",
                "# Facts",
                "",
                "1. Fact. [SRC-001]",
                "",
                "# Inferences",
                "",
                "1. Inference. [SRC-001] Confidence: medium",
                "",
                "# Uncertainty Register",
                "",
                "- Gap.",
                "",
                "# Evidence Gaps",
                "",
                "- More data.",
                "",
                "# Preliminary Disagreements",
                "",
                "- Disagreement. [SRC-002]",
                "",
                "# Source Evaluation",
                "",
                "- Source note.",
                "```",
                "",
                "I have completed the task.",
            ]
        )

        artifact = extract_markdown_artifact("research-a", stdout)
        self.assertTrue(artifact.startswith("# Executive Summary"))
        self.assertNotIn("# Notes", artifact)
        self.assertNotIn("I have completed", artifact)
        self.assertNotIn("```", artifact)

    def test_structured_json_artifact_extraction_prefers_fenced_json_block(self) -> None:
        stdout = "\n".join(
            [
                "# Executive Summary",
                "",
                "Summary text without inline citations.",
                "",
                "```json",
                "{",
                '  "stage": "research-b",',
                '  "summary": "Recovered summary.",',
                '  "facts": [{"id": "F-1", "text": "Fact.", "evidence_sources": ["SRC-001"]}],',
                '  "inferences": [{"id": "I-1", "text": "Inference.", "evidence_sources": ["SRC-001"], "confidence": "high"}],',
                '  "uncertainties": ["Gap."],',
                '  "evidence_gaps": ["More data."],',
                '  "preliminary_disagreements": ["Trade-off remains."],',
                '  "source_evaluation": ["Useful source note."],',
                '  "sources": [{"id": "SRC-001", "title": "Source", "type": "report", "authority": "fixture", "locator": "https://example.com/src-001"}]',
                "}",
                "```",
            ]
        )

        artifact = extract_structured_json_artifact("research-b", stdout)

        self.assertIsNotNone(artifact)
        self.assertEqual(artifact["stage"], "research-b")
        self.assertEqual(artifact["inferences"][0]["evidence_sources"], ["SRC-001"])


if __name__ == "__main__":
    unittest.main()

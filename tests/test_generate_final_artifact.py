import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
GENERATE_FINAL_ARTIFACT = REPO_ROOT / "scripts" / "generate_final_artifact.py"


class GenerateFinalArtifactTests(unittest.TestCase):
    def test_renders_brief_improvement_recommendations_in_documented_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            judge_path = root / "judge.md"
            judge_json_path = root / "judge.json"
            claims_path = root / "claims.json"
            output_path = root / "final.md"

            judge_path.write_text(
                "\n".join(
                    [
                        "# Supported Conclusions",
                        "1. Option A is feasible. [SRC-001]",
                        "",
                        "# Inferences And Synthesis Judgments",
                        "1. Option A is preferred. [SRC-001] Confidence: medium",
                        "",
                        "# Unresolved Disagreements",
                        "- Thermal trade-offs remain open.",
                        "",
                        "# Confidence Assessment",
                        "- Medium confidence.",
                        "",
                        "# Evidence Gaps",
                        "- Thermal benchmark is missing.",
                        "",
                        "# Brief Improvement Recommendations",
                        "1. Missing input: Deployment budget. Why it matters: This could change option ranking. Expected impact: Would narrow the recommendation. Priority: high",
                        "",
                        "# Rationale And Traceability",
                        "- Judge summary.",
                        "",
                        "# Recommended Final Artifact Structure",
                        "- Summary",
                    ]
                ),
                encoding="utf-8",
            )
            judge_json_path.write_text(
                """{
  "stage": "judge",
  "supported_conclusions": [
    {"id": "C-001", "text": "Option A is feasible.", "evidence_sources": ["SRC-001"]}
  ],
  "synthesis_judgments": [
    {"id": "J-001", "text": "Option A is preferred.", "evidence_sources": ["SRC-001"], "confidence": "medium"}
  ],
  "unresolved_disagreements": ["Thermal trade-offs remain open."],
  "confidence_assessment": ["Medium confidence."],
  "evidence_gaps": ["Thermal benchmark is missing."],
  "brief_improvements": [
    {
      "missing_input": "Deployment budget",
      "why_it_matters": "This could change option ranking.",
      "expected_impact": "Would narrow the recommendation.",
      "priority": "high"
    }
  ],
  "rationale": ["Judge summary."],
  "recommended_artifact_structure": ["Summary"],
  "sources": [
    {"id": "SRC-001", "title": "Primary source", "type": "report", "authority": "Vendor", "locator": "https://example.com/src-001"}
  ]
}""",
                encoding="utf-8",
            )
            claims_path.write_text(
                """{
  "claims": [
    {"id": "C-001", "text": "Option A is feasible.", "type": "fact", "provenance": [], "evidence_sources": ["SRC-001"], "unclassified_markers": []},
    {"id": "J-001", "text": "Option A is preferred.", "type": "inference", "provenance": [], "evidence_sources": ["SRC-001"], "unclassified_markers": []}
  ],
  "summary": {
    "claim_type_counts": {"fact": 1, "inference": 1},
    "claims_with_unclassified_markers": [],
    "fact_count": 1,
    "inference_count": 1,
    "provenance_only_fact_ids": [],
    "uncited_fact_ids": [],
    "uncited_inference_ids": []
  }
}""",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    "python3",
                    str(GENERATE_FINAL_ARTIFACT),
                    "--judge-input",
                    str(judge_path),
                    "--judge-structured-input",
                    str(judge_json_path),
                    "--claim-register",
                    str(claims_path),
                    "--output",
                    str(output_path),
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            artifact = output_path.read_text(encoding="utf-8")
            self.assertLess(artifact.index("# Confidence And Uncertainty"), artifact.index("# Brief Improvement Recommendations"))
            self.assertLess(artifact.index("# Brief Improvement Recommendations"), artifact.index("# References"))
            self.assertLess(artifact.index("# References"), artifact.index("# Open Questions"))
    def test_rejects_blocked_policy_sources_during_publication(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            judge_path = root / "judge.md"
            judge_json_path = root / "judge.json"
            claims_path = root / "claims.json"
            output_path = root / "final.md"

            judge_path.write_text(
                "\n".join(
                    [
                        "# Supported Conclusions",
                        "1. Option A is feasible. [SRC-001]",
                    ]
                ),
                encoding="utf-8",
            )
            judge_json_path.write_text(
                """{
  "stage": "judge",
  "supported_conclusions": [
    {"id": "C-001", "text": "Option A is feasible.", "evidence_sources": ["SRC-001"]}
  ],
  "synthesis_judgments": [],
  "unresolved_disagreements": [],
  "confidence_assessment": [],
  "evidence_gaps": [],
  "rationale": [],
  "recommended_artifact_structure": [],
  "sources": [
    {
      "id": "SRC-001",
      "title": "Marketing page",
      "type": "marketing page",
      "authority": "vendor",
      "locator": "https://example.com/product",
      "policy_outcome": "blocked",
      "policy_notes": ["Marketing-only source is blocked for final publication."]
    }
  ]
}""",
                encoding="utf-8",
            )
            claims_path.write_text(
                """{
  "claims": [
    {
      "id": "C-001",
      "text": "Option A is feasible.",
      "type": "fact",
      "provenance": [],
      "evidence_sources": ["SRC-001"],
      "unclassified_markers": []
    }
  ],
  "summary": {
    "claim_type_counts": {"fact": 1},
    "truth_gated_claim_type_counts": {"fact": 1},
    "claims_with_unclassified_markers": [],
    "fact_count": 1,
    "inference_count": 0,
    "assumption_count": 0,
    "provenance_only_fact_ids": [],
    "uncited_fact_ids": [],
    "uncited_inference_ids": [],
    "uncited_truth_gated_ids": [],
    "unsupported_recommendation_ids": []
  }
}""",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    "python3",
                    str(GENERATE_FINAL_ARTIFACT),
                    "--judge-input",
                    str(judge_path),
                    "--judge-structured-input",
                    str(judge_json_path),
                    "--claim-register",
                    str(claims_path),
                    "--output",
                    str(output_path),
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("blocked", result.stderr.lower())
            self.assertIn("marketing-only source", result.stderr.lower())

    def test_prefers_structured_judge_input_and_renders_followable_references(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            job_dir = root / "jobs" / "example-job"
            run_dir = job_dir / "runs" / "run-017"
            stage_outputs = run_dir / "stage-outputs"
            stage_outputs.mkdir(parents=True)
            (job_dir / "brief.md").write_text("# Brief\n\nProject brief contents.\n", encoding="utf-8")

            judge_path = stage_outputs / "06-judge.md"
            judge_json_path = stage_outputs / "06-judge.json"
            claims_path = job_dir / "evidence" / "claims-run-017.json"
            claims_path.parent.mkdir(parents=True)
            output_path = job_dir / "outputs" / "final-run-017.md"
            output_path.parent.mkdir(parents=True)

            judge_path.write_text(
                "\n".join(
                    [
                        "# Supported Conclusions",
                        "1. Placeholder markdown shape. [DOC-001, SRC-001]",
                        "",
                        "# Inferences And Synthesis Judgments",
                        "1. Placeholder inference. [SRC-001] Confidence: medium",
                        "",
                        "# Unresolved Disagreements",
                        "1. Placeholder disagreement",
                        "",
                        "# Confidence Assessment",
                        "- Placeholder confidence.",
                        "",
                        "# Evidence Gaps",
                        "- Placeholder gap.",
                        "",
                        "# Rationale And Traceability",
                        "- Placeholder rationale.",
                        "",
                        "# Recommended Final Artifact Structure",
                        "- Placeholder structure.",
                    ]
                ),
                encoding="utf-8",
            )

            judge_json_path.write_text(
                """{
  "stage": "judge",
  "supported_conclusions": [
    {
      "id": "CONC-001",
      "text": "Upgrading to an on-device architecture is technically feasible.",
      "evidence_sources": ["DOC-001", "SRC-001"]
    }
  ],
  "synthesis_judgments": [
    {
      "id": "JUDG-001",
      "text": "A split FPGA plus embedded compute architecture is the lowest-risk path.",
      "evidence_sources": ["SRC-001", "SRC-002"],
      "confidence": "high"
    }
  ],
  "unresolved_disagreements": [
    {
      "point": "Hardware platform selection",
      "case_a": "Integrated SoC is simpler.",
      "case_b": "Modular accelerator is cooler.",
      "reason_unresolved": "Thermal measurements are missing."
    }
  ],
  "confidence_assessment": {
    "summary": "High confidence in feasibility, medium confidence in hardware selection.",
    "topics": [
      {
        "topic": "Feasibility",
        "confidence": "high",
        "rationale": "Supported by cited hardware capabilities."
      }
    ]
  },
  "evidence_gaps": [
    "Measured thermal envelope under sustained load."
  ],
  "rationale": "Judge preserved the hardware dispute because the thermal record is incomplete.",
  "recommended_artifact_structure": {
    "sections": [
      "Executive Summary",
      "Architecture",
      "Thermal Risks"
    ]
  },
  "sources": [
    {
      "id": "DOC-001",
      "title": "Research Stage Prompt brief.md excerpt for run-017 stage research-a",
      "type": "project_brief",
      "authority": "Project run artifact",
      "locator": "__PROMPT_PACKET__"
    },
    {
      "id": "SRC-001",
      "title": "Primary hardware source",
      "type": "official documentation",
      "authority": "Vendor",
      "locator": "https://example.com/hardware"
    },
    {
      "id": "SRC-002",
      "title": "Thermal source",
      "type": "technical note",
      "authority": "Vendor",
      "locator": "https://example.com/thermal"
    }
  ]
}""".replace("__PROMPT_PACKET__", str(stage_outputs.parent / "prompt-packets" / "02-research-a.md")),
                encoding="utf-8",
            )

            claims_path.write_text(
                """{
  "claims": [
    {
      "id": "CONC-001",
      "text": "Upgrading to an on-device architecture is technically feasible.",
      "type": "fact",
      "provenance": [],
      "evidence_sources": ["DOC-001", "SRC-001"],
      "unclassified_markers": []
    },
    {
      "id": "JUDG-001",
      "text": "A split FPGA plus embedded compute architecture is the lowest-risk path.",
      "type": "inference",
      "provenance": [],
      "evidence_sources": ["SRC-001", "SRC-002"],
      "unclassified_markers": [],
      "confidence": "high"
    }
  ],
  "summary": {
    "claim_type_counts": {"fact": 1, "inference": 1},
    "claims_with_unclassified_markers": [],
    "fact_count": 1,
    "inference_count": 1,
    "provenance_only_fact_ids": [],
    "uncited_fact_ids": [],
    "uncited_inference_ids": []
  }
}""",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    "python3",
                    str(GENERATE_FINAL_ARTIFACT),
                    "--judge-input",
                    str(judge_path),
                    "--judge-structured-input",
                    str(judge_json_path),
                    "--claim-register",
                    str(claims_path),
                    "--output",
                    str(output_path),
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            artifact = output_path.read_text(encoding="utf-8")
            self.assertNotIn("- 1.", artifact)
            self.assertNotIn("- -", artifact)
            self.assertIn("DOC-001: Job brief", artifact)
            self.assertIn(str(job_dir / "brief.md"), artifact)
            self.assertIn("SRC-001: Primary hardware source", artifact)
            self.assertIn("https://example.com/hardware", artifact)

    def test_rejects_user_facing_publication_when_referenced_sources_are_provisional(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            judge_path = root / "judge.md"
            judge_json_path = root / "judge.json"
            claims_path = root / "claims.json"
            output_path = root / "final.md"

            judge_path.write_text(
                "\n".join(
                    [
                        "# Supported Conclusions",
                        "1. Option A is feasible. [SRC-001]",
                        "",
                        "# Inferences And Synthesis Judgments",
                        "1. Option A is preferred. [SRC-001] Confidence: medium",
                    ]
                ),
                encoding="utf-8",
            )
            judge_json_path.write_text(
                """{
  "stage": "judge",
  "supported_conclusions": [
    {"id": "C-001", "text": "Option A is feasible.", "evidence_sources": ["SRC-001"]}
  ],
  "synthesis_judgments": [
    {"id": "J-001", "text": "Option A is preferred.", "evidence_sources": ["SRC-001"], "confidence": "medium"}
  ],
  "unresolved_disagreements": [],
  "confidence_assessment": [],
  "evidence_gaps": [],
  "rationale": [],
  "recommended_artifact_structure": [],
  "sources": [
    {
      "id": "SRC-001",
      "title": "Recovered source",
      "type": "unknown",
      "authority": "recovered-from-markdown",
      "source_class": "recovered_provisional",
      "locator": "urn:recovered:judge:SRC-001"
    }
  ]
}""",
                encoding="utf-8",
            )
            claims_path.write_text(
                """{
  "claims": [
    {
      "id": "C-001",
      "text": "Option A is feasible.",
      "type": "fact",
      "provenance": [],
      "evidence_sources": ["SRC-001"],
      "unclassified_markers": []
    }
  ],
  "summary": {
    "claim_type_counts": {"fact": 1},
    "claims_with_unclassified_markers": [],
    "fact_count": 1,
    "inference_count": 0,
    "provenance_only_fact_ids": [],
    "uncited_fact_ids": [],
    "uncited_inference_ids": []
  }
}""",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    "python3",
                    str(GENERATE_FINAL_ARTIFACT),
                    "--judge-input",
                    str(judge_path),
                    "--judge-structured-input",
                    str(judge_json_path),
                    "--claim-register",
                    str(claims_path),
                    "--output",
                    str(output_path),
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("provisional", result.stderr.lower())

    def test_rejects_user_facing_publication_when_referenced_sources_are_unresolved(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            judge_path = root / "judge.md"
            judge_json_path = root / "judge.json"
            claims_path = root / "claims.json"
            output_path = root / "final.md"

            judge_path.write_text(
                "# Supported Conclusions\n1. Option A is feasible. [SRC-404]\n\n# Inferences And Synthesis Judgments\n1. Option A is preferred. [SRC-404] Confidence: medium\n",
                encoding="utf-8",
            )
            judge_json_path.write_text(
                """{
  "stage": "judge",
  "supported_conclusions": [
    {"id": "C-001", "text": "Option A is feasible.", "evidence_sources": ["SRC-404"]}
  ],
  "synthesis_judgments": [
    {"id": "J-001", "text": "Option A is preferred.", "evidence_sources": ["SRC-404"], "confidence": "medium"}
  ],
  "unresolved_disagreements": [],
  "confidence_assessment": [],
  "evidence_gaps": [],
  "rationale": [],
  "recommended_artifact_structure": [],
  "sources": []
}""",
                encoding="utf-8",
            )
            claims_path.write_text(
                """{
  "claims": [
    {
      "id": "C-001",
      "text": "Option A is feasible.",
      "type": "fact",
      "provenance": [],
      "evidence_sources": ["SRC-404"],
      "unclassified_markers": []
    }
  ],
  "summary": {
    "claim_type_counts": {"fact": 1},
    "claims_with_unclassified_markers": [],
    "fact_count": 1,
    "inference_count": 0,
    "provenance_only_fact_ids": [],
    "uncited_fact_ids": [],
    "uncited_inference_ids": []
  }
}""",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    "python3",
                    str(GENERATE_FINAL_ARTIFACT),
                    "--judge-input",
                    str(judge_path),
                    "--judge-structured-input",
                    str(judge_json_path),
                    "--claim-register",
                    str(claims_path),
                    "--output",
                    str(output_path),
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("referenced source", result.stderr.lower())
            self.assertIn("is unresolved", result.stderr.lower())

    def test_generates_structured_artifact_with_external_references_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            judge_path = root / "judge.md"
            judge_json_path = root / "judge.json"
            claims_path = root / "claims.json"
            output_path = root / "final.md"

            judge_path.write_text(
                "\n".join(
                    [
                        "# Supported Conclusions",
                        "1. Option A has lower implementation risk. [SRC-001]",
                        "",
                        "# Inferences And Synthesis Judgments",
                        "1. Inference: Option A is the safer near-term choice. [SRC-001, SRC-002] Confidence: medium",
                        "",
                        "# Unresolved Disagreements",
                        "- Option B may have better upside if migration costs are overestimated. [SRC-003]",
                        "",
                        "# Confidence Assessment",
                        "- Confidence is medium because source coverage is incomplete. [SRC-002]",
                        "",
                        "# Evidence Gaps",
                        "- No direct benchmark compares both options in this environment. [SRC-004]",
                        "",
                        "# Rationale And Traceability",
                        "- Research A favored Option A; critique B-on-A questioned long-term upside. [PASS-A, CRIT-B-A]",
                        "",
                        "# Recommended Final Artifact Structure",
                        "- Summary, comparison, recommendation, uncertainty, references, open questions.",
                    ]
                ),
                encoding="utf-8",
            )

            claims_path.write_text(
                """{
  "claims": [
    {
      "id": "C001",
      "text": "Option A has lower implementation risk.",
      "type": "fact",
      "provenance": ["PASS-A", "JUDGE"],
      "evidence_sources": ["SRC-001"],
      "unclassified_markers": [],
      "line": 2
    },
    {
      "id": "C002",
      "text": "Option A is the safer near-term choice.",
      "type": "inference",
      "provenance": ["JUDGE"],
      "evidence_sources": ["SRC-001", "SRC-002"],
      "unclassified_markers": [],
      "confidence": "medium",
      "line": 5
    },
    {
      "id": "C003",
      "text": "Option B may have better upside if migration costs are overestimated.",
      "type": "inference",
      "provenance": ["JUDGE"],
      "evidence_sources": ["SRC-003"],
      "unclassified_markers": [],
      "line": 8
    },
    {
      "id": "C004",
      "text": "No direct benchmark compares both options in this environment.",
      "type": "evidence_gap",
      "provenance": ["JUDGE"],
      "evidence_sources": ["SRC-004"],
      "unclassified_markers": [],
      "line": 14
    }
  ],
  "summary": {
    "claim_type_counts": {"evidence_gap": 1, "fact": 1, "inference": 2},
    "claims_with_unclassified_markers": [],
    "fact_count": 1,
    "inference_count": 2,
    "provenance_only_fact_ids": [],
    "uncited_fact_ids": []
  }
}""",
                encoding="utf-8",
            )
            judge_json_path.write_text(
                """{
  "stage": "judge",
  "supported_conclusions": [
    {"id": "C001", "text": "Option A has lower implementation risk.", "evidence_sources": ["SRC-001"]}
  ],
  "synthesis_judgments": [
    {"id": "C002", "text": "Option A is the safer near-term choice.", "evidence_sources": ["SRC-001", "SRC-002"], "confidence": "medium"}
  ],
  "unresolved_disagreements": [
    {"point": "Option B upside", "case_a": "Option A is lower risk.", "case_b": "Option B may have better upside.", "reason_unresolved": "Migration cost evidence is incomplete."}
  ],
  "confidence_assessment": [
    "Confidence is medium because source coverage is incomplete."
  ],
  "evidence_gaps": [
    "No direct benchmark compares both options in this environment."
  ],
  "rationale": [],
  "recommended_artifact_structure": [],
  "sources": [
    {"id": "SRC-001", "title": "Implementation risk source", "type": "report", "authority": "vendor", "locator": "https://example.com/src-001", "source_class": "external_evidence"},
    {"id": "SRC-002", "title": "Near-term choice source", "type": "report", "authority": "analyst", "locator": "https://example.com/src-002", "source_class": "external_evidence"},
    {"id": "SRC-003", "title": "Upside source", "type": "report", "authority": "vendor", "locator": "https://example.com/src-003", "source_class": "external_evidence"},
    {"id": "SRC-004", "title": "Benchmark gap source", "type": "report", "authority": "lab", "locator": "https://example.com/src-004", "source_class": "external_evidence"}
  ]
}""",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    "python3",
                    str(GENERATE_FINAL_ARTIFACT),
                    "--judge-input",
                    str(judge_path),
                    "--judge-structured-input",
                    str(judge_json_path),
                    "--claim-register",
                    str(claims_path),
                    "--output",
                    str(output_path),
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            artifact = output_path.read_text(encoding="utf-8")
            self.assertIn("# Executive Summary", artifact)
            self.assertIn("# Options Comparison", artifact)
            self.assertIn("# Recommendation", artifact)
            self.assertIn("# Confidence And Uncertainty", artifact)
            self.assertIn("# References", artifact)
            self.assertIn("# Open Questions", artifact)
            self.assertIn("SRC-001", artifact)
            self.assertNotIn("PASS-A", artifact)
            self.assertNotIn("CRIT-B-A", artifact)

    def test_rejects_claim_register_with_uncited_facts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            judge_path = root / "judge.md"
            claims_path = root / "claims.json"
            output_path = root / "final.md"
            judge_path.write_text("# Supported Conclusions\n1. Placeholder. [SRC-001]\n", encoding="utf-8")
            claims_path.write_text(
                """{
  "claims": [
    {
      "id": "C001",
      "text": "Placeholder fact.",
      "type": "fact",
      "provenance": ["PASS-A"],
      "evidence_sources": [],
      "unclassified_markers": [],
      "line": 1
    }
  ],
  "summary": {
    "claim_type_counts": {"fact": 1},
    "claims_with_unclassified_markers": [],
    "fact_count": 1,
    "inference_count": 0,
    "provenance_only_fact_ids": ["C001"],
    "uncited_fact_ids": ["C001"]
  }
}""",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    "python3",
                    str(GENERATE_FINAL_ARTIFACT),
                    "--judge-input",
                    str(judge_path),
                    "--claim-register",
                    str(claims_path),
                    "--output",
                    str(output_path),
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("uncited facts", result.stderr.lower())

    def test_rejects_claim_register_with_uncited_inferences(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            judge_path = root / "judge.md"
            claims_path = root / "claims.json"
            output_path = root / "final.md"
            judge_path.write_text("# Supported Conclusions\n1. Placeholder. [SRC-001]\n", encoding="utf-8")
            claims_path.write_text(
                """{
  "claims": [
    {
      "id": "C002",
      "text": "Placeholder inference.",
      "type": "inference",
      "provenance": ["JUDGE"],
      "evidence_sources": [],
      "unclassified_markers": [],
      "confidence": "medium"
    }
  ],
  "summary": {
    "claim_type_counts": {"inference": 1},
    "claims_with_unclassified_markers": [],
    "fact_count": 0,
    "inference_count": 1,
    "provenance_only_fact_ids": [],
    "uncited_fact_ids": [],
    "uncited_inference_ids": ["C002"]
  }
}""",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    "python3",
                    str(GENERATE_FINAL_ARTIFACT),
                    "--judge-input",
                    str(judge_path),
                    "--claim-register",
                    str(claims_path),
                    "--output",
                    str(output_path),
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("uncited inferences", result.stderr.lower())

    def test_rejects_missing_required_sections_in_generated_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            judge_path = root / "judge.md"
            claims_path = root / "claims.json"
            output_path = root / "final.md"
            judge_path.write_text("# Rationale And Traceability\n- Only traceability.\n", encoding="utf-8")
            claims_path.write_text(
                """{
  "claims": [],
  "summary": {
    "claim_type_counts": {},
    "claims_with_unclassified_markers": [],
    "fact_count": 0,
    "inference_count": 0,
    "provenance_only_fact_ids": [],
    "uncited_fact_ids": []
  }
}""",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    "python3",
                    str(GENERATE_FINAL_ARTIFACT),
                    "--judge-input",
                    str(judge_path),
                    "--claim-register",
                    str(claims_path),
                    "--output",
                    str(output_path),
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("recommendation", result.stderr.lower())


if __name__ == "__main__":
    unittest.main()

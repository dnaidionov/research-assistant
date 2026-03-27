import json
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
EXTRACT_CLAIMS = REPO_ROOT / "scripts" / "extract_claims.py"


class ExtractClaimsTests(unittest.TestCase):
    def test_extracts_claims_from_structured_stage_json_without_markdown_heuristics(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "judge.json"
            output_path = Path(tmpdir) / "claims.json"
            input_path.write_text(
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
    {"id": "SRC-001", "title": "Source", "type": "report", "authority": "vendor", "locator": "https://example.com/src-001"}
  ]
}""",
                encoding="utf-8",
            )

            result = subprocess.run(
                ["python3", str(EXTRACT_CLAIMS), "--input", str(input_path), "--output", str(output_path), "--strict"],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["summary"]["fact_count"], 1)
            self.assertEqual(payload["summary"]["inference_count"], 1)
            self.assertEqual(payload["summary"]["uncited_fact_ids"], [])
            self.assertEqual(payload["summary"]["uncited_inference_ids"], [])

    def test_structured_stage_json_preserves_semantic_support_links(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "judge.json"
            output_path = Path(tmpdir) / "claims.json"
            input_path.write_text(
                """{
  "stage": "judge",
  "supported_conclusions": [
    {
      "id": "C-001",
      "text": "Option A is feasible.",
      "evidence_sources": ["SRC-001"],
      "support_links": [
        {"source_id": "SRC-001", "role": "evidence"},
        {"source_id": "SRC-WF", "role": "provenance"}
      ]
    }
  ],
  "synthesis_judgments": [],
  "unresolved_disagreements": [],
  "confidence_assessment": [],
  "evidence_gaps": [],
  "rationale": [],
  "recommended_artifact_structure": [],
  "sources": [
    {"id": "SRC-001", "title": "Source", "type": "report", "authority": "vendor", "locator": "https://example.com/src-001", "source_class": "external_evidence"},
    {"id": "SRC-WF", "title": "Workflow artifact", "type": "workflow_artifact", "authority": "runner", "locator": "urn:workflow:judge", "source_class": "workflow_provenance"}
  ]
}""",
                encoding="utf-8",
            )

            result = subprocess.run(
                ["python3", str(EXTRACT_CLAIMS), "--input", str(input_path), "--output", str(output_path)],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            claim = payload["claims"][0]
            self.assertEqual(claim["evidence_sources"], ["SRC-001"])
            self.assertEqual(claim["provenance"], ["SRC-WF"])
            self.assertEqual(claim["support_links"][1]["role"], "provenance")

    def test_classifies_provenance_evidence_and_unknown_markers_separately(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "report.md"
            output_path = Path(tmpdir) / "claims.json"
            input_path.write_text(
                "\n".join(
                    [
                        "## Facts",
                        "- The workflow writes outputs into the job repo. [PASS-A, SRC-100, NOTE-1]",
                    ]
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                ["python3", str(EXTRACT_CLAIMS), "--input", str(input_path), "--output", str(output_path)],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            claim = payload["claims"][0]
            self.assertEqual(claim["provenance"], ["PASS-A"])
            self.assertEqual(claim["evidence_sources"], ["SRC-100"])
            self.assertEqual(claim["unclassified_markers"], ["NOTE-1"])
            self.assertEqual(payload["summary"]["claims_with_unclassified_markers"], ["C001"])

    def test_recognizes_file_uri_and_local_path_citations_as_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "report.md"
            output_path = Path(tmpdir) / "claims.json"
            input_path.write_text(
                "\n".join(
                    [
                        "## Facts",
                        "- Attached benchmark PDF supports this claim. [file:///tmp/benchmark.pdf, /tmp/local-note.md]",
                    ]
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                ["python3", str(EXTRACT_CLAIMS), "--input", str(input_path), "--output", str(output_path)],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            claim = payload["claims"][0]
            self.assertEqual(
                claim["evidence_sources"],
                ["file:///tmp/benchmark.pdf", "/tmp/local-note.md"],
            )

    def test_extracts_atomic_claims_with_provenance_evidence_and_confidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "report.md"
            output_path = Path(tmpdir) / "claims.json"
            input_path.write_text(
                "\n".join(
                    [
                        "# Report",
                        "",
                        "## Facts",
                        "1. The framework separates assistant and job repos. [SRC-001]",
                        "2. Each run writes artifacts to the job repo. [PASS-A, SRC-002, SRC-003]",
                        "",
                        "## Inferences",
                        "- This separation reduces accidental data leakage. [SRC-004] Confidence: medium",
                    ]
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    "python3",
                    str(EXTRACT_CLAIMS),
                    "--input",
                    str(input_path),
                    "--output",
                    str(output_path),
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual([claim["id"] for claim in payload["claims"]], ["C001", "C002", "C003"])
            self.assertEqual(payload["claims"][0]["type"], "fact")
            self.assertEqual(payload["claims"][1]["provenance"], ["PASS-A"])
            self.assertEqual(payload["claims"][1]["evidence_sources"], ["SRC-002", "SRC-003"])
            self.assertEqual(payload["claims"][2]["type"], "inference")
            self.assertEqual(payload["claims"][2]["confidence"], "medium")
            self.assertEqual(payload["summary"]["claim_type_counts"]["fact"], 2)
            self.assertEqual(payload["summary"]["claim_type_counts"]["inference"], 1)
            self.assertEqual(payload["summary"]["provenance_only_fact_ids"], [])
            self.assertEqual(payload["summary"]["uncited_inference_ids"], [])

    def test_strict_mode_rejects_uncited_facts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "report.md"
            output_path = Path(tmpdir) / "claims.json"
            input_path.write_text(
                "\n".join(
                    [
                        "# Report",
                        "",
                        "## Facts",
                        "- The final report includes citations.",
                    ]
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    "python3",
                    str(EXTRACT_CLAIMS),
                    "--input",
                    str(input_path),
                    "--output",
                    str(output_path),
                    "--strict",
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("uncited fact", result.stderr.lower())

    def test_strict_mode_rejects_provenance_only_fact_support(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "report.md"
            output_path = Path(tmpdir) / "claims.json"
            input_path.write_text(
                "\n".join(
                    [
                        "## Facts",
                        "- The final recommendation is safe. [PASS-A, JUDGE]",
                    ]
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    "python3",
                    str(EXTRACT_CLAIMS),
                    "--input",
                    str(input_path),
                    "--output",
                    str(output_path),
                    "--strict",
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("provenance-only", result.stderr.lower())

    def test_strict_mode_rejects_uncited_inferences(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "report.md"
            output_path = Path(tmpdir) / "claims.json"
            input_path.write_text(
                "\n".join(
                    [
                        "## Inferences",
                        "- This likely improves the workflow. Confidence: medium",
                    ]
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    "python3",
                    str(EXTRACT_CLAIMS),
                    "--input",
                    str(input_path),
                    "--output",
                    str(output_path),
                    "--strict",
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("uncited inference", result.stderr.lower())

    def test_handles_imperfect_markdown_and_splits_atomic_claims(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "rough-notes.md"
            output_path = Path(tmpdir) / "claims.json"
            input_path.write_text(
                "\n".join(
                    [
                        "Facts",
                        "The workflow is multi-stage. [SRC-010] It preserves disagreement. [SRC-011]",
                        "",
                        "Inference",
                        "This makes audits easier. Confidence high",
                    ]
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    "python3",
                    str(EXTRACT_CLAIMS),
                    "--input",
                    str(input_path),
                    "--output",
                    str(output_path),
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(
                [claim["text"] for claim in payload["claims"]],
                [
                    "The workflow is multi-stage.",
                    "It preserves disagreement.",
                    "This makes audits easier.",
                ],
            )
            self.assertEqual(payload["claims"][2]["confidence"], "high")
            self.assertEqual(payload["claims"][0]["evidence_sources"], ["SRC-010"])

    def test_fails_gracefully_on_missing_input(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "missing.md"
            output_path = Path(tmpdir) / "claims.json"

            result = subprocess.run(
                [
                    "python3",
                    str(EXTRACT_CLAIMS),
                    "--input",
                    str(input_path),
                    "--output",
                    str(output_path),
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("not found", result.stderr.lower())

    def test_filters_non_claim_noise_and_classifies_evaluations(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "judge.md"
            output_path = Path(tmpdir) / "claims.json"
            input_path.write_text(
                "\n".join(
                    [
                        "# Judge Output",
                        "",
                        "## Findings",
                        "- The judge accepted the sourcing approach as adequate. [JUDGE, SRC-020]",
                        "- `/tmp/run-001/stage-outputs/02-research-a.md`",
                        "- Recommended section structure:",
                        "- Evidence Gaps",
                        "- Confidence: low",
                    ]
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    "python3",
                    str(EXTRACT_CLAIMS),
                    "--input",
                    str(input_path),
                    "--output",
                    str(output_path),
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(len(payload["claims"]), 1)
            self.assertEqual(payload["claims"][0]["type"], "evaluation")
            self.assertEqual(payload["claims"][0]["provenance"], ["JUDGE"])
            self.assertEqual(payload["claims"][0]["evidence_sources"], ["SRC-020"])

    def test_judge_stage_references_do_not_count_as_external_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "judge.md"
            output_path = Path(tmpdir) / "claims.json"
            input_path.write_text(
                "\n".join(
                    [
                        "# Supported Conclusions",
                        "1. Option A is feasible. [02-research-a][03-research-b]",
                    ]
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    "python3",
                    str(EXTRACT_CLAIMS),
                    "--input",
                    str(input_path),
                    "--output",
                    str(output_path),
                    "--strict",
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
            )

            self.assertNotEqual(result.returncode, 0)
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            claim = payload["claims"][0]
            self.assertEqual(claim["evidence_sources"], [])
            self.assertEqual(claim["unclassified_markers"], ["02-research-a", "03-research-b"])
            self.assertEqual(payload["summary"]["uncited_fact_ids"], ["C001"])

    def test_classifies_disagreements_and_confidence_as_non_fact_claims(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "judge.md"
            output_path = Path(tmpdir) / "claims.json"
            input_path.write_text(
                "\n".join(
                    [
                        "# Unresolved Disagreements",
                        "1. **Hardware Selection (NVIDIA vs. Xilinx/TI):** Trade-off remains unresolved due to missing ADC data.",
                        "",
                        "# Confidence Assessment",
                        "- **Medium Confidence:** Specific hardware selection remains uncertain.",
                    ]
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    "python3",
                    str(EXTRACT_CLAIMS),
                    "--input",
                    str(input_path),
                    "--output",
                    str(output_path),
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual([claim["type"] for claim in payload["claims"]], ["evaluation", "evaluation"])
            self.assertEqual(payload["summary"]["uncited_fact_ids"], [])

    def test_does_not_split_on_vs_abbreviation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "judge.md"
            output_path = Path(tmpdir) / "claims.json"
            input_path.write_text(
                "\n".join(
                    [
                        "# Unresolved Disagreements",
                        "1. **Hardware Selection (NVIDIA vs. Xilinx/TI):** Trade-off remains unresolved. [SRC-001]",
                    ]
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    "python3",
                    str(EXTRACT_CLAIMS),
                    "--input",
                    str(input_path),
                    "--output",
                    str(output_path),
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(len(payload["claims"]), 1)
            self.assertIn("NVIDIA vs. Xilinx/TI", payload["claims"][0]["text"])

    def test_classifies_evidence_gaps_and_open_questions(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "notes.md"
            output_path = Path(tmpdir) / "claims.json"
            input_path.write_text(
                "\n".join(
                    [
                        "## Evidence Gaps",
                        "- No external source confirms the vendor count. [PASS-A]",
                        "",
                        "## Open Questions",
                        "- Which source, if any, verifies the 2024 pricing baseline?",
                    ]
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    "python3",
                    str(EXTRACT_CLAIMS),
                    "--input",
                    str(input_path),
                    "--output",
                    str(output_path),
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual([claim["type"] for claim in payload["claims"]], ["evidence_gap", "open_question"])
            self.assertEqual(payload["claims"][0]["provenance"], ["PASS-A"])
            self.assertEqual(payload["claims"][0]["evidence_sources"], [])
            self.assertEqual(payload["summary"]["provenance_only_fact_ids"], [])


if __name__ == "__main__":
    unittest.main()

import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
GENERATE_FINAL_ARTIFACT = REPO_ROOT / "scripts" / "generate_final_artifact.py"


class GenerateFinalArtifactTests(unittest.TestCase):
    def test_generates_structured_artifact_with_external_references_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            judge_path = root / "judge.md"
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

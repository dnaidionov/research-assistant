import unittest
from pathlib import Path

import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from _stage_contracts import source_registry_placeholder
from _stage_validation import validate_stage_markdown_contract, validate_structured_stage_artifact


class StageValidationTests(unittest.TestCase):
    def test_validate_structured_stage_artifact_rewrites_from_authoritative_json_when_markdown_is_weaker(self) -> None:
        payload = {
            "stage": "research-b",
            "summary": [{"text": "Research B summary.", "evidence_sources": ["SRC-001"]}],
            "facts": [{"id": "F-001", "text": "Fact.", "evidence_sources": ["SRC-001"]}],
            "inferences": [
                {"id": "I-001", "text": "Inference from valid JSON.", "evidence_sources": ["SRC-001"], "confidence": "high"}
            ],
            "uncertainties": ["Gap."],
            "evidence_gaps": ["More data."],
            "preliminary_disagreements": ["Trade-off remains."],
            "source_evaluation": ["Source quality note."],
            "sources": [
                {
                    "id": "SRC-001",
                    "title": "Canonical stage source",
                    "type": "report",
                    "authority": "fixture",
                    "locator": "https://example.com/src-001",
                }
            ],
        }
        registry = source_registry_placeholder("run-xyz")
        markdown = "\n".join(
            [
                "# Executive Summary",
                "",
                "Research B summary.",
                "",
                "# Facts",
                "",
                "1. Fact. [SRC-001]",
                "",
                "# Inferences",
                "",
                "1. Inference without markdown citation. Confidence: high",
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
                "- Trade-off remains.",
                "",
                "# Source Evaluation",
                "",
                "- Source quality note.",
            ]
        )

        result = validate_structured_stage_artifact("research-b", payload, registry, markdown)

        self.assertEqual(result.structured_errors, [])
        self.assertTrue(result.should_rewrite_markdown)
        self.assertEqual(result.markdown_errors, [])
        self.assertIn("[SRC-001]", result.canonical_markdown)
        self.assertIn("Confidence: high", result.canonical_markdown)
        self.assertIsNotNone(result.claim_map)

    def test_validate_structured_stage_artifact_reports_structured_errors_without_markdown_rewrite(self) -> None:
        payload = {
            "stage": "judge",
            "supported_conclusions": [{"id": "C-001", "text": "Conclusion.", "evidence_sources": []}],
            "synthesis_judgments": [{"id": "J-001", "text": "Judgment.", "evidence_sources": ["SRC-001"], "confidence": "medium"}],
            "unresolved_disagreements": [],
            "confidence_assessment": [],
            "evidence_gaps": [],
            "rationale": [],
            "recommended_artifact_structure": [],
            "sources": [
                {"id": "SRC-001", "title": "Source", "type": "report", "authority": "fixture", "locator": "https://example.com/src-001"}
            ],
        }
        registry = source_registry_placeholder("run-xyz")
        markdown = "# Supported Conclusions\n1. Conclusion.\n"

        result = validate_structured_stage_artifact("judge", payload, registry, markdown)

        self.assertTrue(result.structured_errors)
        self.assertFalse(result.should_rewrite_markdown)
        self.assertIsNone(result.claim_map)

    def test_markdown_contract_validator_handles_critique_summary_confidence(self) -> None:
        markdown = "\n".join(
            [
                "# Claims That Survive Review",
                "",
                "- One claim survives review. [SRC-001]",
                "",
                "# Unsupported Claims",
                "",
                "- Target claim: Battery life improves. Why unsupported: No power budget. Needed evidence: measured current draw. [SRC-002]",
                "",
                "# Weak Sources Or Citation Problems",
                "",
                "- Citation is indirect. [SRC-003]",
                "",
                "# Omissions And Missing Alternatives",
                "",
                "- Missing alternative analysis. [SRC-004]",
                "",
                "# Overreach And Overconfident Inference",
                "",
                "- One conclusion is too strong. [SRC-005]",
                "",
                "# Unresolved Disagreements For Judge",
                "",
                "- Option A vs B remains disputed. [SRC-006]",
                "",
                "# Overall Critique Summary",
                "",
                "- Reliability is mixed. Confidence: medium",
            ]
        )

        errors = validate_stage_markdown_contract("critique-a-on-b", markdown)

        self.assertEqual(errors, [], errors)


if __name__ == "__main__":
    unittest.main()

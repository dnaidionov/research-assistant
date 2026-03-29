import unittest
from pathlib import Path

import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from _research_quality import quality_gate_errors


class ResearchQualityTests(unittest.TestCase):
    def test_flags_one_sided_sources_and_disfavored_recommendation_support(self) -> None:
        claim_register = {
            "claims": [
                {
                    "id": "R-001",
                    "text": "Recommend Option A.",
                    "type": "recommendation",
                    "evidence_sources": ["SRC-001"],
                    "confidence": "medium",
                    "section": "Inferences And Synthesis Judgments",
                }
            ]
        }
        source_index = {
            "SRC-001": {
                "id": "SRC-001",
                "authority_tier": "vendor_marketing",
                "policy_outcome": "disfavored",
                "source_class": "external_evidence",
            }
        }

        errors = quality_gate_errors(
            claim_register,
            source_index,
            {
                "one_sided_source_selection": True,
                "disfavored_recommendation_support": True,
            },
        )

        self.assertTrue(any("one-sided" in error.lower() for error in errors))
        self.assertTrue(any("disfavored" in error.lower() for error in errors))

    def test_allows_quality_gates_to_be_disabled(self) -> None:
        claim_register = {
            "claims": [
                {
                    "id": "R-001",
                    "text": "Recommend Option A.",
                    "type": "recommendation",
                    "evidence_sources": ["SRC-001"],
                }
            ]
        }
        source_index = {
            "SRC-001": {
                "id": "SRC-001",
                "authority_tier": "vendor_marketing",
                "policy_outcome": "disfavored",
                "source_class": "external_evidence",
            }
        }

        errors = quality_gate_errors(claim_register, source_index, {"enabled": False})

        self.assertEqual(errors, [])

    def test_flags_missing_required_dimensions_and_evidence_quality_mismatch(self) -> None:
        claim_register = {
            "claims": [
                {
                    "id": "I-001",
                    "text": "Option A performs well.",
                    "type": "inference",
                    "evidence_sources": ["SRC-001"],
                }
            ]
        }
        source_index = {
            "SRC-001": {
                "id": "SRC-001",
                "policy_outcome": "allowed_with_warning",
                "source_class": "external_evidence",
            }
        }

        errors = quality_gate_errors(
            claim_register,
            source_index,
            {
                "required_dimensions": ["runtime", "cost"],
                "evidence_quality_mismatch": True,
            },
        )

        self.assertTrue(any("missing required comparison dimension" in error.lower() for error in errors))
        self.assertTrue(any("evidence-quality mismatch" in error.lower() for error in errors))

    def test_flags_disagreement_collapse_when_conflict_is_present_but_not_preserved(self) -> None:
        claim_register = {
            "claims": [
                {
                    "id": "D-001",
                    "text": "Recommend Option A.",
                    "type": "decision",
                    "evidence_sources": ["SRC-001", "SRC-002"],
                }
            ],
            "summary": {
                "source_conflict_count": 1,
                "disagreement_count": 0,
            },
        }
        source_index = {
            "SRC-001": {"id": "SRC-001", "policy_outcome": "allowed", "source_class": "external_evidence"},
            "SRC-002": {"id": "SRC-002", "policy_outcome": "allowed", "source_class": "external_evidence"},
        }

        errors = quality_gate_errors(
            claim_register,
            source_index,
            {
                "disagreement_collapse": True,
            },
        )

        self.assertTrue(any("disagreement" in error.lower() for error in errors))


if __name__ == "__main__":
    unittest.main()

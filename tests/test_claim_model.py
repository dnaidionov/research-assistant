import unittest
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from _claim_model import build_claim_register, claim_register_errors


class ClaimModelTests(unittest.TestCase):
    def test_build_claim_register_tracks_truth_gated_claim_classes(self) -> None:
        payload = build_claim_register(
            [
                {
                    "id": "F-001",
                    "text": "Fact without evidence.",
                    "type": "fact",
                    "provenance": [],
                    "evidence_sources": [],
                    "unclassified_markers": [],
                },
                {
                    "id": "R-001",
                    "text": "Recommendation without rationale.",
                    "type": "recommendation",
                    "provenance": [],
                    "evidence_sources": ["SRC-001"],
                    "support_links": [{"source_id": "SRC-001", "role": "evidence"}],
                    "unclassified_markers": [],
                },
                {
                    "id": "A-001",
                    "text": "Assume power draw remains stable.",
                    "type": "assumption",
                    "provenance": [],
                    "evidence_sources": [],
                    "unclassified_markers": [],
                },
            ]
        )

        self.assertEqual(payload["summary"]["truth_gated_claim_type_counts"]["fact"], 1)
        self.assertEqual(payload["summary"]["truth_gated_claim_type_counts"]["recommendation"], 1)
        self.assertEqual(payload["summary"]["assumption_count"], 1)
        self.assertEqual(payload["summary"]["uncited_truth_gated_ids"], ["F-001"])
        self.assertEqual(payload["summary"]["unsupported_recommendation_ids"], ["R-001"])

    def test_claim_register_errors_include_unsupported_recommendations(self) -> None:
        payload = build_claim_register(
            [
                {
                    "id": "R-001",
                    "text": "Option A should be recommended.",
                    "type": "recommendation",
                    "provenance": [],
                    "evidence_sources": ["SRC-001"],
                    "unclassified_markers": [],
                }
            ]
        )

        errors = claim_register_errors(payload)

        self.assertTrue(any("unsupported recommendations" in error.lower() for error in errors))


if __name__ == "__main__":
    unittest.main()

import unittest
from pathlib import Path

import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from _intake_contracts import validate_intake_payload


class IntakeContractTests(unittest.TestCase):
    def test_accepts_valid_intake_payload(self) -> None:
        payload = {
            "question": "Which option is better?",
            "scope": ["Compare option A and option B"],
            "constraints": ["Require citations"],
            "assumptions": ["Hardware inputs remain unchanged"],
            "missing_information": ["Power measurements"],
            "required_artifacts": ["judge report"],
            "notes_for_researchers": ["Do not invent benchmarks"],
            "known_facts": [{"statement": "The brief asks for a comparison.", "source_basis": "brief.md"}],
            "working_inferences": [{"statement": "Battery life may matter.", "why_it_is_inference": "The brief implies mobile use but does not state it directly."}],
            "uncertainty_notes": ["Scope may expand after intake review."],
        }

        self.assertEqual(validate_intake_payload(payload), [])

    def test_rejects_invalid_intake_payload(self) -> None:
        payload = {
            "question": "",
            "scope": "Compare option A and option B",
            "constraints": [],
            "assumptions": [],
            "missing_information": [],
            "required_artifacts": [],
            "notes_for_researchers": [],
            "known_facts": [{"statement": "", "source_basis": "brief.md"}],
            "working_inferences": [{"statement": "Battery life may matter."}],
            "uncertainty_notes": [],
        }

        errors = validate_intake_payload(payload)

        self.assertTrue(any("question" in error for error in errors))
        self.assertTrue(any("scope" in error for error in errors))
        self.assertTrue(any("known_facts[1].statement" in error for error in errors))
        self.assertTrue(any("working_inferences[1].why_it_is_inference" in error for error in errors))


if __name__ == "__main__":
    unittest.main()

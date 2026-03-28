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
            "known_facts": [
                {
                    "id": "KF-001",
                    "statement": "The brief asks for a comparison.",
                    "source_ids": ["DOC-BRIEF"],
                    "source_excerpt": "Compare option A and option B.",
                    "source_anchor": "brief.md#Question",
                }
            ],
            "working_inferences": [{"statement": "Battery life may matter.", "why_it_is_inference": "The brief implies mobile use but does not state it directly."}],
            "uncertainty_notes": ["Scope may expand after intake review."],
            "sources": [
                {
                    "id": "DOC-BRIEF",
                    "title": "Job brief",
                    "type": "project_brief",
                    "authority": "job input",
                    "locator": "brief.md",
                    "source_class": "job_input",
                }
            ],
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
            "known_facts": [{"statement": "", "source_ids": ["DOC-BRIEF"], "source_excerpt": "", "source_anchor": ""}],
            "working_inferences": [{"statement": "Battery life may matter."}],
            "uncertainty_notes": [],
            "sources": [],
        }

        errors = validate_intake_payload(payload)

        self.assertTrue(any("question" in error for error in errors))
        self.assertTrue(any("scope" in error for error in errors))
        self.assertTrue(any("known_facts[1].statement" in error for error in errors))
        self.assertTrue(any("working_inferences[1].why_it_is_inference" in error for error in errors))

    def test_rejects_known_facts_that_reference_undefined_sources(self) -> None:
        payload = {
            "question": "Which option is better?",
            "scope": ["Compare option A and option B"],
            "constraints": ["Require citations"],
            "assumptions": [],
            "missing_information": [],
            "required_artifacts": ["judge report"],
            "notes_for_researchers": [],
            "known_facts": [
                {
                    "id": "KF-001",
                    "statement": "The brief asks for a comparison.",
                    "source_ids": ["DOC-BRIEF"],
                    "source_excerpt": "Compare option A and option B.",
                    "source_anchor": "brief.md#Question",
                }
            ],
            "working_inferences": [],
            "uncertainty_notes": [],
            "sources": [
                {
                    "id": "DOC-CONFIG",
                    "title": "Job config",
                    "type": "job_config",
                    "authority": "job input",
                    "locator": "config.yaml",
                    "source_class": "job_input",
                }
            ],
        }

        errors = validate_intake_payload(payload)

        self.assertTrue(any("references undefined source id" in error.lower() for error in errors))

    def test_rejects_known_facts_without_source_excerpt(self) -> None:
        payload = {
            "question": "Which option is better?",
            "scope": ["Compare option A and option B"],
            "constraints": ["Require citations"],
            "assumptions": [],
            "missing_information": [],
            "required_artifacts": ["judge report"],
            "notes_for_researchers": [],
            "known_facts": [{"id": "KF-001", "statement": "The brief asks for a comparison.", "source_ids": ["DOC-BRIEF"], "source_anchor": "brief.md#Question"}],
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
                }
            ],
        }

        errors = validate_intake_payload(payload)

        self.assertTrue(any("source_excerpt" in error for error in errors))

    def test_rejects_known_facts_without_source_anchor(self) -> None:
        payload = {
            "question": "Which option is better?",
            "scope": ["Compare option A and option B"],
            "constraints": ["Require citations"],
            "assumptions": [],
            "missing_information": [],
            "required_artifacts": ["judge report"],
            "notes_for_researchers": [],
            "known_facts": [
                {
                    "id": "KF-001",
                    "statement": "The brief asks for a comparison.",
                    "source_ids": ["DOC-BRIEF"],
                    "source_excerpt": "Compare option A and option B.",
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
                }
            ],
        }

        errors = validate_intake_payload(payload)

        self.assertTrue(any("source_anchor" in error for error in errors))

    def test_accepts_primary_alias_for_job_input_source_class_in_intake(self) -> None:
        payload = {
            "question": "Which option is better?",
            "scope": ["Compare option A and option B"],
            "constraints": ["Require citations"],
            "assumptions": [],
            "missing_information": [],
            "required_artifacts": ["judge report"],
            "notes_for_researchers": [],
            "known_facts": [
                {
                    "id": "KF-001",
                    "statement": "The brief asks for a comparison.",
                    "source_ids": ["DOC-BRIEF"],
                    "source_excerpt": "Compare option A and option B.",
                    "source_anchor": "brief.md#Question",
                }
            ],
            "working_inferences": [],
            "uncertainty_notes": [],
            "sources": [
                {
                    "id": "DOC-BRIEF",
                    "title": "Job brief",
                    "type": "job_input",
                    "authority": "user-provided brief",
                    "locator": "brief.md",
                    "source_class": "primary",
                }
            ],
        }

        self.assertEqual(validate_intake_payload(payload), [])


if __name__ == "__main__":
    unittest.main()

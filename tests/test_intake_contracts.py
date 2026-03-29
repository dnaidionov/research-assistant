import unittest
from pathlib import Path

import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from _intake_contracts import (
    merge_intake_substep_payloads,
    validate_intake_fact_lineage_payload,
    validate_intake_normalization_payload,
    validate_intake_payload,
    validate_intake_sources_payload,
)


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

    def test_rejects_known_facts_backed_by_non_job_input_sources(self) -> None:
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
                    "statement": "A vendor benchmark exists.",
                    "source_ids": ["SRC-001"],
                    "source_excerpt": "Benchmark claims 10x throughput.",
                    "source_anchor": "vendor-benchmark.pdf#Summary",
                }
            ],
            "working_inferences": [],
            "uncertainty_notes": [],
            "sources": [
                {
                    "id": "SRC-001",
                    "title": "Vendor benchmark",
                    "type": "benchmark report",
                    "authority": "vendor",
                    "locator": "vendor-benchmark.pdf",
                    "source_class": "external_evidence",
                }
            ],
        }

        errors = validate_intake_payload(payload)

        self.assertTrue(any("job_input" in error for error in errors))

    def test_rejects_working_inference_that_duplicates_known_fact(self) -> None:
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
            "working_inferences": [
                {
                    "statement": "The brief asks for a comparison.",
                    "why_it_is_inference": "This should not duplicate a known fact.",
                }
            ],
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

        self.assertTrue(any("duplicates known_facts" in error.lower() for error in errors))

    def test_rejects_source_anchor_without_document_reference(self) -> None:
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
                    "source_anchor": "QuestionOnly",
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

    def test_accepts_valid_decomposed_intake_substeps(self) -> None:
        sources_payload = {
            "stage": "intake",
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
        fact_payload = {
            "stage": "intake",
            "known_facts": [
                {
                    "id": "KF-001",
                    "statement": "The brief asks for a comparison.",
                    "source_ids": ["DOC-BRIEF"],
                    "source_excerpt": "Compare option A and option B.",
                    "source_anchor": "brief.md#Question",
                }
            ],
        }
        normalization_payload = {
            "stage": "intake",
            "question": "Which option is better?",
            "scope": ["Compare option A and option B"],
            "constraints": ["Require citations"],
            "assumptions": ["Hardware inputs remain unchanged"],
            "missing_information": ["Power measurements"],
            "required_artifacts": ["judge report"],
            "notes_for_researchers": ["Do not invent benchmarks"],
            "working_inferences": [{"statement": "Battery life may matter.", "why_it_is_inference": "The brief implies mobile use but does not state it directly."}],
            "uncertainty_notes": ["Scope may expand after intake review."],
        }

        self.assertEqual(validate_intake_sources_payload(sources_payload), [])
        self.assertEqual(validate_intake_fact_lineage_payload(fact_payload, sources_payload), [])
        self.assertEqual(validate_intake_normalization_payload(normalization_payload, fact_payload), [])

        merged = merge_intake_substep_payloads(sources_payload, fact_payload, normalization_payload)
        self.assertEqual(validate_intake_payload(merged), [])

    def test_rejects_mixed_fields_inside_decomposed_intake_substeps(self) -> None:
        sources_errors = validate_intake_sources_payload(
            {
                "stage": "intake",
                "sources": [],
                "question": "This does not belong in the source pass.",
            }
        )
        fact_errors = validate_intake_fact_lineage_payload(
            {
                "stage": "intake",
                "known_facts": [],
                "working_inferences": [],
            },
            {"stage": "intake", "sources": []},
        )
        normalization_errors = validate_intake_normalization_payload(
            {
                "stage": "intake",
                "question": "Which option is better?",
                "scope": [],
                "constraints": [],
                "assumptions": [],
                "missing_information": [],
                "required_artifacts": [],
                "notes_for_researchers": [],
                "working_inferences": [],
                "uncertainty_notes": [],
                "sources": [],
            },
            {"stage": "intake", "known_facts": []},
        )

        self.assertTrue(any("only" in error.lower() for error in sources_errors))
        self.assertTrue(any("working_inferences" in error for error in fact_errors))
        self.assertTrue(any("sources" in error for error in normalization_errors))


if __name__ == "__main__":
    unittest.main()

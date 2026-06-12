import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from generate_final_report import (  # noqa: E402
    FALLBACK_REPORT_STRUCTURE,
    build_synthesis_prompt,
    validate_report,
)

SOURCE_INDEX = {
    "SRC-001": {
        "id": "SRC-001",
        "title": "Canonical source",
        "source_class": "external_evidence",
        "locator": "https://example.com/src-001",
    },
    "DOC-INTAKE": {
        "id": "DOC-INTAKE",
        "title": "Intake artifact",
        "source_class": "workflow_provenance",
        "locator": "runs/run-001/stage-outputs/01-intake.json",
    },
}


class FinalReportValidationTests(unittest.TestCase):
    def test_cited_report_passes(self) -> None:
        markdown = (
            "# Executive Summary\n\n"
            "Option A has lower implementation risk. [SRC-001]\n\n"
            "# Recommendation\n\n"
            "Option A is the safer near-term choice. [SRC-001] Confidence: medium\n"
        )
        errors, _warnings = validate_report(markdown, SOURCE_INDEX)
        self.assertEqual(errors, [], errors)

    def test_uncited_fact_is_rejected(self) -> None:
        markdown = (
            "# Executive Summary\n\n"
            "Option A has lower implementation risk.\n\n"
            "# Recommendation\n\n"
            "Option A is the safer near-term choice. [SRC-001]\n"
        )
        errors, _warnings = validate_report(markdown, SOURCE_INDEX)
        self.assertTrue(any("uncited" in error for error in errors), errors)

    def test_hallucinated_source_id_is_rejected(self) -> None:
        markdown = (
            "# Executive Summary\n\n"
            "Option A has lower implementation risk. [SRC-FABRICATED]\n"
        )
        errors, _warnings = validate_report(markdown, SOURCE_INDEX)
        self.assertTrue(any("not in the run source registry" in error for error in errors), errors)

    def test_workflow_provenance_citation_is_rejected(self) -> None:
        markdown = (
            "# Executive Summary\n\n"
            "Option A has lower implementation risk. [DOC-INTAKE]\n"
        )
        errors, _warnings = validate_report(markdown, SOURCE_INDEX)
        self.assertTrue(
            any("not publishable evidence" in error or "workflow provenance" in error for error in errors),
            errors,
        )

    def test_missing_registry_is_warning_not_error(self) -> None:
        markdown = (
            "# Executive Summary\n\n"
            "Option A has lower implementation risk. [SRC-001]\n"
        )
        errors, warnings = validate_report(markdown, {})
        self.assertEqual(errors, [], errors)
        self.assertTrue(any("registry" in warning for warning in warnings), warnings)


class FinalReportPromptTests(unittest.TestCase):
    def test_prompt_is_domain_neutral_and_scoped_to_judge_record(self) -> None:
        prompt = build_synthesis_prompt(
            run_dir=Path("/tmp/job/runs/run-001"),
            output_path=Path("/tmp/job/runs/run-001/stage-outputs/07-final-report.md"),
            recommended_structure=list(FALLBACK_REPORT_STRUCTURE),
            judge_markdown="# Supported Conclusions\n\n1. Conclusion. [SRC-001]\n",
            claim_register_json="{\"claims\": []}",
        )
        self.assertIn("STAGE_ID=final-report", prompt)
        self.assertIn("Do not reintroduce any claim", prompt)
        self.assertIn("[SRC-001]", prompt)
        # The framework prompt must not embed job-specific research content.
        for leaked_token in ("XAVER", "Hailo", "battery", "On-Device Migration"):
            self.assertNotIn(leaked_token, prompt)

    def test_fallback_structure_is_generic(self) -> None:
        joined = " ".join(FALLBACK_REPORT_STRUCTURE)
        for leaked_token in ("XAVER", "Hailo", "Battery", "Thermal", "Migration"):
            self.assertNotIn(leaked_token, joined)
        self.assertIn("Candidate Landscape And Options Considered", FALLBACK_REPORT_STRUCTURE)


if __name__ == "__main__":
    unittest.main()

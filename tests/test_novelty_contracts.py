import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from _stage_contracts import (  # noqa: E402
    normalize_source_record,
    render_stage_markdown_from_json,
    source_quality_warnings,
    source_registry_placeholder,
    validate_stage_json,
)


def research_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "stage": "research-a",
        "summary": "Summary.",
        "facts": [{"id": "F-001", "text": "Fact.", "evidence_sources": ["SRC-001"]}],
        "inferences": [{"id": "I-001", "text": "Inference.", "evidence_sources": ["SRC-001"], "confidence": "high"}],
        "uncertainties": [],
        "evidence_gaps": [],
        "preliminary_disagreements": [],
        "source_evaluation": [],
        "sources": [
            {
                "id": "SRC-001",
                "title": "Vendor datasheet",
                "type": "official documentation",
                "authority": "vendor",
                "locator": "https://example.com/datasheet",
                "source_class": "external_evidence",
            }
        ],
    }
    payload.update(overrides)
    return payload


class FreshnessInferenceTests(unittest.TestCase):
    def test_recent_publication_date_is_fresh(self) -> None:
        recent = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")
        record = normalize_source_record(
            {"id": "SRC-001", "title": "T", "type": "report", "authority": "a", "locator": "https://example.com/x", "publication_date": recent}
        )
        self.assertEqual(record["freshness_status"], "fresh")

    def test_old_publication_date_is_stale(self) -> None:
        record = normalize_source_record(
            {"id": "SRC-001", "title": "T", "type": "report", "authority": "a", "locator": "https://example.com/x", "publication_date": "2020-01-01"}
        )
        self.assertEqual(record["freshness_status"], "stale")

    def test_missing_publication_date_is_undated(self) -> None:
        record = normalize_source_record(
            {"id": "SRC-001", "title": "T", "type": "report", "authority": "a", "locator": "https://example.com/x"}
        )
        self.assertEqual(record["freshness_status"], "undated")

    def test_unparseable_publication_date_is_unknown(self) -> None:
        record = normalize_source_record(
            {"id": "SRC-001", "title": "T", "type": "report", "authority": "a", "locator": "https://example.com/x", "publication_date": "next spring"}
        )
        self.assertEqual(record["freshness_status"], "unknown")

    def test_stale_source_gets_policy_warning_outcome(self) -> None:
        record = normalize_source_record(
            {"id": "SRC-001", "title": "T", "type": "report", "authority": "a", "locator": "https://example.com/x", "publication_date": "2019-06-01"}
        )
        self.assertEqual(record["policy_outcome"], "allowed_with_warning")

    def test_undated_external_evidence_produces_quality_warning(self) -> None:
        warnings = source_quality_warnings(research_payload())
        self.assertTrue(any("undated external evidence" in warning for warning in warnings))


class VendorAnnouncementTests(unittest.TestCase):
    def test_announcement_type_classifies_as_vendor_announcement(self) -> None:
        record = normalize_source_record(
            {
                "id": "SRC-NEW",
                "title": "New accelerator announced",
                "type": "vendor announcement",
                "authority": "vendor",
                "locator": "https://example.com/announcement",
                "source_class": "external_evidence",
            }
        )
        self.assertEqual(record["evidence_kind"], "vendor_announcement")
        self.assertEqual(record["authority_tier"], "vendor_announcement")
        self.assertEqual(record["policy_outcome"], "allowed_with_warning")
        self.assertTrue(any("availability risk" in note for note in record["policy_notes"]))

    def test_press_release_type_classifies_as_vendor_announcement(self) -> None:
        record = normalize_source_record(
            {
                "id": "SRC-PR",
                "title": "Press release",
                "type": "press release",
                "authority": "vendor",
                "locator": "https://example.com/pr",
            }
        )
        self.assertEqual(record["evidence_kind"], "vendor_announcement")

    def test_announcement_still_supports_world_claims(self) -> None:
        record = normalize_source_record(
            {
                "id": "SRC-NEW",
                "title": "New accelerator announced",
                "type": "vendor announcement",
                "authority": "vendor",
                "locator": "https://example.com/announcement",
            }
        )
        self.assertTrue(record["supports_world_claims"])


class CandidateValidationTests(unittest.TestCase):
    def registry(self) -> dict[str, object]:
        return source_registry_placeholder("run-xyz")

    def test_payload_without_candidates_remains_valid(self) -> None:
        errors = validate_stage_json("research-a", research_payload(), self.registry())
        self.assertEqual(errors, [], errors)

    def test_valid_candidates_pass(self) -> None:
        payload = research_payload(
            candidates=[
                {
                    "name": "Established Option",
                    "maturity": "ga",
                    "fit_summary": "Mature and proven.",
                    "evidence_sources": ["SRC-001"],
                },
                {
                    "name": "Announced Option",
                    "maturity": "announced_unreleased",
                    "fit_summary": "Could fit if shipped in time.",
                    "availability_risk": "No committed release date.",
                    "evidence_sources": ["SRC-001"],
                },
            ]
        )
        errors = validate_stage_json("research-a", payload, self.registry())
        self.assertEqual(errors, [], errors)

    def test_invalid_maturity_fails(self) -> None:
        payload = research_payload(
            candidates=[{"name": "X", "maturity": "vaporware", "fit_summary": "?", "evidence_sources": ["SRC-001"]}]
        )
        errors = validate_stage_json("research-a", payload, self.registry())
        self.assertTrue(any("maturity" in error for error in errors))

    def test_announced_candidate_requires_availability_risk(self) -> None:
        payload = research_payload(
            candidates=[
                {"name": "X", "maturity": "announced_unreleased", "fit_summary": "Promising.", "evidence_sources": ["SRC-001"]}
            ]
        )
        errors = validate_stage_json("research-a", payload, self.registry())
        self.assertTrue(any("availability_risk" in error for error in errors))

    def test_candidate_requires_resolvable_evidence(self) -> None:
        payload = research_payload(
            candidates=[{"name": "X", "maturity": "ga", "fit_summary": "Fine.", "evidence_sources": ["SRC-MISSING"]}]
        )
        errors = validate_stage_json("research-a", payload, self.registry())
        self.assertTrue(any("unresolved source id" in error for error in errors))

    def test_candidate_without_evidence_fails(self) -> None:
        payload = research_payload(
            candidates=[{"name": "X", "maturity": "ga", "fit_summary": "Fine.", "evidence_sources": []}]
        )
        errors = validate_stage_json("research-a", payload, self.registry())
        self.assertTrue(any("at least one evidence source" in error for error in errors))

    def test_markdown_rendering_includes_candidate_landscape(self) -> None:
        payload = research_payload(
            candidates=[
                {
                    "name": "Announced Option",
                    "maturity": "announced_unreleased",
                    "fit_summary": "Could fit if shipped in time.",
                    "availability_risk": "No committed release date.",
                    "evidence_sources": ["SRC-001"],
                }
            ]
        )
        markdown = render_stage_markdown_from_json("research-a", payload)
        self.assertIn("# Candidate Landscape", markdown)
        self.assertIn("Announced Option (announced_unreleased)", markdown)
        self.assertIn("Availability risk: No committed release date.", markdown)
        self.assertIn("[SRC-001]", markdown)

    def test_markdown_rendering_omits_section_without_candidates(self) -> None:
        markdown = render_stage_markdown_from_json("research-a", research_payload())
        self.assertNotIn("# Candidate Landscape", markdown)


if __name__ == "__main__":
    unittest.main()

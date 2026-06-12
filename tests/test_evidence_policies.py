import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from _stage_contracts import (  # noqa: E402
    configure_freshness_max_days,
    evidence_excerpt_findings,
    normalize_source_record,
    normalize_stage_citations,
    source_registry_placeholder,
)
from _stage_validation import (  # noqa: E402
    configure_excerpt_requirement,
    validate_structured_stage_artifact,
)


def research_payload(facts: list[dict[str, object]]) -> dict[str, object]:
    return {
        "stage": "research-a",
        "summary": "Summary.",
        "facts": facts,
        "inferences": [],
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


def fact(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {"id": "F-001", "text": "Fact.", "evidence_sources": ["SRC-001"]}
    base.update(overrides)
    return base


VALID_MARKDOWN = "\n".join(
    [
        "# Executive Summary",
        "",
        "Summary.",
        "",
        "# Facts",
        "",
        "1. Fact. [SRC-001]",
        "",
        "# Inferences",
        "",
        "# Uncertainty Register",
        "",
        "# Evidence Gaps",
        "",
        "# Preliminary Disagreements",
        "",
        "# Source Evaluation",
        "",
    ]
)


class FreshnessWindowConfigTests(unittest.TestCase):
    def tearDown(self) -> None:
        configure_freshness_max_days(None)

    def test_configured_window_reclassifies_freshness(self) -> None:
        ninety_days_ago = (datetime.now(timezone.utc) - timedelta(days=90)).strftime("%Y-%m-%d")
        source = {
            "id": "SRC-001",
            "title": "T",
            "type": "report",
            "authority": "a",
            "locator": "https://example.com/x",
            "publication_date": ninety_days_ago,
        }

        self.assertEqual(normalize_source_record(dict(source))["freshness_status"], "fresh")

        configure_freshness_max_days(30)
        self.assertEqual(normalize_source_record(dict(source))["freshness_status"], "stale")

    def test_none_resets_to_default_and_garbage_is_ignored(self) -> None:
        configure_freshness_max_days(30)
        configure_freshness_max_days("not-a-number")
        ninety_days_ago = (datetime.now(timezone.utc) - timedelta(days=90)).strftime("%Y-%m-%d")
        source = {
            "id": "SRC-001",
            "title": "T",
            "type": "report",
            "authority": "a",
            "locator": "https://example.com/x",
            "publication_date": ninety_days_ago,
        }
        self.assertEqual(normalize_source_record(dict(source))["freshness_status"], "stale")

        configure_freshness_max_days(None)
        self.assertEqual(normalize_source_record(dict(source))["freshness_status"], "fresh")


class EvidenceExcerptTests(unittest.TestCase):
    def tearDown(self) -> None:
        configure_excerpt_requirement(False)

    def test_missing_excerpt_is_flagged(self) -> None:
        payload = research_payload([fact()])
        findings = evidence_excerpt_findings("research-a", payload, source_registry_placeholder("run-x"))
        self.assertEqual(len(findings), 1)
        self.assertIn("without a quoted excerpt", findings[0])

    def test_evidence_link_with_excerpt_satisfies_requirement(self) -> None:
        payload = research_payload(
            [fact(support_links=[{"source_id": "SRC-001", "role": "evidence", "excerpt": "Quoted spec line."}])]
        )
        findings = evidence_excerpt_findings("research-a", payload, source_registry_placeholder("run-x"))
        self.assertEqual(findings, [], findings)

    def test_job_input_only_claims_do_not_require_excerpts(self) -> None:
        payload = research_payload([fact(evidence_sources=["DOC-BRIEF"])])
        payload["sources"] = [
            {
                "id": "DOC-BRIEF",
                "title": "Job brief",
                "type": "project_brief",
                "authority": "job input",
                "locator": "brief.md",
                "source_class": "job_input",
            }
        ]
        findings = evidence_excerpt_findings("research-a", payload, source_registry_placeholder("run-x"))
        self.assertEqual(findings, [], findings)

    def test_non_research_stages_are_not_checked(self) -> None:
        findings = evidence_excerpt_findings("judge", {"supported_conclusions": []}, source_registry_placeholder("run-x"))
        self.assertEqual(findings, [])

    def test_missing_excerpt_is_warning_by_default_and_error_when_strict(self) -> None:
        payload = research_payload([fact()])
        registry = source_registry_placeholder("run-x")

        result = validate_structured_stage_artifact("research-a", payload, registry, VALID_MARKDOWN)
        self.assertEqual(result.structured_errors, [], result.structured_errors)
        self.assertTrue(any("excerpt" in warning for warning in result.structured_warnings))

        configure_excerpt_requirement(True)
        strict_result = validate_structured_stage_artifact("research-a", payload, registry, VALID_MARKDOWN)
        self.assertTrue(any("excerpt" in error for error in strict_result.structured_errors))

    def test_normalization_preserves_excerpts_on_support_links(self) -> None:
        payload = research_payload(
            [fact(support_links=[{"source_id": "SRC-001", "role": "evidence", "excerpt": "Quoted spec line."}])]
        )
        normalized = normalize_stage_citations("research-a", payload)
        links = normalized["facts"][0]["support_links"]
        self.assertEqual(links[0].get("excerpt"), "Quoted spec line.")


if __name__ == "__main__":
    unittest.main()

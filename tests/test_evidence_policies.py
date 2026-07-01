import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from _stage_contracts import (  # noqa: E402
    configure_freshness_max_days,
    configure_source_policy,
    evidence_excerpt_findings,
    normalize_source_record,
    normalize_stage_citations,
    source_quality_warnings,
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


JOB_SOURCE_POLICY = {
    "preferred": ["official documentation", "academic papers"],
    "allowed_with_caution": ["analyst commentary"],
    "disallowed": ["anonymous blogs", "uncited forum posts"],
}


def external_source(source_type: str, authority: str = "independent") -> dict[str, object]:
    return {
        "id": "SRC-001",
        "title": "T",
        "type": source_type,
        "authority": authority,
        "locator": "https://example.com/x",
        "source_class": "external_evidence",
    }


class SourcePolicyEnforcementTests(unittest.TestCase):
    def setUp(self) -> None:
        configure_source_policy(JOB_SOURCE_POLICY)

    def tearDown(self) -> None:
        configure_source_policy(None)

    def test_disallowed_source_is_blocked_with_note(self) -> None:
        record = normalize_source_record(external_source("anonymous blog"))
        self.assertEqual(record["policy_outcome"], "blocked")
        self.assertEqual(record["source_policy_list"], "disallowed")
        self.assertEqual(record["authority_tier"], "policy_disallowed")
        self.assertTrue(any("disallows" in note for note in record["policy_notes"]), record["policy_notes"])

    def test_caution_source_is_allowed_with_warning(self) -> None:
        record = normalize_source_record(external_source("analyst commentary"))
        self.assertEqual(record["policy_outcome"], "allowed_with_warning")
        self.assertEqual(record["source_policy_list"], "allowed_with_caution")

    def test_preferred_match_cannot_relax_intrinsic_outcome(self) -> None:
        # "official documentation" is preferred, but a stale source stays warned.
        stale_date = (datetime.now(timezone.utc) - timedelta(days=800)).strftime("%Y-%m-%d")
        source = external_source("official documentation", authority="vendor")
        source["publication_date"] = stale_date
        record = normalize_source_record(source)
        self.assertEqual(record["policy_outcome"], "allowed_with_warning")
        self.assertEqual(record["source_policy_list"], "preferred")
        self.assertTrue(any("prefers" in note for note in record["policy_notes"]))

    def test_unmatched_source_is_untouched(self) -> None:
        record = normalize_source_record(external_source("technical report"))
        self.assertEqual(record["policy_outcome"], "allowed")
        self.assertNotIn("source_policy_list", record)

    def test_qualified_entries_do_not_match_unqualified_sources(self) -> None:
        # "uncited forum posts" is disallowed; a plain forum post is not.
        record = normalize_source_record(external_source("forum post"))
        self.assertEqual(record["policy_outcome"], "allowed")
        self.assertNotIn("source_policy_list", record)

        record = normalize_source_record(external_source("blog", authority="independent analyst"))
        self.assertEqual(record["policy_outcome"], "allowed")

        record = normalize_source_record(external_source("uncited forum post"))
        self.assertEqual(record["policy_outcome"], "blocked")

    def test_entry_qualifiers_may_span_type_and_authority(self) -> None:
        record = normalize_source_record(external_source("blog", authority="anonymous"))
        self.assertEqual(record["policy_outcome"], "blocked")

    def test_singular_type_matches_plural_entry(self) -> None:
        record = normalize_source_record(external_source("academic paper", authority="peer reviewed"))
        self.assertEqual(record["source_policy_list"], "preferred")

    def test_no_configured_policy_is_a_no_op(self) -> None:
        configure_source_policy(None)
        record = normalize_source_record(external_source("anonymous blog"))
        self.assertEqual(record["policy_outcome"], "allowed")

    def test_disallowed_and_caution_sources_produce_stage_warnings(self) -> None:
        payload = {
            "sources": [
                external_source("anonymous blog"),
                {**external_source("analyst commentary"), "id": "SRC-002", "locator": "https://example.com/y"},
            ]
        }
        warnings = source_quality_warnings(payload)
        self.assertTrue(any("disallowed source policy list" in warning for warning in warnings), warnings)
        self.assertTrue(any("allowed-with-caution" in warning for warning in warnings), warnings)

    def test_matching_is_idempotent_across_renormalization(self) -> None:
        record = normalize_source_record(external_source("anonymous blog"))
        renormalized = normalize_source_record(dict(record))
        self.assertEqual(renormalized["policy_outcome"], "blocked")
        self.assertEqual(
            [note for note in renormalized["policy_notes"] if "disallows" in note],
            [note for note in record["policy_notes"] if "disallows" in note],
        )


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

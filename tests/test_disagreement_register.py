import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from _disagreement_register import (  # noqa: E402
    apply_judge_dispositions,
    disagreement_register_path,
    merge_stage_disagreements,
)
from _stage_contracts import assign_disagreement_ids, normalize_stage_citations  # noqa: E402
from _stage_validation import (  # noqa: E402
    configure_disagreement_coverage_requirement,
    judge_disagreement_coverage_findings,
    validate_structured_stage_artifact,
)


class AssignDisagreementIdTests(unittest.TestCase):
    def test_string_entries_get_positional_ids(self) -> None:
        items = assign_disagreement_ids("critique-a-on-b", ["Latency claims conflict.", "Pricing is contested."])
        self.assertEqual([item["id"] for item in items], ["DIS-AB-001", "DIS-AB-002"])
        self.assertEqual(items[0]["text"], "Latency claims conflict.")

    def test_valid_agent_ids_are_kept_and_embedded_ids_are_lifted(self) -> None:
        items = assign_disagreement_ids(
            "critique-b-on-a",
            [
                {"id": "DIS-BA-007", "text": "Benchmark scope disputed."},
                "DIS-BA-002: Thermal envelope contested.",
            ],
        )
        self.assertEqual(items[0]["id"], "DIS-BA-007")
        self.assertEqual(items[1]["id"], "DIS-BA-002")
        self.assertEqual(items[1]["text"], "Thermal envelope contested.")

    def test_wrong_prefix_agent_ids_are_reassigned(self) -> None:
        # A critique must not claim ids in the sibling critique's namespace.
        items = assign_disagreement_ids(
            "critique-a-on-b",
            [{"id": "DIS-BA-001", "text": "Copied from the other pass."}],
        )
        self.assertEqual(items[0]["id"], "DIS-AB-001")

    def test_duplicate_and_malformed_ids_fall_back_to_positional(self) -> None:
        items = assign_disagreement_ids(
            "critique-a-on-b",
            [
                {"id": "DIS-AB-001", "text": "First."},
                {"id": "DIS-AB-001", "text": "Duplicate id."},
                {"id": "not-an-id", "text": "Malformed."},
            ],
        )
        ids = [item["id"] for item in items]
        self.assertEqual(len(set(ids)), 3)
        self.assertEqual(ids[0], "DIS-AB-001")

    def test_normalization_assigns_ids_for_critique_stages(self) -> None:
        payload = {
            "stage": "critique-a-on-b",
            "unresolved_disagreements": ["Contested point."],
        }
        normalized = normalize_stage_citations("critique-a-on-b", payload)
        self.assertEqual(normalized["unresolved_disagreements"][0]["id"], "DIS-AB-001")


class JudgeCoverageTests(unittest.TestCase):
    def tearDown(self) -> None:
        configure_disagreement_coverage_requirement(False)

    def critique_dependency(self) -> dict[str, object]:
        return {
            "stage": "critique-a-on-b",
            "unresolved_disagreements": [
                {"id": "DIS-AB-001", "text": "Latency claims conflict."},
                {"id": "DIS-AB-002", "text": "Pricing is contested."},
            ],
        }

    def judge_payload(self, mention: str) -> dict[str, object]:
        return {
            "stage": "judge",
            "supported_conclusions": [],
            "synthesis_judgments": [],
            "unresolved_disagreements": [f"{mention}: still open, evidence is mixed."],
            "confidence_assessment": "Medium.",
            "evidence_gaps": [],
            "rationale": ["DIS-AB-002 resolved: pricing confirmed by two sources."],
            "recommended_artifact_structure": ["Summary"],
            "sources": [],
        }

    def test_unmentioned_ids_are_flagged(self) -> None:
        findings = judge_disagreement_coverage_findings(
            self.judge_payload("DIS-AB-001"), [self.critique_dependency()]
        )
        self.assertEqual(findings, [], findings)

        findings = judge_disagreement_coverage_findings(
            self.judge_payload("something else"), [self.critique_dependency()]
        )
        self.assertEqual(len(findings), 1)
        self.assertIn("DIS-AB-001", findings[0])

    def test_coverage_is_warning_by_default_and_error_when_strict(self) -> None:
        judge = self.judge_payload("no ids mentioned at all")
        judge["rationale"] = ["General rationale."]
        markdown = "\n".join(
            [
                "# Supported Conclusions",
                "",
                "# Inferences And Synthesis Judgments",
                "",
                "# Unresolved Disagreements",
                "",
                "- Still open.",
                "",
                "# Confidence Assessment",
                "",
                "Medium.",
                "",
                "# Evidence Gaps",
                "",
                "# Rationale And Traceability",
                "",
                "# Recommended Final Artifact Structure",
                "",
                "- Summary",
            ]
        )
        result = validate_structured_stage_artifact(
            "judge", judge, {"sources": []}, markdown, [self.critique_dependency()]
        )
        self.assertEqual(result.structured_errors, [], result.structured_errors)
        self.assertTrue(any("DIS-AB-001" in warning for warning in result.structured_warnings))

        configure_disagreement_coverage_requirement(True)
        strict = validate_structured_stage_artifact(
            "judge", judge, {"sources": []}, markdown, [self.critique_dependency()]
        )
        self.assertTrue(any("DIS-AB-001" in error for error in strict.structured_errors))


class RegisterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.run_dir = Path(self.tmpdir.name)

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_register_merges_critiques_and_records_judge_dispositions(self) -> None:
        merge_stage_disagreements(
            self.run_dir,
            "critique-a-on-b",
            {"unresolved_disagreements": [{"id": "DIS-AB-001", "text": "Latency conflict."}]},
        )
        merge_stage_disagreements(
            self.run_dir,
            "critique-b-on-a",
            {"unresolved_disagreements": [{"id": "DIS-BA-001", "text": "Coverage gap."}]},
        )
        register = json.loads(disagreement_register_path(self.run_dir).read_text(encoding="utf-8"))
        self.assertEqual({entry["id"] for entry in register["disagreements"]}, {"DIS-AB-001", "DIS-BA-001"})
        self.assertTrue(all(entry["status"] == "open" for entry in register["disagreements"]))

        apply_judge_dispositions(
            self.run_dir,
            {
                "unresolved_disagreements": ["DIS-AB-001: still open."],
                "rationale": ["No mention of the other id."],
            },
        )
        register = json.loads(disagreement_register_path(self.run_dir).read_text(encoding="utf-8"))
        statuses = {entry["id"]: entry["status"] for entry in register["disagreements"]}
        self.assertEqual(statuses["DIS-AB-001"], "unresolved_by_judge")
        self.assertEqual(statuses["DIS-BA-001"], "unaddressed")

    def test_remerge_is_idempotent(self) -> None:
        payload = {"unresolved_disagreements": [{"id": "DIS-AB-001", "text": "Latency conflict."}]}
        merge_stage_disagreements(self.run_dir, "critique-a-on-b", payload)
        merge_stage_disagreements(self.run_dir, "critique-a-on-b", payload)
        register = json.loads(disagreement_register_path(self.run_dir).read_text(encoding="utf-8"))
        self.assertEqual(len(register["disagreements"]), 1)

    def test_rerun_replaces_the_stage_entries_without_stranding_stale_ones(self) -> None:
        merge_stage_disagreements(
            self.run_dir,
            "critique-a-on-b",
            {
                "unresolved_disagreements": [
                    {"id": "DIS-AB-001", "text": "First."},
                    {"id": "DIS-AB-002", "text": "Second, later withdrawn."},
                ]
            },
        )
        merge_stage_disagreements(
            self.run_dir,
            "critique-b-on-a",
            {"unresolved_disagreements": [{"id": "DIS-BA-001", "text": "Sibling entry."}]},
        )
        # Rerun of critique-a-on-b drops its second disagreement.
        merge_stage_disagreements(
            self.run_dir,
            "critique-a-on-b",
            {"unresolved_disagreements": [{"id": "DIS-AB-001", "text": "First."}]},
        )
        register = json.loads(disagreement_register_path(self.run_dir).read_text(encoding="utf-8"))
        ids = {entry["id"] for entry in register["disagreements"]}
        self.assertEqual(ids, {"DIS-AB-001", "DIS-BA-001"})


if __name__ == "__main__":
    unittest.main()

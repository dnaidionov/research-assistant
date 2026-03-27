import tempfile
import unittest
from pathlib import Path

import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from _stage_contracts import (
    build_claim_map_from_stage_json,
    merge_source_registry,
    normalize_stage_citations,
    render_stage_markdown_from_json,
    source_quality_warnings,
    source_registry_placeholder,
    validate_stage_json,
)


class StageContractTests(unittest.TestCase):
    def test_accepts_structured_critique_payload(self) -> None:
        payload = {
            "stage": "critique-a-on-b",
            "supported_claims": [
                {"text": "The baseline processing split is well supported.", "evidence_sources": ["SRC-001"]}
            ],
            "unsupported_claims": [
                {
                    "target_claim": "Battery life will improve automatically.",
                    "reason": "No system power budget is provided.",
                    "needed_evidence": "Measured subsystem power draw.",
                    "evidence_sources": ["SRC-002"],
                }
            ],
            "weak_source_issues": [
                {"text": "One hardware claim depends on marketing material.", "evidence_sources": ["SRC-003"]}
            ],
            "omissions": [
                {"text": "Thermal design trade-offs were not compared.", "evidence_sources": ["SRC-004"]}
            ],
            "overreach": [
                {"text": "Inference is stronger than the cited benchmark supports.", "evidence_sources": ["SRC-005"]}
            ],
            "unresolved_disagreements": [
                {"text": "Jetson versus accelerator-only remains unresolved.", "evidence_sources": ["SRC-006"]}
            ],
            "summary": {
                "text": "The target report is directionally sound but too confident on battery and thermal claims.",
                "confidence": "medium",
            },
            "sources": [
                {"id": "SRC-001", "title": "Source 1", "type": "document", "authority": "vendor", "locator": "https://example.com/src-001"},
                {"id": "SRC-002", "title": "Source 2", "type": "document", "authority": "vendor", "locator": "https://example.com/src-002"},
                {"id": "SRC-003", "title": "Source 3", "type": "document", "authority": "vendor", "locator": "https://example.com/src-003"},
                {"id": "SRC-004", "title": "Source 4", "type": "document", "authority": "vendor", "locator": "https://example.com/src-004"},
                {"id": "SRC-005", "title": "Source 5", "type": "document", "authority": "vendor", "locator": "https://example.com/src-005"},
                {"id": "SRC-006", "title": "Source 6", "type": "document", "authority": "vendor", "locator": "https://example.com/src-006"},
            ],
        }
        registry = source_registry_placeholder("run-xyz")

        errors = validate_stage_json("critique-a-on-b", payload, registry)

        self.assertEqual(errors, [], errors)

    def test_normalizes_missing_source_class_for_job_input_and_external_evidence(self) -> None:
        payload = {
            "stage": "judge",
            "supported_conclusions": [
                {"id": "C-001", "text": "Conclusion.", "evidence_sources": ["DOC-001", "SRC-001"]}
            ],
            "synthesis_judgments": [
                {"id": "J-001", "text": "Judgment.", "evidence_sources": ["SRC-001"], "confidence": "medium"}
            ],
            "unresolved_disagreements": [],
            "confidence_assessment": [],
            "evidence_gaps": [],
            "rationale": [],
            "recommended_artifact_structure": [],
            "sources": [
                {"id": "DOC-001", "title": "Job brief", "type": "project_brief", "authority": "Job input", "locator": "brief.md"},
                {"id": "SRC-001", "title": "Vendor source", "type": "official documentation", "authority": "vendor", "locator": "https://example.com/src-001"},
            ],
        }
        registry = source_registry_placeholder("run-xyz")

        errors = validate_stage_json("judge", payload, registry)

        self.assertEqual(errors, [], errors)

    def test_rejects_unknown_source_class(self) -> None:
        payload = {
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
                    "title": "Source",
                    "type": "document",
                    "authority": "vendor",
                    "locator": "https://example.com/src-001",
                    "source_class": "mystery",
                }
            ],
        }
        registry = source_registry_placeholder("run-xyz")

        errors = validate_stage_json("research-a", payload, registry)

        self.assertTrue(any("source_class" in error for error in errors))

    def test_semantic_support_links_distinguish_evidence_from_provenance(self) -> None:
        payload = {
            "stage": "judge",
            "supported_conclusions": [
                {
                    "id": "C-001",
                    "text": "Option A is feasible.",
                    "evidence_sources": ["SRC-001"],
                    "support_links": [
                        {"source_id": "SRC-001", "role": "evidence"},
                        {"source_id": "DOC-001", "role": "context"},
                        {"source_id": "SRC-WF", "role": "provenance"},
                    ],
                }
            ],
            "synthesis_judgments": [
                {
                    "id": "J-001",
                    "text": "Option A is preferred.",
                    "evidence_sources": ["SRC-001"],
                    "confidence": "medium",
                    "support_links": [
                        {"source_id": "SRC-001", "role": "evidence"},
                        {"source_id": "SRC-WF", "role": "provenance"},
                    ],
                }
            ],
            "unresolved_disagreements": [],
            "confidence_assessment": [],
            "evidence_gaps": [],
            "rationale": [],
            "recommended_artifact_structure": [],
            "sources": [
                {"id": "SRC-001", "title": "Vendor source", "type": "official documentation", "authority": "vendor", "locator": "https://example.com/src-001", "source_class": "external_evidence"},
                {"id": "DOC-001", "title": "Job brief", "type": "project_brief", "authority": "Job input", "locator": "brief.md", "source_class": "job_input"},
                {"id": "SRC-WF", "title": "Workflow critique artifact", "type": "workflow_artifact", "authority": "runner", "locator": "urn:workflow:critique", "source_class": "workflow_provenance"},
            ],
        }
        registry = source_registry_placeholder("run-xyz")

        errors = validate_stage_json("judge", payload, registry)
        claim_map = build_claim_map_from_stage_json("judge", payload)

        self.assertEqual(errors, [], errors)
        first_claim = claim_map["claims"][0]
        self.assertEqual(first_claim["evidence_sources"], ["SRC-001", "DOC-001"])
        self.assertEqual(first_claim["provenance"], ["SRC-WF"])
        self.assertEqual(first_claim["support_links"][0]["role"], "evidence")

    def test_semantic_links_require_semantic_evidence_for_world_claims(self) -> None:
        payload = {
            "stage": "judge",
            "supported_conclusions": [
                {
                    "id": "C-001",
                    "text": "Option A is feasible.",
                    "evidence_sources": [],
                    "support_links": [
                        {"source_id": "SRC-WF", "role": "provenance"}
                    ],
                }
            ],
            "synthesis_judgments": [],
            "unresolved_disagreements": [],
            "confidence_assessment": [],
            "evidence_gaps": [],
            "rationale": [],
            "recommended_artifact_structure": [],
            "sources": [
                {"id": "SRC-WF", "title": "Workflow critique artifact", "type": "workflow_artifact", "authority": "runner", "locator": "urn:workflow:critique", "source_class": "workflow_provenance"}
            ],
        }
        registry = source_registry_placeholder("run-xyz")

        errors = validate_stage_json("judge", payload, registry)

        self.assertTrue(any("semantic evidence" in error.lower() for error in errors))

    def test_critique_semantic_support_links_are_validated(self) -> None:
        payload = {
            "stage": "critique-a-on-b",
            "supported_claims": [
                {
                    "text": "The latency claim survives review.",
                    "evidence_sources": ["SRC-001"],
                    "support_links": [
                        {"source_id": "SRC-001", "role": "evidence"},
                        {"source_id": "SRC-WF", "role": "provenance"},
                    ],
                }
            ],
            "unsupported_claims": [],
            "weak_source_issues": [],
            "omissions": [],
            "overreach": [],
            "unresolved_disagreements": [],
            "summary": {"text": "Mostly sound.", "confidence": "medium"},
            "sources": [
                {"id": "SRC-001", "title": "Benchmarks", "type": "report", "authority": "vendor", "locator": "https://example.com/src-001", "source_class": "external_evidence"},
                {"id": "SRC-WF", "title": "Research A artifact", "type": "workflow_artifact", "authority": "runner", "locator": "urn:workflow:research-a", "source_class": "workflow_provenance"},
            ],
        }
        registry = source_registry_placeholder("run-xyz")

        errors = validate_stage_json("critique-a-on-b", payload, registry)
        claim_map = build_claim_map_from_stage_json("critique-a-on-b", payload)

        self.assertEqual(errors, [], errors)
        self.assertEqual(claim_map["claims"][0]["evidence_sources"], ["SRC-001"])
        self.assertEqual(claim_map["claims"][0]["provenance"], ["SRC-WF"])

    def test_critique_semantic_links_reject_provenance_only_support(self) -> None:
        payload = {
            "stage": "critique-b-on-a",
            "supported_claims": [
                {
                    "text": "The throughput claim survives review.",
                    "evidence_sources": [],
                    "support_links": [
                        {"source_id": "SRC-WF", "role": "provenance"}
                    ],
                }
            ],
            "unsupported_claims": [],
            "weak_source_issues": [],
            "omissions": [],
            "overreach": [],
            "unresolved_disagreements": [],
            "summary": {"text": "Not supportable.", "confidence": "low"},
            "sources": [
                {"id": "SRC-WF", "title": "Research artifact", "type": "workflow_artifact", "authority": "runner", "locator": "urn:workflow:research-b", "source_class": "workflow_provenance"}
            ],
        }
        registry = source_registry_placeholder("run-xyz")

        errors = validate_stage_json("critique-b-on-a", payload, registry)

        self.assertTrue(any("semantic evidence" in error.lower() for error in errors))

    def test_builds_claim_map_and_markdown_from_structured_critique_payload(self) -> None:
        payload = {
            "stage": "critique-b-on-a",
            "supported_claims": [
                {"text": "The current pipeline split is well supported.", "evidence_sources": ["SRC-001"]}
            ],
            "unsupported_claims": [
                {
                    "target_claim": "Battery life will improve automatically.",
                    "reason": "No system power budget is provided.",
                    "needed_evidence": "Measured subsystem power draw.",
                    "evidence_sources": ["SRC-002"],
                }
            ],
            "weak_source_issues": ["Thermal claim rests on indirect evidence."],
            "omissions": ["No comparison against lower-power accelerators."],
            "overreach": ["The recommendation outruns the benchmark evidence."],
            "unresolved_disagreements": ["Jetson versus accelerator-only remains unresolved."],
            "summary": {"text": "The target report is too confident on battery claims.", "confidence": "medium"},
            "sources": [
                {"id": "SRC-001", "title": "Source 1", "type": "document", "authority": "vendor", "locator": "https://example.com/src-001"},
                {"id": "SRC-002", "title": "Source 2", "type": "document", "authority": "vendor", "locator": "https://example.com/src-002"},
            ],
        }

        claim_map = build_claim_map_from_stage_json("critique-b-on-a", payload)
        markdown = render_stage_markdown_from_json("critique-b-on-a", payload)

        self.assertTrue(any(claim["type"] == "evaluation" for claim in claim_map["claims"]))
        self.assertIn("# Unsupported Claims", markdown)
        self.assertIn("Battery life will improve automatically.", markdown)
        self.assertIn("Confidence: medium", markdown)

    def test_accepts_flexible_non_critical_research_sections(self) -> None:
        payload = {
            "stage": "research-b",
            "summary": "Feasible with a heterogeneous SoC path.",
            "facts": [
                {"id": "F-001", "text": "Current processing is split across FPGA and laptop.", "evidence_sources": ["SRC-001"]}
            ],
            "inferences": [
                {
                    "id": "I-001",
                    "text": "A heterogeneous SoC is the strongest consolidation path.",
                    "evidence_sources": ["SRC-001", "SRC-002"],
                    "confidence": "high",
                }
            ],
            "uncertainties": [
                {
                    "issue": "Battery draw mismatch",
                    "impact": "High",
                    "reduction_strategy": "Measure current draw under load.",
                }
            ],
            "evidence_gaps": ["Detailed RF front-end power profile."],
            "preliminary_disagreements": ["Single-SoC versus multi-chip architecture trade-off."],
            "source_evaluation": [
                {
                    "id": "SRC-001",
                    "source_name": "brief.md",
                    "quality": "High",
                    "limitation": "Possible inconsistency in power/runtime data.",
                }
            ],
            "sources": [
                {"id": "SRC-001", "title": "Brief", "type": "document", "authority": "client", "locator": "brief.md"},
                {
                    "id": "SRC-002",
                    "title": "Hardware docs",
                    "type": "vendor documentation",
                    "authority": "vendor",
                    "locator": "https://example.com/hardware",
                },
            ],
        }
        registry = source_registry_placeholder("run-xyz")

        errors = validate_stage_json("research-b", payload, registry)

        self.assertEqual(errors, [], errors)

    def test_accepts_source_evaluation_items_with_local_ids_and_text(self) -> None:
        payload = {
            "stage": "research-a",
            "summary": "Feasible with a hybrid architecture.",
            "facts": [
                {"id": "F-001", "text": "Fact.", "evidence_sources": ["SRC-001"]}
            ],
            "inferences": [
                {"id": "I-001", "text": "Inference.", "evidence_sources": ["SRC-001"], "confidence": "high"}
            ],
            "uncertainties": ["Gap."],
            "evidence_gaps": ["Missing benchmark."],
            "preliminary_disagreements": ["Architecture trade-off remains."],
            "source_evaluation": [
                {"id": "SE1", "text": "Vendor sources are authoritative for platform specs but weak on workload-specific latency.", "evidence_sources": ["SRC-001"]}
            ],
            "sources": [
                {"id": "SRC-001", "title": "Source", "type": "document", "authority": "vendor", "locator": "https://example.com/src-001"}
            ],
        }
        registry = source_registry_placeholder("run-xyz")

        errors = validate_stage_json("research-a", payload, registry)

        self.assertEqual(errors, [], errors)

    def test_accepts_source_evaluation_items_with_assessment_or_source_metadata(self) -> None:
        payload = {
            "stage": "research-a",
            "summary": "Feasible with a hybrid architecture.",
            "facts": [
                {"id": "F-001", "text": "Fact.", "evidence_sources": ["SRC-001"]}
            ],
            "inferences": [
                {"id": "I-001", "text": "Inference.", "evidence_sources": ["SRC-001"], "confidence": "high"}
            ],
            "uncertainties": ["Gap."],
            "evidence_gaps": ["Missing benchmark."],
            "preliminary_disagreements": ["Architecture trade-off remains."],
            "source_evaluation": [
                {"source_group": "SRC-001", "assessment": "Primary source for baseline constraints."},
                {
                    "id": "SRC-002",
                    "title": "Vendor spec",
                    "type": "official documentation",
                    "authority": "primary",
                    "locator": "https://example.com/src-002",
                },
            ],
            "sources": [
                {"id": "SRC-001", "title": "Source 1", "type": "document", "authority": "vendor", "locator": "https://example.com/src-001"},
                {"id": "SRC-002", "title": "Source 2", "type": "document", "authority": "vendor", "locator": "https://example.com/src-002"},
            ],
        }
        registry = source_registry_placeholder("run-xyz")

        errors = validate_stage_json("research-a", payload, registry)

        self.assertEqual(errors, [], errors)

    def test_accepts_source_evaluation_group_labels(self) -> None:
        payload = {
            "stage": "research-b",
            "summary": "Feasible with edge compute.",
            "facts": [
                {"id": "FACT-001", "text": "Fact one.", "evidence_sources": ["SRC-001"]}
            ],
            "inferences": [
                {"id": "INF-001", "text": "Inference built on prior facts.", "evidence_sources": ["SRC-001"], "confidence": "high"}
            ],
            "uncertainties": ["Gap."],
            "evidence_gaps": ["Missing benchmark."],
            "preliminary_disagreements": ["Architecture trade-off remains."],
            "source_evaluation": [
                {"source_group": "Academic Research (IEEE)", "quality": "high", "limitation": "Lab-biased results."}
            ],
            "sources": [
                {"id": "SRC-001", "title": "Source 1", "type": "document", "authority": "vendor", "locator": "https://example.com/src-001"}
            ],
        }
        registry = source_registry_placeholder("run-xyz")

        errors = validate_stage_json("research-b", payload, registry)

        self.assertEqual(errors, [], errors)

    def test_normalizes_local_fact_references_inside_inferences(self) -> None:
        payload = {
            "stage": "research-b",
            "summary": "Feasible with edge compute.",
            "facts": [
                {"id": "FACT-001", "text": "Fact one.", "evidence_sources": ["SRC-001"]},
                {"id": "FACT-002", "text": "Fact two.", "evidence_sources": ["SRC-002"]},
            ],
            "inferences": [
                {
                    "id": "INF-001",
                    "text": "Inference built on prior facts.",
                    "evidence_sources": ["FACT-001", "FACT-002"],
                    "confidence": "high",
                }
            ],
            "uncertainties": ["Gap."],
            "evidence_gaps": ["Missing benchmark."],
            "preliminary_disagreements": ["Architecture trade-off remains."],
            "source_evaluation": ["Useful note."],
            "sources": [
                {"id": "SRC-001", "title": "Source 1", "type": "document", "authority": "vendor", "locator": "https://example.com/src-001"},
                {"id": "SRC-002", "title": "Source 2", "type": "document", "authority": "vendor", "locator": "https://example.com/src-002"},
            ],
        }

        normalized = normalize_stage_citations("research-b", payload)
        registry = source_registry_placeholder("run-xyz")
        errors = validate_stage_json("research-b", normalized, registry)

        self.assertEqual(normalized["inferences"][0]["evidence_sources"], ["SRC-001", "SRC-002"])
        self.assertEqual(errors, [], errors)

    def test_normalizes_local_fact_references_inside_support_links_into_claim_dependencies(self) -> None:
        payload = {
            "stage": "research-b",
            "summary": "Feasible with edge compute.",
            "facts": [
                {"id": "FACT-001", "text": "Fact one.", "evidence_sources": ["SRC-001"]},
                {"id": "FACT-002", "text": "Fact two.", "evidence_sources": ["SRC-002"]},
            ],
            "inferences": [
                {
                    "id": "INF-001",
                    "text": "Inference built on prior facts.",
                    "evidence_sources": ["FACT-001", "FACT-002"],
                    "support_links": [
                        {"source_id": "FACT-001", "role": "evidence"},
                        {"source_id": "FACT-002", "role": "context"},
                    ],
                    "confidence": "high",
                }
            ],
            "uncertainties": ["Gap."],
            "evidence_gaps": ["Missing benchmark."],
            "preliminary_disagreements": ["Architecture trade-off remains."],
            "source_evaluation": ["Useful note."],
            "sources": [
                {"id": "SRC-001", "title": "Source 1", "type": "document", "authority": "vendor", "locator": "https://example.com/src-001"},
                {"id": "SRC-002", "title": "Source 2", "type": "document", "authority": "vendor", "locator": "https://example.com/src-002"},
            ],
        }

        normalized = normalize_stage_citations("research-b", payload)
        registry = source_registry_placeholder("run-xyz")
        errors = validate_stage_json("research-b", normalized, registry)
        claim_map = build_claim_map_from_stage_json("research-b", normalized)

        self.assertEqual(errors, [], errors)
        self.assertEqual(normalized["inferences"][0]["claim_dependencies"], ["FACT-001", "FACT-002"])
        self.assertEqual(
            normalized["inferences"][0]["support_links"],
            [
                {"source_id": "SRC-001", "role": "evidence"},
                {"source_id": "SRC-002", "role": "context"},
            ],
        )
        self.assertEqual(claim_map["claims"][2]["claim_dependencies"], ["FACT-001", "FACT-002"])

    def test_rejects_vague_external_evidence_locator(self) -> None:
        payload = {
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
                    "title": "Benchmark summary",
                    "type": "trade publication",
                    "authority": "vendor roundup",
                    "locator": "Various industry benchmarks",
                    "source_class": "external_evidence",
                }
            ],
        }
        registry = source_registry_placeholder("run-xyz")

        errors = validate_stage_json("research-a", payload, registry)

        self.assertTrue(any("auditable locator" in error for error in errors))

    def test_accepts_external_evidence_with_local_file_locator(self) -> None:
        payload = {
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
                    "title": "Attached PDF",
                    "type": "pdf",
                    "authority": "fixture",
                    "locator": "/tmp/evidence.pdf",
                    "source_class": "external_evidence",
                }
            ],
        }
        registry = source_registry_placeholder("run-xyz")

        errors = validate_stage_json("research-a", payload, registry)

        self.assertEqual(errors, [], errors)

    def test_accepts_external_evidence_with_file_uri_locator(self) -> None:
        payload = {
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
                    "title": "Attached PDF",
                    "type": "pdf",
                    "authority": "fixture",
                    "locator": "file:///tmp/evidence.pdf",
                    "source_class": "external_evidence",
                }
            ],
        }
        registry = source_registry_placeholder("run-xyz")

        errors = validate_stage_json("research-a", payload, registry)

        self.assertEqual(errors, [], errors)

    def test_accepts_job_input_as_world_supporting_evidence_when_labeled_evidence(self) -> None:
        payload = {
            "stage": "research-a",
            "summary": "Summary.",
            "facts": [
                {
                    "id": "F-001",
                    "text": "The brief states the current system uses an external laptop.",
                    "evidence_sources": ["DOC-001"],
                    "support_links": [{"source_id": "DOC-001", "role": "evidence"}],
                }
            ],
            "inferences": [
                {
                    "id": "I-001",
                    "text": "Removing the laptop is a valid upgrade target.",
                    "evidence_sources": ["DOC-001"],
                    "support_links": [{"source_id": "DOC-001", "role": "evidence"}],
                    "confidence": "medium",
                }
            ],
            "uncertainties": [],
            "evidence_gaps": [],
            "preliminary_disagreements": [],
            "source_evaluation": [],
            "sources": [
                {
                    "id": "DOC-001",
                    "title": "Job brief",
                    "type": "project_brief",
                    "authority": "client",
                    "locator": "brief.md",
                    "source_class": "job_input",
                }
            ],
        }
        registry = source_registry_placeholder("run-xyz")

        errors = validate_stage_json("research-a", payload, registry)
        claim_map = build_claim_map_from_stage_json("research-a", payload)

        self.assertEqual(errors, [], errors)
        self.assertEqual(claim_map["claims"][0]["evidence_sources"], ["DOC-001"])

    def test_normalizes_local_claim_references_inside_critique_entries(self) -> None:
        payload = {
            "stage": "critique-a-on-b",
            "supported_claims": [
                {
                    "text": "The target's core pipeline description is accurate.",
                    "evidence_sources": ["F-001"],
                    "support_links": [{"source_id": "F-001", "role": "evidence"}],
                }
            ],
            "unsupported_claims": [],
            "weak_source_issues": [],
            "omissions": [],
            "overreach": [],
            "unresolved_disagreements": [],
            "summary": {"text": "Mostly sound.", "confidence": "medium"},
            "sources": [
                {"id": "SRC-001", "title": "Source 1", "type": "document", "authority": "vendor", "locator": "https://example.com/src-001"}
            ],
            "target_claim_catalog": [
                {"id": "F-001", "evidence_sources": ["SRC-001"]}
            ],
        }

        normalized = normalize_stage_citations("critique-a-on-b", payload)
        errors = validate_stage_json("critique-a-on-b", normalized, source_registry_placeholder("run-xyz"))

        self.assertEqual(errors, [], errors)
        self.assertEqual(normalized["supported_claims"][0]["evidence_sources"], ["SRC-001"])
        self.assertEqual(normalized["supported_claims"][0]["claim_dependencies"], ["F-001"])
        self.assertEqual(normalized["supported_claims"][0]["support_links"], [{"source_id": "SRC-001", "role": "evidence"}])

    def test_bare_domain_external_locator_produces_warning_not_error(self) -> None:
        payload = {
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
                    "title": "Vendor page",
                    "type": "official documentation",
                    "authority": "vendor",
                    "locator": "example.com",
                    "source_class": "external_evidence",
                }
            ],
        }

        errors = validate_stage_json("research-a", payload, source_registry_placeholder("run-xyz"))
        warnings = source_quality_warnings(payload)

        self.assertEqual(errors, [], errors)
        self.assertTrue(any("bare domain" in warning.lower() for warning in warnings))

    def test_job_input_prompt_packet_locator_produces_canonical_artifact_warning(self) -> None:
        payload = {
            "stage": "research-a",
            "summary": "Summary.",
            "facts": [{"id": "F-001", "text": "Fact.", "evidence_sources": ["DOC-001"]}],
            "inferences": [{"id": "I-001", "text": "Inference.", "evidence_sources": ["DOC-001"], "confidence": "high"}],
            "uncertainties": [],
            "evidence_gaps": [],
            "preliminary_disagreements": [],
            "source_evaluation": [],
            "sources": [
                {
                    "id": "DOC-001",
                    "title": "Prompt packet brief excerpt",
                    "type": "project_brief",
                    "authority": "runner",
                    "locator": "/tmp/example/runs/run-001/prompt-packets/02-research-a.md",
                    "source_class": "job_input",
                }
            ],
        }

        errors = validate_stage_json("research-a", payload, source_registry_placeholder("run-xyz"))
        warnings = source_quality_warnings(payload)

        self.assertEqual(errors, [], errors)
        self.assertTrue(any("prompt packet" in warning.lower() for warning in warnings))

    def test_external_evidence_root_url_produces_locator_precision_warning(self) -> None:
        payload = {
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
                    "title": "Vendor root page",
                    "type": "official documentation",
                    "authority": "vendor",
                    "locator": "https://example.com/",
                    "source_class": "external_evidence",
                }
            ],
        }

        errors = validate_stage_json("research-a", payload, source_registry_placeholder("run-xyz"))
        warnings = source_quality_warnings(payload)

        self.assertEqual(errors, [], errors)
        self.assertTrue(any("exact location" in warning.lower() for warning in warnings))

    def test_source_registry_upgrades_bare_domain_to_specific_page_locator(self) -> None:
        existing = {
            "run_id": "run-xyz",
            "notes": "",
            "sources": [
                {
                    "id": "SRC-001",
                    "title": "Vendor source",
                    "type": "official documentation",
                    "authority": "vendor",
                    "locator": "example.com",
                    "source_class": "external_evidence",
                }
            ],
        }
        stage_sources = [
            {
                "id": "SRC-001",
                "title": "Vendor source",
                "type": "official documentation",
                "authority": "vendor",
                "locator": "https://example.com/products/radar-board",
                "source_class": "external_evidence",
            }
        ]

        merged = merge_source_registry(existing, stage_sources)

        self.assertEqual(
            merged["sources"][0]["locator"],
            "https://example.com/products/radar-board",
        )

    def test_source_registry_upgrades_root_url_to_more_specific_page_locator(self) -> None:
        existing = {
            "run_id": "run-xyz",
            "notes": "",
            "sources": [
                {
                    "id": "SRC-001",
                    "title": "Vendor source",
                    "type": "official documentation",
                    "authority": "vendor",
                    "locator": "https://example.com/",
                    "source_class": "external_evidence",
                }
            ],
        }
        stage_sources = [
            {
                "id": "SRC-001",
                "title": "Vendor source",
                "type": "official documentation",
                "authority": "vendor",
                "locator": "https://example.com/products/radar-board",
                "source_class": "external_evidence",
            }
        ]

        merged = merge_source_registry(existing, stage_sources)

        self.assertEqual(
            merged["sources"][0]["locator"],
            "https://example.com/products/radar-board",
        )

    def test_accepts_flexible_non_critical_judge_sections(self) -> None:
        payload = {
            "stage": "judge",
            "supported_conclusions": [
                {"id": "SC-001", "text": "Hybrid edge architecture is feasible.", "evidence_sources": ["SRC-001"]}
            ],
            "synthesis_judgments": [
                {
                    "id": "SJ-001",
                    "text": "Thermal design is the main blocker.",
                    "evidence_sources": ["SRC-001", "SRC-002"],
                    "confidence": "high",
                }
            ],
            "unresolved_disagreements": [
                {
                    "point": "Platform choice",
                    "case_a": "Jetson provides higher headroom.",
                    "case_b": "Host plus accelerator reduces thermal load.",
                    "reason_unresolved": "System power budget is still unknown.",
                }
            ],
            "confidence_assessment": {
                "summary": "High confidence in feasibility, medium confidence in platform choice.",
                "topics": [
                    {
                        "topic": "Feasibility",
                        "confidence": "high",
                        "rationale": "The compute path is supported by cited module capabilities.",
                    }
                ],
            },
            "evidence_gaps": ["Measured enclosure thermals under sustained compute load."],
            "rationale": "Judge favors the hybrid path but preserves the power dispute for auditability.",
            "recommended_artifact_structure": {
                "sections": ["Executive Summary", "Architecture", "Thermal Risks", "Roadmap"]
            },
            "sources": [
                {"id": "SRC-001", "title": "Source 1", "type": "document", "authority": "vendor", "locator": "https://example.com/src-001"},
                {"id": "SRC-002", "title": "Source 2", "type": "document", "authority": "vendor", "locator": "https://example.com/src-002"},
            ],
        }
        registry = source_registry_placeholder("run-xyz")

        errors = validate_stage_json("judge", payload, registry)

        self.assertEqual(errors, [], errors)

    def test_builds_claim_map_and_markdown_from_flexible_judge_sections(self) -> None:
        payload = {
            "stage": "judge",
            "supported_conclusions": [
                {"id": "SC-001", "text": "Hybrid edge architecture is feasible.", "evidence_sources": ["SRC-001"]}
            ],
            "synthesis_judgments": [
                {
                    "id": "SJ-001",
                    "text": "Thermal design is the main blocker.",
                    "evidence_sources": ["SRC-001", "SRC-002"],
                    "confidence": "high",
                }
            ],
            "unresolved_disagreements": [
                {
                    "point": "Platform choice",
                    "case_a": "Jetson provides higher headroom.",
                    "case_b": "Host plus accelerator reduces thermal load.",
                    "reason_unresolved": "System power budget is still unknown.",
                }
            ],
            "confidence_assessment": {
                "summary": "High confidence in feasibility, medium confidence in platform choice.",
                "topics": [
                    {
                        "topic": "Feasibility",
                        "confidence": "high",
                        "rationale": "The compute path is supported by cited module capabilities.",
                    }
                ],
            },
            "evidence_gaps": ["Measured enclosure thermals under sustained compute load."],
            "rationale": "Judge favors the hybrid path but preserves the power dispute for auditability.",
            "recommended_artifact_structure": {
                "sections": ["Executive Summary", "Architecture", "Thermal Risks", "Roadmap"]
            },
            "sources": [
                {"id": "SRC-001", "title": "Source 1", "type": "document", "authority": "vendor", "locator": "https://example.com/src-001"},
                {"id": "SRC-002", "title": "Source 2", "type": "document", "authority": "vendor", "locator": "https://example.com/src-002"},
            ],
        }

        claim_map = build_claim_map_from_stage_json("judge", payload)
        markdown = render_stage_markdown_from_json("judge", payload)

        self.assertTrue(any(claim["text"] == "Platform choice" for claim in claim_map["claims"]))
        self.assertTrue(any(claim["text"] == "Executive Summary" for claim in claim_map["claims"]))
        self.assertIn("Platform choice", markdown)
        self.assertIn("High confidence in feasibility, medium confidence in platform choice.", markdown)
        self.assertIn("- Executive Summary", markdown)


if __name__ == "__main__":
    unittest.main()

import tempfile
import unittest
from pathlib import Path

import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from _stage_contracts import normalize_stage_citations, source_registry_placeholder, validate_stage_json


class StageContractTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()

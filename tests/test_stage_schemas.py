import json
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMAS_DIR = REPO_ROOT / "schemas"


def load_schema(name: str) -> dict:
    return json.loads((SCHEMAS_DIR / name).read_text(encoding="utf-8"))


class StageSchemaTests(unittest.TestCase):
    def test_research_schema_exposes_semantic_support_links(self) -> None:
        schema = load_schema("research-stage.schema.json")
        fact_item = schema["properties"]["facts"]["items"]["properties"]
        inference_item = schema["properties"]["inferences"]["items"]["properties"]

        self.assertIn("support_links", fact_item)
        self.assertIn("support_links", inference_item)
        self.assertIn("claim_dependencies", inference_item)
        self.assertEqual(
            fact_item["support_links"]["items"]["properties"]["role"]["enum"],
            ["evidence", "context", "challenge", "provenance"],
        )

    def test_judge_schema_exposes_semantic_support_links(self) -> None:
        schema = load_schema("judge-stage.schema.json")
        conclusion_item = schema["properties"]["supported_conclusions"]["items"]["properties"]
        judgment_item = schema["properties"]["synthesis_judgments"]["items"]["properties"]

        self.assertIn("support_links", conclusion_item)
        self.assertIn("support_links", judgment_item)
        self.assertIn("claim_dependencies", judgment_item)
        self.assertEqual(
            judgment_item["support_links"]["items"]["properties"]["role"]["enum"],
            ["evidence", "context", "challenge", "provenance"],
        )

    def test_critique_schema_exposes_semantic_support_links(self) -> None:
        schema = load_schema("critique-stage.schema.json")
        supported_claim = schema["properties"]["supported_claims"]["items"]["oneOf"][1]["properties"]
        weak_source_issue = schema["properties"]["weak_source_issues"]["items"]["oneOf"][1]["properties"]

        self.assertIn("support_links", supported_claim)
        self.assertIn("support_links", weak_source_issue)
        self.assertIn("claim_dependencies", supported_claim)
        self.assertEqual(
            supported_claim["support_links"]["items"]["properties"]["role"]["enum"],
            ["evidence", "context", "challenge", "provenance"],
        )

    def test_stage_schemas_expose_source_class_enum(self) -> None:
        expected_classes = [
            "external_evidence",
            "job_input",
            "workflow_provenance",
            "recovered_provisional",
        ]
        for schema_name in [
            "research-stage.schema.json",
            "critique-stage.schema.json",
            "judge-stage.schema.json",
        ]:
            with self.subTest(schema=schema_name):
                schema = load_schema(schema_name)
                source_item = schema["properties"]["sources"]["items"]["properties"]
                self.assertEqual(source_item["source_class"]["enum"], expected_classes)

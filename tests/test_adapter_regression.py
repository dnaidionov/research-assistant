import json
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
import sys

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from _adapter_regression import (
    path_requires_adapter_regression,
    qualification_inputs_fingerprint,
    report_is_stale_for_current_inputs,
)


class AdapterRegressionTests(unittest.TestCase):
    def test_path_requires_adapter_regression_for_prompt_schema_and_config_inputs(self) -> None:
        self.assertTrue(path_requires_adapter_regression("shared/prompts/research-template.md"))
        self.assertTrue(path_requires_adapter_regression("schemas/research-stage.schema.json"))
        self.assertTrue(path_requires_adapter_regression("scripts/execute_workflow.py"))
        self.assertTrue(path_requires_adapter_regression("jobs/georadar/config.yaml"))
        self.assertTrue(
            path_requires_adapter_regression(
                "fixtures/adapter-qualification/families/neutral/workflow-regression-realistic/06-judge.md"
            )
        )
        self.assertTrue(path_requires_adapter_regression("fixtures/reference-job/families/neutral/config.yaml"))

    def test_path_requires_adapter_regression_ignores_docs_only_paths(self) -> None:
        self.assertFalse(path_requires_adapter_regression("docs/product/product-spec.md"))
        self.assertFalse(path_requires_adapter_regression("README.md"))

    def test_qualification_inputs_fingerprint_changes_when_job_config_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            job_dir = Path(tmpdir) / "job"
            job_dir.mkdir()
            (job_dir / "config.yaml").write_text("topic: one\n", encoding="utf-8")

            before = qualification_inputs_fingerprint(REPO_ROOT, job_dir)
            (job_dir / "config.yaml").write_text("topic: two\n", encoding="utf-8")
            after = qualification_inputs_fingerprint(REPO_ROOT, job_dir)

            self.assertNotEqual(before, after)

    def test_report_is_stale_when_profile_or_fingerprint_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            job_dir = Path(tmpdir) / "job"
            job_dir.mkdir()
            (job_dir / "config.yaml").write_text("topic: one\n", encoding="utf-8")
            fingerprint = qualification_inputs_fingerprint(REPO_ROOT, job_dir)

            current_report = {
                "profile": "workflow-regression",
                "probe_set_version": "workflow-regression.v2",
                "qualification_inputs_fingerprint": fingerprint,
            }
            stale_report = dict(current_report)
            stale_report["qualification_inputs_fingerprint"] = "stale"

            self.assertFalse(
                report_is_stale_for_current_inputs(
                    current_report,
                    repo_root=REPO_ROOT,
                    job_dir=job_dir,
                    expected_profile="workflow-regression",
                    expected_probe_set_version="workflow-regression.v2",
                )
            )
            self.assertTrue(
                report_is_stale_for_current_inputs(
                    stale_report,
                    repo_root=REPO_ROOT,
                    job_dir=job_dir,
                    expected_profile="workflow-regression",
                    expected_probe_set_version="workflow-regression.v2",
                )
            )
            self.assertTrue(
                report_is_stale_for_current_inputs(
                    current_report,
                    repo_root=REPO_ROOT,
                    job_dir=job_dir,
                    expected_profile="smoke",
                    expected_probe_set_version="smoke.v1",
                )
            )

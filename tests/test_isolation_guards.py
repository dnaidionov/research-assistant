import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from _execution_guards import (  # noqa: E402
    final_report_protected_paths,
    merge_sources_into_tracked_registry,
    register_source_registry_baseline,
    reset_source_registry_tracking,
    revert_unauthorized_source_registry_edits,
)
from execute_workflow import (  # noqa: E402
    EXECUTION_BY_STAGE_ID,
    protected_stage_paths,
    refresh_run_manifest,
    restore_protected_files,
    snapshot_protected_files,
)


class IsolationGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.job_dir = Path(self.tmpdir.name) / "job"
        self.run_dir = self.job_dir / "runs" / "run-001"
        (self.run_dir / "stage-outputs").mkdir(parents=True)
        (self.run_dir / "audit").mkdir(parents=True)
        (self.job_dir / "brief.md").write_text("# Brief\n", encoding="utf-8")
        (self.job_dir / "config.yaml").write_text("topic: x\n", encoding="utf-8")
        (self.run_dir / "stage-outputs" / "01-intake.json").write_text(
            json.dumps({"stage": "intake"}), encoding="utf-8"
        )

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_protected_paths_cover_job_inputs_and_dependencies(self) -> None:
        stage = EXECUTION_BY_STAGE_ID["research-a"]
        paths = protected_stage_paths(stage, self.run_dir, self.job_dir)
        names = {path.name for path in paths}
        self.assertIn("brief.md", names)
        self.assertIn("config.yaml", names)
        self.assertIn("01-intake.json", names)

    def test_modified_protected_file_is_restored_and_journaled(self) -> None:
        stage = EXECUTION_BY_STAGE_ID["research-a"]
        snapshot = snapshot_protected_files(protected_stage_paths(stage, self.run_dir, self.job_dir))

        (self.job_dir / "brief.md").write_text("# Tampered\n", encoding="utf-8")
        restored = restore_protected_files(self.run_dir, "research-a", snapshot)

        self.assertEqual((self.job_dir / "brief.md").read_text(encoding="utf-8"), "# Brief\n")
        self.assertEqual(len(restored), 1)
        events = (self.run_dir / "events.jsonl").read_text(encoding="utf-8")
        self.assertIn("protected_artifacts_restored", events)

    def test_untouched_protected_files_produce_no_event(self) -> None:
        stage = EXECUTION_BY_STAGE_ID["research-a"]
        snapshot = snapshot_protected_files(protected_stage_paths(stage, self.run_dir, self.job_dir))
        restored = restore_protected_files(self.run_dir, "research-a", snapshot)
        self.assertEqual(restored, [])
        self.assertFalse((self.run_dir / "events.jsonl").exists())

    def test_final_report_protected_paths_cover_inputs_but_allow_the_report_itself(self) -> None:
        stage_outputs = self.run_dir / "stage-outputs"
        (stage_outputs / "06-judge.md").write_text("# Judge\n", encoding="utf-8")
        (self.run_dir / "sources.json").write_text(json.dumps({"sources": []}), encoding="utf-8")
        report_output = stage_outputs / "07-final-report.md"
        report_output.write_text("# Stale report\n", encoding="utf-8")
        claim_register = self.job_dir / "evidence" / "claims-run-001.json"
        claim_register.parent.mkdir(parents=True)
        claim_register.write_text(json.dumps({"claims": []}), encoding="utf-8")

        paths = final_report_protected_paths(
            self.run_dir,
            self.job_dir,
            claim_register_path=claim_register,
            report_output_path=report_output,
        )
        names = {path.name for path in paths}
        self.assertIn("brief.md", names)
        self.assertIn("config.yaml", names)
        self.assertIn("sources.json", names)
        self.assertIn("06-judge.md", names)
        self.assertIn("01-intake.json", names)
        self.assertIn("claims-run-001.json", names)
        self.assertNotIn("07-final-report.md", names)

    def test_tampered_judge_artifact_is_restored_after_final_report_step(self) -> None:
        stage_outputs = self.run_dir / "stage-outputs"
        judge_path = stage_outputs / "06-judge.md"
        judge_path.write_text("# Judge\n", encoding="utf-8")
        snapshot = snapshot_protected_files(
            final_report_protected_paths(self.run_dir, self.job_dir)
        )

        judge_path.write_text("# Tampered by synthesis agent\n", encoding="utf-8")
        restored = restore_protected_files(self.run_dir, "final-report", snapshot)

        self.assertEqual(judge_path.read_text(encoding="utf-8"), "# Judge\n")
        self.assertEqual(len(restored), 1)

    def test_refresh_run_manifest_reflects_current_run_contents(self) -> None:
        refresh_run_manifest(self.run_dir)
        manifest_path = self.run_dir / "audit" / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        paths = {entry["path"] for entry in manifest["files"]}
        self.assertIn("stage-outputs/01-intake.json", paths)
        self.assertNotIn("audit/manifest.json", paths)

        (self.run_dir / "stage-outputs" / "02-research-a.md").write_text("# Output\n", encoding="utf-8")
        refresh_run_manifest(self.run_dir)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        paths = {entry["path"] for entry in manifest["files"]}
        self.assertIn("stage-outputs/02-research-a.md", paths)
        for entry in manifest["files"]:
            self.assertEqual(len(entry["sha256"]), 64)


def _source(source_id: str) -> dict[str, object]:
    return {
        "id": source_id,
        "title": f"Source {source_id}",
        "type": "report",
        "authority": "vendor",
        "locator": f"https://example.com/{source_id}",
        "source_class": "external_evidence",
    }


class TrackedSourceRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_source_registry_tracking()
        self.tmpdir = tempfile.TemporaryDirectory()
        self.registry_path = Path(self.tmpdir.name) / "sources.json"
        self.registry_path.write_text(json.dumps({"sources": []}), encoding="utf-8")

    def tearDown(self) -> None:
        self.tmpdir.cleanup()
        reset_source_registry_tracking()

    def test_revert_preserves_sibling_merge_that_landed_mid_stage(self) -> None:
        # Stage B starts and takes its baseline.
        register_source_registry_baseline(self.registry_path)
        # Sibling stage A completes; the runner merges its sources.
        merge_sources_into_tracked_registry(self.registry_path, [_source("SRC-A")])
        # Stage B's agent tampers with the registry directly.
        self.registry_path.write_text(json.dumps({"sources": [_source("SRC-EVIL")]}), encoding="utf-8")

        self.assertTrue(revert_unauthorized_source_registry_edits(self.registry_path))

        ids = {source["id"] for source in json.loads(self.registry_path.read_text(encoding="utf-8"))["sources"]}
        self.assertIn("SRC-A", ids)
        self.assertNotIn("SRC-EVIL", ids)

    def test_merge_ignores_agent_tampered_disk_state(self) -> None:
        register_source_registry_baseline(self.registry_path)
        # An agent injects a fake source before the runner merges a completed stage.
        self.registry_path.write_text(json.dumps({"sources": [_source("SRC-EVIL")]}), encoding="utf-8")

        merge_sources_into_tracked_registry(self.registry_path, [_source("SRC-B")])

        ids = {source["id"] for source in json.loads(self.registry_path.read_text(encoding="utf-8"))["sources"]}
        self.assertIn("SRC-B", ids)
        self.assertNotIn("SRC-EVIL", ids)

    def test_baseline_registration_is_first_writer_wins(self) -> None:
        register_source_registry_baseline(self.registry_path)
        self.registry_path.write_text(json.dumps({"sources": [_source("SRC-EVIL")]}), encoding="utf-8")
        # A later stage start must not bless the tampered content.
        register_source_registry_baseline(self.registry_path)

        self.assertTrue(revert_unauthorized_source_registry_edits(self.registry_path))
        self.assertEqual(json.loads(self.registry_path.read_text(encoding="utf-8"))["sources"], [])

    def test_untracked_registry_is_left_alone(self) -> None:
        self.assertFalse(revert_unauthorized_source_registry_edits(self.registry_path))


if __name__ == "__main__":
    unittest.main()

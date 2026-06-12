import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

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


if __name__ == "__main__":
    unittest.main()

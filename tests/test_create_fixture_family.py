import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
import sys

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from create_fixture_family import scaffold_fixture_family


class CreateFixtureFamilyTests(unittest.TestCase):
    def test_scaffold_fixture_family_copies_neutral_baseline_into_new_family(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            source_qualification = repo_root / "fixtures" / "adapter-qualification" / "families" / "neutral" / "workflow-regression-realistic"
            source_reference = repo_root / "fixtures" / "reference-job" / "families" / "neutral"
            source_qualification.mkdir(parents=True)
            source_reference.mkdir(parents=True)
            (source_qualification / "06-judge.md").write_text(
                "# Judge Synthesis Prompt\nFixture Family: neutral\nStable Qualification Fixture: judge\n",
                encoding="utf-8",
            )
            (source_reference / "brief.md").write_text("# Neutral Reference Job\n", encoding="utf-8")
            (source_reference / "config.yaml").write_text("topic: reference-job-neutral\n", encoding="utf-8")

            result = scaffold_fixture_family("market-entry", repo_root=repo_root)

            qualification_dir = repo_root / "fixtures" / "adapter-qualification" / "families" / "market-entry" / "workflow-regression-realistic"
            reference_dir = repo_root / "fixtures" / "reference-job" / "families" / "market-entry"
            self.assertEqual(result["family"], "market-entry")
            self.assertTrue(qualification_dir.is_dir())
            self.assertTrue(reference_dir.is_dir())
            self.assertIn("Fixture Family: market-entry", (qualification_dir / "06-judge.md").read_text(encoding="utf-8"))
            self.assertIn("market-entry", (reference_dir / "config.yaml").read_text(encoding="utf-8"))

    def test_scaffold_fixture_family_rejects_existing_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            (repo_root / "fixtures" / "adapter-qualification" / "families" / "neutral" / "workflow-regression-realistic").mkdir(parents=True)
            (repo_root / "fixtures" / "reference-job" / "families" / "neutral").mkdir(parents=True)
            (repo_root / "fixtures" / "adapter-qualification" / "families" / "neutral" / "workflow-regression-realistic" / "01-intake.md").write_text(
                "Fixture Family: neutral\n",
                encoding="utf-8",
            )
            (repo_root / "fixtures" / "reference-job" / "families" / "neutral" / "brief.md").write_text(
                "# Neutral Reference Job\n",
                encoding="utf-8",
            )
            (repo_root / "fixtures" / "reference-job" / "families" / "neutral" / "config.yaml").write_text(
                "topic: reference-job-neutral\n",
                encoding="utf-8",
            )
            (repo_root / "fixtures" / "adapter-qualification" / "families" / "market-entry" / "workflow-regression-realistic").mkdir(parents=True)

            with self.assertRaisesRegex(ValueError, "already exists"):
                scaffold_fixture_family("market-entry", repo_root=repo_root)


if __name__ == "__main__":
    unittest.main()

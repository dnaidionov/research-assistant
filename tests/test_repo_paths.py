import tempfile
import unittest
from pathlib import Path

import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from _repo_paths import RepoPathConfig, load_repo_path_config, resolve_jobs_root


class RepoPathsTests(unittest.TestCase):
    def test_load_repo_path_config_uses_yaml_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir) / "research-assistant"
            (repo_root / "config").mkdir(parents=True)
            (repo_root / "config" / "paths.yaml").write_text(
                f"assistant_root: {repo_root}\n"
                "jobs_root: ~/Projects/research-hub/jobs\n",
                encoding="utf-8",
            )

            config = load_repo_path_config(repo_root=repo_root)

        self.assertIsInstance(config, RepoPathConfig)
        self.assertEqual(config.jobs_root, Path("~/Projects/research-hub/jobs").expanduser())
        self.assertEqual(config.jobs_index_root, (repo_root / "jobs-index").resolve())

    def test_load_repo_path_config_rejects_assistant_root_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir) / "research-assistant"
            (repo_root / "config").mkdir(parents=True)
            (repo_root / "config" / "paths.yaml").write_text(
                "assistant_root: ~/Projects/somewhere-else/research-assistant\n"
                "jobs_root: ~/Projects/research-hub/jobs\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "assistant_root"):
                load_repo_path_config(repo_root=repo_root)

    def test_resolve_jobs_root_prefers_cli_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir) / "research-assistant"
            (repo_root / "config").mkdir(parents=True)
            (repo_root / "config" / "paths.yaml").write_text(
                f"assistant_root: {repo_root}\n"
                "jobs_root: ~/Projects/research-hub/jobs\n",
                encoding="utf-8",
            )
            override = Path(tmpdir) / "custom-jobs"

            resolved = resolve_jobs_root(repo_root=repo_root, cli_jobs_root=override)

        self.assertEqual(resolved, override)

    def test_jobs_index_root_is_fixed_under_assistant_repo(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir) / "research-assistant"
            (repo_root / "config").mkdir(parents=True)
            (repo_root / "config" / "paths.yaml").write_text(
                f"assistant_root: {repo_root}\n"
                "jobs_root: ~/Projects/research-hub/jobs\n",
                encoding="utf-8",
            )

            config = load_repo_path_config(repo_root=repo_root)

        self.assertEqual(config.jobs_index_root, (repo_root / "jobs-index").resolve())


if __name__ == "__main__":
    unittest.main()

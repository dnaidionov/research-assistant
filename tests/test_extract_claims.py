import json
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
EXTRACT_CLAIMS = REPO_ROOT / "scripts" / "extract_claims.py"


class ExtractClaimsTests(unittest.TestCase):
    def test_extracts_atomic_claims_with_types_and_citations(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "report.md"
            output_path = Path(tmpdir) / "claims.json"
            input_path.write_text(
                "\n".join(
                    [
                        "# Report",
                        "",
                        "## Facts",
                        "1. The framework separates assistant and job repos. [SRC-001]",
                        "2. Each run writes artifacts to the job repo. [SRC-002, SRC-003]",
                        "",
                        "## Inferences",
                        "- This separation reduces accidental data leakage. [SRC-004]",
                    ]
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    "python3",
                    str(EXTRACT_CLAIMS),
                    "--input",
                    str(input_path),
                    "--output",
                    str(output_path),
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual([claim["id"] for claim in payload["claims"]], ["CLM-0001", "CLM-0002", "CLM-0003"])
            self.assertEqual(payload["claims"][0]["type"], "fact")
            self.assertEqual(payload["claims"][1]["citations"], ["SRC-002", "SRC-003"])
            self.assertEqual(payload["claims"][2]["type"], "inference")

    def test_strict_mode_rejects_uncited_facts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "report.md"
            output_path = Path(tmpdir) / "claims.json"
            input_path.write_text(
                "\n".join(
                    [
                        "# Report",
                        "",
                        "## Facts",
                        "- The final report includes citations.",
                    ]
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    "python3",
                    str(EXTRACT_CLAIMS),
                    "--input",
                    str(input_path),
                    "--output",
                    str(output_path),
                    "--strict",
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("uncited fact", result.stderr.lower())


if __name__ == "__main__":
    unittest.main()

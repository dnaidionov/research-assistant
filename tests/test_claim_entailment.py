import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from verify_claim_entailment import (  # noqa: E402
    collect_entailment_candidates,
    parse_verdict,
    run_entailment_checks,
    sample_candidates,
)


def candidate(claim_id: str, claim_text: str = "The module draws 2.5 watts.") -> dict[str, str]:
    return {
        "stage": "research-a",
        "claim_id": claim_id,
        "claim_text": claim_text,
        "source_id": "SRC-001",
        "excerpt": "draws 2.5 watts under sustained load",
    }


def scripted_runner(script: dict[str, tuple[int, str, str]]):
    """Route by claim text embedded in the prompt (last cmd arg)."""

    def run(cmd: list[str], cwd: Path, timeout: float) -> tuple[int, str, str]:
        prompt = cmd[-1]
        for needle, result in script.items():
            if needle in prompt:
                return result
        return 0, "SUPPORTED — matches.", ""

    return run


class EntailmentCheckTests(unittest.TestCase):
    def test_verdicts_are_parsed_and_summarized(self) -> None:
        sampled = [
            candidate("F-001", "The module draws 2.5 watts."),
            candidate("F-002", "The module includes a 40 TOPS accelerator."),
            candidate("F-003", "The module is efficient."),
        ]
        runner = scripted_runner(
            {
                "2.5 watts.": (0, "SUPPORTED — the excerpt states the power draw.", ""),
                "40 TOPS": (0, "UNSUPPORTED — the excerpt says nothing about an accelerator.", ""),
                "efficient": (0, "PARTIAL — efficiency is implied but not stated.", ""),
            }
        )
        report = run_entailment_checks(
            sampled,
            adapter_name="claude",
            adapter_bin="claude",
            job_dir=Path("."),
            model=None,
            timeout=5,
            command_runner=runner,
        )
        verdicts = {record["claim_id"]: record["verdict"] for record in report["results"]}
        self.assertEqual(verdicts, {"F-001": "SUPPORTED", "F-002": "UNSUPPORTED", "F-003": "PARTIAL"})
        self.assertEqual(report["summary"]["unsupported_claims"], ["research-a:F-002"])

    def test_adapter_failure_and_chatter_are_reported_not_crashed(self) -> None:
        sampled = [candidate("F-001", "Claim one text."), candidate("F-002", "Claim two text.")]
        runner = scripted_runner(
            {
                "Claim one": (1, "", "provider quota exceeded"),
                "Claim two": (0, "I could not decide either way, sorry!", ""),
            }
        )
        report = run_entailment_checks(
            sampled,
            adapter_name="claude",
            adapter_bin="claude",
            job_dir=Path("."),
            model=None,
            timeout=5,
            command_runner=runner,
        )
        verdicts = [record["verdict"] for record in report["results"]]
        self.assertEqual(verdicts, ["ERROR", "UNPARSEABLE"])

    def test_sampling_is_deterministic_and_bounded(self) -> None:
        candidates = [candidate(f"F-{index:03d}") for index in range(20)]
        first = sample_candidates(candidates, 5, seed=42)
        second = sample_candidates(candidates, 5, seed=42)
        self.assertEqual(first, second)
        self.assertEqual(len(first), 5)
        self.assertEqual(sample_candidates(candidates, 0, seed=42), candidates)

    def test_parse_verdict_prefers_first_verdict_token(self) -> None:
        self.assertEqual(parse_verdict("PARTIAL — some support. Not UNSUPPORTED.")[0], "PARTIAL")
        self.assertEqual(parse_verdict("no verdict here")[0], "UNPARSEABLE")

    def test_collect_candidates_reads_research_stage_links(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir)
            stage_dir = run_dir / "stage-outputs"
            stage_dir.mkdir()
            (stage_dir / "02-research-a.json").write_text(
                json.dumps(
                    {
                        "stage": "research-a",
                        "facts": [
                            {
                                "id": "F-001",
                                "text": "Fact text.",
                                "support_links": [
                                    {"source_id": "SRC-001", "role": "evidence", "excerpt": "Quoted."},
                                    {"source_id": "SRC-002", "role": "context", "excerpt": "Ignored."},
                                ],
                            }
                        ],
                        "inferences": [],
                    }
                ),
                encoding="utf-8",
            )
            collected = collect_entailment_candidates(run_dir)
        self.assertEqual(len(collected), 1)
        self.assertEqual(collected[0]["claim_id"], "F-001")


if __name__ == "__main__":
    unittest.main()

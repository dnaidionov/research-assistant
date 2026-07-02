import json
import os
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from _stage_contracts import configure_source_policy  # noqa: E402
from generate_final_report import (  # noqa: E402
    FALLBACK_REPORT_STRUCTURE,
    UNVALIDATED_REPORT_MARKER,
    build_synthesis_prompt,
    load_source_index,
    resolve_report_markdown,
    validate_report,
)

GENERATE_FINAL_REPORT = REPO_ROOT / "scripts" / "generate_final_report.py"

SOURCE_INDEX = {
    "SRC-001": {
        "id": "SRC-001",
        "title": "Canonical source",
        "source_class": "external_evidence",
        "locator": "https://example.com/src-001",
    },
    "DOC-INTAKE": {
        "id": "DOC-INTAKE",
        "title": "Intake artifact",
        "source_class": "workflow_provenance",
        "locator": "runs/run-001/stage-outputs/01-intake.json",
    },
}


class FinalReportValidationTests(unittest.TestCase):
    def test_cited_report_passes(self) -> None:
        markdown = (
            "# Executive Summary\n\n"
            "Option A has lower implementation risk. [SRC-001]\n\n"
            "# Recommendation\n\n"
            "Option A is the safer near-term choice. [SRC-001] Confidence: medium\n"
        )
        errors, _warnings = validate_report(markdown, SOURCE_INDEX)
        self.assertEqual(errors, [], errors)

    def test_uncited_fact_is_rejected(self) -> None:
        markdown = (
            "# Executive Summary\n\n"
            "Option A has lower implementation risk.\n\n"
            "# Recommendation\n\n"
            "Option A is the safer near-term choice. [SRC-001]\n"
        )
        errors, _warnings = validate_report(markdown, SOURCE_INDEX)
        self.assertTrue(any("uncited" in error for error in errors), errors)

    def test_hallucinated_source_id_is_rejected(self) -> None:
        markdown = (
            "# Executive Summary\n\n"
            "Option A has lower implementation risk. [SRC-FABRICATED]\n"
        )
        errors, _warnings = validate_report(markdown, SOURCE_INDEX)
        self.assertTrue(any("not in the run source registry" in error for error in errors), errors)

    def test_workflow_provenance_citation_is_rejected(self) -> None:
        markdown = (
            "# Executive Summary\n\n"
            "Option A has lower implementation risk. [DOC-INTAKE]\n"
        )
        errors, _warnings = validate_report(markdown, SOURCE_INDEX)
        self.assertTrue(
            any("not publishable evidence" in error or "workflow provenance" in error for error in errors),
            errors,
        )

    def test_missing_registry_is_warning_not_error(self) -> None:
        markdown = (
            "# Executive Summary\n\n"
            "Option A has lower implementation risk. [SRC-001]\n"
        )
        errors, warnings = validate_report(markdown, {})
        self.assertEqual(errors, [], errors)
        self.assertTrue(any("registry" in warning for warning in warnings), warnings)

    def test_policy_blocked_source_is_rejected_with_notes(self) -> None:
        markdown = (
            "# Executive Summary\n\n"
            "Option A has lower implementation risk. [SRC-001]\n"
        )
        source_index = {
            "SRC-001": {
                **SOURCE_INDEX["SRC-001"],
                "policy_outcome": "blocked",
                "policy_notes": ["Job source policy disallows this source type (anonymous blogs)."],
            }
        }
        errors, _warnings = validate_report(markdown, source_index)
        self.assertTrue(any("blocked by source policy" in error for error in errors), errors)
        self.assertTrue(any("anonymous blogs" in error for error in errors), errors)

    def test_job_source_policy_escalates_registry_records_to_blocked(self) -> None:
        """The end-to-end path the deterministic artifact already enforces:
        a configured disallowed list must block the synthesized report too."""
        configure_source_policy({"disallowed": ["anonymous blogs"]})
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                run_dir = Path(tmpdir)
                (run_dir / "sources.json").write_text(
                    json.dumps(
                        {
                            "sources": [
                                {
                                    "id": "SRC-001",
                                    "title": "Some anonymous blog post",
                                    "type": "anonymous blog",
                                    "authority": "unknown",
                                    "locator": "https://example.com/post",
                                    "source_class": "external_evidence",
                                }
                            ]
                        }
                    ),
                    encoding="utf-8",
                )
                source_index = load_source_index(run_dir)
            markdown = (
                "# Executive Summary\n\n"
                "Option A has lower implementation risk. [SRC-001]\n"
            )
            errors, _warnings = validate_report(markdown, source_index)
            self.assertTrue(any("blocked by source policy" in error for error in errors), errors)
        finally:
            configure_source_policy(None)


class FinalReportMainFlowTests(unittest.TestCase):
    """End-to-end main() behavior with a scripted adapter binary."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        root = Path(self.tmpdir.name)
        self.job_dir = root / "job"
        self.run_dir = self.job_dir / "runs" / "run-001"
        stage_outputs = self.run_dir / "stage-outputs"
        stage_outputs.mkdir(parents=True)
        (self.job_dir / "config.yaml").write_text("topic: test-job\n", encoding="utf-8")
        (self.job_dir / "evidence").mkdir()
        (self.job_dir / "evidence" / "claims-run-001.json").write_text(
            json.dumps({"claims": [], "summary": {}}), encoding="utf-8"
        )
        (self.run_dir / "sources.json").write_text(
            json.dumps(
                {
                    "sources": [
                        {
                            "id": "SRC-001",
                            "title": "Canonical source",
                            "type": "report",
                            "authority": "test fixture",
                            "locator": "https://example.com/src-001",
                            "source_class": "external_evidence",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        (stage_outputs / "06-judge.json").write_text(
            json.dumps({"stage": "judge", "recommended_artifact_structure": ["Executive Summary", "Recommendation"]}),
            encoding="utf-8",
        )
        (stage_outputs / "06-judge.md").write_text(
            "# Supported Conclusions\n\n1. Option A has lower implementation risk. [SRC-001]\n",
            encoding="utf-8",
        )
        self.output_path = stage_outputs / "07-final-report.md"
        self.adapter_bin = root / "claude"

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def _write_adapter(self, *, stdout_markdown: str, write_output_file: bool = False) -> None:
        self.adapter_bin.write_text(
            textwrap.dedent(
                f"""\
                #!/usr/bin/env python3
                import re
                import sys

                prompt = " ".join(sys.argv[1:])
                output_match = re.search(r"OUTPUT_PATH=(.+)", prompt)
                if {write_output_file!r} and output_match:
                    from pathlib import Path
                    Path(output_match.group(1).strip()).write_text({stdout_markdown!r}, encoding="utf-8")
                    print("Sure! I wrote the report to the requested path.")
                else:
                    print({stdout_markdown!r})
                """
            ),
            encoding="utf-8",
        )
        self.adapter_bin.chmod(0o755)

    def _run(self, *extra: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                "python3",
                str(GENERATE_FINAL_REPORT),
                "--run-dir",
                str(self.run_dir),
                "--job-dir",
                str(self.job_dir),
                "--adapter-name",
                "claude",
                "--adapter-bin",
                str(self.adapter_bin),
                "--output",
                str(self.output_path),
                *extra,
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )

    def test_rejected_draft_is_preserved_and_canonical_output_is_removed(self) -> None:
        # The adapter writes an uncited draft straight to the canonical path.
        self._write_adapter(
            stdout_markdown="# Executive Summary\n\nOption A has lower implementation risk.\n",
            write_output_file=True,
        )

        result = self._run()

        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("failed claim/reference validation", result.stderr)
        rejected = self.output_path.with_suffix(self.output_path.suffix + ".rejected.md")
        self.assertTrue(rejected.is_file())
        self.assertIn("Option A has lower implementation risk.", rejected.read_text(encoding="utf-8"))
        # The unvalidated draft must not remain at the canonical path, or a
        # resumed run would treat it as completed output.
        self.assertFalse(self.output_path.is_file())

    def test_validated_report_is_written_to_canonical_path(self) -> None:
        self._write_adapter(
            stdout_markdown="# Executive Summary\n\nOption A has lower implementation risk. [SRC-001]\n",
        )

        result = self._run()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.output_path.is_file())
        self.assertNotIn(UNVALIDATED_REPORT_MARKER, self.output_path.read_text(encoding="utf-8"))

    def test_no_validate_marks_the_artifact_as_unvalidated(self) -> None:
        # An uncited draft that would fail validation publishes under
        # --no-validate, but must carry the unvalidated marker.
        self._write_adapter(
            stdout_markdown="# Executive Summary\n\nOption A has lower implementation risk.\n",
        )

        result = self._run("--no-validate")

        self.assertEqual(result.returncode, 0, result.stderr)
        content = self.output_path.read_text(encoding="utf-8")
        self.assertTrue(content.startswith(UNVALIDATED_REPORT_MARKER), content[:120])


class FinalReportPromptTests(unittest.TestCase):
    def test_prompt_is_domain_neutral_and_scoped_to_judge_record(self) -> None:
        prompt = build_synthesis_prompt(
            run_dir=Path("/tmp/job/runs/run-001"),
            output_path=Path("/tmp/job/runs/run-001/stage-outputs/07-final-report.md"),
            recommended_structure=list(FALLBACK_REPORT_STRUCTURE),
            judge_markdown="# Supported Conclusions\n\n1. Conclusion. [SRC-001]\n",
            claim_register_json="{\"claims\": []}",
        )
        self.assertIn("STAGE_ID=final-report", prompt)
        self.assertIn("Do not reintroduce any claim", prompt)
        self.assertIn("[SRC-001]", prompt)
        # The framework prompt must not embed job-specific research content.
        for leaked_token in ("XAVER", "Hailo", "battery", "On-Device Migration"):
            self.assertNotIn(leaked_token, prompt)

    def test_fallback_structure_is_generic(self) -> None:
        joined = " ".join(FALLBACK_REPORT_STRUCTURE)
        for leaked_token in ("XAVER", "Hailo", "Battery", "Thermal", "Migration"):
            self.assertNotIn(leaked_token, joined)
        self.assertIn("Candidate Landscape And Options Considered", FALLBACK_REPORT_STRUCTURE)


class ResolveReportMarkdownTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.output_path = Path(self.tmpdir.name) / "07-final-report.md"

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_stale_output_file_is_not_trusted(self) -> None:
        self.output_path.write_text("# Stale report from a previous run\n", encoding="utf-8")
        hour_ago = time.time() - 3600
        os.utime(self.output_path, (hour_ago, hour_ago))
        invocation_started = time.time()
        self.assertEqual(resolve_report_markdown("", self.output_path, invocation_started), "")

    def test_file_written_during_invocation_wins_over_stdout_chatter(self) -> None:
        invocation_started = time.time() - 5
        self.output_path.write_text("# Real Report\n\nContent. [SRC-001]\n", encoding="utf-8")
        resolved = resolve_report_markdown(
            "Sure! I have written the report to the requested path.",
            self.output_path,
            invocation_started,
        )
        self.assertTrue(resolved.startswith("# Real Report"))

    def test_stdout_is_used_when_no_file_was_written(self) -> None:
        invocation_started = time.time()
        resolved = resolve_report_markdown("# Report\n\nBody. [SRC-001]", self.output_path, invocation_started)
        self.assertTrue(resolved.startswith("# Report"))

    def test_code_fence_wrapper_is_stripped(self) -> None:
        invocation_started = time.time()
        resolved = resolve_report_markdown(
            "```markdown\n# Report\n\nBody. [SRC-001]\n```",
            self.output_path,
            invocation_started,
        )
        self.assertTrue(resolved.startswith("# Report"))
        self.assertNotIn("```", resolved)


if __name__ == "__main__":
    unittest.main()

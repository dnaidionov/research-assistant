#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

from _claim_model import build_claim_register
from _cli_adapters import build_adapter_command
from _job_config import load_freshness_max_days, load_source_policy
from _stage_contracts import configure_freshness_max_days, configure_source_policy, normalize_source_record
from extract_claims import extract_claims as extract_markdown_claims

# Generic decision-research shape used only when the judge record does not
# provide a recommended structure. Must stay domain-neutral: this repo is
# framework only and must not embed job-specific content.
FALLBACK_REPORT_STRUCTURE = [
    "Executive Summary",
    "Candidate Landscape And Options Considered",
    "Options Comparison",
    "Recommendation",
    "Risks, Limitations, And Evidence Gaps",
    "Confidence And Uncertainty",
    "References",
    "Open Questions",
]

NON_PUBLISHABLE_SOURCE_CLASSES = {"workflow_provenance", "recovered_provisional"}

# Prepended to reports generated with --no-validate. Invisible in rendered
# markdown, but keeps skipped validation detectable in the raw artifact.
UNVALIDATED_REPORT_MARKER = (
    "<!-- UNVALIDATED: generated with --no-validate; claim/reference validation "
    "was skipped. Operator-reviewed output only. -->"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a custom LLM-synthesized final report based on the judge's recommended structure."
    )
    parser.add_argument("--run-dir", required=True, help="Path to the run directory.")
    parser.add_argument("--job-dir", required=True, help="Path to the job directory.")
    parser.add_argument("--adapter-name", required=True, help="Name of the LLM adapter (e.g., claude, gemini).")
    parser.add_argument("--adapter-bin", required=True, help="Path/binary for the adapter CLI.")
    parser.add_argument("--model", help="Optional model name to use.")
    parser.add_argument("--output", required=True, help="Path where the generated report should be saved.")
    parser.add_argument(
        "--no-validate",
        action="store_true",
        help="Skip post-generation claim and reference validation. The report is then operator-reviewed output only.",
    )
    return parser.parse_args()


def output_written_during_invocation(output_path: Path, invocation_started: float) -> bool:
    """Only trust an output file (re)written after the adapter started.

    A leftover report from an earlier invocation must not be re-validated and
    reported as freshly generated. The one-second slack absorbs coarse
    filesystem mtime granularity.
    """
    if not output_path.is_file():
        return False
    try:
        return output_path.stat().st_mtime >= invocation_started - 1.0
    except OSError:
        return False


def strip_code_fence(markdown: str) -> str:
    if not markdown.startswith("```"):
        return markdown
    lines = markdown.splitlines()
    if lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def resolve_report_markdown(stdout_text: str, output_path: Path, invocation_started: float) -> str:
    """Pick the adapter's report content: a file it wrote during this invocation
    is authoritative over stdout, which may be conversational chatter."""
    candidate = stdout_text.strip()
    if output_written_during_invocation(output_path, invocation_started):
        candidate = output_path.read_text(encoding="utf-8").strip()
    return strip_code_fence(candidate)


def read_file_safe(path: Path) -> str:
    if path.is_file():
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            return ""
    return ""


def load_source_index(run_dir: Path) -> dict[str, dict[str, object]]:
    registry_path = run_dir / "sources.json"
    if not registry_path.is_file():
        return {}
    try:
        payload = json.loads(registry_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    index: dict[str, dict[str, object]] = {}
    for source in payload.get("sources", []):
        if not isinstance(source, dict):
            continue
        normalized = normalize_source_record(source)
        source_id = normalized.get("id")
        if isinstance(source_id, str) and source_id.strip():
            # Keep policy_notes (a list) alongside the string fields so policy
            # failures can cite the reason a source is blocked.
            index[source_id] = {
                key: value if key == "policy_notes" else str(value)
                for key, value in normalized.items()
                if isinstance(value, str) or key == "policy_notes"
            }
    return index


def validate_report(markdown: str, source_index: dict[str, dict[str, object]]) -> tuple[list[str], list[str]]:
    """Validate the synthesized report with the same claim substrate as the deterministic artifact.

    Returns (errors, warnings).
    """
    claims = extract_markdown_claims(markdown, source_index or None)
    register = build_claim_register(claims)
    summary = register["summary"]
    errors: list[str] = []
    warnings: list[str] = []

    for summary_key, label in (
        ("uncited_fact_ids", "uncited fact claims"),
        ("uncited_inference_ids", "uncited inference claims"),
        ("uncited_truth_gated_ids", "uncited truth-gated claims"),
        ("provenance_only_fact_ids", "facts supported only by workflow provenance"),
    ):
        flagged = summary.get(summary_key) or []
        if flagged:
            errors.append(f"Final report contains {label}: {', '.join(flagged)}.")

    referenced: list[str] = []
    seen: set[str] = set()
    for claim in claims:
        for source_id in claim.get("evidence_sources", []):
            normalized = str(source_id)
            if normalized and normalized not in seen:
                seen.add(normalized)
                referenced.append(normalized)

    if source_index:
        for reference_id in referenced:
            record = source_index.get(reference_id)
            if record is None:
                errors.append(
                    f"Final report cites source {reference_id} which is not in the run source registry."
                )
                continue
            if record.get("source_class") in NON_PUBLISHABLE_SOURCE_CLASSES:
                errors.append(
                    f"Final report cites source {reference_id} whose class {record.get('source_class')} is not publishable evidence."
                )
            if record.get("policy_outcome") == "blocked":
                policy_notes = record.get("policy_notes")
                if isinstance(policy_notes, list):
                    policy_detail = "; ".join(str(note) for note in policy_notes if str(note).strip())
                else:
                    policy_detail = str(policy_notes or "")
                detail = f" {policy_detail}" if policy_detail else ""
                errors.append(
                    f"Final report cites source {reference_id} which is blocked by source policy.{detail}"
                )
    else:
        warnings.append("Run source registry is missing or empty; cited source IDs could not be resolved.")

    unclassified = summary.get("claims_with_unclassified_markers") or []
    if unclassified:
        warnings.append(f"Final report contains unclassified citation markers on claims: {', '.join(unclassified)}.")

    return errors, warnings


def build_synthesis_prompt(
    *,
    run_dir: Path,
    output_path: Path,
    recommended_structure: list[str],
    judge_markdown: str,
    claim_register_json: str,
) -> str:
    structure_bulleted = "\n".join(f"- {section}" for section in recommended_structure)
    context_paths = [
        run_dir / "stage-outputs" / "02-research-a.md",
        run_dir / "stage-outputs" / "03-research-b.md",
        run_dir / "stage-outputs" / "04-critique-a-on-b.md",
        run_dir / "stage-outputs" / "05-critique-b-on-a.md",
    ]
    context_lines = "\n".join(f"- `{path}`" for path in context_paths if path.is_file())
    return f"""STAGE_ID=final-report
OUTPUT_PATH={output_path}

You are the final report writer. Compile the user-facing research report from the judge synthesis and the validated claim register below. The judge record is the authoritative adjudication of this run.

The report must use exactly this top-level section structure:
{structure_bulleted}

=== JUDGE SYNTHESIS (authoritative) ===
{judge_markdown}
=== END JUDGE SYNTHESIS ===

=== CLAIM REGISTER ===
{claim_register_json}
=== END CLAIM REGISTER ===

Earlier stage artifacts are available at the paths below as optional background only. Consult them solely for phrasing detail on points the judge already accepted. Do not reintroduce any claim that the critiques or the judge rejected, weakened, or left unresolved, and do not add findings absent from the judge record.
{context_lines}

INSTRUCTIONS:
1. Write a comprehensive, professional markdown report covering each required section in order.
2. Every factual statement must carry an inline citation in square brackets using the canonical source IDs from the run record, for example [SRC-001] or [DOC-BRIEF]. Do not invent new source IDs.
2a. Citations are validated per sentence, per bullet, and per table row — a citation at the end of a paragraph does not cover the paragraph's other sentences. Every sentence, list item, and table row that states a fact must itself contain at least one bracketed source ID. This includes closing or appendix sections (claim register, confidence tables, source lists): give each row an inline citation or fold that content into cited prose.
2b. Never place a bracketed citation on a source whose class is recovered_provisional or that is blocked by source policy — not even to say it was unused or unverified. Describe such corroboration in words (e.g. "a provisional, access-blocked review suggests...") without the bracketed ID, and support the sentence with a citation to a validated source instead.
3. Preserve unresolved disagreements and uncertainty exactly as adjudicated; do not resolve them editorially.
4. Keep inference and recommendation statements labeled with their confidence where the judge record provides one, and keep availability risk visible for any candidate that is announced but not yet released.
5. Do NOT use placeholders, TODOs, or template labels. Every section must be fully written.
6. Output ONLY the markdown report, with no conversational introduction and no wrapping code fences.
"""


def main() -> int:
    args = parse_args()
    run_dir = Path(args.run_dir).expanduser()
    job_dir = Path(args.job_dir).expanduser()
    output_path = Path(args.output).expanduser()

    # This script runs as its own process, so the orchestrator's in-process
    # policy configuration does not reach it: load the job's freshness window
    # and source policy here so validation matches the deterministic artifact
    # (which does the same from its --config).
    configure_freshness_max_days(load_freshness_max_days(job_dir))
    configure_source_policy(load_source_policy(job_dir))

    judge_json_path = run_dir / "stage-outputs" / "06-judge.json"
    judge_md_path = run_dir / "stage-outputs" / "06-judge.md"
    claim_reg_path = job_dir / "evidence" / f"claims-{run_dir.name}.json"

    if not judge_json_path.is_file() or not judge_md_path.is_file():
        print(f"Error: Judge output files not found in {run_dir}/stage-outputs", file=sys.stderr)
        return 1

    try:
        judge_json = json.loads(judge_json_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        print(f"Error loading judge JSON: {exc}", file=sys.stderr)
        return 1

    recommended_structure = judge_json.get("recommended_artifact_structure", [])
    if isinstance(recommended_structure, dict):
        recommended_structure = recommended_structure.get("sections", [])
    recommended_structure = [
        str(section.get("text", "")).strip() if isinstance(section, dict) else str(section).strip()
        for section in recommended_structure
        if (isinstance(section, dict) and str(section.get("text", "")).strip()) or (isinstance(section, str) and section.strip())
    ]
    if not recommended_structure:
        print(
            "Warning: recommended_artifact_structure not found in judge JSON, using the generic fallback structure.",
            file=sys.stderr,
        )
        recommended_structure = list(FALLBACK_REPORT_STRUCTURE)

    claim_register_json = read_file_safe(claim_reg_path)
    if not claim_register_json.strip():
        print(
            f"Warning: claim register {claim_reg_path} is missing or empty; the synthesis prompt carries no validated claims.",
            file=sys.stderr,
        )

    prompt = build_synthesis_prompt(
        run_dir=run_dir,
        output_path=output_path,
        recommended_structure=recommended_structure,
        judge_markdown=read_file_safe(judge_md_path),
        claim_register_json=claim_register_json,
    )

    try:
        cmd = build_adapter_command(args.adapter_name, args.adapter_bin, job_dir, prompt, args.model or None)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    log_path = run_dir / "logs" / "final-report-generation.driver.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    # The synthesis prompt embeds the judge record and claim register; persist it
    # so the orchestrator can attribute real prompt size in usage telemetry.
    (run_dir / "logs" / "final-report-generation.prompt.md").write_text(prompt, encoding="utf-8")

    # Capture the source registry before the adapter runs: validation must
    # resolve citations against the pre-invocation registry, or a misbehaving
    # agent could inject fake sources that pass the missing-source-ID gate.
    source_index = load_source_index(run_dir)

    invocation_started = time.time()
    result = subprocess.run(cmd, cwd=job_dir, capture_output=True, text=True)
    log_path.write_text(
        "\n".join(
            ["COMMAND:", " ".join(cmd), "", "STDOUT:", result.stdout, "", "STDERR:", result.stderr]
        ),
        encoding="utf-8",
    )

    if result.returncode != 0:
        print(f"Error running LLM adapter CLI: {result.stderr}", file=sys.stderr)
        return result.returncode

    report_body = resolve_report_markdown(result.stdout, output_path, invocation_started)
    if not report_body:
        print(
            "Error: adapter produced no report content (stdout was empty and no output file was written during this invocation).",
            file=sys.stderr,
        )
        return 1

    report_markdown = report_body + "\n"

    if args.no_validate:
        # Mark skipped validation in the artifact itself: a later resumed run
        # publishes the canonical file as-is, so without this marker an
        # unvalidated report would be indistinguishable from a validated one.
        report_markdown = UNVALIDATED_REPORT_MARKER + "\n" + report_markdown

    if not args.no_validate:
        errors, warnings = validate_report(report_markdown, source_index)
        for warning in warnings:
            print(f"Warning: {warning}", file=sys.stderr)
        if errors:
            rejected_path = output_path.with_suffix(output_path.suffix + ".rejected.md")
            rejected_path.parent.mkdir(parents=True, exist_ok=True)
            rejected_path.write_text(report_markdown, encoding="utf-8")
            if output_written_during_invocation(output_path, invocation_started):
                # An adapter that wrote the rejected draft straight to the canonical
                # path must not leave it there, or a resumed run would treat the
                # unvalidated report as completed output.
                output_path.unlink()
            print(
                "Final report failed claim/reference validation and was written to "
                f"{rejected_path} for operator review:",
                file=sys.stderr,
            )
            for error in errors:
                print(f"- {error}", file=sys.stderr)
            return 1

    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(report_markdown, encoding="utf-8")
    except OSError as exc:
        print(f"Error writing custom final report: {exc}", file=sys.stderr)
        return 1

    print(f"Custom final report successfully generated and saved to {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

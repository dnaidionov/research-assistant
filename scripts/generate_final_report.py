#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from _claim_model import build_claim_register
from _cli_adapters import build_adapter_command
from _stage_contracts import normalize_source_record
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


def read_file_safe(path: Path) -> str:
    if path.is_file():
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            return ""
    return ""


def load_source_index(run_dir: Path) -> dict[str, dict[str, str]]:
    registry_path = run_dir / "sources.json"
    if not registry_path.is_file():
        return {}
    try:
        payload = json.loads(registry_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    index: dict[str, dict[str, str]] = {}
    for source in payload.get("sources", []):
        if not isinstance(source, dict):
            continue
        normalized = normalize_source_record(source)
        source_id = normalized.get("id")
        if isinstance(source_id, str) and source_id.strip():
            index[source_id] = {key: str(value) for key, value in normalized.items() if isinstance(value, str)}
    return index


def validate_report(markdown: str, source_index: dict[str, dict[str, str]]) -> tuple[list[str], list[str]]:
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

    prompt = build_synthesis_prompt(
        run_dir=run_dir,
        output_path=output_path,
        recommended_structure=recommended_structure,
        judge_markdown=read_file_safe(judge_md_path),
        claim_register_json=read_file_safe(claim_reg_path),
    )

    try:
        cmd = build_adapter_command(args.adapter_name, args.adapter_bin, job_dir, prompt, args.model or None)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    log_path = run_dir / "logs" / "final-report-generation.driver.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)

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

    stdout_clean = result.stdout.strip()
    if not stdout_clean and output_path.is_file():
        # Some adapters write the artifact directly instead of materializing stdout.
        stdout_clean = output_path.read_text(encoding="utf-8").strip()
    # Strip any markdown code fence wrapper (e.g., ```markdown ... ```) if the LLM generated it
    if stdout_clean.startswith("```"):
        lines = stdout_clean.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        stdout_clean = "\n".join(lines).strip()

    if not stdout_clean:
        print("Error: adapter produced no report content.", file=sys.stderr)
        return 1

    report_markdown = stdout_clean + "\n"

    if not args.no_validate:
        errors, warnings = validate_report(report_markdown, load_source_index(run_dir))
        for warning in warnings:
            print(f"Warning: {warning}", file=sys.stderr)
        if errors:
            rejected_path = output_path.with_suffix(output_path.suffix + ".rejected.md")
            rejected_path.parent.mkdir(parents=True, exist_ok=True)
            rejected_path.write_text(report_markdown, encoding="utf-8")
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

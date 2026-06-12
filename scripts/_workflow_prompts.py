#!/usr/bin/env python3

"""Prompt builders for automated stage, substep, and repair execution."""

from __future__ import annotations

from pathlib import Path

from _execution_plan import StageExecution, stage_output_path, stage_packet_path
from _stage_contracts import (
    is_structured_stage,
    source_registry_path,
    stage_structured_output_path,
)


def build_agent_prompt(stage: StageExecution, run_dir: Path) -> str:
    packet_path = stage_packet_path(run_dir, stage.packet_name)
    output_path = stage_output_path(run_dir, stage.output_name)
    json_output_path = stage_structured_output_path(run_dir, stage.stage_id) if is_structured_stage(stage.stage_id) else None
    sources_path = source_registry_path(run_dir)
    return "\n".join(
        [
            f"STAGE_ID={stage.stage_id}",
            f"OUTPUT_PATH={output_path}",
            f"OUTPUT_JSON_PATH={json_output_path}" if json_output_path is not None else "OUTPUT_JSON_PATH=not_applicable",
            f"SOURCE_REGISTRY_PATH={sources_path}",
            f"PROMPT_PACKET={packet_path}",
            "",
            f"Execute workflow stage `{stage.stage_id}`.",
            f"Read the stage instructions from `{packet_path}`.",
            f"Write the completed stage output to `{output_path}`.",
            (
                f"Write the completed structured JSON output to `{json_output_path}`."
                if json_output_path is not None
                else "This stage does not require a structured JSON artifact."
            ),
            f"Use `{sources_path}` as the run-level source registry reference only. Do not modify that file directly.",
            "Do not leave placeholder content in the output file.",
            "Use upstream stage output artifacts when the prompt packet references them.",
            "Do not read or use artifacts from other runs under `runs/`, and do not read the parallel research pass output; only this stage's declared upstream artifacts are admissible workflow inputs.",
            "Do not modify the job brief, the job config, or any artifact other than this stage's declared outputs.",
            "Evidence is never obvious. Every fact and world-claim inference must carry explicit evidence support on that exact item; nearby citations do not count.",
        ]
    )


def intake_source_materials(job_dir: Path) -> tuple[str, str]:
    brief_path = job_dir / "brief.md"
    config_path = job_dir / "config.yaml"
    brief_text = brief_path.read_text(encoding="utf-8") if brief_path.is_file() else ""
    config_text = config_path.read_text(encoding="utf-8") if config_path.is_file() else ""
    return brief_text, config_text


def build_intake_source_prompt(job_dir: Path, run_dir: Path, output_json_path: Path, scratch_markdown_path: Path) -> str:
    brief_text, config_text = intake_source_materials(job_dir)
    return "\n".join(
        [
            "STAGE_ID=intake",
            "SUBSTEP=source-pass",
            f"OUTPUT_PATH={output_json_path}",
            f"OUTPUT_JSON_PATH={output_json_path}",
            "",
            "Execute only the source declaration pass for intake.",
            "Return JSON only.",
            'Allowed JSON shape: {"stage": "intake", "sources": [...]}',
            "Define only canonical job_input sources for the provided materials you actually used.",
            "Do not emit facts, inferences, or normalization fields.",
            "",
            "SOURCE MATERIALS:",
            "### brief.md",
            brief_text,
            "",
            "### config.yaml",
            config_text,
        ]
    )


def build_intake_fact_prompt(
    job_dir: Path,
    run_dir: Path,
    source_output_path: Path,
    output_json_path: Path,
    scratch_markdown_path: Path,
) -> str:
    brief_text, config_text = intake_source_materials(job_dir)
    return "\n".join(
        [
            "STAGE_ID=intake",
            "SUBSTEP=fact-lineage",
            f"OUTPUT_PATH={output_json_path}",
            f"OUTPUT_JSON_PATH={output_json_path}",
            f"SOURCE_PASS_PATH={source_output_path}",
            "",
            "Execute only the direct fact-lineage pass for intake.",
            "Return JSON only.",
            'Allowed JSON shape: {"stage": "intake", "known_facts": [...]}',
            "Use only the source IDs defined in SOURCE_PASS_PATH.",
            "known_facts must contain only directly stated brief/config facts with source_ids, source_excerpt, and source_anchor.",
            "Do not emit assumptions, constraints, missing information, or working inferences.",
            "",
            "SOURCE MATERIALS:",
            "### brief.md",
            brief_text,
            "",
            "### config.yaml",
            config_text,
        ]
    )


def build_intake_normalization_prompt(
    job_dir: Path,
    run_dir: Path,
    fact_output_path: Path,
    output_json_path: Path,
    scratch_markdown_path: Path,
) -> str:
    brief_text, config_text = intake_source_materials(job_dir)
    return "\n".join(
        [
            "STAGE_ID=intake",
            "SUBSTEP=normalization",
            f"OUTPUT_PATH={output_json_path}",
            f"OUTPUT_JSON_PATH={output_json_path}",
            f"FACT_LINEAGE_PATH={fact_output_path}",
            "",
            "Execute only the intake normalization pass.",
            "Return JSON only.",
            'Allowed JSON shape: {"stage": "intake", "question": ..., "scope": [...], "constraints": [...], "assumptions": [...], "missing_information": [...], "required_artifacts": [...], "notes_for_researchers": [...], "working_inferences": [...], "uncertainty_notes": [...]}',
            "Do not repeat known_facts here. Use FACT_LINEAGE_PATH only to avoid restating direct facts as working_inferences.",
            "Keep assumptions, missing information, and working inferences separate from direct facts.",
            "",
            "SOURCE MATERIALS:",
            "### brief.md",
            brief_text,
            "",
            "### config.yaml",
            config_text,
        ]
    )


def build_source_pass_prompt(stage: StageExecution, run_dir: Path, source_output_path: Path, scratch_markdown_path: Path) -> str:
    packet_path = stage_packet_path(run_dir, stage.packet_name)
    sources_path = source_registry_path(run_dir)
    return "\n".join(
        [
            f"STAGE_ID={stage.stage_id}",
            "SUBSTEP=source-pass",
            f"OUTPUT_PATH={scratch_markdown_path}",
            f"OUTPUT_JSON_PATH={source_output_path}",
            f"SOURCE_REGISTRY_PATH={sources_path}",
            f"PROMPT_PACKET={packet_path}",
            "",
            f"Execute only the source pass for workflow stage `{stage.stage_id}`.",
            f"Read the full stage instructions from `{packet_path}`.",
            f"Write JSON to `{source_output_path}`.",
            "Return only the structured source payload for this stage.",
            "Required JSON shape:",
            '{"stage": "<stage-id>", "sources": [...]}',
            "Do not write claims, summaries, conclusions, or markdown in the authoritative JSON output for this substep.",
            f"While researching, keep a working scratchpad at `{scratch_markdown_path}`: for each source you declare, record a short note with the key findings, figures, and quoted excerpts you extracted from it.",
            "The scratchpad is the handoff to the claim pass, which runs without your memory of this pass; capture enough detail there that the claims can be written without re-fetching every source.",
            "Do not read or use artifacts from other runs under `runs/`, and do not read the parallel research pass; gather your own evidence.",
            "Do not modify the job brief, the job config, or any artifact other than this substep's declared outputs.",
            "Retain exact source locators. Evidence is never obvious.",
        ]
    )


def build_claim_pass_prompt(
    stage: StageExecution,
    run_dir: Path,
    source_output_path: Path,
    claim_output_path: Path,
    scratch_markdown_path: Path,
    source_scratch_path: Path | None = None,
) -> str:
    packet_path = stage_packet_path(run_dir, stage.packet_name)
    sources_path = source_registry_path(run_dir)
    lines = [
        f"STAGE_ID={stage.stage_id}",
        "SUBSTEP=claim-pass",
        f"OUTPUT_PATH={scratch_markdown_path}",
        f"OUTPUT_JSON_PATH={claim_output_path}",
        f"SOURCE_PASS_PATH={source_output_path}",
    ]
    if source_scratch_path is not None:
        lines.append(f"SOURCE_NOTES_PATH={source_scratch_path}")
    lines.extend(
        [
            f"SOURCE_REGISTRY_PATH={sources_path}",
            f"PROMPT_PACKET={packet_path}",
            "",
            f"Execute only the claim pass for workflow stage `{stage.stage_id}`.",
            f"Read the full stage instructions from `{packet_path}`.",
            f"Read the validated stage-local sources from `{source_output_path}` and use only those source IDs.",
        ]
    )
    if source_scratch_path is not None:
        lines.append(
            f"Read the source pass research notes from `{source_scratch_path}` first; they contain the findings and excerpts already extracted from each source. Re-fetch a source only when the notes are insufficient for a claim."
        )
    lines.extend(
        [
            f"Write JSON to `{claim_output_path}`.",
            "Return the structured claim payload for this stage without a sources list; the runner will attach validated sources separately.",
            "Do not read or use artifacts from other runs under `runs/`, and do not read the parallel research pass.",
            "Do not modify the job brief, the job config, or any artifact other than this substep's declared outputs.",
            "Evidence is never obvious. Every fact and world-claim inference must carry explicit evidence on that exact item; nearby citations do not count.",
        ]
    )
    return "\n".join(lines)


def build_substep_repair_prompt(
    stage: StageExecution,
    *,
    run_dir: Path,
    substep: str,
    output_json_path: Path,
    validation_errors: list[str],
    scratch_markdown_path: Path,
    source_output_path: Path | None = None,
) -> str:
    packet_path = stage_packet_path(run_dir, stage.packet_name)
    sources_path = source_registry_path(run_dir)
    current_json = output_json_path.read_text(encoding="utf-8") if output_json_path.is_file() else "<missing>"
    prompt_lines = [
        f"STAGE_ID={stage.stage_id}",
        f"SUBSTEP={substep}",
        "REPAIR_ATTEMPT=1",
        f"OUTPUT_PATH={scratch_markdown_path}",
        f"OUTPUT_JSON_PATH={output_json_path}",
        f"SOURCE_REGISTRY_PATH={sources_path}",
        f"PROMPT_PACKET={packet_path}",
        "",
        f"Repair only the `{substep}` output for workflow stage `{stage.stage_id}`.",
        "Do not perform fresh research. Fix structure and support only.",
        "Evidence is never obvious. Nearby citations do not count.",
    ]
    if source_output_path is not None:
        prompt_lines.append(f"SOURCE_PASS_PATH={source_output_path}")
    prompt_lines.extend(
        [
            "",
            "VALIDATION_ERRORS:",
            *validation_errors,
            "",
            "CURRENT_STRUCTURED_OUTPUT:",
            current_json,
        ]
    )
    return "\n".join(prompt_lines)


def build_repair_prompt(
    stage: StageExecution,
    run_dir: Path,
    validation_errors: list[str],
) -> str:
    packet_path = stage_packet_path(run_dir, stage.packet_name)
    output_path = stage_output_path(run_dir, stage.output_name)
    json_output_path = stage_structured_output_path(run_dir, stage.stage_id) if is_structured_stage(stage.stage_id) else None
    sources_path = source_registry_path(run_dir)
    markdown_content = output_path.read_text(encoding="utf-8") if output_path.is_file() else "<missing>"
    json_content = (
        json_output_path.read_text(encoding="utf-8")
        if json_output_path is not None and json_output_path.is_file()
        else "<missing>"
    )
    return "\n".join(
        [
            f"STAGE_ID={stage.stage_id}",
            "REPAIR_ATTEMPT=1",
            f"OUTPUT_PATH={output_path}",
            f"OUTPUT_JSON_PATH={json_output_path}" if json_output_path is not None else "OUTPUT_JSON_PATH=not_applicable",
            f"SOURCE_REGISTRY_PATH={sources_path}",
            f"PROMPT_PACKET={packet_path}",
            "",
            f"Repair workflow stage `{stage.stage_id}`.",
            "Do not perform new research or reinterpret the task.",
            "Repair only the existing stage artifacts so they satisfy the contract.",
            "Evidence is never obvious. Every fact and world-claim inference must carry explicit evidence support on that exact item; nearby citations do not count.",
            "Keep source IDs canonical and keep local claim references only in claim_dependencies.",
            "",
            "VALIDATION_ERRORS:",
            *validation_errors,
            "",
            "CURRENT_MARKDOWN_ARTIFACT:",
            markdown_content,
            "",
            "CURRENT_STRUCTURED_ARTIFACT:",
            json_content,
        ]
    )

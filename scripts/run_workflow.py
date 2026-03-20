#!/usr/bin/env python3

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from _workflow_lib import (
    STAGES,
    build_manifest,
    ensure_job_is_external,
    load_template,
    validate_job_dir,
    write_json,
    write_text,
)


def render_packet(stage: dict[str, object], context: dict[str, str]) -> str:
    template = load_template(str(stage["template"]))
    return template.format(**context).rstrip() + "\n"


def stage_output_placeholder(stage: dict[str, object]) -> str:
    output_format = stage["format"]
    stage_id = stage["id"]
    if output_format == "json":
        return (
            "{\n"
            f'  "stage": "{stage_id}",\n'
            '  "status": "not_started",\n'
            '  "notes": "Populate this artifact during execution."\n'
            "}\n"
        )
    return (
        f"# Stage Output Placeholder: {stage_id}\n\n"
        "Status: not started\n\n"
        "Replace this placeholder with the stage output. Preserve citations, disagreement notes, "
        "and fact vs inference separation.\n"
    )


def build_state(job_dir: Path, run_id: str, run_dir: Path, created_at: str) -> dict[str, object]:
    return {
        "created_at": created_at,
        "job_dir": str(job_dir),
        "run_dir": str(run_dir),
        "run_id": run_id,
        "status": "scaffolded",
        "stages": [
            {
                "description": stage["description"],
                "depends_on": stage["depends_on"],
                "id": stage["id"],
                "output_path": str(run_dir / "stage-outputs" / str(stage["output"])),
                "packet_path": str(run_dir / "prompt-packets" / str(stage["packet"])),
                "status": "pending",
            }
            for stage in STAGES
        ],
    }


def build_work_order(job_dir: Path, run_id: str, created_at: str) -> str:
    lines = [
        "# Work Order",
        "",
        f"- Job directory: `{job_dir.resolve()}`",
        f"- Run ID: `{run_id}`",
        f"- Created at (UTC): `{created_at}`",
        "",
        "## Execution Rules",
        "",
        "- Write all artifacts into this job repo only.",
        "- Preserve disagreements until judge synthesis explicitly resolves them.",
        "- Do not introduce uncited factual claims.",
        "- Separate facts from inference in every analytical stage.",
        "- Keep provider-specific instructions out of the orchestration layer.",
        "",
        "## Stages",
        "",
    ]
    for index, stage in enumerate(STAGES, start=1):
        lines.append(
            f"{index}. `{stage['id']}` -> output `stage-outputs/{stage['output']}`"
        )
        dependencies = ", ".join(stage["depends_on"]) if stage["depends_on"] else "none"
        lines.append(f"   Depends on: {dependencies}")
        lines.append(f"   Prompt packet: `prompt-packets/{stage['packet']}`")
        lines.append(f"   Purpose: {stage['description']}")
    return "\n".join(lines) + "\n"


def scaffold_run(job_dir: Path, run_id: str) -> Path:
    ensure_job_is_external(job_dir)
    validation = validate_job_dir(job_dir)
    if not validation.ok:
        raise ValueError("Job repo validation failed:\n- " + "\n- ".join(validation.errors))

    run_dir = job_dir / "runs" / run_id
    if run_dir.exists():
        raise ValueError(f"Run directory already exists: {run_dir}")

    prompt_dir = run_dir / "prompt-packets"
    stage_dir = run_dir / "stage-outputs"
    audit_dir = run_dir / "audit"
    log_dir = run_dir / "logs"
    for directory in (prompt_dir, stage_dir, audit_dir, log_dir):
        directory.mkdir(parents=True, exist_ok=False)

    created_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    brief_text = (job_dir / "brief.md").read_text(encoding="utf-8").strip()
    config_text = (job_dir / "config.yaml").read_text(encoding="utf-8").strip()
    common_context = {
        "brief_markdown": brief_text,
        "config_yaml": config_text,
        "job_dir": str(job_dir.resolve()),
        "run_id": run_id,
        "run_dir": str(run_dir.resolve()),
    }

    created_files: list[Path] = []
    for stage in STAGES:
        context = dict(common_context)
        context["stage_id"] = str(stage["id"])
        context["stage_description"] = str(stage["description"])
        context["depends_on"] = ", ".join(stage["depends_on"]) if stage["depends_on"] else "none"
        context["stage_output_path"] = str((stage_dir / str(stage["output"])).resolve())
        context["prompt_packet_path"] = str((prompt_dir / str(stage["packet"])).resolve())
        context["researcher_label"] = str(stage.get("researcher_label", "Researcher"))
        context["critic_label"] = str(stage.get("critic_label", "Critic"))
        context["target_label"] = str(stage.get("target_label", "Target"))

        packet_path = prompt_dir / str(stage["packet"])
        write_text(packet_path, render_packet(stage, context))
        created_files.append(packet_path)

        output_path = stage_dir / str(stage["output"])
        write_text(output_path, stage_output_placeholder(stage))
        created_files.append(output_path)

    state_path = run_dir / "workflow-state.json"
    write_json(state_path, build_state(job_dir, run_id, run_dir, created_at))
    created_files.append(state_path)

    work_order_path = run_dir / "WORK_ORDER.md"
    write_text(work_order_path, build_work_order(job_dir, run_id, created_at))
    created_files.append(work_order_path)

    manifest_path = audit_dir / "manifest.json"
    write_json(manifest_path, {"files": build_manifest(created_files, run_dir)})
    created_files.append(manifest_path)

    summary_path = audit_dir / "run-summary.md"
    write_text(
        summary_path,
        "\n".join(
            [
                "# Run Summary",
                "",
                f"- Run ID: `{run_id}`",
                f"- Job directory: `{job_dir.resolve()}`",
                f"- Prompt packets: `{len(STAGES)}`",
                f"- Stage placeholders: `{len(STAGES)}`",
                "",
                "This run is scaffolded only. Provider API execution is intentionally out of scope for v1.",
            ]
        ),
    )

    return run_dir


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scaffold a multi-stage research workflow run.")
    parser.add_argument("--job-dir", required=True, help="Path to the target job repository.")
    parser.add_argument("--run-id", help="Stable run identifier. If omitted, a UTC timestamp is used.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    job_dir = Path(args.job_dir).expanduser()
    run_id = args.run_id or datetime.now(timezone.utc).strftime("run-%Y%m%dT%H%M%SZ")

    try:
        run_dir = scaffold_run(job_dir, run_id)
    except ValueError as exc:
        print(str(exc), flush=True, file=__import__("sys").stderr)
        return 1

    print(run_dir.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

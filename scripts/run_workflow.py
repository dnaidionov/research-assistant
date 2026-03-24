#!/usr/bin/env python3

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from _workflow_lib import (
    DEFAULT_JOB_ROOT,
    REPO_ROOT,
    build_manifest,
    ensure_job_is_external,
    load_template,
    validate_job_dir,
    write_json,
    write_text,
)

STAGE_CLAIM_STAGE_IDS = {"research-a", "research-b", "judge"}


RUN_STAGES: list[dict[str, object]] = [
    {
        "id": "intake",
        "packet": "01-intake.md",
        "template": "intake-template.md",
        "output": "01-intake.json",
        "format": "json",
        "depends_on": [],
        "description": "Normalize the brief into a structured intake record without inventing facts.",
    },
    {
        "id": "research-a",
        "packet": "02-research-a.md",
        "template": "research-template.md",
        "output": "02-research-a.md",
        "format": "markdown",
        "depends_on": ["intake"],
        "description": "Produce the first independent research pass with explicit citations and uncertainty.",
        "researcher_label": "Research Pass A",
    },
    {
        "id": "research-b",
        "packet": "03-research-b.md",
        "template": "research-template.md",
        "output": "03-research-b.md",
        "format": "markdown",
        "depends_on": ["intake"],
        "description": "Produce the second independent research pass without borrowing from pass A.",
        "researcher_label": "Research Pass B",
    },
    {
        "id": "critique-a-on-b",
        "packet": "04-critique-a-on-b.md",
        "template": "critique-template.md",
        "output": "04-critique-a-on-b.md",
        "format": "markdown",
        "depends_on": ["research-a", "research-b"],
        "description": "Have perspective A critique pass B for unsupported claims, omissions, weak sources, and overreach.",
        "critic_label": "Research Pass A",
        "target_label": "Research Pass B",
    },
    {
        "id": "critique-b-on-a",
        "packet": "05-critique-b-on-a.md",
        "template": "critique-template.md",
        "output": "05-critique-b-on-a.md",
        "format": "markdown",
        "depends_on": ["research-a", "research-b"],
        "description": "Have perspective B critique pass A for unsupported claims, omissions, weak sources, and overreach.",
        "critic_label": "Research Pass B",
        "target_label": "Research Pass A",
    },
    {
        "id": "judge",
        "packet": "06-judge.md",
        "template": "judge-template.md",
        "output": "06-judge.md",
        "format": "markdown",
        "depends_on": ["critique-a-on-b", "critique-b-on-a"],
        "description": "Synthesize both passes and both critiques while preserving unresolved disagreement where evidence is mixed.",
    },
]


def parse_simple_yaml_mapping(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        cleaned = value.strip().strip("'").strip('"')
        values[key.strip()] = cleaned
    return values


def resolve_job_index_entry(job_identifier: str, jobs_index_root: Path) -> tuple[str, Path] | None:
    active_dir = jobs_index_root / "active"
    direct_index_file = active_dir / f"{job_identifier}.yaml"
    candidate_files = [direct_index_file] if direct_index_file.is_file() else []
    if active_dir.is_dir():
        for path in sorted(active_dir.glob("*.yaml")):
            if path not in candidate_files:
                candidate_files.append(path)

    for index_file in candidate_files:
        metadata = parse_simple_yaml_mapping(index_file)
        if metadata.get("job_id") != job_identifier and index_file.stem != job_identifier:
            continue
        local_path = metadata.get("local_path")
        if local_path:
            candidate = (index_file.parent / local_path).resolve()
            return candidate.name, candidate
        return index_file.stem, (jobs_index_root.parent / index_file.stem).resolve()

    return None


def resolve_job_path(
    *,
    job_name: str | None,
    job_id: str | None,
    job_path: str | None,
    jobs_root: Path,
    jobs_index_root: Path,
) -> tuple[str, Path]:
    specified = [value is not None for value in (job_name, job_id, job_path)]
    if sum(specified) != 1:
        raise ValueError("Provide exactly one of --job-name, --job-id, or --job-path.")

    if job_path:
        resolved_path = Path(job_path).expanduser()
        return resolved_path.name, resolved_path

    if job_id is not None:
        resolved = resolve_job_index_entry(job_id, jobs_index_root)
        if resolved is not None:
            return resolved
        return job_id, (jobs_root / job_id).expanduser()

    assert job_name is not None
    resolved = resolve_job_index_entry(job_name, jobs_index_root)
    if resolved is not None:
        return resolved

    return job_name, (jobs_root / job_name).expanduser()


def render_packet(stage: dict[str, object], context: dict[str, str]) -> str:
    template = load_template(str(stage["template"]))
    return template.format(**context).rstrip() + "\n"


def dependency_output_paths(stage: dict[str, object], stage_dir: Path) -> list[Path]:
    outputs_by_id = {
        str(candidate["id"]): stage_dir / str(candidate["output"])
        for candidate in RUN_STAGES
    }
    return [outputs_by_id[str(stage_id)] for stage_id in stage["depends_on"]]


def render_upstream_artifacts_section(paths: list[Path]) -> str:
    if not paths:
        return "No upstream stage artifacts. This stage starts from the job brief and config.\n"

    lines = [
        "Use the output artifact from the dependency stage, not the dependency prompt packet.",
        "",
    ]
    for path in paths:
        lines.append(f"- `{path}`")
    return "\n".join(lines) + "\n"


def stage_output_placeholder(stage: dict[str, object], output_path: Path) -> str:
    output_format = str(stage["format"])
    stage_id = str(stage["id"])
    if output_format == "json":
        return (
            "{\n"
            f'  "stage": "{stage_id}",\n'
            '  "status": "not_started",\n'
            f'  "expected_output_target": "{output_path}",\n'
            '  "notes": "Populate this JSON artifact during execution."\n'
            "}\n"
        )

    return (
        f"# Stage Output Placeholder: {stage_id}\n\n"
        "Status: not started\n\n"
        f"Expected output target: `{output_path}`\n\n"
        "Replace this placeholder with the stage output. Preserve citations, explicit uncertainty, "
        "fact vs inference separation, and unresolved disagreement where applicable.\n"
    )


def stage_claim_output_path(run_dir: Path, stage: dict[str, object]) -> Path | None:
    stage_id = str(stage["id"])
    if stage_id not in STAGE_CLAIM_STAGE_IDS:
        return None
    output_name = Path(str(stage["output"]))
    return run_dir / "stage-claims" / f"{output_name.stem}.claims.json"


def stage_claim_placeholder(stage: dict[str, object], output_path: Path, claim_path: Path) -> dict[str, object]:
    return {
        "stage": str(stage["id"]),
        "status": "not_started",
        "expected_markdown_input": str(output_path),
        "expected_output_target": str(claim_path),
        "notes": "Populate this claim sidecar after the markdown stage output is complete and validated.",
    }


def build_state(job_name: str, job_dir: Path, run_id: str, run_dir: Path, created_at: str) -> dict[str, object]:
    stage_claims = {}
    for stage in RUN_STAGES:
        claim_path = stage_claim_output_path(run_dir, stage)
        if claim_path is None:
            continue
        stage_claims[str(stage["id"])] = {"output_path": str(claim_path), "status": "pending"}
    return {
        "created_at": created_at,
        "job_dir": str(job_dir),
        "job_name": job_name,
        "post_processing": {
            "stage_claims": stage_claims,
        },
        "run_dir": str(run_dir),
        "run_id": run_id,
        "status": "scaffolded",
        "stages": [
            {
                "depends_on": list(stage["depends_on"]),
                "description": stage["description"],
                "dependency_artifacts": [
                    str(path)
                    for path in dependency_output_paths(stage, run_dir / "stage-outputs")
                ],
                "expected_output_target": str(run_dir / "stage-outputs" / str(stage["output"])),
                "id": stage["id"],
                "packet_path": str(run_dir / "prompt-packets" / str(stage["packet"])),
                "prompt_template": str(stage["template"]),
                "status": "pending",
            }
            for stage in RUN_STAGES
        ],
    }


def build_work_order(job_name: str, job_dir: Path, run_id: str, created_at: str) -> str:
    lines = [
        "# Work Order",
        "",
        f"- Job name: `{job_name}`",
        f"- Job directory: `{job_dir.resolve()}`",
        f"- Run ID: `{run_id}`",
        f"- Created at (UTC): `{created_at}`",
        "",
        "## Execution Rules",
        "",
        "- Write all artifacts into this job repo only.",
        "- Keep provider-specific execution outside the orchestration layer.",
        "- Preserve disagreement when evidence is mixed.",
        "- Keep facts distinct from inference.",
        "- Do not introduce uncited factual claims.",
        "",
        "## Stages",
        "",
    ]
    for index, stage in enumerate(RUN_STAGES, start=1):
        output_name = f"stage-outputs/{stage['output']}"
        packet_name = f"prompt-packets/{stage['packet']}"
        dependencies = ", ".join(stage["depends_on"]) if stage["depends_on"] else "none"
        dependency_artifacts = dependency_output_paths(stage, job_dir / "runs" / run_id / "stage-outputs")
        lines.append(f"{index}. `{stage['id']}`")
        lines.append(f"   Depends on: {dependencies}")
        if dependency_artifacts:
            lines.append("   Upstream stage artifacts:")
            for artifact_path in dependency_artifacts:
                lines.append(f"   - `stage-outputs/{artifact_path.name}`")
            lines.append("   Use the output artifact from the dependency stage, not the dependency prompt packet.")
        else:
            lines.append("   Upstream stage artifacts: none")
        lines.append(f"   Prompt packet: `{packet_name}`")
        lines.append(f"   Expected output target: `{output_name}`")
        lines.append(f"   Purpose: {stage['description']}")
    return "\n".join(lines) + "\n"


def scaffold_run(job_name: str, job_dir: Path, run_id: str) -> Path:
    ensure_job_is_external(job_dir)
    validation = validate_job_dir(job_dir)
    if not validation.ok:
        raise ValueError("Job repo validation failed:\n- " + "\n- ".join(validation.errors))

    run_dir = job_dir / "runs" / run_id
    if run_dir.exists():
        raise ValueError(f"Run directory already exists: {run_dir}")

    prompt_dir = run_dir / "prompt-packets"
    stage_dir = run_dir / "stage-outputs"
    stage_claim_dir = run_dir / "stage-claims"
    audit_dir = run_dir / "audit"
    log_dir = run_dir / "logs"
    for directory in (prompt_dir, stage_dir, stage_claim_dir, audit_dir, log_dir):
        directory.mkdir(parents=True, exist_ok=False)

    created_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    brief_text = (job_dir / "brief.md").read_text(encoding="utf-8").strip()
    config_text = (job_dir / "config.yaml").read_text(encoding="utf-8").strip()

    common_context = {
        "brief_markdown": brief_text,
        "config_yaml": config_text,
        "job_dir": str(job_dir.resolve()),
        "prompt_packet_path": "",
        "run_id": run_id,
        "run_dir": str(run_dir.resolve()),
        "stage_description": "",
        "stage_id": "",
        "stage_output_path": "",
        "depends_on": "",
        "researcher_label": "Researcher",
        "critic_label": "Critic",
        "target_label": "Target",
    }

    created_files: list[Path] = []
    for stage in RUN_STAGES:
        output_path = stage_dir / str(stage["output"])
        packet_path = prompt_dir / str(stage["packet"])
        context = dict(common_context)
        context.update(
            {
                "critic_label": str(stage.get("critic_label", "Critic")),
                "depends_on": ", ".join(stage["depends_on"]) if stage["depends_on"] else "none",
                "prompt_packet_path": str(packet_path.resolve()),
                "researcher_label": str(stage.get("researcher_label", "Researcher")),
                "stage_description": str(stage["description"]),
                "stage_id": str(stage["id"]),
                "stage_output_path": str(output_path.resolve()),
                "upstream_stage_artifacts": render_upstream_artifacts_section(
                    dependency_output_paths(stage, stage_dir)
                ),
                "target_label": str(stage.get("target_label", "Target")),
            }
        )
        packet_body = render_packet(stage, context)
        packet_body += "\n## Upstream Stage Artifacts\n\n"
        packet_body += context["upstream_stage_artifacts"]
        write_text(packet_path, packet_body)
        created_files.append(packet_path)

        write_text(output_path, stage_output_placeholder(stage, output_path.resolve()))
        created_files.append(output_path)

        claim_path = stage_claim_output_path(run_dir, stage)
        if claim_path is not None:
            write_json(claim_path, stage_claim_placeholder(stage, output_path.resolve(), claim_path.resolve()))
            created_files.append(claim_path)

    state_path = run_dir / "workflow-state.json"
    write_json(state_path, build_state(job_name, job_dir, run_id, run_dir, created_at))
    created_files.append(state_path)

    work_order_path = run_dir / "WORK_ORDER.md"
    write_text(work_order_path, build_work_order(job_name, job_dir, run_id, created_at))
    created_files.append(work_order_path)

    manifest_path = audit_dir / "manifest.json"
    write_json(manifest_path, {"files": build_manifest(created_files, run_dir)})

    summary_path = audit_dir / "run-summary.md"
    write_text(
        summary_path,
        "\n".join(
            [
                "# Run Summary",
                "",
                f"- Job name: `{job_name}`",
                f"- Run ID: `{run_id}`",
                f"- Job directory: `{job_dir.resolve()}`",
                f"- Prompt packets rendered: `{len(RUN_STAGES)}`",
                f"- Stage output targets created: `{len(RUN_STAGES)}`",
                f"- Stage claim sidecars scaffolded: `{len(STAGE_CLAIM_STAGE_IDS)}`",
                "",
                "This run scaffold is provider-agnostic. Provider execution must be handled by a separate adapter layer.",
            ]
        ),
    )

    return run_dir


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a deterministic, auditable workflow run scaffold inside a research job repo.",
    )
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--job-name", help="Job name to resolve via jobs-index or jobs root.")
    target.add_argument("--job-id", help="Job id to resolve via jobs-index metadata or jobs root.")
    target.add_argument("--job-path", help="Explicit path to the target job repository.")
    parser.add_argument("--run-id", help="Stable run identifier. If omitted, a UTC timestamp is used.")
    parser.add_argument(
        "--jobs-root",
        default=str(DEFAULT_JOB_ROOT),
        help="Root directory containing job repos. Used when resolving --job-name or --job-id.",
    )
    parser.add_argument(
        "--jobs-index-root",
        default=str(REPO_ROOT / "jobs-index"),
        help="Root directory containing jobs-index metadata. Used when resolving --job-name or --job-id.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    jobs_root = Path(args.jobs_root).expanduser()
    jobs_index_root = Path(args.jobs_index_root).expanduser()

    try:
        job_name, job_dir = resolve_job_path(
            job_name=args.job_name,
            job_id=args.job_id,
            job_path=args.job_path,
            jobs_root=jobs_root,
            jobs_index_root=jobs_index_root,
        )
        run_id = args.run_id or datetime.now(timezone.utc).strftime("run-%Y%m%dT%H%M%SZ")
        run_dir = scaffold_run(job_name, job_dir, run_id)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"Workflow scaffolding failed: {exc}", file=sys.stderr)
        return 1

    print(run_dir.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

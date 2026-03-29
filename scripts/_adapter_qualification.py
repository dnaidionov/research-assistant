#!/usr/bin/env python3

from __future__ import annotations

import json
import tempfile
import subprocess
from pathlib import Path

from _adapter_regression import qualification_inputs_fingerprint
from _workflow_lib import REPO_ROOT
from _workflow_lib import write_json


PROBE_SET_VERSIONS: dict[str, str] = {
    "smoke": "smoke.v1",
    "workflow-regression": "workflow-regression.v2",
    "workflow-regression-realistic": "workflow-regression-realistic.v1",
}

STRUCTURED_TRUST_LEVELS = (
    "structured_safe_smoke",
    "structured_safe_regression",
    "structured_safe_realistic",
)
TRUST_LEVEL_ORDER: dict[str, int] = {
    "unsupported": 0,
    "markdown_only": 1,
    "structured_safe_smoke": 2,
    "structured_safe_regression": 3,
    "structured_safe_realistic": 4,
}
PROFILE_TRUST_LEVEL: dict[str, str] = {
    "smoke": "structured_safe_smoke",
    "workflow-regression": "structured_safe_regression",
    "workflow-regression-realistic": "structured_safe_realistic",
}
TRUST_LEVEL_PROFILE: dict[str, str] = {value: key for key, value in PROFILE_TRUST_LEVEL.items()}

QUALIFICATION_PROFILES: dict[str, tuple[dict[str, str | None], ...]] = {
    "smoke": (
        {
            "name": "markdown_render",
            "artifact_kind": "markdown",
            "stage_id": "research-a",
            "substep": None,
        },
        {
            "name": "intake_structured_json",
            "artifact_kind": "structured_json",
            "stage_id": "intake",
            "substep": None,
        },
        {
            "name": "source_pass_structured_json",
            "artifact_kind": "structured_json",
            "stage_id": "research-a",
            "substep": "source-pass",
        },
        {
            "name": "claim_pass_structured_json",
            "artifact_kind": "structured_json",
            "stage_id": "research-a",
            "substep": "claim-pass",
        },
    ),
    "workflow-regression": (
        {
            "name": "markdown_render",
            "artifact_kind": "markdown",
            "stage_id": "research-a",
            "substep": None,
        },
        {
            "name": "intake_structured_json",
            "artifact_kind": "structured_json",
            "stage_id": "intake",
            "substep": None,
        },
        {
            "name": "source_pass_structured_json",
            "artifact_kind": "structured_json",
            "stage_id": "research-a",
            "substep": "source-pass",
        },
        {
            "name": "claim_pass_structured_json",
            "artifact_kind": "structured_json",
            "stage_id": "research-a",
            "substep": "claim-pass",
        },
        {
            "name": "critique_claim_pass_structured_json",
            "artifact_kind": "structured_json",
            "stage_id": "critique-b-on-a",
            "substep": "claim-pass",
        },
        {
            "name": "judge_claim_pass_structured_json",
            "artifact_kind": "structured_json",
            "stage_id": "judge",
            "substep": "claim-pass",
        },
    ),
    "workflow-regression-realistic": (
        {
            "name": "markdown_render",
            "artifact_kind": "markdown",
            "stage_id": "research-a",
            "substep": None,
        },
        {
            "name": "intake_structured_json",
            "artifact_kind": "structured_json",
            "stage_id": "intake",
            "substep": None,
        },
        {
            "name": "source_pass_structured_json",
            "artifact_kind": "structured_json",
            "stage_id": "research-a",
            "substep": "source-pass",
        },
        {
            "name": "claim_pass_structured_json",
            "artifact_kind": "structured_json",
            "stage_id": "research-a",
            "substep": "claim-pass",
        },
        {
            "name": "critique_claim_pass_structured_json",
            "artifact_kind": "structured_json",
            "stage_id": "critique-b-on-a",
            "substep": "claim-pass",
        },
        {
            "name": "judge_claim_pass_structured_json",
            "artifact_kind": "structured_json",
            "stage_id": "judge",
            "substep": "claim-pass",
        },
    ),
}
REALISTIC_REFERENCE_PACKET_FILES: dict[str, str] = {
    "intake": "01-intake.md",
    "research-a": "02-research-a.md",
    "research-b": "03-research-b.md",
    "critique-a-on-b": "04-critique-a-on-b.md",
    "critique-b-on-a": "05-critique-b-on-a.md",
    "judge": "06-judge.md",
}
DEFAULT_FIXTURE_FAMILY = "neutral"
QUALIFICATION_FIXTURE_FAMILIES_ROOT = REPO_ROOT / "fixtures" / "adapter-qualification" / "families"


def trust_satisfies(actual: str, required: str) -> bool:
    return TRUST_LEVEL_ORDER.get(actual, -1) >= TRUST_LEVEL_ORDER.get(required, 10)


def list_fixture_families() -> list[str]:
    if not QUALIFICATION_FIXTURE_FAMILIES_ROOT.is_dir():
        return []
    return sorted(path.name for path in QUALIFICATION_FIXTURE_FAMILIES_ROOT.iterdir() if path.is_dir())


def resolve_qualification_fixture_dir(profile: str, family: str = DEFAULT_FIXTURE_FAMILY) -> Path:
    fixture_dir = QUALIFICATION_FIXTURE_FAMILIES_ROOT / family / profile
    if not fixture_dir.is_dir():
        raise ValueError(f"Qualification fixture family '{family}' does not provide profile '{profile}'.")
    return fixture_dir


def profile_for_required_trust(required_trust: str) -> str:
    try:
        return TRUST_LEVEL_PROFILE[required_trust]
    except KeyError as exc:
        raise ValueError(f"Unknown provider trust requirement: {required_trust}") from exc


def derive_trust_level(classification: str, profile: str) -> str:
    if classification == "structured_safe":
        return PROFILE_TRUST_LEVEL[profile]
    if classification == "markdown_only":
        return "markdown_only"
    return "unsupported"


def qualification_report_path(run_dir: Path, provider_key: str, adapter_name: str, profile: str = "smoke") -> Path:
    safe_provider = provider_key.replace("/", "-")
    suffix = "" if profile == "smoke" else f".{profile}"
    return run_dir / "audit" / "adapter-qualification" / f"{safe_provider}.{adapter_name}{suffix}.json"


def build_qualification_prompt(
    probe_name: str,
    artifact_kind: str,
    output_path: Path,
    *,
    stage_id: str,
    substep: str | None,
    qualification_profile: str,
    reference_packet: str | None = None,
) -> str:
    lines = [
        "ADAPTER_QUALIFICATION=1",
        f"QUALIFICATION_PROBE={probe_name}",
        f"QUALIFICATION_PROFILE={qualification_profile}",
        f"STAGE_ID={stage_id}",
        f"OUTPUT_PATH={output_path}",
        f"QUALIFY_ARTIFACT_KIND={artifact_kind}",
        "",
    ]
    if substep is not None:
        lines.insert(3, f"SUBSTEP={substep}")
    if artifact_kind == "structured_json":
        lines.extend(
            [
                "Return exact JSON only and nothing else.",
                'Required payload: {"stage": "adapter-qualification", "status": "ok"}',
            ]
        )
    else:
        lines.extend(
            [
                "Write markdown only and nothing else.",
                "Required content: # Adapter qualification markdown",
            ]
        )
    if reference_packet is not None:
        lines.extend(
            [
                "",
                "REFERENCE_PROMPT_PACKET_BEGIN",
                reference_packet.strip(),
                "REFERENCE_PROMPT_PACKET_END",
                "",
                "The reference packet above is a sanitized real workflow packet. Do not answer it. Obey the qualification artifact instruction only.",
            ]
        )
    return "\n".join(lines)


def render_reference_prompt_packet(
    stage_id: str,
    root: Path,
    *,
    profile: str = "workflow-regression",
    family: str = DEFAULT_FIXTURE_FAMILY,
) -> str:
    if profile == "workflow-regression-realistic":
        fixture_name = REALISTIC_REFERENCE_PACKET_FILES[stage_id]
        fixture_path = resolve_qualification_fixture_dir(profile, family) / fixture_name
        return fixture_path.read_text(encoding="utf-8")

    from run_workflow import RUN_STAGES, render_packet, render_upstream_artifacts_section
    from _stage_contracts import is_structured_stage, source_registry_path, stage_structured_output_path

    stage = next(candidate for candidate in RUN_STAGES if str(candidate["id"]) == stage_id)
    run_dir = root / "qualification-run"
    stage_dir = run_dir / "stage-outputs"
    prompt_dir = run_dir / "prompt-packets"
    packet_path = prompt_dir / str(stage["packet"])
    output_path = stage_dir / str(stage["output"])
    brief_text = "# Research Brief\n\n## Question\nWhich option is better?\n\n## Constraints\n- Keep citations explicit.\n"
    config_text = "topic: adapter-qualification\nrequirements:\n  require_citations: true\n"
    outputs_by_id = {str(candidate["id"]): stage_dir / str(candidate["output"]) for candidate in RUN_STAGES}
    upstream_paths = [outputs_by_id[str(dep)] for dep in stage["depends_on"]]
    context = {
        "brief_markdown": brief_text.strip(),
        "config_yaml": config_text.strip(),
        "critic_label": str(stage.get("critic_label", "Critic")),
        "depends_on": ", ".join(stage["depends_on"]) if stage["depends_on"] else "none",
        "job_dir": str(root.resolve()),
        "prompt_packet_path": str(packet_path.resolve()),
        "researcher_label": str(stage.get("researcher_label", "Researcher")),
        "run_id": "qualification-run",
        "run_dir": str(run_dir.resolve()),
        "source_registry_path": str(source_registry_path(run_dir).resolve()),
        "stage_description": str(stage["description"]),
        "stage_id": stage_id,
        "stage_output_path": str(output_path.resolve()),
        "stage_structured_output_path": (
            str(stage_structured_output_path(run_dir, stage_id).resolve())
            if is_structured_stage(stage_id)
            else "not_applicable"
        ),
        "target_label": str(stage.get("target_label", "Target")),
        "upstream_stage_artifacts": render_upstream_artifacts_section(upstream_paths),
    }
    packet_body = render_packet(stage, context)
    packet_body += "\n## Upstream Stage Artifacts\n\n"
    packet_body += context["upstream_stage_artifacts"]
    return packet_body


def _validate_markdown_output(path: Path) -> tuple[bool, str | None]:
    if not path.is_file():
        return False, "markdown artifact was not written"
    content = path.read_text(encoding="utf-8")
    if not content.strip():
        return False, "markdown artifact is empty"
    return True, None


def _validate_structured_output(path: Path) -> tuple[bool, str | None]:
    if not path.is_file():
        return False, "structured output artifact was not written"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return False, f"structured output is not exact JSON: {exc}"
    if not isinstance(payload, dict):
        return False, "structured output must be a top-level object"
    if payload.get("stage") != "adapter-qualification":
        return False, "structured output did not preserve the expected stage marker"
    if payload.get("status") != "ok":
        return False, "structured output did not preserve the expected status marker"
    return True, None


def detect_adapter_version(adapter_bin: Path) -> str:
    version_commands = (
        [str(adapter_bin), "--version"],
        [str(adapter_bin), "version"],
        [str(adapter_bin), "-v"],
    )
    for cmd in version_commands:
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        except Exception:
            continue
        output = (result.stdout or result.stderr or "").strip()
        if output:
            return output.splitlines()[0].strip()
    return "<unavailable>"


def classify_adapter_qualification(
    adapter_name: str,
    adapter_bin: Path,
    job_dir: Path,
    *,
    profile: str = "smoke",
) -> dict[str, object]:
    from execute_workflow import build_adapter_executor, resolve_adapter

    if profile not in QUALIFICATION_PROFILES:
        raise ValueError(f"Unknown qualification profile: {profile}")
    adapter = resolve_adapter(adapter_name)
    probe_results: dict[str, dict[str, object]] = {}
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        for probe in QUALIFICATION_PROFILES[profile]:
            probe_name = str(probe["name"])
            artifact_kind = str(probe["artifact_kind"])
            probe_path = root / ("probe.md" if artifact_kind == "markdown" else "probe.json")
            try:
                executor = build_adapter_executor(adapter_name, adapter_bin, artifact_kind)
            except ValueError as exc:
                probe_results[probe_name] = {"ok": False, "error": str(exc)}
                continue
            prompt = build_qualification_prompt(
                probe_name,
                artifact_kind,
                probe_path,
                stage_id=str(probe["stage_id"]),
                substep=str(probe["substep"]) if probe["substep"] is not None else None,
                qualification_profile=profile,
                reference_packet=(
                    render_reference_prompt_packet(
                        str(probe["stage_id"]),
                        root,
                        profile=profile,
                        family=DEFAULT_FIXTURE_FAMILY,
                    )
                    if profile in {"workflow-regression", "workflow-regression-realistic"}
                    else None
                ),
            )
            cmd = adapter.command_builder(str(adapter_bin), job_dir, prompt, None)
            result = executor(cmd, job_dir=job_dir, output_path=probe_path, stage_id="adapter-qualification")
            if result.returncode != 0:
                probe_results[probe_name] = {
                    "ok": False,
                    "error": result.stderr.strip() or f"{artifact_kind} qualification command failed",
                }
                continue
            ok, error = (
                _validate_markdown_output(probe_path)
                if artifact_kind == "markdown"
                else _validate_structured_output(probe_path)
            )
            probe_results[probe_name] = {"ok": ok}
            if error:
                probe_results[probe_name]["error"] = error

    markdown_probe = probe_results.get("markdown_render", {"ok": False, "error": "not tested"})
    structured_probe_names = [
        str(probe["name"])
        for probe in QUALIFICATION_PROFILES[profile]
        if str(probe["artifact_kind"]) == "structured_json"
    ]
    structured_ok = all(probe_results.get(name, {}).get("ok") for name in structured_probe_names)
    structured_errors = [
        f"{name}: {probe_results[name]['error']}"
        for name in structured_probe_names
        if not probe_results.get(name, {}).get("ok") and "error" in probe_results.get(name, {})
    ]

    if markdown_probe.get("ok") and structured_ok:
        classification = "structured_safe"
    elif markdown_probe.get("ok"):
        classification = "markdown_only"
    else:
        classification = "unsupported"
    return {
        "adapter": adapter_name,
        "binary": str(adapter_bin),
        "adapter_version": detect_adapter_version(adapter_bin),
        "classification": classification,
        "trust_level": derive_trust_level(classification, profile),
        "profile": profile,
        "probe_set_version": PROBE_SET_VERSIONS[profile],
        "qualification_inputs_fingerprint": qualification_inputs_fingerprint(REPO_ROOT, job_dir),
        "markdown": markdown_probe,
        "structured_json": {
            "ok": structured_ok,
            **({"error": "; ".join(structured_errors)} if structured_errors else {}),
        },
        "probes": probe_results,
    }


def persist_adapter_qualification(
    run_dir: Path,
    provider_key: str,
    adapter_name: str,
    payload: dict[str, object],
    *,
    profile: str = "smoke",
) -> Path:
    path = qualification_report_path(run_dir, provider_key, adapter_name, profile)
    write_json(path, payload)
    return path

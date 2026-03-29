#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from _job_config import load_quality_policy
from _publication import publication_readiness_errors
from _workflow_lib import REPO_ROOT, REQUIRED_JOB_DIRS, REQUIRED_JOB_FILES, validate_job_dir


EXIT_OK = 0
EXIT_VALIDATION_ERROR = 2
EXIT_RUNTIME_ERROR = 3

TEMPLATE_README = REPO_ROOT / "templates" / "job-template" / "README.md"
AUTOMATION_DOC = REPO_ROOT / "docs" / "product" / "automation-workflow.md"
CODEX_HANDOFF = REPO_ROOT / "docs" / "product" / "codex-handoff.md"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate a research job repository and the repo-level job contract it depends on."
    )
    parser.add_argument("--job-dir", required=True, help="Path to the job repository.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    parser.add_argument(
        "--final-artifact-ready",
        action="store_true",
        help="Validate that the job has the minimum required inputs for final artifact generation.",
    )
    parser.add_argument("--judge-artifact", help="Path to the judge markdown artifact to validate.")
    parser.add_argument("--claim-register", help="Path to the claim register JSON artifact to validate.")
    return parser.parse_args()


def list_required_paths_from_template() -> tuple[set[str], set[str]]:
    readme = TEMPLATE_README.read_text(encoding="utf-8")
    required_files = set(re.findall(r"- `([^`]+)` -", readme))
    required_dirs = {name for name in required_files if name.endswith("/")}
    required_files = {name for name in required_files if not name.endswith("/")}
    return required_files, {name.rstrip("/") for name in required_dirs}


def list_expected_job_root_dirs_from_docs() -> set[str]:
    docs_text = AUTOMATION_DOC.read_text(encoding="utf-8") + "\n" + CODEX_HANDOFF.read_text(encoding="utf-8")
    matches = re.findall(r"- `([a-z0-9_-]+)/`", docs_text)
    return {name for name in matches if name in {"outputs", "evidence", "audit", "logs"}}


def is_readable_file(path: Path) -> bool:
    try:
        path.read_text(encoding="utf-8")
    except OSError:
        return False
    except UnicodeDecodeError:
        return False
    return True


def validate_repo_boundary(job_dir: Path, errors: list[str]) -> bool:
    try:
        job_dir.resolve().relative_to(REPO_ROOT.resolve())
    except ValueError:
        return True
    errors.append(
        "Job repository must be separate from the assistant repo. "
        f"Received path inside assistant repo: {job_dir.resolve()}"
    )
    return False


def validate_readable_job_artifacts(job_dir: Path, errors: list[str], checks: dict[str, bool]) -> None:
    readable = True
    key_files = ["brief.md", "config.yaml"]
    for file_name in key_files:
        path = job_dir / file_name
        if not path.is_file():
            readable = False
            errors.append(f"Required file is missing or not a regular file: {file_name}")
            continue
        if not is_readable_file(path):
            readable = False
            errors.append(f"Required file is not readable as UTF-8 text: {file_name}")
    checks["key_files_readable"] = readable


def validate_runs_path(job_dir: Path, errors: list[str], checks: dict[str, bool]) -> None:
    runs_path = job_dir / "runs"
    if not runs_path.exists():
        checks["runs_path_valid"] = False
        errors.append("Missing required runs path: runs")
        return
    if not runs_path.is_dir():
        checks["runs_path_valid"] = False
        errors.append("Invalid runs path: runs must be a directory.")
        return
    checks["runs_path_valid"] = True


def validate_template_consistency(errors: list[str], checks: dict[str, bool]) -> None:
    template_files, template_dirs = list_required_paths_from_template()
    doc_dirs = list_expected_job_root_dirs_from_docs()

    expected_template_files = set(REQUIRED_JOB_FILES)
    expected_template_dirs = set(REQUIRED_JOB_DIRS)

    consistent = True
    if template_files != expected_template_files:
        consistent = False
        errors.append(
            "Template README required files are out of sync with validator expectations: "
            f"template={sorted(template_files)} validator={sorted(expected_template_files)}"
        )
    if template_dirs != expected_template_dirs:
        consistent = False
        errors.append(
            "Template README required directories are out of sync with validator expectations: "
            f"template={sorted(template_dirs)} validator={sorted(expected_template_dirs)}"
        )
    if doc_dirs != {"outputs", "evidence", "audit", "logs"}:
        consistent = False
        errors.append(
            "Job artifact directories documented in product docs are inconsistent. "
            f"Found: {sorted(doc_dirs)}"
        )
    checks["template_docs_consistent"] = consistent


def validate_final_artifact_readiness(
    job_dir: Path,
    judge_artifact: str | None,
    claim_register: str | None,
    errors: list[str],
    checks: dict[str, bool],
) -> None:
    if judge_artifact is None or claim_register is None:
        checks["final_artifact_ready"] = False
        errors.append("Final artifact readiness requires both --judge-artifact and --claim-register.")
        return

    ready = True
    judge_path = Path(judge_artifact).expanduser()
    claim_path = Path(claim_register).expanduser()
    judge_text = ""
    judge_structured_payload = None

    if not judge_path.is_file():
        ready = False
        errors.append(f"Missing required judge artifact: {judge_path}")
    else:
        judge_text = judge_path.read_text(encoding="utf-8")
        if not judge_text.strip():
            ready = False
            errors.append(f"Judge artifact is empty: {judge_path}")
        judge_json_path = judge_path.with_suffix(".json")
        if judge_json_path.is_file():
            judge_structured_payload = json.loads(judge_json_path.read_text(encoding="utf-8"))

    if not claim_path.is_file():
        ready = False
        errors.append(f"Missing required claim register: {claim_path}")
    else:
        payload = json.loads(claim_path.read_text(encoding="utf-8"))
        publication_errors = publication_readiness_errors(
            judge_text,
            payload,
            judge_structured_payload=judge_structured_payload,
            judge_path=judge_path if judge_text else None,
            quality_policy=load_quality_policy(job_dir),
        )
        if publication_errors:
            ready = False
            errors.extend(publication_errors)

    checks["final_artifact_ready"] = ready


def build_payload(job_dir: Path, errors: list[str], warnings: list[str], checks: dict[str, bool]) -> dict[str, object]:
    ok = not errors
    return {
        "checks": checks,
        "errors": errors,
        "exit_code": EXIT_OK if ok else EXIT_VALIDATION_ERROR,
        "job_dir": str(job_dir.resolve()),
        "ok": ok,
        "warnings": warnings,
    }


def emit_text(payload: dict[str, object]) -> None:
    print(f"Job: {payload['job_dir']}")
    print(f"OK: {payload['ok']}")
    print(f"Exit code: {payload['exit_code']}")
    print("Checks:")
    for key, value in payload["checks"].items():
        status = "PASS" if value else "FAIL"
        print(f"- {key}: {status}")
    if payload["warnings"]:
        print("Warnings:")
        for warning in payload["warnings"]:
            print(f"- {warning}")
    if payload["errors"]:
        print("Errors:")
        for error in payload["errors"]:
            print(f"- {error}")


def main() -> int:
    args = parse_args()
    job_dir = Path(args.job_dir).expanduser()
    errors: list[str] = []
    warnings: list[str] = []
    checks: dict[str, bool] = {}

    try:
        base_result = validate_job_dir(job_dir)
        errors.extend(base_result.errors)
        warnings.extend(base_result.warnings)
        checks["required_paths_exist"] = not base_result.errors

        checks["separate_from_assistant_repo"] = validate_repo_boundary(job_dir, errors)
        validate_readable_job_artifacts(job_dir, errors, checks)
        validate_runs_path(job_dir, errors, checks)
        validate_template_consistency(errors, checks)
        if args.final_artifact_ready:
            validate_final_artifact_readiness(job_dir, args.judge_artifact, args.claim_register, errors, checks)

        payload = build_payload(job_dir, sorted(set(errors)), sorted(set(warnings)), checks)
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            emit_text(payload)
        return int(payload["exit_code"])
    except OSError as exc:
        payload = {
            "checks": checks,
            "errors": [f"Validator runtime error: {exc}"],
            "exit_code": EXIT_RUNTIME_ERROR,
            "job_dir": str(job_dir),
            "ok": False,
            "warnings": warnings,
        }
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            emit_text(payload)
        return EXIT_RUNTIME_ERROR


if __name__ == "__main__":
    raise SystemExit(main())

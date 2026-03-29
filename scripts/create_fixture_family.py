#!/usr/bin/env python3

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from _adapter_qualification import DEFAULT_FIXTURE_FAMILY
from _workflow_lib import REPO_ROOT


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scaffold a new fixture family by copying the neutral baseline into both fixture roots."
    )
    parser.add_argument("family", help="New fixture family name, for example market-entry or biomedical-review.")
    parser.add_argument(
        "--from-family",
        default=DEFAULT_FIXTURE_FAMILY,
        help="Existing fixture family to copy from. Defaults to the neutral baseline.",
    )
    return parser.parse_args()


def _slug(value: str) -> str:
    slug = value.strip().lower().replace("_", "-").replace(" ", "-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug


def _replace_markers(path: Path, target_family: str) -> None:
    text = path.read_text(encoding="utf-8")
    replacements = {
        "Fixture Family: neutral": f"Fixture Family: {target_family}",
        "Neutral Research Brief": f"{target_family.title()} Research Brief",
        "Neutral Reference Job": f"{target_family.title()} Reference Job",
        "qualification-fixture-neutral": f"qualification-fixture-{target_family}",
        "reference-job-neutral": f"reference-job-{target_family}",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    path.write_text(text, encoding="utf-8")


def scaffold_fixture_family(
    family: str,
    *,
    repo_root: Path = REPO_ROOT,
    from_family: str = DEFAULT_FIXTURE_FAMILY,
) -> dict[str, str]:
    target_family = _slug(family)
    source_family = _slug(from_family)
    qualification_source = repo_root / "fixtures" / "adapter-qualification" / "families" / source_family
    reference_source = repo_root / "fixtures" / "reference-job" / "families" / source_family
    qualification_target = repo_root / "fixtures" / "adapter-qualification" / "families" / target_family
    reference_target = repo_root / "fixtures" / "reference-job" / "families" / target_family

    if not qualification_source.is_dir() or not reference_source.is_dir():
        raise ValueError(f"Source fixture family does not exist: {source_family}")
    if qualification_target.exists() or reference_target.exists():
        raise ValueError(f"Fixture family '{target_family}' already exists.")

    shutil.copytree(qualification_source, qualification_target)
    shutil.copytree(reference_source, reference_target)

    for path in list(qualification_target.rglob("*")) + list(reference_target.rglob("*")):
        if path.is_file():
            _replace_markers(path, target_family)

    return {
        "family": target_family,
        "qualification_dir": str(qualification_target),
        "reference_dir": str(reference_target),
    }


def main() -> int:
    args = parse_args()
    result = scaffold_fixture_family(args.family, from_family=args.from_family)
    print(f"Created fixture family '{result['family']}'.")
    print(f"Qualification fixtures: {result['qualification_dir']}")
    print(f"Reference job fixtures: {result['reference_dir']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

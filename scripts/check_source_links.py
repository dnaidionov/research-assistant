#!/usr/bin/env python3

"""Deterministic locator checker for a run's source registry.

Verifies that external-evidence locators are actually followable: http(s)
URLs respond, and local file locators exist. This is the cheap first line of
defense against hallucinated citations — a fabricated URL passes schema
validation but fails here.

Network access makes this checker unsuitable for the inline execution path,
so it ships as a standalone post-run audit step:

    python3 scripts/check_source_links.py --sources <run-dir>/sources.json
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

DEFAULT_TIMEOUT_SECONDS = 15
USER_AGENT = "research-assistant-link-check/1.0"

CHECKED_SOURCE_CLASSES = {"external_evidence"}


def default_url_fetcher(url: str, timeout: float) -> tuple[bool, str]:
    """Return (reachable, detail). Tries HEAD first, falls back to GET."""
    for method in ("HEAD", "GET"):
        request = urllib.request.Request(url, method=method, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                status = getattr(response, "status", 200)
                if 200 <= status < 400:
                    return True, f"{method} {status}"
                if method == "GET":
                    return False, f"{method} {status}"
        except urllib.error.HTTPError as exc:
            # Some hosts reject HEAD; only trust the GET verdict.
            if method == "GET":
                return False, f"{method} HTTP {exc.code}"
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            if method == "GET":
                return False, f"{method} failed: {exc}"
    return False, "unreachable"


def check_source(
    source: dict[str, object],
    *,
    timeout: float,
    url_fetcher: Callable[[str, float], tuple[bool, str]],
    base_dir: Path,
) -> dict[str, str]:
    source_id = str(source.get("id") or "<missing-id>")
    source_class = str(source.get("source_class") or "")
    locator = str(source.get("locator") or "").strip()

    if source_class and source_class not in CHECKED_SOURCE_CLASSES:
        return {"id": source_id, "locator": locator, "status": "skipped", "detail": f"source_class {source_class}"}
    if not locator:
        return {"id": source_id, "locator": locator, "status": "broken", "detail": "empty locator"}

    if locator.startswith(("http://", "https://")):
        reachable, detail = url_fetcher(locator, timeout)
        return {"id": source_id, "locator": locator, "status": "ok" if reachable else "broken", "detail": detail}

    if locator.startswith("file://"):
        path = Path(locator[len("file://") :])
        exists = path.is_file() or path.is_dir()
        return {
            "id": source_id,
            "locator": locator,
            "status": "ok" if exists else "broken",
            "detail": "file exists" if exists else "file missing",
        }

    candidate = Path(locator).expanduser()
    if not candidate.is_absolute():
        candidate = base_dir / candidate
    if candidate.exists():
        return {"id": source_id, "locator": locator, "status": "ok", "detail": "path exists"}
    return {"id": source_id, "locator": locator, "status": "unverifiable", "detail": "locator form not checkable"}


def check_registry(
    registry: dict[str, object],
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    url_fetcher: Callable[[str, float], tuple[bool, str]] = default_url_fetcher,
    base_dir: Path | None = None,
) -> dict[str, object]:
    results = [
        check_source(
            source,
            timeout=timeout,
            url_fetcher=url_fetcher,
            base_dir=base_dir or Path.cwd(),
        )
        for source in registry.get("sources", [])
        if isinstance(source, dict)
    ]
    counts: dict[str, int] = {}
    for result in results:
        counts[result["status"]] = counts.get(result["status"], 0) + 1
    return {
        "results": results,
        "summary": {
            "checked": len(results),
            **counts,
            "broken_ids": [result["id"] for result in results if result["status"] == "broken"],
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check that source registry locators are followable.")
    parser.add_argument("--sources", required=True, help="Path to a run's sources.json.")
    parser.add_argument("--output", help="Optional path to write the JSON check report.")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS, help="Per-URL timeout in seconds.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    sources_path = Path(args.sources).expanduser()
    if not sources_path.is_file():
        print(f"Source registry not found: {sources_path}", file=sys.stderr)
        return 1
    try:
        registry = json.loads(sources_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        print(f"Could not read source registry: {exc}", file=sys.stderr)
        return 1

    report = check_registry(registry, timeout=args.timeout, base_dir=sources_path.parent)

    if args.output:
        output_path = Path(args.output).expanduser()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    summary = report["summary"]
    print(
        f"Checked {summary['checked']} sources: "
        f"{summary.get('ok', 0)} ok, {summary.get('broken', 0)} broken, "
        f"{summary.get('skipped', 0)} skipped, {summary.get('unverifiable', 0)} unverifiable."
    )
    for result in report["results"]:
        if result["status"] == "broken":
            print(f"- BROKEN {result['id']}: {result['locator']} ({result['detail']})")
    return 1 if summary.get("broken") else 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3

"""Deterministic locator checker for a run's source registry.

Verifies that external-evidence locators are actually followable: http(s)
URLs respond, and local file locators exist. This is the cheap first line of
defense against hallucinated citations — a fabricated URL passes schema
validation but fails here.

With --verify-excerpts it additionally fetches each cited document and checks
that the quoted excerpts recorded on research-stage evidence links actually
appear in the source text, catching excerpts that were paraphrased or
invented rather than quoted.

Network access makes this checker unsuitable for the inline execution path,
so it ships as a standalone post-run audit step:

    python3 scripts/check_source_links.py --sources <run-dir>/sources.json [--verify-excerpts]
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

DEFAULT_TIMEOUT_SECONDS = 15
USER_AGENT = "research-assistant-link-check/1.0"

CHECKED_SOURCE_CLASSES = {"external_evidence"}

# Matches schemeless URLs such as "example.com/page" or "docs.python.org",
# which are not checkable as local paths and not fetched without a scheme.
SCHEMELESS_URL_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]*(\.[A-Za-z]{2,})+([/:?#]|$)")

# Extensions that mark a bare, separator-less locator such as "spec.pdf" as a
# local file rather than a schemeless domain. Deliberately excludes extensions
# that are also plausible TLDs in citations (e.g. zip, app, mov).
LOCAL_FILE_EXTENSIONS = {
    "pdf", "md", "markdown", "txt", "rst",
    "doc", "docx", "xls", "xlsx", "ppt", "pptx",
    "csv", "tsv", "json", "yaml", "yml", "xml",
    "html", "htm", "png", "jpg", "jpeg", "gif", "svg",
}


def looks_like_local_path(locator: str) -> bool:
    if locator.startswith(("~", "/", "./", "../")):
        return True
    if "/" not in locator and "\\" not in locator:
        suffix = locator.rsplit(".", 1)[-1].lower() if "." in locator else ""
        return suffix in LOCAL_FILE_EXTENSIONS
    if SCHEMELESS_URL_PATTERN.match(locator):
        return False
    return True


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
    if looks_like_local_path(locator):
        # Concrete local paths are a first-class resolvable locator form; a
        # missing one is a failed check, same as a missing file:// locator.
        return {"id": source_id, "locator": locator, "status": "broken", "detail": "path missing"}
    return {"id": source_id, "locator": locator, "status": "unverifiable", "detail": "locator form not checkable"}


MAX_DOCUMENT_BYTES = 4 * 1024 * 1024
SHINGLE_WORDS = 5
PARTIAL_MATCH_THRESHOLD = 0.5

RESEARCH_STAGE_IDS = {"research-a", "research-b"}

_TAG_PATTERN = re.compile(r"<(script|style)\b.*?</\1>", re.IGNORECASE | re.DOTALL)
_ANY_TAG_PATTERN = re.compile(r"<[^>]+>")
_NORMALIZE_PATTERN = re.compile(r"[\s ]+")
_QUOTE_TRANSLATION = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-"})


def default_content_fetcher(url: str, timeout: float) -> tuple[str | None, str]:
    """Return (document_text, detail). None when the document could not be fetched."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(MAX_DOCUMENT_BYTES)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return None, f"fetch failed: {exc}"
    return raw.decode("utf-8", errors="replace"), "fetched"


def html_to_text(payload: str) -> str:
    without_blocks = _TAG_PATTERN.sub(" ", payload)
    without_tags = _ANY_TAG_PATTERN.sub(" ", without_blocks)
    return html.unescape(without_tags)


def normalize_for_match(text: str) -> str:
    return _NORMALIZE_PATTERN.sub(" ", text.translate(_QUOTE_TRANSLATION)).casefold().strip()


def match_excerpt(document_text: str, excerpt: str) -> tuple[str, float]:
    """Match a quoted excerpt against document text.

    Full normalized containment verifies; otherwise the fraction of the
    excerpt's word shingles found in the document scores a partial match,
    tolerating trimming at the edges without accepting invented quotes.
    """
    norm_doc = normalize_for_match(document_text)
    norm_excerpt = normalize_for_match(excerpt)
    if not norm_excerpt:
        return "not_found", 0.0
    if norm_excerpt in norm_doc:
        return "verified", 1.0
    words = norm_excerpt.split()
    if len(words) <= SHINGLE_WORDS:
        return "not_found", 0.0
    shingles = [" ".join(words[i : i + SHINGLE_WORDS]) for i in range(len(words) - SHINGLE_WORDS + 1)]
    hits = sum(1 for shingle in shingles if shingle in norm_doc)
    score = hits / len(shingles)
    if score >= PARTIAL_MATCH_THRESHOLD:
        return "partial", round(score, 3)
    return "not_found", round(score, 3)


def collect_evidence_excerpts(run_dir: Path) -> list[dict[str, str]]:
    """Gather (source_id, excerpt) pairs from research-stage evidence links."""
    excerpts: list[dict[str, str]] = []
    stage_outputs = run_dir / "stage-outputs"
    if not stage_outputs.is_dir():
        return excerpts
    for stage_json in sorted(stage_outputs.glob("*.json")):
        try:
            payload = json.loads(stage_json.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(payload, dict) or payload.get("stage") not in RESEARCH_STAGE_IDS:
            continue
        for section in ("facts", "inferences"):
            for item in payload.get(section, []):
                if not isinstance(item, dict):
                    continue
                for link in item.get("support_links", []):
                    if not isinstance(link, dict) or link.get("role") != "evidence":
                        continue
                    excerpt = str(link.get("excerpt") or "").strip()
                    source_id = str(link.get("source_id") or "").strip()
                    if excerpt and source_id:
                        excerpts.append(
                            {
                                "stage": str(payload.get("stage")),
                                "claim_id": str(item.get("id") or ""),
                                "source_id": source_id,
                                "excerpt": excerpt,
                            }
                        )
    return excerpts


def _load_document_for_source(
    source: dict[str, object],
    *,
    timeout: float,
    content_fetcher: Callable[[str, float], tuple[str | None, str]],
    base_dir: Path,
    cache: dict[str, tuple[str | None, str]],
) -> tuple[str | None, str]:
    locator = str(source.get("locator") or "").strip()
    if not locator:
        return None, "empty locator"
    if locator in cache:
        return cache[locator]
    # Strip query/fragment so PDFs served behind ?download=1 style URLs are
    # still recognized; content sniffing below catches the rest.
    locator_path = locator.split("#", 1)[0].split("?", 1)[0]
    if locator_path.lower().endswith(".pdf"):
        result: tuple[str | None, str] = (None, "binary format not text-checkable")
    elif locator.startswith(("http://", "https://")):
        text, detail = content_fetcher(locator, timeout)
        if text is not None and text.lstrip().startswith("%PDF-"):
            result = (None, "binary format not text-checkable")
        else:
            result = (html_to_text(text) if text is not None else None, detail)
    else:
        path = Path(locator[len("file://") :]) if locator.startswith("file://") else Path(locator).expanduser()
        if not path.is_absolute():
            path = base_dir / path
        if not path.is_file():
            result = (None, "file missing")
        else:
            try:
                raw = path.read_text(encoding="utf-8", errors="replace")
                result = (html_to_text(raw) if path.suffix.lower() in {".html", ".htm"} else raw, "read from file")
            except OSError as exc:
                result = (None, f"read failed: {exc}")
    if result[0] is not None and "\x00" in result[0][:1024]:
        result = (None, "binary content not text-checkable")
    cache[locator] = result
    return result


def verify_excerpts(
    excerpts: list[dict[str, str]],
    registry: dict[str, object],
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    content_fetcher: Callable[[str, float], tuple[str | None, str]] = default_content_fetcher,
    base_dir: Path | None = None,
) -> dict[str, object]:
    source_index = {
        str(source.get("id")): source
        for source in registry.get("sources", [])
        if isinstance(source, dict) and str(source.get("id") or "").strip()
    }
    cache: dict[str, tuple[str | None, str]] = {}
    results: list[dict[str, object]] = []
    for entry in excerpts:
        source = source_index.get(entry["source_id"])
        record: dict[str, object] = dict(entry)
        if source is None:
            record.update(status="unresolved_source", detail="source id not in registry")
        elif str(source.get("source_class") or "external_evidence") != "external_evidence":
            record.update(status="skipped", detail=f"source_class {source.get('source_class')}")
        else:
            document, detail = _load_document_for_source(
                source,
                timeout=timeout,
                content_fetcher=content_fetcher,
                base_dir=base_dir or Path.cwd(),
                cache=cache,
            )
            if document is None:
                record.update(status="unfetchable", detail=detail)
            else:
                status, score = match_excerpt(document, entry["excerpt"])
                record.update(status=status, score=score, detail=detail)
        results.append(record)
    counts: dict[str, int] = {}
    for record in results:
        counts[str(record["status"])] = counts.get(str(record["status"]), 0) + 1
    return {
        "results": results,
        "summary": {
            "checked": len(results),
            **counts,
            "not_found_claims": [
                f"{record['stage']}:{record['claim_id']}" for record in results if record["status"] == "not_found"
            ],
        },
    }


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
    parser.add_argument(
        "--verify-excerpts",
        action="store_true",
        help="Fetch cited documents and verify that quoted evidence excerpts from the run's research stages appear in them.",
    )
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

    excerpt_report: dict[str, object] | None = None
    if args.verify_excerpts:
        run_dir = sources_path.parent
        excerpts = collect_evidence_excerpts(run_dir)
        excerpt_report = verify_excerpts(excerpts, registry, timeout=args.timeout, base_dir=run_dir)
        report["excerpts"] = excerpt_report

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

    excerpts_failed = False
    if excerpt_report is not None:
        excerpt_summary = excerpt_report["summary"]
        print(
            f"Checked {excerpt_summary['checked']} excerpts: "
            f"{excerpt_summary.get('verified', 0)} verified, {excerpt_summary.get('partial', 0)} partial, "
            f"{excerpt_summary.get('not_found', 0)} not found, {excerpt_summary.get('unfetchable', 0)} unfetchable."
        )
        for result in excerpt_report["results"]:
            if result["status"] in {"not_found", "unresolved_source"}:
                excerpts_failed = True
                print(
                    f"- EXCERPT {result['status'].upper()} {result['stage']}:{result['claim_id']} "
                    f"[{result['source_id']}]: {str(result['excerpt'])[:80]!r}"
                )
    return 1 if summary.get("broken") or excerpts_failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

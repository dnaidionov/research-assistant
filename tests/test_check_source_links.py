import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from check_source_links import (  # noqa: E402
    check_registry,
    collect_evidence_excerpts,
    match_excerpt,
    verify_excerpts,
)


def fake_fetcher(reachable_urls: set[str]):
    def fetch(url: str, timeout: float) -> tuple[bool, str]:
        if url in reachable_urls:
            return True, "HEAD 200"
        return False, "GET HTTP 404"

    return fetch


class CheckSourceLinksTests(unittest.TestCase):
    def test_reachable_url_is_ok_and_fabricated_url_is_broken(self) -> None:
        registry = {
            "sources": [
                {"id": "SRC-001", "source_class": "external_evidence", "locator": "https://example.com/real"},
                {"id": "SRC-002", "source_class": "external_evidence", "locator": "https://example.com/hallucinated"},
            ]
        }
        report = check_registry(registry, url_fetcher=fake_fetcher({"https://example.com/real"}))
        statuses = {result["id"]: result["status"] for result in report["results"]}
        self.assertEqual(statuses["SRC-001"], "ok")
        self.assertEqual(statuses["SRC-002"], "broken")
        self.assertEqual(report["summary"]["broken_ids"], ["SRC-002"])

    def test_non_external_sources_are_skipped(self) -> None:
        registry = {
            "sources": [
                {"id": "DOC-BRIEF", "source_class": "job_input", "locator": "brief.md"},
                {"id": "DOC-INTAKE", "source_class": "workflow_provenance", "locator": "runs/run-001/x.json"},
            ]
        }
        report = check_registry(registry, url_fetcher=fake_fetcher(set()))
        self.assertEqual({result["status"] for result in report["results"]}, {"skipped"})

    def test_existing_file_locator_is_ok_and_missing_path_is_broken(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            real_file = base / "attachment.pdf"
            real_file.write_text("content", encoding="utf-8")
            registry = {
                "sources": [
                    {"id": "SRC-FILE", "source_class": "external_evidence", "locator": str(real_file)},
                    {"id": "SRC-GONE", "source_class": "external_evidence", "locator": "attachments/missing.pdf"},
                    {"id": "SRC-ABS-GONE", "source_class": "external_evidence", "locator": str(base / "fabricated" / "spec.pdf")},
                    {"id": "SRC-BARE-GONE", "source_class": "external_evidence", "locator": "spec.pdf"},
                ]
            }
            report = check_registry(registry, url_fetcher=fake_fetcher(set()), base_dir=base)
            statuses = {result["id"]: result["status"] for result in report["results"]}
            self.assertEqual(statuses["SRC-FILE"], "ok")
            self.assertEqual(statuses["SRC-GONE"], "broken")
            self.assertEqual(statuses["SRC-ABS-GONE"], "broken")
            self.assertEqual(statuses["SRC-BARE-GONE"], "broken")
            self.assertIn("SRC-GONE", report["summary"]["broken_ids"])

    def test_uncheckable_locator_forms_stay_unverifiable(self) -> None:
        registry = {
            "sources": [
                {"id": "SRC-DOMAIN", "source_class": "external_evidence", "locator": "example.com/page"},
                {"id": "SRC-BARE-DOMAIN", "source_class": "external_evidence", "locator": "example.com"},
                {"id": "SRC-VAGUE", "source_class": "external_evidence", "locator": "Various industry benchmarks"},
            ]
        }
        report = check_registry(registry, url_fetcher=fake_fetcher(set()))
        statuses = {result["id"]: result["status"] for result in report["results"]}
        self.assertEqual(statuses["SRC-DOMAIN"], "unverifiable")
        self.assertEqual(statuses["SRC-BARE-DOMAIN"], "unverifiable")
        self.assertEqual(statuses["SRC-VAGUE"], "unverifiable")
        self.assertEqual(report["summary"].get("broken", 0), 0)

    def test_file_uri_locator_checks_existence(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            real_file = Path(tmpdir) / "doc.txt"
            real_file.write_text("x", encoding="utf-8")
            registry = {
                "sources": [
                    {"id": "SRC-URI", "source_class": "external_evidence", "locator": f"file://{real_file}"},
                    {"id": "SRC-URI-GONE", "source_class": "external_evidence", "locator": f"file://{real_file}.missing"},
                ]
            }
            report = check_registry(registry, url_fetcher=fake_fetcher(set()))
            statuses = {result["id"]: result["status"] for result in report["results"]}
            self.assertEqual(statuses["SRC-URI"], "ok")
            self.assertEqual(statuses["SRC-URI-GONE"], "broken")


DOCUMENT = """<html><head><style>body { color: red; }</style></head>
<body><h1>Product Spec</h1>
<p>The X100 module draws 2.5 watts under sustained load and supports
PCIe Gen4 with a maximum throughput of 8 GB/s in both directions.</p>
</body></html>"""


def fake_content_fetcher(documents: dict[str, str]):
    def fetch(url: str, timeout: float) -> tuple[str | None, str]:
        if url in documents:
            return documents[url], "fetched"
        return None, "fetch failed: 404"

    return fetch


class ExcerptVerificationTests(unittest.TestCase):
    def registry(self) -> dict[str, object]:
        return {
            "sources": [
                {
                    "id": "SRC-001",
                    "source_class": "external_evidence",
                    "locator": "https://example.com/spec",
                }
            ]
        }

    def excerpt_entry(self, excerpt: str) -> dict[str, str]:
        return {"stage": "research-a", "claim_id": "F-001", "source_id": "SRC-001", "excerpt": excerpt}

    def test_quoted_excerpt_is_verified_through_html(self) -> None:
        report = verify_excerpts(
            [self.excerpt_entry("The X100 module draws 2.5 watts under sustained load")],
            self.registry(),
            content_fetcher=fake_content_fetcher({"https://example.com/spec": DOCUMENT}),
        )
        self.assertEqual(report["results"][0]["status"], "verified")

    def test_trimmed_excerpt_scores_partial(self) -> None:
        report = verify_excerpts(
            [
                self.excerpt_entry(
                    "the X100 module draws 2.5 watts under sustained load and supports PCIe Gen5 rails"
                )
            ],
            self.registry(),
            content_fetcher=fake_content_fetcher({"https://example.com/spec": DOCUMENT}),
        )
        self.assertEqual(report["results"][0]["status"], "partial")

    def test_invented_excerpt_is_not_found(self) -> None:
        report = verify_excerpts(
            [self.excerpt_entry("The X100 module includes a dedicated neural accelerator rated at 40 TOPS")],
            self.registry(),
            content_fetcher=fake_content_fetcher({"https://example.com/spec": DOCUMENT}),
        )
        self.assertEqual(report["results"][0]["status"], "not_found")
        self.assertIn("research-a:F-001", report["summary"]["not_found_claims"])

    def test_unfetchable_and_unresolved_sources_are_reported(self) -> None:
        report = verify_excerpts(
            [
                self.excerpt_entry("Any excerpt text at all for this claim body"),
                {"stage": "research-b", "claim_id": "F-002", "source_id": "SRC-GHOST", "excerpt": "Quoted."},
            ],
            self.registry(),
            content_fetcher=fake_content_fetcher({}),
        )
        statuses = [result["status"] for result in report["results"]]
        self.assertEqual(statuses, ["unfetchable", "unresolved_source"])

    def test_collect_evidence_excerpts_reads_research_stage_links(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir)
            stage_dir = run_dir / "stage-outputs"
            stage_dir.mkdir()
            (stage_dir / "02-research-a.json").write_text(
                json.dumps(
                    {
                        "stage": "research-a",
                        "facts": [
                            {
                                "id": "F-001",
                                "text": "Fact.",
                                "evidence_sources": ["SRC-001"],
                                "support_links": [
                                    {"source_id": "SRC-001", "role": "evidence", "excerpt": "Quoted line."},
                                    {"source_id": "SRC-002", "role": "context", "excerpt": "Context, ignored."},
                                ],
                            }
                        ],
                        "inferences": [],
                    }
                ),
                encoding="utf-8",
            )
            (stage_dir / "06-judge.json").write_text(json.dumps({"stage": "judge"}), encoding="utf-8")

            excerpts = collect_evidence_excerpts(run_dir)

        self.assertEqual(len(excerpts), 1)
        self.assertEqual(excerpts[0]["source_id"], "SRC-001")
        self.assertEqual(excerpts[0]["excerpt"], "Quoted line.")

    def test_match_excerpt_normalizes_curly_quotes_and_whitespace(self) -> None:
        status, score = match_excerpt(
            "It supports “sustained load” operation.",
            'it supports "sustained   load" operation.',
        )
        self.assertEqual(status, "verified")
        self.assertEqual(score, 1.0)


if __name__ == "__main__":
    unittest.main()

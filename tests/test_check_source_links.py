import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from check_source_links import check_registry  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()

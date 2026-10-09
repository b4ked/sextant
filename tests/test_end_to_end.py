"""Index real files with the real CPU models, then search them. Skipped without models."""

from __future__ import annotations

import os
import shutil

import pytest
from fastapi.testclient import TestClient

from sextant.embed import Embedder
from sextant.indexer import Indexer
from sextant.search import Searcher
from sextant.server import create_app
from sextant.store import Store


@pytest.fixture(scope="module")
def engine(real_settings, corpus, tmp_path_factory):
    work = tmp_path_factory.mktemp("docs")
    shutil.copytree(corpus, work, dirs_exist_ok=True)
    store = Store(real_settings)
    embedder = Embedder(real_settings)
    indexer = Indexer(real_settings, store, embedder)
    report = indexer.index(work)
    return real_settings, store, indexer, Searcher(real_settings, store, embedder), work, report


def test_index_report(engine):
    _, store, _, _, _, report = engine
    assert (report.total, report.indexed, report.failed) == (3, 3, 0)
    assert store.stats()["pages"] == 4  # two 2-page PDFs; markdown has no pages
    assert store.chunk_count() == report.chunks > 0


@pytest.mark.parametrize("mode", ["hybrid", "semantic", "keyword"])
def test_finds_the_right_page(engine, mode):
    searcher = engine[3]
    hit = searcher.search("how many unused days can be carried forward", k=3, mode=mode).hits[0]
    assert hit.rel_path == "leave-policy.pdf" and hit.page_start == 2
    assert "five unused days" in hit.text


def test_semantic_match_without_shared_keywords(engine):
    # "holiday allowance" never appears in the corpus; "annual leave" does.
    hit = engine[3].search("holiday allowance for staff", k=3, mode="semantic").hits[0]
    assert hit.rel_path == "leave-policy.pdf" and hit.page_start == 1


def test_exact_identifier_lookup(engine):
    hit = engine[3].search("QX-7731-B", k=3, mode="hybrid").hits[0]
    assert hit.rel_path == "pump-maintenance.pdf" and hit.page_start == 2
    assert hit.keyword_rank == 1


def test_markdown_and_heading_context(engine):
    hit = engine[3].search("overnight meal allowance", k=3).hits[0]
    assert hit.rel_path == os.path.join("notes", "expenses.md")
    assert hit.page_start == 0 and "Meals" in hit.headings


def test_incremental_update_and_removal(engine):
    _, store, indexer, searcher, work, _ = engine
    again = indexer.index(work)
    assert (again.indexed, again.unchanged) == (0, 3)

    target = work / "notes" / "expenses.md"
    target.write_text(target.read_text() + "\n## Mileage\n\nPrivate car mileage is paid at 45 "
                      "pence per mile.\n")
    (work / "pump-maintenance.pdf").unlink()
    changed = indexer.index(work)
    assert (changed.indexed, changed.unchanged, changed.removed) == (1, 1, 1)
    assert searcher.search("mileage rate per mile", k=1).hits[0].rel_path.endswith("expenses.md")
    assert all(h.rel_path != "pump-maintenance.pdf"
               for h in searcher.search("QX-7731-B", k=5).hits)
    assert store.chunk_count() == store.stats()["chunks"]


def test_http_api(engine):
    settings = engine[0]
    client = TestClient(create_app(settings))
    status = client.get("/api/status").json()
    assert status["offline"] is True and status["llm"]["egress"] == "none"
    assert status["models"]["device"] == "cpu"

    page = client.get("/")
    assert page.status_code == 200 and "Sextant" in page.text
    assert "default-src 'self'" in page.headers["content-security-policy"]
    assert "http://" not in page.text.replace("https://parrytech.co", "")

    body = client.get("/api/search", params={"q": "carry forward unused days", "k": 2}).json()
    top = body["hits"][0]
    assert top["rel_path"] == "leave-policy.pdf" and body["reranked"] is True
    file = client.get(f"/api/documents/{top['doc_id']}/file")
    assert file.status_code == 200 and file.content.startswith(b"%PDF")
    assert client.get("/api/documents/..%2F..%2Fetc%2Fpasswd/file").status_code == 404
    assert client.get("/api/search", params={"q": "x", "mode": "nope"}).status_code == 400
    assert client.post("/api/ask", json={"question": "anything"}).status_code == 409

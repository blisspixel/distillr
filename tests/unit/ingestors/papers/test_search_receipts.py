from __future__ import annotations

import pytest

from distill.ingestors.papers import arxiv
from distill.ingestors.papers.search_receipts import SearchReceipt
from distill.library.paper_revisions import classify_paper_revision, parse_revision_status


def test_error_feed_is_a_failure_instead_of_a_ghost_paper(monkeypatch):
    feed = """<feed xmlns="http://www.w3.org/2005/Atom"><entry>
    <id>http://arxiv.org/api/errors#incorrect_id_format_for_1234.12345</id>
    <title>Error</title><summary>incorrect id format</summary></entry></feed>"""
    monkeypatch.setattr(arxiv, "_fetch_text", lambda _: feed)
    with pytest.raises(arxiv.NetworkError, match="API error"):
        arxiv.search_arxiv_papers("test")
    result = arxiv.search_arxiv_multi(["test"])
    assert result == []
    assert isinstance(result, arxiv.PaperSearchResults)
    assert result.receipts[0].status == "failed"


def test_valid_empty_feed_has_successful_empty_receipt(monkeypatch):
    monkeypatch.setattr(
        arxiv, "_fetch_text", lambda _: '<feed xmlns="http://www.w3.org/2005/Atom"/>'
    )
    result = arxiv.search_arxiv_papers("no matches")
    assert isinstance(result, arxiv.PaperSearchResults)
    assert result.receipts[0].status == "successful-empty"
    assert SearchReceipt.from_row(result.receipts[0].to_row()) == result.receipts[0]


def test_partial_search_keeps_papers_and_query_identity(monkeypatch):
    def search(query, **kwargs):
        if query == "unavailable":
            raise arxiv.NetworkError("DNS refused", url="https://export.arxiv.org")
        return [arxiv.PaperRecord(paper_id="2601.00001v1", title="Kept", abstract="")]

    monkeypatch.setattr(arxiv, "search_arxiv_papers", search)
    result = arxiv.search_arxiv_multi(["unavailable", "useful"])
    assert isinstance(result, arxiv.PaperSearchResults)
    assert len(result) == 1
    assert [(r.query, r.status, r.result_count) for r in result.receipts] == [
        ("unavailable", "failed", 0),
        ("useful", "successful", 1),
    ]


@pytest.mark.parametrize(
    "payload",
    [
        '<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>fake</id><title>x</title></entry></feed>',
        "<html/>",
        "broken XML",
    ],
)
def test_untrusted_feed_failure_differs_from_empty(payload):
    with pytest.raises(arxiv.NetworkError):
        arxiv._parse_arxiv_feed(payload)


@pytest.mark.parametrize(
    ("captured", "candidate", "status"),
    [
        ([], "2601.00001v1", "new"),
        (["2601.00001v1"], "2601.00001v1", "captured"),
        (["2601.00001v1", "2601.00001"], "2601.00001v2", "update"),
        (["2601.00001v2"], "2601.00001v1", "older"),
        (["2601.00001"], "2601.00001v2", "unknown"),
        (["2601.00001v2"], "2601.00001", "unknown"),
    ],
)
def test_revision_identity_is_distinct_from_work(captured, candidate, status):
    result = classify_paper_revision(candidate, frozenset(captured))
    assert result.status == status
    assert result.work_id == "2601.00001"
    assert parse_revision_status(status) == status


def test_invalid_revision_status_rejected():
    with pytest.raises(ValueError):
        parse_revision_status("current-ish")


@pytest.mark.parametrize(
    "value",
    [
        None,
        [],
        {"query": 1},
        {
            "query": "q",
            "captured_at": "2026-01-01T00:00:00Z",
            "status": "maybe",
            "result_count": 0,
        },
    ],
)
def test_bad_search_receipt_rejected(value):
    with pytest.raises(ValueError):
        SearchReceipt.from_row(value)

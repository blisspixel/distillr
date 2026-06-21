import importlib
from types import SimpleNamespace

SAMPLE_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2602.12670v1</id>
    <updated>2026-02-18T00:00:00Z</updated>
    <published>2026-02-17T00:00:00Z</published>
    <title> Agent Memory Systems </title>
    <summary> A paper about memory systems. </summary>
    <arxiv:doi>10.5555/agent-memory</arxiv:doi>
    <author><name>Alice</name></author>
    <author><name>Bob</name></author>
    <link rel="alternate" href="https://arxiv.org/abs/2602.12670v1" />
    <link title="pdf" href="https://arxiv.org/pdf/2602.12670v1.pdf" />
    <category term="cs.AI" />
  </entry>
</feed>"""


class FakePdfResponse:
    def __init__(self, *, status_code=200, headers=None, chunks=None):
        self.status_code = status_code
        self.headers = headers or {}
        self._chunks = chunks or [b"%PDF"]

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def raise_for_status(self):
        return None

    def iter_content(self, chunk_size=65536):
        yield from self._chunks


def test_is_arxiv_pdf_url_accepts_http_and_https():
    arxiv = importlib.import_module("distill.ingestors.papers.arxiv")
    # arXiv's Atom feed serves pdf links as http://; both schemes must pass.
    assert arxiv._is_arxiv_pdf_url("http://arxiv.org/pdf/2602.12670v1") is True
    assert arxiv._is_arxiv_pdf_url("https://arxiv.org/pdf/2602.12670v1.pdf") is True
    # Host allow-list still bounds it; non-arxiv hosts and non-pdf paths fail.
    assert arxiv._is_arxiv_pdf_url("https://evil.example.com/pdf/x") is False
    assert arxiv._is_arxiv_pdf_url("https://arxiv.org/abs/2602.12670v1") is False


def test_parse_arxiv_id_supports_abs_and_pdf():
    paper_ingest = importlib.import_module("distill.ingestors.papers.arxiv")
    assert paper_ingest.parse_arxiv_id("https://arxiv.org/abs/2602.12670") == "2602.12670"
    assert paper_ingest.parse_arxiv_id("https://arxiv.org/pdf/2602.12670.pdf") == "2602.12670"
    assert paper_ingest.parse_arxiv_id("2602.12670v1") == "2602.12670v1"


def test_search_arxiv_papers_parses_feed(monkeypatch):
    paper_ingest = importlib.import_module("distill.ingestors.papers.arxiv")
    monkeypatch.setattr("distill.ingestors.papers.arxiv._fetch_text", lambda url: SAMPLE_FEED)

    papers = paper_ingest.search_arxiv_papers("agent memory", limit=1)

    assert len(papers) == 1
    assert papers[0].paper_id == "2602.12670v1"
    assert papers[0].title == "Agent Memory Systems"
    assert papers[0].authors == ["Alice", "Bob"]
    assert papers[0].doi == "10.5555/agent-memory"


def test_parse_feed_skips_entries_without_id_or_title(monkeypatch):
    # arXiv error/partial feeds can carry entries with no real id or title; those
    # must not become ghost PaperRecords with an empty paper_id.
    paper_ingest = importlib.import_module("distill.ingestors.papers.arxiv")
    feed = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2602.12670v1</id>
    <title> Good Paper </title>
    <summary> ok </summary>
  </entry>
  <entry>
    <title> Missing Id </title>
    <summary> no id element </summary>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2602.99999v1</id>
    <summary> no title element </summary>
  </entry>
</feed>"""
    monkeypatch.setattr("distill.ingestors.papers.arxiv._fetch_text", lambda url: feed)

    papers = paper_ingest.search_arxiv_papers("anything", limit=10)

    assert len(papers) == 1
    assert papers[0].paper_id == "2602.12670v1"
    assert papers[0].title == "Good Paper"


def test_search_arxiv_alias_uses_max_results(monkeypatch):
    paper_ingest = importlib.import_module("distill.ingestors.papers.arxiv")
    calls = []

    def fake_search(query, limit=10, sort="date"):
        calls.append((query, limit, sort))
        return []

    monkeypatch.setattr(paper_ingest, "search_arxiv_papers", fake_search)

    assert paper_ingest.search_arxiv("agent memory", max_results=7) == []
    assert calls == [("agent memory", 7, "date")]


def test_search_arxiv_is_exported_from_package():
    paper_ingest = importlib.import_module("distill.ingestors.papers.arxiv")
    paper_package = importlib.import_module("distill.ingestors.papers")

    assert paper_package.search_arxiv is paper_ingest.search_arxiv


def test_fetch_arxiv_paper_returns_single_record(monkeypatch):
    paper_ingest = importlib.import_module("distill.ingestors.papers.arxiv")
    monkeypatch.setattr("distill.ingestors.papers.arxiv._fetch_text", lambda url: SAMPLE_FEED)

    paper = paper_ingest.fetch_arxiv_paper("https://arxiv.org/abs/2602.12670")

    assert paper is not None
    assert paper.paper_id == "2602.12670v1"


def test_build_search_query_policy():
    """The arXiv query-building policy: phrase-match short queries, AND-join long ones."""
    paper_ingest = importlib.import_module("distill.ingestors.papers.arxiv")

    # Empty and single-word
    assert paper_ingest._build_search_query("") == "all:"
    assert paper_ingest._build_search_query("  ") == "all:"
    assert paper_ingest._build_search_query("transformer") == "all:transformer"

    # 2-word queries: phrase match (naturally phrasal)
    assert paper_ingest._build_search_query("music transformer") == 'all:"music transformer"'
    assert paper_ingest._build_search_query("agent memory") == 'all:"agent memory"'

    # 3+ word queries: AND-joined to avoid phrase-match brittleness
    assert (
        paper_ingest._build_search_query("temporal knowledge graph")
        == "all:temporal AND all:knowledge AND all:graph"
    )
    assert (
        paper_ingest._build_search_query("symbolic music transformer composition")
        == "all:symbolic AND all:music AND all:transformer AND all:composition"
    )

    # Pre-operator input passes through
    assert (
        paper_ingest._build_search_query('"exact phrase" AND cs.LG')
        == 'all:"exact phrase" AND cs.LG'
    )
    assert paper_ingest._build_search_query("term1 OR term2") == "all:term1 OR term2"


def test_build_paper_document_contains_key_sections():
    paper_ingest = importlib.import_module("distill.ingestors.papers.arxiv")
    doc = paper_ingest.build_paper_document(
        paper_ingest.PaperRecord(
            paper_id="2602.12670v1",
            title="Agent Memory Systems",
            abstract="A paper about memory systems.",
            authors=["Alice", "Bob"],
            published_at="2026-02-17",
            updated_at="2026-02-18",
            categories=["cs.AI"],
            doi="10.5555/agent-memory",
            abs_url="https://arxiv.org/abs/2602.12670v1",
            pdf_url="https://arxiv.org/pdf/2602.12670v1.pdf",
        )
    )

    assert "# Agent Memory Systems" in doc
    assert "## Abstract" in doc
    assert "Alice, Bob" in doc
    assert "10.5555/agent-memory" in doc


def test_search_arxiv_multi_dedupes_and_continues_on_failures(monkeypatch):
    paper_ingest = importlib.import_module("distill.ingestors.papers.arxiv")
    calls = []

    def fake_search(query, **kwargs):
        calls.append(query)
        if query == "bad":
            raise RuntimeError("network")
        record = paper_ingest.PaperRecord(
            paper_id="2602.12670v1" if query != "extra" else "2603.00001",
            title=f"Paper {query}",
            abstract="Summary",
        )
        return [record]

    monkeypatch.setattr("distill.ingestors.papers.arxiv.search_arxiv_papers", fake_search)
    sleeps = []
    monkeypatch.setattr(
        "distill.ingestors.papers.arxiv.time.sleep", lambda seconds: sleeps.append(seconds)
    )

    records = paper_ingest.search_arxiv_multi(["first", "bad", "extra"])

    assert [record.paper_id for record in records] == ["2602.12670v1", "2603.00001"]
    assert calls == ["first", "bad", "extra"]
    assert sleeps == [3.5, 3.5]


def test_fetch_paper_pdf_text_reads_full_text_within_page_limit(monkeypatch):
    paper_ingest = importlib.import_module("distill.ingestors.papers.arxiv")

    class FakePage:
        def extract_text(self):
            return "A" * 50000

    monkeypatch.setattr(
        "distill.ingestors.papers.arxiv.requests.get",
        lambda *args, **kwargs: FakePdfResponse(),
    )
    monkeypatch.setattr(
        "distill.ingestors.papers.arxiv.PdfReader",
        lambda stream: SimpleNamespace(pages=[FakePage(), FakePage(), FakePage()]),
    )

    text = paper_ingest.fetch_paper_pdf_text("https://arxiv.org/pdf/2602.12670.pdf")

    assert len(text) == 150004  # 3 x 50k pages joined with \n\n


def test_fetch_paper_pdf_text_rejects_non_arxiv_url(monkeypatch):
    paper_ingest = importlib.import_module("distill.ingestors.papers.arxiv")
    calls = []
    monkeypatch.setattr(
        "distill.ingestors.papers.arxiv.requests.get",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    assert paper_ingest.fetch_paper_pdf_text("https://example.com/pdf/2602.12670.pdf") == ""
    assert calls == []


def test_fetch_paper_pdf_text_rejects_oversized_pdf(monkeypatch):
    paper_ingest = importlib.import_module("distill.ingestors.papers.arxiv")

    monkeypatch.setattr(
        "distill.ingestors.papers.arxiv.requests.get",
        lambda *args, **kwargs: FakePdfResponse(headers={"Content-Length": str(51 * 1024 * 1024)}),
    )

    assert paper_ingest.fetch_paper_pdf_text("https://arxiv.org/pdf/2602.12670.pdf") == ""


def test_fetch_paper_pdf_text_revalidates_redirect(monkeypatch):
    paper_ingest = importlib.import_module("distill.ingestors.papers.arxiv")
    calls = []

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        return FakePdfResponse(status_code=302, headers={"Location": "https://example.com/x.pdf"})

    monkeypatch.setattr("distill.ingestors.papers.arxiv.requests.get", fake_get)

    assert paper_ingest.fetch_paper_pdf_text("https://arxiv.org/pdf/2602.12670.pdf") == ""
    assert calls == [
        (
            "https://arxiv.org/pdf/2602.12670.pdf",
            {"timeout": 60, "stream": True, "allow_redirects": False},
        )
    ]


def test_fetch_paper_pdf_text_upgrades_http_to_https(monkeypatch):
    # An http:// arXiv PDF link (arXiv's Atom feed serves some as http) must be
    # fetched over TLS, never cleartext: the wire URL passed to requests.get is
    # forced to https before the first hop so an on-path attacker cannot inject
    # PDF bytes. The host allow-list still bounds SSRF.
    paper_ingest = importlib.import_module("distill.ingestors.papers.arxiv")
    calls = []

    def fake_get(url, **kwargs):
        calls.append(url)
        return FakePdfResponse()

    monkeypatch.setattr("distill.ingestors.papers.arxiv.requests.get", fake_get)
    monkeypatch.setattr(
        "distill.ingestors.papers.arxiv.PdfReader",
        lambda stream: SimpleNamespace(pages=[]),
    )

    paper_ingest.fetch_paper_pdf_text("http://arxiv.org/pdf/2602.12670v1")

    assert calls == ["https://arxiv.org/pdf/2602.12670v1"]


def test_fetch_paper_pdf_text_returns_empty_on_errors(monkeypatch):
    paper_ingest = importlib.import_module("distill.ingestors.papers.arxiv")
    monkeypatch.setattr(
        "distill.ingestors.papers.arxiv.requests.get",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    assert paper_ingest.fetch_paper_pdf_text("https://arxiv.org/pdf/2602.12670.pdf") == ""


def test_paper_record_metadata_round_trips():
    paper_ingest = importlib.import_module("distill.ingestors.papers.arxiv")
    record = paper_ingest.PaperRecord(
        paper_id="2602.12670v1",
        title="Agent Memory Systems",
        abstract="A paper about memory systems.",
        authors=["Alice", "Bob"],
        categories=["cs.AI"],
        doi="10.5555/agent-memory",
    )

    metadata = record.metadata()

    assert metadata["paper_id"] == "2602.12670v1"
    assert metadata["authors"] == ["Alice", "Bob"]
    assert metadata["doi"] == "10.5555/agent-memory"

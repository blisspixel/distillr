import importlib
import io
import threading
import urllib.error
from concurrent.futures import ThreadPoolExecutor

import pytest

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


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


@pytest.fixture
def arxiv_clock(monkeypatch):
    arxiv = importlib.import_module("distill.ingestors.papers.arxiv")
    net = importlib.import_module("distill.ingestors.net")
    clock = FakeClock()
    monkeypatch.setattr(arxiv, "time", clock)
    monkeypatch.setattr(net, "time", clock)
    monkeypatch.setattr(arxiv, "_ARXIV_REQUEST_PACER", arxiv._ArxivRequestPacer())
    return clock


def test_query_entry_points_share_pacing_through_response_close(monkeypatch, arxiv_clock):
    arxiv = importlib.import_module("distill.ingestors.papers.arxiv")
    starts = []

    class Response(io.BytesIO):
        def read(self, size=-1):
            arxiv_clock.now += 2.0
            return super().read(size)

        def close(self):
            arxiv_clock.now += 1.0
            super().close()

    def open_feed(url, *, request_interval_seconds, deadline):
        assert request_interval_seconds >= 3.0
        assert deadline.remaining() > 0
        starts.append(arxiv_clock.now)
        return Response(SAMPLE_FEED.encode())

    monkeypatch.setattr(arxiv, "safe_urlopen", open_feed)
    assert len(arxiv.search_arxiv_papers("direct")) == 1
    assert arxiv.fetch_arxiv_paper("2602.12670v1") is not None
    assert len(arxiv.search_arxiv("alias")) == 1
    assert len(arxiv.search_arxiv_multi(["batch-one", "batch-two"])) == 1
    assert starts == [0.0, 6.5, 13.0, 19.5, 26.0]
    assert arxiv_clock.sleeps == [3.5] * 4

    arxiv_clock.now += 10
    arxiv.fetch_arxiv_paper("2602.12670v1")
    assert starts[-1] == 39.0
    assert arxiv_clock.sleeps == [3.5] * 4


@pytest.mark.parametrize("failure", ["open", "read", "oversized"])
def test_failed_query_still_paces_next_request(monkeypatch, arxiv_clock, failure):
    arxiv = importlib.import_module("distill.ingestors.papers.arxiv")
    starts = []
    deadlines = []

    class Response(io.BytesIO):
        def read(self, size=-1):
            if failure == "read" and len(starts) == 1:
                raise arxiv.NetworkError("body interrupted", url=arxiv.ARXIV_API)
            return super().read(size)

    def open_feed(url, **kwargs):
        starts.append(arxiv_clock.now)
        deadlines.append(kwargs["deadline"])
        if len(starts) == 1 and failure == "open":
            raise arxiv.NetworkError("HTTP 404", url=url, status_code=404)
        body = b"x" * 17 if len(starts) == 1 else b"<feed />"
        return Response(body)

    monkeypatch.setattr(arxiv, "safe_urlopen", open_feed)
    monkeypatch.setattr(arxiv, "_FEED_CAP_BYTES", 16)
    with pytest.raises(arxiv.NetworkError) as error:
        arxiv._fetch_text(arxiv.ARXIV_API)
    assert error.value.url == arxiv.ARXIV_API
    with pytest.raises(arxiv.NetworkError, match="deadline"):
        deadlines[0].remaining()
    if failure == "open":
        assert error.value.status_code == 404
        assert isinstance(error.value.__cause__, arxiv.NetworkError)
    assert arxiv._fetch_text(arxiv.ARXIV_API) == "<feed />"
    assert starts == [0.0, 3.5]


@pytest.mark.parametrize("failure", [503, 429, "timeout", "url", "os"])
def test_generic_retries_preserve_arxiv_request_interval(monkeypatch, arxiv_clock, failure):
    arxiv = importlib.import_module("distill.ingestors.papers.arxiv")
    net = importlib.import_module("distill.ingestors.net")
    starts = []

    def open_feed(*args, **kwargs):
        starts.append(arxiv_clock.now)
        if len(starts) == 1:
            if isinstance(failure, int):
                raise urllib.error.HTTPError(arxiv.ARXIV_API, failure, "unavailable", {}, None)
            if failure == "timeout":
                raise TimeoutError("timed out")
            if failure == "url":
                raise urllib.error.URLError("unavailable")
            raise OSError("connection failed")
        return io.BytesIO(SAMPLE_FEED.encode())

    monkeypatch.setattr(net, "time", arxiv_clock)
    monkeypatch.setattr(net, "_resolve_public_ip_before_deadline", lambda *a: "8.8.8.8")
    monkeypatch.setattr(net._SSRF_SAFE_OPENER, "open", open_feed)

    assert arxiv.fetch_arxiv_paper("2602.12670v1") is not None
    expected_gap = 10.5 if failure == 429 else 3.5
    assert starts == [0.0, expected_gap]
    assert arxiv_clock.sleeps == [expected_gap]


def test_rate_limit_cooldown_then_next_direct_query_remain_paced(monkeypatch, arxiv_clock):
    arxiv = importlib.import_module("distill.ingestors.papers.arxiv")
    starts = []

    def open_feed(url, **kwargs):
        starts.append(arxiv_clock.now)
        if len(starts) == 1:
            raise arxiv.NetworkError("rate limited", url=url, status_code=429)
        return io.BytesIO(SAMPLE_FEED.encode())

    monkeypatch.setattr(arxiv, "safe_urlopen", open_feed)
    assert len(arxiv.search_arxiv_papers("retry")) == 1
    assert arxiv.fetch_arxiv_paper("2602.12670v1") is not None
    assert starts == [0.0, 30.0, 33.5]
    assert arxiv_clock.sleeps == [30, 3.5]


def test_batch_failure_cooldown_is_bounded_and_resets_after_success(
    monkeypatch, arxiv_clock, caplog
):
    arxiv = importlib.import_module("distill.ingestors.papers.arxiv")
    starts = []

    def search(query, **kwargs):
        starts.append(arxiv_clock.now)
        if query != "ok":
            raise arxiv.NetworkError("unavailable", status_code=503)
        return []

    monkeypatch.setattr(arxiv, "search_arxiv_papers", search)
    assert arxiv.search_arxiv_multi(["bad"] * 7 + ["ok", "ok"]) == []
    assert arxiv_clock.sleeps == [7.0, 14.0, 28.0, 56.0, 60.0, 60.0]
    assert starts[-1] == starts[-2]
    assert caplog.text.count("arXiv search failed (NetworkError): unavailable") == 7
    assert "rate-limited" not in caplog.text


def test_concurrent_queries_wait_until_response_closed(monkeypatch, arxiv_clock):
    arxiv = importlib.import_module("distill.ingestors.papers.arxiv")
    reading = threading.Event()
    release = threading.Event()
    second_attempted = threading.Event()
    second_opened = threading.Event()
    closed = threading.Event()
    starts = []

    class Response(io.BytesIO):
        def read(self, size=-1):
            if len(starts) == 1:
                reading.set()
                assert release.wait(timeout=5)
            return super().read(size)

        def close(self):
            super().close()
            closed.set()

    def open_feed(url, **kwargs):
        starts.append(arxiv_clock.now)
        if len(starts) == 2:
            assert closed.is_set()
            second_opened.set()
        return Response(SAMPLE_FEED.encode())

    def second_query():
        second_attempted.set()
        return arxiv.fetch_arxiv_paper("2602.12670v1")

    monkeypatch.setattr(arxiv, "safe_urlopen", open_feed)
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(arxiv.search_arxiv_papers, "first")
        try:
            assert reading.wait(timeout=5)
            second = executor.submit(second_query)
            assert second_attempted.wait(timeout=5)
            assert not second_opened.wait(timeout=0.05)
        finally:
            release.set()
        assert len(first.result(timeout=5)) == 1
        assert second.result(timeout=5) is not None
    assert starts == [0.0, 3.5]


def test_query_interval_consumes_deadline_and_releases_gate(monkeypatch, arxiv_clock):
    arxiv = importlib.import_module("distill.ingestors.papers.arxiv")
    deadlines = []
    starts = []
    original_deadline = arxiv.NetworkDeadline

    def create_deadline(*args, **kwargs):
        deadline = original_deadline(*args, **kwargs)
        deadlines.append(deadline)
        return deadline

    def open_feed(url, **kwargs):
        assert kwargs["deadline"] is deadlines[-1]
        starts.append(arxiv_clock.now)
        return io.BytesIO(SAMPLE_FEED.encode())

    monkeypatch.setattr(arxiv, "NetworkDeadline", create_deadline)
    monkeypatch.setattr(arxiv, "safe_urlopen", open_feed)
    arxiv.fetch_arxiv_paper("2602.12670v1")
    monkeypatch.setattr(arxiv, "DEFAULT_FETCH_TIMEOUT_SECONDS", 2.0)
    with pytest.raises(arxiv.NetworkError, match="deadline") as error:
        arxiv.fetch_arxiv_paper("2602.12670v1")
    assert error.value.url.startswith(arxiv.ARXIV_API)
    assert starts == [0.0]
    assert arxiv_clock.sleeps == [2.0]

    # The expired waiter must release the gate without extending its cooldown.
    arxiv.fetch_arxiv_paper("2602.12670v1")
    assert starts == [0.0, 3.5]
    assert arxiv_clock.sleeps == [2.0, 1.5]
    for deadline in deadlines:
        with pytest.raises(arxiv.NetworkError, match="deadline"):
            deadline.remaining()


def test_waiting_query_expires_while_another_response_holds_gate(monkeypatch):
    arxiv = importlib.import_module("distill.ingestors.papers.arxiv")
    monkeypatch.setattr(arxiv, "_ARXIV_REQUEST_PACER", arxiv._ArxivRequestPacer())
    reading = threading.Event()
    release = threading.Event()
    opens = []

    class Response(io.BytesIO):
        def read(self, size=-1):
            reading.set()
            assert release.wait(timeout=5)
            return super().read(size)

    def open_feed(url, **kwargs):
        opens.append(url)
        return Response(SAMPLE_FEED.encode())

    monkeypatch.setattr(arxiv, "safe_urlopen", open_feed)
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(arxiv.search_arxiv_papers, "first")
        try:
            assert reading.wait(timeout=5)
            monkeypatch.setattr(arxiv, "DEFAULT_FETCH_TIMEOUT_SECONDS", 0.05)
            second = executor.submit(arxiv.fetch_arxiv_paper, "2602.12670v1")
            with pytest.raises(arxiv.NetworkError, match="deadline") as error:
                second.result(timeout=2)
            assert error.value.url.startswith(arxiv.ARXIV_API)
            assert not first.done()
            assert len(opens) == 1
        finally:
            release.set()
        assert len(first.result(timeout=5)) == 1


def test_is_arxiv_pdf_url_accepts_http_and_https():
    arxiv = importlib.import_module("distill.ingestors.papers.arxiv")
    # arXiv's Atom feed serves pdf links as http://; both schemes must pass.
    assert arxiv._is_arxiv_pdf_url("http://arxiv.org/pdf/2602.12670v1") is True
    assert arxiv._is_arxiv_pdf_url("https://arxiv.org/pdf/2602.12670v1.pdf") is True
    # Host allow-list still bounds it; non-arxiv hosts and non-pdf paths fail.
    assert arxiv._is_arxiv_pdf_url("https://evil.example.com/pdf/x") is False
    assert arxiv._is_arxiv_pdf_url("https://arxiv.org/abs/2602.12670v1") is False
    assert arxiv._is_arxiv_pdf_url("https://user:pass@arxiv.org/pdf/2602.12670v1") is False


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


def test_parse_feed_returns_empty_on_non_xml_body():
    # arXiv returns an HTML error page on some bad/rate-limited requests; a
    # non-XML body must degrade to "no results", not raise a ParseError into the
    # discover/papers run (the other xml_fromstring sites already guard this way).
    paper_ingest = importlib.import_module("distill.ingestors.papers.arxiv")
    assert paper_ingest._parse_arxiv_feed("<html><body>503 Service Unavailable</body></html>") == []
    assert paper_ingest._parse_arxiv_feed("not xml at all {{{") == []


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


def test_search_arxiv_multi_dedupes_and_reports_failures(monkeypatch, caplog):
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
    assert sleeps == []  # The request boundary owns pacing, not this mocked search.
    assert "arXiv search failed (RuntimeError): network" in caplog.text


def test_fetch_paper_pdf_text_reads_full_text_within_page_limit(monkeypatch):
    paper_ingest = importlib.import_module("distill.ingestors.papers.arxiv")

    monkeypatch.setattr(
        "distill.ingestors.papers.arxiv.requests.get",
        lambda *args, **kwargs: FakePdfResponse(),
    )
    monkeypatch.setattr(
        "distill.ingestors.papers.arxiv.extract_pdf_text_bounded",
        lambda path, *, max_chars, max_pages: "A" * 150004,
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


@pytest.mark.parametrize("declared", ["\u00b2", "\u0661\u0662", "9" * 5000])
def test_fetch_paper_pdf_text_ignores_invalid_content_length(monkeypatch, declared):
    paper_ingest = importlib.import_module("distill.ingestors.papers.arxiv")
    monkeypatch.setattr(
        "distill.ingestors.papers.arxiv.requests.get",
        lambda *args, **kwargs: FakePdfResponse(headers={"Content-Length": declared}),
    )
    monkeypatch.setattr(
        "distill.ingestors.papers.arxiv.extract_pdf_text_bounded",
        lambda path, *, max_chars, max_pages: "parsed",
    )

    assert paper_ingest.fetch_paper_pdf_text("https://arxiv.org/pdf/2602.12670.pdf") == "parsed"


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
            {
                "timeout": 60,
                "stream": True,
                "allow_redirects": False,
                "proxies": {"http": "", "https": ""},
            },
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
        "distill.ingestors.papers.arxiv.extract_pdf_text_bounded",
        lambda path, *, max_chars, max_pages: "",
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

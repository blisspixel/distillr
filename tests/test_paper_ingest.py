import importlib

SAMPLE_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2602.12670v1</id>
    <updated>2026-02-18T00:00:00Z</updated>
    <published>2026-02-17T00:00:00Z</published>
    <title> Agent Memory Systems </title>
    <summary> A paper about memory systems. </summary>
    <author><name>Alice</name></author>
    <author><name>Bob</name></author>
    <link rel="alternate" href="https://arxiv.org/abs/2602.12670v1" />
    <link title="pdf" href="https://arxiv.org/pdf/2602.12670v1.pdf" />
    <category term="cs.AI" />
  </entry>
</feed>"""


def test_parse_arxiv_id_supports_abs_and_pdf():
    paper_ingest = importlib.import_module("distill.paper_ingest")
    assert paper_ingest.parse_arxiv_id("https://arxiv.org/abs/2602.12670") == "2602.12670"
    assert paper_ingest.parse_arxiv_id("https://arxiv.org/pdf/2602.12670.pdf") == "2602.12670"
    assert paper_ingest.parse_arxiv_id("2602.12670v1") == "2602.12670v1"


def test_search_arxiv_papers_parses_feed(monkeypatch):
    paper_ingest = importlib.import_module("distill.paper_ingest")
    monkeypatch.setattr("distill.paper_ingest._fetch_text", lambda url: SAMPLE_FEED)

    papers = paper_ingest.search_arxiv_papers("agent memory", limit=1)

    assert len(papers) == 1
    assert papers[0].paper_id == "2602.12670v1"
    assert papers[0].title == "Agent Memory Systems"
    assert papers[0].authors == ["Alice", "Bob"]


def test_fetch_arxiv_paper_returns_single_record(monkeypatch):
    paper_ingest = importlib.import_module("distill.paper_ingest")
    monkeypatch.setattr("distill.paper_ingest._fetch_text", lambda url: SAMPLE_FEED)

    paper = paper_ingest.fetch_arxiv_paper("https://arxiv.org/abs/2602.12670")

    assert paper is not None
    assert paper.paper_id == "2602.12670v1"


def test_build_search_query_policy():
    """The arXiv query-building policy: phrase-match short queries, AND-join long ones."""
    paper_ingest = importlib.import_module("distill.paper_ingest")

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
    paper_ingest = importlib.import_module("distill.paper_ingest")
    doc = paper_ingest.build_paper_document(
        paper_ingest.PaperRecord(
            paper_id="2602.12670v1",
            title="Agent Memory Systems",
            abstract="A paper about memory systems.",
            authors=["Alice", "Bob"],
            published_at="2026-02-17",
            updated_at="2026-02-18",
            categories=["cs.AI"],
            abs_url="https://arxiv.org/abs/2602.12670v1",
            pdf_url="https://arxiv.org/pdf/2602.12670v1.pdf",
        )
    )

    assert "# Agent Memory Systems" in doc
    assert "## Abstract" in doc
    assert "Alice, Bob" in doc

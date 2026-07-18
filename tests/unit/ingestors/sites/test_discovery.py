import pytest

from distill.ingestors.sites.discovery import (
    LandingParseLimit,
    _AnchorParser,
    _candidate_urls_from_landing,
    _candidate_urls_from_sitemaps,
    _dedupe_landing_candidates,
    _LandingPageCandidate,
    discover_trusted_site_seeds,
)


def test_sitemap_quota_counts_failed_fetch_attempts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "distill.ingestors.sites.discovery.is_public_web_url",
        lambda url: url.startswith("https://example.com/"),
    )
    nested = "".join(
        f"<sitemap><loc>https://example.com/child-{index}.xml</loc></sitemap>"
        for index in range(100)
    )
    sitemap_index = f"<sitemapindex>{nested}</sitemapindex>"
    calls: list[str] = []

    def fetch(url: str) -> str:
        calls.append(url)
        return sitemap_index if url.endswith("/sitemap.xml") else ""

    urls, fetched = _candidate_urls_from_sitemaps(
        "https://example.com/docs",
        fetch_text=fetch,
        max_sitemaps=4,
    )

    assert urls == []
    assert fetched == 1
    assert len(calls) == 4


def test_sitemap_parser_caps_nested_entries() -> None:
    from distill.ingestors.sites.discovery import _parse_sitemap

    nested = "".join(
        f"<sitemap><loc>https://example.com/child-{index}.xml</loc></sitemap>"
        for index in range(20)
    )

    sitemap_urls, page_urls = _parse_sitemap(
        f"<sitemapindex>{nested}</sitemapindex>",
        max_entries=3,
    )

    assert len(sitemap_urls) == 3
    assert page_urls == []


def test_discover_trusted_site_seeds_enumerates_sitemaps_and_landing_links(monkeypatch):
    monkeypatch.setattr(
        "distill.ingestors.sites.discovery.is_public_web_url",
        lambda url: url.startswith("https://learn.example.com/"),
    )

    sitemap = """
    <urlset>
      <url>
        <loc>https://learn.example.com/docs/agents/overview?utm_source=x</loc>
        <lastmod>2026-06-18T12:00:00Z</lastmod>
      </url>
      <url><loc>https://learn.example.com/docs/other/ignored</loc></url>
      <url><loc>https://learn.example.com/docs/agents/file.pdf</loc></url>
      <url><loc>https://other.example.com/docs/agents/outside</loc></url>
    </urlset>
    """
    landing = """
    <html><body>
      <a href="/docs/agents/build">Build agents</a>
      <a href="/docs/other/ignored">Other docs</a>
      <a href="/docs/agents/overview?utm_source=y">Duplicate overview</a>
    </body></html>
    """
    responses = {
        "https://learn.example.com/sitemap.xml": sitemap,
        "https://learn.example.com/sitemap_index.xml": "",
        "https://learn.example.com/docs/agents": landing,
    }

    result = discover_trusted_site_seeds(
        ["https://learn.example.com/docs/agents"],
        topic="agent365",
        max_candidates=10,
        fetch_text=lambda url: responses.get(url, ""),
    )

    assert result.source_count == 1
    assert result.fetched_sitemaps == 1
    assert result.fetched_landing_pages == 1
    assert [seed.url for seed in result.seeds] == [
        "https://learn.example.com/docs/agents/overview",
        "https://learn.example.com/docs/agents/build",
        "https://learn.example.com/docs/agents",
    ]
    assert [seed.label for seed in result.seeds] == ["overview", "Build agents", "agents"]
    assert [seed.section_label for seed in result.seeds] == [
        "docs/agents",
        "docs/agents",
        "docs/agents",
    ]
    assert [seed.source_hint for seed in result.seeds] == [
        "sitemap",
        "landing link",
        "trusted site",
    ]
    assert result.seeds[0].freshness_hint == "2026-06-18"
    assert all(seed.max_depth == 0 and seed.max_pages == 1 for seed in result.seeds)
    assert {seed.crawl_prefix for seed in result.seeds} == {"/docs/agents"}


def test_discover_trusted_site_seeds_accepts_bare_domain_and_caps(monkeypatch):
    monkeypatch.setattr(
        "distill.ingestors.sites.discovery.is_public_web_url",
        lambda url: url.startswith("https://docs.example.com/"),
    )

    result = discover_trusted_site_seeds(
        ["docs.example.com"],
        topic="docs",
        max_candidates=1,
        fetch_text=lambda _url: '<a href="/guide">Guide</a>',
    )

    assert [seed.url for seed in result.seeds] == ["https://docs.example.com/guide"]
    assert result.seeds[0].site_name == "docs.example.com"
    assert result.seeds[0].source_hint == "landing link"
    assert result.seeds[0].crawl_prefix == ""


def test_discover_trusted_site_seeds_prefers_toc_links_from_landing_page(monkeypatch):
    monkeypatch.setattr(
        "distill.ingestors.sites.discovery.is_public_web_url",
        lambda url: url.startswith("https://learn.example.com/"),
    )

    landing = """
    <html><body>
      <main>
        <a href="/docs/agents/install">Generic install link</a>
        <a href="/docs/agents/body">Body link</a>
      </main>
      <nav aria-label="Table of contents">
        <a href="/docs/agents/overview">Overview</a>
        <a href="/docs/agents/install">Install from TOC</a>
      </nav>
      <div role="navigation">
        <a href="/docs/agents/deploy">Deploy</a>
      </div>
    </body></html>
    """
    responses = {
        "https://learn.example.com/sitemap.xml": "",
        "https://learn.example.com/sitemap_index.xml": "",
        "https://learn.example.com/docs/agents": landing,
    }

    result = discover_trusted_site_seeds(
        ["https://learn.example.com/docs/agents"],
        topic="agent365",
        max_candidates=10,
        fetch_text=lambda url: responses.get(url, ""),
    )

    assert [seed.url for seed in result.seeds] == [
        "https://learn.example.com/docs/agents/overview",
        "https://learn.example.com/docs/agents/install",
        "https://learn.example.com/docs/agents/deploy",
        "https://learn.example.com/docs/agents/body",
        "https://learn.example.com/docs/agents",
    ]
    assert [seed.label for seed in result.seeds] == [
        "Overview",
        "Install from TOC",
        "Deploy",
        "Body link",
        "agents",
    ]
    assert [seed.source_hint for seed in result.seeds] == [
        "toc link",
        "toc link",
        "toc link",
        "landing link",
        "trusted site",
    ]
    assert result.fetched_landing_pages == 1


def test_anchor_parser_preserves_toc_context_without_stack_scans():
    parser = _AnchorParser()

    parser.feed(
        '<main><a href="/body">Body</a></main>'
        '<nav aria-label="Table of contents"><div><a href="/toc">TOC</a></div></nav>'
    )
    parser.close()

    assert parser.links == [("/body", "Body", False), ("/toc", "TOC", True)]


def test_anchor_parser_unmatched_end_is_constant_state_noop():
    parser = _AnchorParser()
    parser.feed("<div><section>")
    before = list(parser._element_stack)
    positions_before = {tag: list(values) for tag, values in parser._positions.items()}

    parser.feed("</span>" * 100)

    assert parser._element_stack == before
    assert parser._positions == positions_before


def test_anchor_parser_matched_end_removes_malformed_suffix():
    parser = _AnchorParser()
    parser.feed("<div><section><span>")

    parser.feed("</section>")

    assert parser._element_stack == [("div", False)]
    assert parser._positions == {"div": [0]}


def test_anchor_parser_event_budget_is_cumulative_across_feed_calls():
    parser = _AnchorParser(max_events=3)
    parser.feed("<div>")
    parser.feed("text")
    parser.feed("</div>")

    with pytest.raises(LandingParseLimit, match="event budget"):
        parser.feed("<span>")


def test_anchor_parser_depth_budget_accepts_boundary_and_rejects_next_tag():
    parser = _AnchorParser(max_depth=2)
    parser.feed("<div><section>")

    with pytest.raises(LandingParseLimit, match="nesting depth"):
        parser.feed("<span>")


def test_anchor_parser_anchor_budget_accepts_boundary_and_rejects_next_anchor():
    parser = _AnchorParser(max_anchors=2)
    parser.feed('<a href="/one">One</a><a href="/two">Two</a>')

    with pytest.raises(LandingParseLimit, match="anchor budget"):
        parser.feed('<a href="/three">Three</a>')

    assert [href for href, _text, _toc in parser.links] == ["/one", "/two"]


def test_anchor_parser_bounds_retained_anchor_text():
    parser = _AnchorParser(max_anchor_text_chars=8)

    parser.feed('<a href="/bounded">abcdefghijk</a>')

    assert parser.links == [("/bounded", "abcdefgh", False)]


def test_landing_parse_limit_discards_partial_candidates():
    result = _candidate_urls_from_landing(
        "https://example.com/docs",
        fetch_text=lambda _url: "<div>" * 513 + '<a href="/partial">Partial</a>',
    )

    assert result.urls == []
    assert result.landing_fetches == 1


def test_dedupe_promotes_reverse_toc_duplicates_in_linear_mapping_order():
    ordinary = [
        _LandingPageCandidate(f"https://example.com/{index}", f"ordinary-{index}", "landing link")
        for index in range(4)
    ]
    toc = [
        _LandingPageCandidate(f"https://example.com/{index}", f"toc-{index}", "toc link")
        for index in reversed(range(4))
    ]

    deduped = _dedupe_landing_candidates(ordinary + toc)

    assert [candidate.label for candidate in deduped] == [
        "toc-3",
        "toc-2",
        "toc-1",
        "toc-0",
    ]

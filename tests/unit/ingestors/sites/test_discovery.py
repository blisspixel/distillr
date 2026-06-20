from distill.ingestors.sites.discovery import discover_trusted_site_seeds


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

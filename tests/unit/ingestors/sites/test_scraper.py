import json
import sys
from types import SimpleNamespace

import pytest

from distill.ingestors.sites.scraper import (
    SitePage,
    SiteSeed,
    _extract_page,
    _install_public_web_route,
    _prioritize_links,
    build_page_document,
    canonicalize_url,
    classify_page_type,
    crawl_prefix_from_url,
    crawl_site,
    dedupe_urls,
    is_crawlable_url,
    is_same_section,
    load_site_batch,
    normalize_host,
    page_id_from_url,
    site_section_key,
)
from distill.library.paths import site_name_from_url


def test_site_name_from_url_strips_www():
    assert site_name_from_url("https://www.example.com/path") == "example.com"


def test_load_site_batch_from_text(tmp_path):
    path = tmp_path / "sites.txt"
    path.write_text("https://example.com\n# ignore\nhttps://vendor.example.com\n", encoding="utf-8")

    batch = load_site_batch(path, topic_override="agents")

    assert batch.topic == "agents"
    assert [seed.url for seed in batch.seeds] == [
        "https://example.com",
        "https://vendor.example.com",
    ]


def test_load_site_batch_from_json_with_collections(tmp_path):
    path = tmp_path / "sites.json"
    path.write_text(
        json.dumps(
            {
                "topic": "web-ai",
                "crawl": {
                    "max_depth": 2,
                    "max_pages_per_seed": 5,
                    "crawl_prefix": "/topic/applied-ai",
                },
                "collections": [
                    {
                        "name": "example",
                        "label": "Example Vendor",
                        "seeds": ["https://www.example.com/topic/applied-ai/overview"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    batch = load_site_batch(path)

    assert batch.topic == "web-ai"
    assert len(batch.seeds) == 1
    assert batch.seeds[0].max_depth == 2
    assert batch.seeds[0].max_pages == 5
    assert batch.seeds[0].label == "Example Vendor"
    assert batch.seeds[0].crawl_prefix == "/topic/applied-ai"


def test_load_site_batch_from_json_url_objects(tmp_path):
    path = tmp_path / "sites.json"
    path.write_text(
        json.dumps(
            {
                "topic": "web-ai",
                "urls": [
                    {
                        "url": "https://example.com",
                        "topic": "agents",
                        "max_depth": 2,
                        "max_pages": 4,
                        "crawl_prefix": "https://example.com/agents",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    batch = load_site_batch(path)

    assert batch.topic == "web-ai"
    assert batch.seeds[0].topic == "agents"
    assert batch.seeds[0].max_depth == 2
    assert batch.seeds[0].max_pages == 4
    assert batch.seeds[0].crawl_prefix == "/agents"


def test_load_site_batch_from_json_explicit_modes(tmp_path):
    path = tmp_path / "sites.json"
    path.write_text(
        json.dumps(
            {
                "topic": "web-ai",
                "crawl": {
                    "max_depth": 2,
                    "max_pages_per_seed": 6,
                    "same_section_only": True,
                },
                "collections": [
                    {
                        "name": "overview",
                        "label": "Overview",
                        "mode": "exact-page",
                        "seeds": ["https://example.com/overview"],
                    },
                    {
                        "name": "docs",
                        "label": "Docs",
                        "mode": "shallow-crawl",
                        "crawl_prefix": "/docs",
                        "seeds": ["https://example.com/docs/start"],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    batch = load_site_batch(path)

    assert [(seed.max_depth, seed.max_pages) for seed in batch.seeds] == [(0, 1), (2, 6)]
    assert [seed.same_section_only for seed in batch.seeds] == [True, True]
    assert batch.seeds[1].crawl_prefix == "/docs"


def test_load_site_batch_from_json_crawl_false_alias(tmp_path):
    path = tmp_path / "sites.json"
    path.write_text(
        json.dumps(
            {
                "topic": "web-ai",
                "crawl": {"max_depth": 2, "max_pages_per_seed": 6},
                "urls": [
                    {"url": "https://example.com/exact", "crawl": False},
                    {"url": "https://example.com/docs", "crawl": True},
                ],
            }
        ),
        encoding="utf-8",
    )

    batch = load_site_batch(path)

    assert [(seed.max_depth, seed.max_pages) for seed in batch.seeds] == [(0, 1), (2, 6)]


def test_load_site_batch_from_json_rejects_unknown_crawl_mode(tmp_path):
    path = tmp_path / "sites.json"
    path.write_text(
        json.dumps(
            {
                "topic": "web-ai",
                "urls": [
                    {
                        "url": "https://example.com/docs",
                        "mode": "wide-open",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Unsupported site crawl mode"):
        load_site_batch(path)


def test_classify_page_type_prefers_video_when_flagged():
    assert classify_page_type("https://example.com/page", "Title", "", True) == "video"
    assert classify_page_type("https://example.com/topic/ai", "Title", "", False) == "topic"
    assert classify_page_type("https://example.com/partner/tool", "Title", "", False) == "partner"


def test_build_page_document_includes_transcript_when_present():
    page = SitePage(
        url="https://example.com/video/demo",
        title="Demo",
        site_name="example.com",
        page_type="video",
        text="Main body",
        transcript="Hello transcript",
        attachment_context="### PDF Attachment: https://example.com/guide.pdf\nAttachment body",
        has_video=True,
        video_links=["https://player.example.com/embed/1"],
        pdf_links=["https://example.com/guide.pdf"],
    )

    doc = build_page_document(page)

    assert "# Demo" in doc
    assert "## Transcript" in doc
    assert "Hello transcript" in doc
    assert "## Video Links" in doc
    assert "## PDF Links" in doc
    assert "## Attachment Extracts" in doc


def test_site_page_metadata_and_page_id():
    page = SitePage(
        url="https://example.com/research/agent-memory",
        title="Agent Memory",
        site_name="example.com",
        page_type="research",
        text="Body",
        transcript="",
        source_url="https://example.com/start",
        final_url="https://example.com/research/agent-memory",
        canonical_url="https://example.com/research/agent-memory",
        depth=1,
    )

    metadata = page.metadata()

    assert page.page_id
    assert metadata["has_transcript"] is False
    assert metadata["has_attachment_context"] is False
    assert metadata["source_url"] == "https://example.com/start"
    assert metadata["depth"] == 1
    assert metadata["final_url"] == "https://example.com/research/agent-memory"


def test_url_helpers_normalize_and_filter():
    assert normalize_host("https://www.example.com/path") == "example.com"
    assert (
        canonicalize_url("https://example.com/path/?utm_source=x&b=2&a=1")
        == "https://example.com/path?a=1&b=2"
    )
    assert page_id_from_url("https://example.com/some/page")
    assert is_crawlable_url("https://example.com/page") is True
    assert is_crawlable_url("https://example.com/file.pdf") is False


def test_public_web_route_aborts_private_requests(monkeypatch):
    class FakeRoute:
        def __init__(self):
            self.action = ""

        def continue_(self):
            self.action = "continue"

        def abort(self):
            self.action = "abort"

    class FakeContext:
        def route(self, pattern, handler):
            self.pattern = pattern
            self.handler = handler

    monkeypatch.setattr(
        "distill.ingestors.net.is_public_web_url",
        lambda url: url == "https://example.com/page",
    )
    context = FakeContext()

    _install_public_web_route(context)

    allowed = FakeRoute()
    context.handler(allowed, SimpleNamespace(url="https://example.com/page"))
    blocked = FakeRoute()
    context.handler(blocked, SimpleNamespace(url="http://127.0.0.1/admin"))

    assert context.pattern == "**/*"
    assert allowed.action == "continue"
    assert blocked.action == "abort"


def test_site_section_key_uses_first_two_segments():
    assert (
        site_section_key("https://www.example.com/topic/applied-ai/overview") == "topic/applied-ai"
    )
    assert (
        site_section_key("https://www.example.com/partner/windsurf/explore") == "partner/windsurf"
    )
    assert site_section_key("https://example.com") == "root"


def test_crawl_prefix_from_url_uses_path_only():
    assert (
        crawl_prefix_from_url("https://learn.example.com/en-us/microsoft-365/agents?view=x")
        == "/en-us/microsoft-365/agents"
    )
    assert crawl_prefix_from_url("https://example.com") == ""


def test_dedupe_urls_canonicalizes_query_order():
    result = dedupe_urls(
        [
            "https://example.com/path?b=2&a=1",
            "https://example.com/path?a=1&b=2",
        ]
    )

    assert result == ["https://example.com/path?a=1&b=2"]


def test_is_same_section_matches_first_path_segment():
    assert (
        is_same_section(
            "https://www.example.com/partner/glean-ai/overview",
            "https://www.example.com/partner/cisco/overview",
        )
        is True
    )
    assert (
        is_same_section(
            "https://www.example.com/topic/applied-ai/overview",
            "https://www.example.com/topic/ai-assistants-and-ai-agents/overview",
        )
        is True
    )
    assert (
        is_same_section(
            "https://www.example.com/partner/glean-ai/overview",
            "https://www.example.com/topic/applied-ai/overview",
        )
        is False
    )


def test_prioritize_links_keeps_same_section_first():
    result = _prioritize_links(
        [
            "https://www.example.com/",
            "https://www.example.com/contact",
            "https://www.example.com/atc/ai-proving-ground/insights",
            "https://www.example.com/atc/ai-proving-ground/labs",
        ],
        seed_url="https://www.example.com/atc/ai-proving-ground/overview",
        current_url="https://www.example.com/atc/ai-proving-ground/overview",
    )

    assert set(result[:2]) == {
        "https://www.example.com/atc/ai-proving-ground/insights",
        "https://www.example.com/atc/ai-proving-ground/labs",
    }
    assert result.index("https://www.example.com/contact") > result.index(
        "https://www.example.com/atc/ai-proving-ground/insights"
    )
    assert result.index("https://www.example.com/") > result.index(
        "https://www.example.com/atc/ai-proving-ground/labs"
    )


class FakeMouse:
    def wheel(self, dx, dy):
        return None


class FakePage:
    def __init__(self, payload=None, goto_error=None):
        self.payload = payload or {}
        self.goto_error = goto_error
        self.mouse = FakeMouse()
        self.url = self.payload.get("final_url", "https://example.com/final")

    def goto(self, url, wait_until="domcontentloaded"):
        if self.goto_error:
            raise self.goto_error
        self.url = self.payload.get("final_url", url)

    def wait_for_timeout(self, ms):
        return None

    def evaluate(self, script):
        return self.payload


def _install_fake_playwright(monkeypatch, fake_extract, *, is_public=None):
    """Wire a headless-browser stand-in plus extract/network patches for crawl_site.

    ``is_public`` overrides the public-URL predicate (defaults to allowing only
    ``https://example.com`` hosts); ``fake_extract`` replaces ``_extract_page``.
    """

    class FakeBrowserPage:
        def set_default_timeout(self, timeout):
            return None

    class FakeContext:
        def route(self, pattern, handler):
            return None

        def new_page(self):
            return FakeBrowserPage()

        def close(self):
            return None

    class FakeBrowser:
        def new_context(self):
            return FakeContext()

        def close(self):
            return None

    class FakeChromium:
        def launch(self, headless=True):
            return FakeBrowser()

    class FakePlaywright:
        chromium = FakeChromium()

    class FakePlaywrightContextManager:
        def __enter__(self):
            return FakePlaywright()

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setitem(
        sys.modules,
        "playwright.sync_api",
        SimpleNamespace(sync_playwright=lambda: FakePlaywrightContextManager()),
    )
    monkeypatch.setattr(
        "distill.ingestors.net.is_public_web_url",
        is_public or (lambda url: url.startswith("https://example.com")),
    )
    monkeypatch.setattr("distill.ingestors.sites.scraper._extract_page", fake_extract)


def test_extract_page_returns_none_on_navigation_error():
    page = FakePage(goto_error=RuntimeError("boom"))

    assert (
        _extract_page(page, "https://example.com", "example.com", "https://example.com", 0) is None
    )


def test_extract_page_parses_payload_and_dedupes_fields():
    payload = {
        "title": " Agent Lab - Example ",
        "final_url": "https://example.com/video/agent-lab",
        "canonical_url": "https://example.com/video/agent-lab",
        "description": "Agent systems overview",
        "published_at": "2026-03-20",
        "authors": ["Alice", "alice", "Bob"],
        "tags": ["AI", "ai", "Agents"],
        "transcript": "Line 1\n\nLine 2",
        "text": "Body text\n\nwith spaces",
        "links": [
            "https://example.com/topic/agents?b=2&a=1",
            "https://example.com/topic/agents?a=1&b=2",
            "https://other.com/page",
        ],
        "pdf_links": ["https://example.com/guide.pdf"],
        "video_links": ["https://player.example.com/embed/123"],
        "has_video": True,
    }
    page = FakePage(payload=payload)

    extracted = _extract_page(
        page,
        "https://example.com/video/agent-lab",
        "example.com",
        "https://example.com/start",
        1,
    )

    assert extracted is not None
    assert extracted.page_type == "video"
    assert extracted.title == "Agent Lab - Example"
    assert extracted.authors == ["Alice", "Bob"]
    assert extracted.tags == ["AI", "Agents"]
    assert extracted.links[0] == "https://example.com/topic/agents?a=1&b=2"
    assert extracted.pdf_links == ["https://example.com/guide.pdf"]
    assert extracted.video_links == ["https://player.example.com/embed/123"]
    assert extracted.final_url == "https://example.com/video/agent-lab"
    assert extracted.source_url == "https://example.com/start"
    assert extracted.depth == 1


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "http://127.0.0.1:8000/admin",
        "http://localhost:8000/admin",
        "http://169.254.169.254/latest/meta-data/",
    ],
)
def test_crawl_site_rejects_unsafe_seed_before_browser_launch(url, monkeypatch):
    def fail_import(name, *args, **kwargs):
        if name == "playwright.sync_api":
            raise AssertionError("Playwright should not be imported for unsafe seeds")
        return original_import(name, *args, **kwargs)

    original_import = __import__
    monkeypatch.setattr("builtins.__import__", fail_import)

    assert crawl_site(SiteSeed(url=url, topic="web")) == []


def test_crawl_site_respects_depth_host_and_crawlability(monkeypatch):
    pages_by_url = {
        "https://example.com/start": SitePage(
            url="https://example.com/start",
            title="Start",
            site_name="example.com",
            page_type="page",
            text="Start body",
            links=[
                "https://example.com/next",
                "https://other.com/outside",
                "https://example.com/file.pdf",
            ],
        ),
        "https://example.com/next": SitePage(
            url="https://example.com/next",
            title="Next",
            site_name="example.com",
            page_type="page",
            text="Next body",
            links=["https://example.com/deeper"],
            depth=1,
        ),
    }

    def fake_extract(page, url, site_name, source_url, depth):
        result = pages_by_url.get(url)
        if result is None:
            return None
        result.source_url = source_url
        result.depth = depth
        return result

    _install_fake_playwright(monkeypatch, fake_extract)

    pages = crawl_site(
        SiteSeed(url="https://example.com/start", topic="web", max_depth=1, max_pages=5)
    )

    assert [page.url for page in pages] == ["https://example.com/start", "https://example.com/next"]
    assert pages[1].source_url == "https://example.com/start"
    assert pages[1].depth == 1


def test_crawl_site_respects_crawl_prefix(monkeypatch):
    pages_by_url = {
        "https://example.com/docs/agents": SitePage(
            url="https://example.com/docs/agents",
            title="Agents",
            site_name="example.com",
            page_type="page",
            text="Agents body",
            links=[
                "https://example.com/docs/agents/build",
                "https://example.com/docs/other",
            ],
        ),
        "https://example.com/docs/agents/build": SitePage(
            url="https://example.com/docs/agents/build",
            title="Build",
            site_name="example.com",
            page_type="page",
            text="Build body",
        ),
        "https://example.com/docs/other": SitePage(
            url="https://example.com/docs/other",
            title="Other",
            site_name="example.com",
            page_type="page",
            text="Other body",
        ),
    }

    def fake_extract(page, url, site_name, source_url, depth):
        result = pages_by_url.get(url)
        if result is None:
            return None
        result.source_url = source_url
        result.depth = depth
        return result

    _install_fake_playwright(monkeypatch, fake_extract)

    pages = crawl_site(
        SiteSeed(
            url="https://example.com/docs/agents",
            topic="web",
            max_depth=1,
            max_pages=5,
            crawl_prefix="/docs/agents",
        )
    )

    assert [page.url for page in pages] == [
        "https://example.com/docs/agents",
        "https://example.com/docs/agents/build",
    ]


def test_crawl_site_drops_off_host_redirect(monkeypatch):
    """A page.goto redirect that lands off the seed host is dropped, not ingested.

    The crawler already confines followed links to the seed host
    (_link_is_crawlable_for_seed); a redirect target must meet the same
    invariant. Otherwise an allowlisted seed that 30x-redirects off-host would
    escape the crawl scope and any MCP ingest allowlist that only checked the
    seed URL. test_crawl_site_respects_depth_host_and_crawlability is the
    same-host positive control (on-host pages are kept).
    """
    redirected = SitePage(
        url="https://example.com/start",
        title="Start",
        site_name="example.com",
        page_type="page",
        text="body",
        final_url="https://evil.example.net/landing",
    )

    def fake_extract(page, url, site_name, source_url, depth):
        redirected.source_url = source_url
        redirected.depth = depth
        return redirected

    # Treat every host as public so only the same-host confinement can drop it.
    _install_fake_playwright(monkeypatch, fake_extract, is_public=lambda url: True)

    pages = crawl_site(SiteSeed(url="https://example.com/start", topic="web", max_pages=5))

    assert pages == []

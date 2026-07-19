import contextlib
import io
import json
import sys
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

import pytest

from distill.ingestors.sites import _site_urls as site_urls
from distill.ingestors.sites import scraper as scraper_module
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
    crawl_site_in_browser_worker,
    dedupe_urls,
    is_crawlable_url,
    is_same_section,
    load_site_batch,
    normalize_host,
    page_id_from_url,
    parse_site_batch_json,
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


@pytest.mark.parametrize(
    ("max_depth", "max_pages", "message"),
    [
        (-1, 1, "max_depth must be between 0 and 4"),
        (5, 1, "max_depth must be between 0 and 4"),
        (0, 0, "max_pages must be between 1 and 100"),
        (0, 101, "max_pages must be between 1 and 100"),
        (True, 1, "max_depth must be an integer"),
        (0, "8", "max_pages must be an integer"),
    ],
)
def test_site_seed_rejects_invalid_crawl_limits(max_depth, max_pages, message):
    with pytest.raises(ValueError, match=message):
        SiteSeed(
            url="https://example.com/docs",
            topic="web",
            max_depth=max_depth,
            max_pages=max_pages,
        )


def test_site_seed_accepts_crawl_limit_boundaries():
    exact = SiteSeed(
        url="https://example.com/exact",
        topic="web",
        max_depth=0,
        max_pages=1,
    )
    maximum = SiteSeed(
        url="https://example.com/crawl",
        topic="web",
        max_depth=4,
        max_pages=100,
    )

    assert (exact.max_depth, exact.max_pages) == (0, 1)
    assert (maximum.max_depth, maximum.max_pages) == (4, 100)


@pytest.mark.parametrize(
    "payload",
    [
        {
            "crawl": {"max_depth": 5},
            "urls": [{"url": "https://example.com/global"}],
        },
        {
            "collections": [
                {
                    "seeds": ["https://example.com/collection"],
                    "max_pages": 101,
                }
            ]
        },
        {
            "urls": [
                {
                    "url": "https://example.com/per-url",
                    "max_pages": 101,
                }
            ]
        },
    ],
)
def test_load_site_batch_rejects_oversized_limits_at_every_json_level(tmp_path, payload):
    path = tmp_path / "sites.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="must be between"):
        load_site_batch(path)


def test_parse_site_batch_rejects_malformed_json() -> None:
    with pytest.raises(ValueError, match="valid JSON"):
        parse_site_batch_json("{")


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (None, "object or array"),
        ({"crawl": []}, "'crawl' must be an object"),
        ({"urls": {}}, "'urls' must be an array"),
        ({"collections": {}}, "'collections' must be an array"),
        (
            {
                "urls": ["https://example.com/a"],
                "collections": [{"seeds": ["https://example.com/b"]}],
            },
            "either 'urls' or 'collections'",
        ),
        ({"collections": [{}] * 501}, "too many collections"),
        ({"collections": ["invalid"]}, "collection 1 must be an object"),
        ({"collections": [{"seeds": {}}]}, "field 'seeds' must be an array"),
        (
            {"collections": [{"seeds": ["https://example.com"] * 501}]},
            "too many seeds",
        ),
        ({"collections": [{"seeds": [""]}]}, "must be a URL string"),
        ({"collections": [{"seeds": [73]}]}, "must be a URL string"),
        ({"urls": ["https://example.com"] * 501}, "too many seeds"),
        ({"urls": [""]}, "must not be empty"),
        ({"urls": [73]}, "must be a URL or object"),
        ({"urls": [{}]}, "requires a URL string"),
        ({"topic": 73}, "field 'topic' must be a string"),
        (
            {"urls": [{"url": "https://example.com", "label": 73}]},
            "field 'label' must be a string",
        ),
        (
            {"urls": [{"url": "https://example.com", "discover_crawl": "yes"}]},
            "field 'discover_crawl' must be a boolean",
        ),
        (
            {"urls": [{"url": "https://example.com", "crawl": "yes"}]},
            "field 'crawl' must be a boolean",
        ),
        (
            {"urls": [{"url": "https://example.com", "max_pages": True}]},
            "field 'max_pages' must be an integer",
        ),
        (
            {"urls": [{"url": "https://example.com", "source_hint": "x" * 4_097}]},
            "field 'source_hint' is too long",
        ),
    ],
)
def test_parse_site_batch_rejects_unbounded_or_mistyped_manifest_shapes(
    payload: object,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        parse_site_batch_json(json.dumps(payload))


def test_classify_page_type_prefers_video_when_flagged():
    assert classify_page_type("https://example.com/page", "Title", "", True) == "video"
    assert classify_page_type("https://example.com/topic/ai", "Title", "", False) == "topic"
    assert classify_page_type("https://example.com/partner/tool", "Title", "", False) == "partner"


@pytest.mark.parametrize(
    ("path", "page_type"),
    [
        ("lab", "lab"),
        ("research", "research"),
        ("research-and-insights", "research"),
        ("insights", "research"),
        ("category", "category"),
        ("overview", "overview"),
        ("explore", "explore"),
        ("ecosystem", "ecosystem"),
        ("plain", "page"),
    ],
)
def test_classify_page_type_covers_supported_content_families(path: str, page_type: str) -> None:
    assert classify_page_type(f"https://example.com/{path}/item", "Title", "", False) == page_type


def test_site_url_helpers_cover_scope_and_canonicalization_edges() -> None:
    assert site_urls.is_within_crawl_prefix("https://example.com/anything", "") is True
    assert site_urls.canonicalize_url("https://[2001:db8::1]:443/docs") == (
        "https://[2001:db8::1]/docs"
    )
    assert site_urls.canonicalize_url("https://Example.COM:bad/docs") == (
        "https://example.com:bad/docs"
    )
    assert site_urls.is_crawlable_url("ftp://example.com/docs") is False
    assert site_urls.is_same_section("https://example.com/", "https://example.com/docs") is False
    assert (
        site_urls.canonical_url_in_seed_scope(
            "http://example.com/docs",
            seed=SiteSeed(url="https://example.com/docs", topic="web"),
            root_host="example.com",
        )
        is None
    )
    assert (
        site_urls.link_relevance_score(
            "https://example.com/docs/start",
            "https://example.com/docs/start",
            "https://example.com/docs/current",
        )
        >= 100
    )


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
        normalize_host("https://user:pass@www.example.com:8443/path?token=canary")
        == "example.com:8443"
    )
    assert (
        canonicalize_url("https://example.com/path/?utm_source=x&b=2&a=1")
        == "https://example.com/path?b=2&a=1"
    )
    assert canonicalize_url("HTTPS://EXAMPLE.COM.:443/path/") == "https://example.com/path"
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

    verdicts = iter((True, False))
    checked_urls = []

    def public_verdict(url):
        checked_urls.append(url)
        return next(verdicts)

    monkeypatch.setattr("distill.ingestors.net.is_public_web_url", public_verdict)
    context = FakeContext()

    _install_public_web_route(context)

    allowed = FakeRoute()
    context.handler(allowed, SimpleNamespace(url="https://example.com/page"))
    rebound = FakeRoute()
    context.handler(rebound, SimpleNamespace(url="https://example.com/asset.js"))
    blocked = FakeRoute()
    context.handler(blocked, SimpleNamespace(url="http://127.0.0.1/admin"))

    assert context.pattern == "**/*"
    assert allowed.action == "continue"
    assert rebound.action == "abort"
    assert blocked.action == "abort"
    assert checked_urls == [
        "https://example.com/page",
        "https://example.com/asset.js",
    ]


def test_public_web_route_bounds_requests_and_blocks_non_text_assets(monkeypatch):
    class FakeRoute:
        def __init__(self):
            self.action = ""

        def continue_(self):
            self.action = "continue"

        def abort(self):
            self.action = "abort"

    class FakeContext:
        def route(self, pattern, handler):
            self.handler = handler

    monkeypatch.setattr("distill.ingestors.net.is_public_web_url", lambda _url: True)
    context = FakeContext()
    budget = _install_public_web_route(context)

    image = FakeRoute()
    context.handler(
        image,
        SimpleNamespace(url="https://example.com/image.png", resource_type="image"),
    )
    assert image.action == "abort"

    routes = []
    for index in range(129):
        route = FakeRoute()
        routes.append(route)
        context.handler(
            route,
            SimpleNamespace(
                url=f"https://example.com/data/{index}",
                resource_type="fetch",
            ),
        )
    assert all(route.action == "continue" for route in routes[:128])
    assert routes[-1].action == "abort"

    budget.reset()
    after_reset = FakeRoute()
    context.handler(
        after_reset,
        SimpleNamespace(url="https://example.com/next", resource_type="document"),
    )
    assert after_reset.action == "continue"


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


def test_dedupe_urls_preserves_query_order_as_identity():
    result = dedupe_urls(
        [
            "https://example.com/path?b=2&a=1",
            "https://example.com/path?a=1&b=2",
        ]
    )

    assert result == [
        "https://example.com/path?b=2&a=1",
        "https://example.com/path?a=1&b=2",
    ]


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


class FakeCDPSession:
    def __init__(self, payload, runtime_response=None):
        self.payload = payload
        self.runtime_response = runtime_response
        self.calls = []
        self.detached = False

    def send(self, method, params=None):
        self.calls.append((method, params))
        if method == "Page.getFrameTree":
            return {"frameTree": {"frame": {"id": "main-frame"}}}
        if method == "Page.createIsolatedWorld":
            return {"executionContextId": 17}
        if method == "Runtime.evaluate":
            if self.runtime_response is not None:
                return self.runtime_response
            return {"result": {"type": "object", "value": self.payload}}
        raise AssertionError(f"Unexpected CDP method: {method}")

    def detach(self):
        self.detached = True


class FakePage:
    def __init__(self, payload=None, goto_error=None, runtime_response=None):
        self.payload = payload or {}
        self.goto_error = goto_error
        self.mouse = FakeMouse()
        self.url = self.payload.get("final_url", "https://example.com/final")
        self.cdp_session = FakeCDPSession(self.payload, runtime_response)
        self.context = SimpleNamespace(new_cdp_session=lambda page: self.cdp_session)

    def goto(self, url, wait_until="domcontentloaded"):
        if self.goto_error:
            raise self.goto_error
        self.url = self.payload.get("final_url", url)

    def wait_for_timeout(self, ms):
        return None

    def evaluate(self, script):
        pytest.fail("page-realm evaluate must not handle untrusted extraction")


def _install_fake_playwright(monkeypatch, fake_extract, *, is_public=None, observed=None):
    """Wire a headless-browser stand-in plus extract/network patches for crawl_site.

    ``is_public`` overrides the public-URL predicate (defaults to allowing only
    ``https://example.com`` hosts); ``fake_extract`` replaces ``_extract_page``.
    """

    observed = observed if observed is not None else {}

    page = SimpleNamespace(set_default_timeout=lambda timeout: None, close=lambda: None)
    context = SimpleNamespace(
        route=lambda pattern, handler: None,
        new_page=lambda: page,
        close=lambda: None,
    )

    def new_context(**kwargs):
        observed["context"] = kwargs
        return context

    browser = SimpleNamespace(new_context=new_context, close=lambda: None)

    def launch(headless=True, **kwargs):
        observed["launch"] = {"headless": headless, **kwargs}
        return browser

    playwright = SimpleNamespace(chromium=SimpleNamespace(launch=launch))

    monkeypatch.setitem(
        sys.modules,
        "playwright.sync_api",
        SimpleNamespace(sync_playwright=lambda: contextlib.nullcontext(playwright)),
    )
    monkeypatch.setattr(
        "distill.ingestors.net.is_public_web_url",
        is_public or (lambda url: url.startswith("https://example.com")),
    )
    monkeypatch.setattr(
        "distill.ingestors.sites.scraper.PinnedBrowserProxy",
        lambda: contextlib.nullcontext("http://127.0.0.1:43123"),
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
    assert extracted.links[:2] == [
        "https://example.com/topic/agents?b=2&a=1",
        "https://example.com/topic/agents?a=1&b=2",
    ]
    assert extracted.pdf_links == ["https://example.com/guide.pdf"]
    assert extracted.video_links == ["https://player.example.com/embed/123"]
    assert extracted.final_url == "https://example.com/video/agent-lab"
    assert extracted.source_url == "https://example.com/start"
    assert extracted.depth == 1


def test_extract_page_uses_timed_isolated_world_and_detaches_session():
    page = FakePage(
        payload={
            "title": "Bounded",
            "final_url": "https://example.com/bounded",
            "text": "body",
        }
    )

    assert (
        _extract_page(
            page,
            "https://example.com/bounded",
            "example.com",
            "https://example.com/start",
            0,
        )
        is not None
    )

    assert [method for method, _params in page.cdp_session.calls] == [
        "Page.getFrameTree",
        "Page.createIsolatedWorld",
        "Runtime.evaluate",
    ]
    world_params = page.cdp_session.calls[1][1]
    runtime_params = page.cdp_session.calls[2][1]
    assert world_params == {"frameId": "main-frame", "worldName": "distill-bounded-extraction"}
    assert runtime_params["contextId"] == 17
    assert runtime_params["returnByValue"] is True
    assert runtime_params["awaitPromise"] is False
    assert runtime_params["timeout"] == 2_000
    assert "innerText" not in runtime_params["expression"]
    assert "querySelectorAll" not in runtime_params["expression"]
    assert '"maxDomNodes":50000' in runtime_params["expression"]
    assert '"maxLinks":512' in runtime_params["expression"]
    assert page.cdp_session.detached is True


def test_extract_page_discards_cdp_exception_and_detaches_session():
    page = FakePage(
        runtime_response={
            "result": {"type": "object"},
            "exceptionDetails": {"text": "Execution was terminated"},
        }
    )

    result = _extract_page(
        page,
        "https://example.com/bounded",
        "example.com",
        "https://example.com/start",
        0,
    )

    assert result is None
    assert page.cdp_session.detached is True


def test_extract_page_defensively_bounds_payload_and_records_truncation():
    payload = {
        "title": "T" * 600,
        "final_url": "https://example.com/bounded",
        "description": "D" * 5_000,
        "published_at": "2" * 200,
        "authors": [f"author-{index}" for index in range(6)],
        "tags": [f"tag-{index}" for index in range(13)],
        "text": "body",
        "links": [f"https://example.com/page/{index}" for index in range(513)],
        "pdf_links": [f"https://example.com/file/{index}.pdf" for index in range(513)],
        "video_links": [f"https://video.example.com/{index}" for index in range(65)],
        "truncation_reasons": ["body_text", "not-a-real-reason"],
    }

    extracted = _extract_page(
        FakePage(payload=payload),
        "https://example.com/bounded",
        "example.com",
        "https://example.com/start",
        0,
    )

    assert extracted is not None
    assert len(extracted.title) == 512
    assert len(extracted.description) == 4_096
    assert len(extracted.published_at) == 128
    assert len(extracted.authors) == 5
    assert len(extracted.tags) == 12
    assert len(extracted.links) == 512
    assert len(extracted.pdf_links) == 512
    assert len(extracted.video_links) == 64
    assert set(extracted.truncation_reasons) == {
        "authors",
        "body_text",
        "description",
        "links",
        "metadata",
        "pdf_links",
        "tags",
        "title",
        "video_links",
    }
    assert extracted.metadata()["extraction_truncated"] is True


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "http://127.0.0.1:8000/admin",
        "http://localhost:8000/admin",
        "http://169.254.169.254/latest/meta-data/",
        "http://example.com/public",
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


def test_crawl_site_revalidates_mutated_limits_before_browser_launch(monkeypatch):
    seed = SiteSeed(url="https://example.com/docs", topic="web")
    seed.max_pages = 101
    monkeypatch.setattr(
        "distill.ingestors.sites.scraper.PinnedBrowserProxy",
        lambda: pytest.fail("browser proxy must not start for an invalid crawl plan"),
    )

    with pytest.raises(ValueError, match="max_pages must be between 1 and 100"):
        crawl_site(seed)


def test_crawl_site_delegates_valid_seed_to_isolated_worker(monkeypatch):
    seed = SiteSeed(url="https://example.com/docs", topic="web")
    expected = [
        SitePage(
            url=seed.url,
            title="Worker page",
            site_name="example.com",
            page_type="page",
            text="body",
        )
    ]
    monkeypatch.setattr("distill.ingestors.net.is_public_web_url", lambda _url: True)
    monkeypatch.setattr(
        "distill.ingestors.sites.scraper._run_browser_worker",
        lambda received: expected if received is seed else [],
    )

    assert crawl_site(seed) == expected


class _BrowserControlPipe:
    def __init__(self) -> None:
        self.data = b""

    def write(self, data: bytes) -> None:
        self.data += data

    def close(self) -> None:
        return None


class _FakeBrowserProcess:
    pid = 73

    def __init__(self, *, returncode: int = 0, stderr: bytes = b"") -> None:
        self.stdin = _BrowserControlPipe()
        self.stderr = io.BytesIO(stderr)
        self.returncode = returncode
        self.killed = False

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        return self.returncode

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9


def test_browser_worker_parent_validates_bounded_result(monkeypatch, tmp_path: Path) -> None:
    seed = SiteSeed(url="https://example.com/docs", topic="web", max_depth=0, max_pages=1)
    page = SitePage(
        url=seed.url,
        title="Docs",
        site_name="example.com",
        page_type="page",
        text="body",
    )
    process = _FakeBrowserProcess()
    observed = {}
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", "untrusted-browser-path")
    monkeypatch.setenv("PYTHONWARNINGS", "ignore::untrusted.Warning")

    def popen(argv, **kwargs):
        observed["argv"] = argv
        observed["kwargs"] = kwargs
        Path(argv[5]).write_text(
            json.dumps({"schema_version": 1, "pages": [asdict(page)]}),
            encoding="utf-8",
        )
        return process

    monkeypatch.setattr(scraper_module.subprocess, "Popen", popen)
    monkeypatch.setattr(scraper_module, "assign_windows_memory_job", lambda *a, **k: None)
    monkeypatch.setattr(scraper_module, "close_windows_job", lambda _handle: None)
    monkeypatch.setattr(scraper_module, "wait_for_process_budget", lambda *a, **k: 100)
    terminated = []
    monkeypatch.setattr(
        scraper_module,
        "terminate_isolated_process_tree",
        terminated.append,
    )

    assert scraper_module._run_browser_worker(seed) == [page]
    assert terminated == [process]
    assert process.stdin is None
    assert observed["argv"][:4] == [
        sys.executable,
        "-P",
        "-m",
        "distill.ingestors.sites._browser_worker",
    ]
    assert observed["kwargs"]["cwd"] == str(Path(sys.executable).resolve().parent)
    assert "PLAYWRIGHT_BROWSERS_PATH" not in observed["kwargs"]["env"]
    assert "PYTHONWARNINGS" not in observed["kwargs"]["env"]
    assert observed["kwargs"]["env"]["PYTHONNOUSERSITE"] == "1"


def test_browser_worker_parent_terminates_on_memory_budget(monkeypatch, tmp_path: Path) -> None:
    seed = SiteSeed(url="https://example.com/docs", topic="web", max_depth=0, max_pages=1)
    process = _FakeBrowserProcess()
    terminated = []
    monkeypatch.setattr(scraper_module.subprocess, "Popen", lambda *a, **k: process)
    monkeypatch.setattr(scraper_module, "package_install_context", lambda: (str(tmp_path), {}))
    monkeypatch.setattr(scraper_module, "assign_windows_memory_job", lambda *a, **k: None)
    monkeypatch.setattr(scraper_module, "close_windows_job", lambda _handle: None)
    monkeypatch.setattr(
        scraper_module,
        "wait_for_process_budget",
        lambda *a, **k: (_ for _ in ()).throw(
            scraper_module.ProcessBudgetExceeded("memory", 100, 101)
        ),
    )
    monkeypatch.setattr(scraper_module, "terminate_isolated_process_tree", terminated.append)

    assert scraper_module._run_browser_worker(seed) == []
    assert terminated == [process]


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

    pages = crawl_site_in_browser_worker(
        SiteSeed(url="https://example.com/start", topic="web", max_depth=1, max_pages=5)
    )

    assert [page.url for page in pages] == ["https://example.com/start", "https://example.com/next"]
    assert pages[1].source_url == "https://example.com/start"
    assert pages[1].depth == 1


def test_crawl_site_uses_pinned_proxy_and_blocks_service_workers(monkeypatch):
    observed = {}

    def fake_extract(page, url, site_name, source_url, depth):
        return SitePage(
            url=url,
            title="Pinned",
            site_name=site_name,
            page_type="page",
            text="body",
        )

    _install_fake_playwright(monkeypatch, fake_extract, observed=observed)

    pages = crawl_site_in_browser_worker(SiteSeed(url="https://example.com/start", topic="web"))

    assert len(pages) == 1
    assert observed["context"] == {
        "proxy": {"server": "http://127.0.0.1:43123"},
        "service_workers": "block",
        "accept_downloads": False,
        "extra_http_headers": {"Accept-Encoding": "identity"},
    }
    assert "--disable-quic" in observed["launch"]["args"]
    assert "--force-webrtc-ip-handling-policy=disable_non_proxied_udp" in observed["launch"]["args"]


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

    pages = crawl_site_in_browser_worker(
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

    pages = crawl_site_in_browser_worker(
        SiteSeed(url="https://example.com/start", topic="web", max_pages=5)
    )

    assert pages == []


@pytest.mark.parametrize(
    ("seed", "landed_url"),
    [
        (
            SiteSeed(
                url="https://example.com/docs/agents/start",
                topic="web",
                crawl_prefix="/docs/agents",
            ),
            "https://example.com/docs/other/landing",
        ),
        (
            SiteSeed(
                url="https://example.com/docs/start",
                topic="web",
                same_section_only=True,
            ),
            "https://example.com/blog/landing",
        ),
    ],
)
def test_crawl_site_drops_redirect_outside_seed_path_scope(seed, landed_url, monkeypatch):
    redirected = SitePage(
        url=seed.url,
        title="Redirected",
        site_name="example.com",
        page_type="page",
        text="body",
        final_url=landed_url,
    )

    _install_fake_playwright(monkeypatch, lambda *_args: redirected)

    assert crawl_site_in_browser_worker(seed) == []


def test_crawl_site_keeps_redirect_within_seed_path_scope(monkeypatch):
    seed = SiteSeed(
        url="https://example.com/docs/agents/start",
        topic="web",
        crawl_prefix="/docs/agents",
        same_section_only=True,
    )
    redirected = SitePage(
        url=seed.url,
        title="Redirected",
        site_name="example.com",
        page_type="page",
        text="body",
        final_url="https://example.com/docs/agents/landing",
    )

    _install_fake_playwright(monkeypatch, lambda *_args: redirected)

    assert crawl_site_in_browser_worker(seed) == [redirected]

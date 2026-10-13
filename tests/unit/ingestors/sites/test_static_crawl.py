"""Exact-page crawls fall back to HTTP only when no browser can launch."""

from __future__ import annotations

import pytest

from distill.ingestors.sites.http_static import StaticFetchError
from distill.ingestors.sites.records import SitePage, SiteSeed
from distill.ingestors.sites.scraper import SiteCrawlResult, crawl_site_with_receipts


def _page(url: str) -> SitePage:
    return SitePage(
        url=url,
        title="Static",
        site_name="example.com",
        page_type="page",
        text="body",
        capture="http-static",
    )


def test_exact_page_uses_http_when_no_browser_can_launch(monkeypatch: pytest.MonkeyPatch) -> None:
    page = _page("https://example.com/docs")
    monkeypatch.setattr(
        "distill.ingestors.sites.system_browser.browser_can_launch",
        lambda: False,
    )
    monkeypatch.setattr(
        "distill.ingestors.sites.http_static.fetch_static_page",
        lambda url: page,
    )

    result = crawl_site_with_receipts(SiteSeed(url=page.url, topic="web", max_pages=1, max_depth=0))

    assert result.pages == [page]
    assert result.failures == []


def test_static_fetch_failure_is_a_navigation_receipt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "distill.ingestors.sites.system_browser.browser_can_launch",
        lambda: False,
    )

    def fail(url: str) -> SitePage:
        raise StaticFetchError("timed out")

    monkeypatch.setattr("distill.ingestors.sites.http_static.fetch_static_page", fail)

    result = crawl_site_with_receipts(
        SiteSeed(url="https://example.com/docs", topic="web", max_pages=1, max_depth=0)
    )

    assert result.pages == []
    assert result.failures[0].outcome == "navigation-failed"
    assert result.failures[0].detail == "timed out"


def test_deeper_crawl_stays_on_the_browser_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []
    monkeypatch.setattr(
        "distill.ingestors.sites.system_browser.browser_can_launch",
        lambda: False,
    )

    def worker(seed: SiteSeed) -> SiteCrawlResult:
        seen.append(seed.url)
        return SiteCrawlResult()

    monkeypatch.setattr("distill.ingestors.sites.scraper._run_browser_worker", worker)

    crawl_site_with_receipts(SiteSeed(url="https://example.com/docs", topic="web"))

    assert seen == ["https://example.com/docs"]

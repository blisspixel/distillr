"""Tests for distill.browser_search."""

import json
import sys
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from distill.ingestors.youtube.browser_search import (
    _build_search_url,
    _duration_to_seconds,
    _extract_owner_url,
    _extract_text,
    _fetch_search_html,
    _fetch_with_playwright,
    _is_search_url,
    _parse_int,
    _parse_upload_date,
    _relative_to_yyyymmdd,
    _video_from_renderer,
    parse_search_results_html,
    search_youtube_results,
)
from distill.ingestors.youtube.discovery import VideoInfo


def test_parse_search_results_html_extracts_video_candidates():
    html = """
    <html><body><script>var ytInitialData = {
      "contents": {
        "twoColumnSearchResultsRenderer": {
          "primaryContents": {
            "sectionListRenderer": {
              "contents": [
                {
                  "itemSectionRenderer": {
                    "contents": [
                      {
                        "videoRenderer": {
                          "videoId": "abc123",
                          "title": {"runs": [{"text": "Microsoft Fabric Best Practices"}]},
                          "ownerText": {"runs": [{"text": "Fabric Guy", "navigationEndpoint": {"browseEndpoint": {"canonicalBaseUrl": "/@FabricGuy"}}}]},
                          "publishedTimeText": {"simpleText": "2 weeks ago"},
                          "lengthText": {"simpleText": "12:34"},
                          "viewCountText": {"simpleText": "1,234 views"},
                          "descriptionSnippet": {"runs": [{"text": "Architecture guide and best practices"}]}
                        }
                      }
                    ]
                  }
                }
              ]
            }
          }
        }
      }
    };</script></body></html>
    """

    videos = parse_search_results_html(html)

    assert len(videos) == 1
    assert videos[0].video_id == "abc123"
    assert videos[0].channel_url == "https://www.youtube.com/@FabricGuy"
    assert videos[0].duration == 754
    assert videos[0].view_count == 1234


def test_search_youtube_results_filters_old_results(monkeypatch):
    html = """
    <html><body><script>var ytInitialData = {
      "contents": {
        "twoColumnSearchResultsRenderer": {
          "primaryContents": {
            "sectionListRenderer": {
              "contents": [
                {
                  "itemSectionRenderer": {
                    "contents": [
                      {"videoRenderer": {"videoId": "new1", "title": {"runs": [{"text": "New"}]}, "ownerText": {"runs": [{"text": "Chan"}]}, "publishedTimeText": {"simpleText": "Premiered 3 weeks ago"}, "lengthText": {"simpleText": "10:00"}}},
                      {"videoRenderer": {"videoId": "old1", "title": {"runs": [{"text": "Old"}]}, "ownerText": {"runs": [{"text": "Chan"}]}, "publishedTimeText": {"simpleText": "8 months ago"}, "lengthText": {"simpleText": "10:00"}}}
                    ]
                  }
                }
              ]
            }
          }
        }
      }
    };</script></body></html>
    """
    monkeypatch.setattr(
        "distill.ingestors.youtube.browser_search._fetch_search_html", lambda url: html
    )

    videos = search_youtube_results("Microsoft Fabric", days=60, limit=5)

    assert [video.video_id for video in videos] == ["new1"]


def test_search_youtube_results_rejects_undated_candidates(monkeypatch):
    payload = {
        "items": [
            {
                "videoRenderer": {
                    "videoId": "undated123",
                    "title": {"simpleText": "Undated"},
                    "publishedTimeText": {"simpleText": "recently-ish"},
                }
            }
        ]
    }
    html = f"var ytInitialData = {json.dumps(payload)};</script>"
    monkeypatch.setattr(
        "distill.ingestors.youtube.browser_search._fetch_search_html", lambda _url: html
    )

    assert search_youtube_results("agent loops", days=60) == []


def test_parse_search_results_html_returns_empty_without_initial_data():
    assert parse_search_results_html("<html></html>") == []


def test_parse_search_results_html_malformed_json_returns_empty():
    # ytInitialData comes from an untrusted fetched page and can be truncated;
    # a malformed blob must degrade to [], not raise JSONDecodeError into the run.
    html = 'var ytInitialData = {"contents": };</script>'
    assert parse_search_results_html(html) == []


def test_parse_search_results_html_isolates_malformed_renderer_shapes():
    valid = {"videoId": "valid", "title": {"simpleText": "Valid"}}
    malformed_renderers: list[object] = [
        "not-an-object",
        {"videoId": "bad&id"},
        {"videoId": "x" * 1_000_000},
        {"videoId": "bad-title", "title": {"runs": [1]}},
        {"videoId": "bad-owner", "ownerText": "not-an-object"},
        {"videoId": "bad-length", "lengthText": {"simpleText": 123}},
        {
            "videoId": "bad-navigation",
            "ownerText": {"runs": [{"navigationEndpoint": "not-an-object"}]},
        },
    ]

    for malformed in malformed_renderers:
        payload = {"items": [{"videoRenderer": malformed}, {"videoRenderer": valid}]}
        html = f"var ytInitialData = {json.dumps(payload)};</script>"

        videos = parse_search_results_html(html)

        assert any(video.video_id == "valid" for video in videos)


def test_parse_search_results_html_rejects_excessive_nesting():
    nested = '{"child":' * 1200 + "{}" + "}" * 1200
    html = f"var ytInitialData = {nested};</script>"

    assert parse_search_results_html(html) == []


def test_search_youtube_results_returns_empty_for_non_positive_limit():
    assert search_youtube_results("Microsoft Fabric", limit=0) == []


def test_search_youtube_results_rejects_unbounded_inputs_before_fetch(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(
        "distill.ingestors.youtube.browser_search._fetch_search_html",
        lambda url: calls.append(url) or "<html></html>",
    )

    assert search_youtube_results("x", days=10**4000) == []
    assert search_youtube_results("x", hours=10**4000) == []
    assert search_youtube_results("x", limit=10**4000) == []
    assert search_youtube_results("x", days=True) == []
    assert calls == []


def test_fetch_search_html_falls_back_to_urllib(monkeypatch):
    monkeypatch.setattr(
        "distill.ingestors.youtube.browser_search._fetch_with_playwright", lambda url: ""
    )
    monkeypatch.setattr(
        "distill.ingestors.youtube.browser_search._fetch_with_urllib", lambda url: "<html>ok</html>"
    )

    assert (
        _fetch_search_html("https://www.youtube.com/results?search_query=fabric")
        == "<html>ok</html>"
    )


def test_build_and_detect_search_urls():
    url = _build_search_url("Microsoft Fabric best practices")

    assert "search_query=Microsoft+Fabric+best+practices" in url
    assert _is_search_url(url) is True
    assert _is_search_url("https://youtube.com/watch?v=abc") is False
    for unsafe in (
        "http://www.youtube.com/results?search_query=x",
        "https://user@www.youtube.com/results?search_query=x",
        "https://www.youtube.com:444/results?search_query=x",
        "https://www.youtube.com/results?search_query=x#fragment",
        "https://www.youtube.com.evil.example/results?search_query=x",
    ):
        assert _is_search_url(unsafe) is False


def test_extract_text_handles_nested_structures():
    node = {"runs": [{"text": "Hello"}, {"text": " world"}]}

    assert _extract_text(node) == "Hello world"
    assert _extract_text([{"simpleText": "one"}, {"simpleText": "two"}]) == "one two"


def test_extract_text_bounds_characters_without_recursive_descent():
    assert len(_extract_text({"simpleText": "x" * 10_000})) == 4_096
    assert len(_extract_text({"runs": [{"text": "x" * 3_000}, {"text": "y" * 3_000}]})) == 4_096
    assert len(_extract_text([{"simpleText": "x" * 3_000}] * 3)) == 4_096

    nested: dict[str, object] = {}
    cursor = nested
    for _ in range(2_000):
        child: dict[str, object] = {}
        cursor["child"] = child
        cursor = child
    cursor["simpleText"] = "deep"
    assert _extract_text(nested) == "deep"


def test_relative_to_yyyymmdd_and_parse_upload_date():
    assert _relative_to_yyyymmdd("streamed 2 days ago")
    assert _relative_to_yyyymmdd("nonsense") == ""
    assert _parse_upload_date("20260312") is not None
    assert _parse_upload_date("bad-date") is None


def test_duration_and_int_parsing_helpers():
    assert _duration_to_seconds("1:02:03") == 3723
    assert _duration_to_seconds("12:34") == 754
    assert _duration_to_seconds("45") == 45
    assert _duration_to_seconds("bad") == 0
    assert _duration_to_seconds("1:bad:02") == 0
    assert _duration_to_seconds("1:\u00b2:02") == 0
    assert _duration_to_seconds("\u0661\u0662:\u0663\u0664") == 0
    assert _duration_to_seconds("9" * 5000) == 0
    assert _parse_int("1,234 views") == 1234
    assert _parse_int("") == 0
    assert _parse_int("9" * 5000 + " views") == 0
    assert _parse_int("1,\u066234 views") == 0
    assert _parse_int("1,23 views") == 0
    assert _duration_to_seconds("1:" * 5_000) == 0
    assert _duration_to_seconds("999999:59:59") == 0


def test_relative_date_rejects_unicode_and_overflowing_numbers():
    assert _relative_to_yyyymmdd("Premiered 2 hours ago")
    assert _relative_to_yyyymmdd("Streamed 2 days ago")
    assert _relative_to_yyyymmdd("\u0662 days ago") == ""
    assert _relative_to_yyyymmdd(f"{'9' * 5000} days ago") == ""
    assert _relative_to_yyyymmdd("999999999999 days ago") == ""
    assert _relative_to_yyyymmdd("2 days ago extra") == ""


def test_search_result_parser_rejects_oversized_json_integer():
    html = f'<script>var ytInitialData = {{"n": {"9" * 5000}}};</script>'
    previous = sys.get_int_max_str_digits()
    try:
        sys.set_int_max_str_digits(0)
        assert parse_search_results_html(html) == []
    finally:
        sys.set_int_max_str_digits(previous)


def test_fetch_with_urllib_uses_response_body(monkeypatch):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self, size=-1):
            return b"<html>body</html>"

    # safe_urlopen now SSRF-guards the host and fetches via a validating opener,
    # so patch those net internals rather than urllib.request.urlopen.
    from distill.ingestors import net

    monkeypatch.setattr(net, "is_public_web_url", lambda url: True)
    monkeypatch.setattr(net._SSRF_SAFE_OPENER, "open", lambda req, timeout=30: FakeResponse())

    from distill.ingestors.youtube.browser_search import _fetch_with_urllib

    assert (
        _fetch_with_urllib("https://www.youtube.com/results?search_query=fabric")
        == "<html>body</html>"
    )


def test_video_from_renderer_returns_none_without_video_id():
    assert _video_from_renderer({"title": {"simpleText": "Nope"}}) is None


def test_video_from_renderer_uses_browse_id_and_detailed_metadata():
    renderer = {
        "videoId": "vid123",
        "title": {"simpleText": "Deep Dive"},
        "longBylineText": {
            "runs": [
                {
                    "text": "Creator",
                    "navigationEndpoint": {"browseEndpoint": {"browseId": "UC123456"}},
                }
            ]
        },
        "publishedTimeText": {"simpleText": "1 day ago"},
        "lengthText": {"simpleText": "1:02:03"},
        "viewCountText": {"simpleText": "12,345 views"},
        "detailedMetadataSnippets": [{"simpleText": "Detailed description"}],
    }

    video = _video_from_renderer(renderer)

    assert video is not None
    assert video.channel_url == "https://www.youtube.com/channel/UC123456"
    assert video.description == "Detailed description"
    assert video.duration == 3723
    assert video.view_count == 12345


def test_extract_owner_url_returns_empty_without_runs():
    assert _extract_owner_url({"ownerText": {"runs": []}}) == ""


def test_extract_owner_url_rejects_noncanonical_metadata() -> None:
    def renderer(endpoint: dict[str, object]) -> dict[str, object]:
        return {
            "ownerText": {
                "runs": [
                    {
                        "navigationEndpoint": {"browseEndpoint": endpoint},
                    }
                ]
            }
        }

    for endpoint in (
        {"canonicalBaseUrl": "//evil.example/@Creator"},
        {"canonicalBaseUrl": "/redirect?q=https://evil.example"},
        {"canonicalBaseUrl": "/@ab"},
        {"canonicalBaseUrl": "/@Creator?next=https://evil.example"},
        {"browseId": "UC123"},
        {"browseId": "UC123456/../../redirect"},
    ):
        assert _extract_owner_url(renderer(endpoint)) == ""


def test_search_youtube_results_rejects_future_candidates(monkeypatch) -> None:
    future = datetime.now(UTC) + timedelta(days=1)
    candidate = VideoInfo(
        video_id="future123",
        title="Future",
        upload_date=future.strftime("%Y%m%d"),
        duration=60,
        url="https://www.youtube.com/watch?v=future123",
        published_at=future.isoformat(),
    )
    monkeypatch.setattr(
        "distill.ingestors.youtube.browser_search._fetch_search_html",
        lambda _url: "<html></html>",
    )
    monkeypatch.setattr(
        "distill.ingestors.youtube.browser_search.parse_search_results_html",
        lambda _html: [candidate],
    )

    assert search_youtube_results("future", days=7) == []


def test_fetch_with_playwright_returns_empty_when_module_missing(monkeypatch):
    monkeypatch.setitem(sys.modules, "playwright", None)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", None)

    assert _fetch_with_playwright("https://www.youtube.com/results?search_query=fabric") == ""


def test_fetch_with_playwright_returns_page_content(monkeypatch):
    class FakePage:
        def goto(self, *args, **kwargs):
            return None

        def wait_for_timeout(self, *args, **kwargs):
            return None

        def evaluate(self, _expression):
            return len("<html>playwright</html>")

        def content(self):
            return "<html>playwright</html>"

    class FakeBrowser:
        def new_page(self):
            return FakePage()

        def close(self):
            return None

    class FakeChromium:
        def launch(self, headless=True):
            return FakeBrowser()

    class FakePlaywright:
        chromium = FakeChromium()

    class FakeManager:
        def __enter__(self):
            return FakePlaywright()

        def __exit__(self, exc_type, exc, tb):
            return False

    fake_module = SimpleNamespace(sync_playwright=lambda: FakeManager())
    monkeypatch.setitem(sys.modules, "playwright", SimpleNamespace(sync_api=fake_module))
    monkeypatch.setitem(sys.modules, "playwright.sync_api", fake_module)

    assert (
        _fetch_with_playwright("https://www.youtube.com/results?search_query=fabric")
        == "<html>playwright</html>"
    )


def test_fetch_with_playwright_rejects_oversized_dom_before_copy(monkeypatch):
    closed = []

    class FakePage:
        def goto(self, *args, **kwargs):
            return None

        def wait_for_timeout(self, *args, **kwargs):
            return None

        def evaluate(self, _expression):
            return 10_000_001

        def content(self):
            raise AssertionError("oversized DOM must not be copied into Python")

    class FakeBrowser:
        def new_page(self):
            return FakePage()

        def close(self):
            closed.append(True)

    class FakeChromium:
        def launch(self, headless=True):
            return FakeBrowser()

    class FakePlaywright:
        chromium = FakeChromium()

    class FakeManager:
        def __enter__(self):
            return FakePlaywright()

        def __exit__(self, exc_type, exc, tb):
            return False

    fake_module = SimpleNamespace(sync_playwright=lambda: FakeManager())
    monkeypatch.setitem(sys.modules, "playwright", SimpleNamespace(sync_api=fake_module))
    monkeypatch.setitem(sys.modules, "playwright.sync_api", fake_module)

    assert _fetch_with_playwright("https://www.youtube.com/results?search_query=fabric") == ""
    assert closed == [True]


def test_fetch_with_playwright_returns_empty_on_runtime_error(monkeypatch):
    class FakeManager:
        def __enter__(self):
            raise RuntimeError("boom")

        def __exit__(self, exc_type, exc, tb):
            return False

    fake_module = SimpleNamespace(sync_playwright=lambda: FakeManager())
    monkeypatch.setitem(sys.modules, "playwright", SimpleNamespace(sync_api=fake_module))
    monkeypatch.setitem(sys.modules, "playwright.sync_api", fake_module)

    assert _fetch_with_playwright("https://www.youtube.com/results?search_query=fabric") == ""


def test_fetch_search_html_prefers_playwright_result(monkeypatch):
    monkeypatch.setattr(
        "distill.ingestors.youtube.browser_search._fetch_with_playwright",
        lambda url: "<html>playwright-first</html>",
    )
    monkeypatch.setattr(
        "distill.ingestors.youtube.browser_search._fetch_with_urllib",
        lambda url: (_ for _ in ()).throw(AssertionError("urllib should not be used")),
    )

    assert (
        _fetch_search_html("https://www.youtube.com/results?search_query=fabric")
        == "<html>playwright-first</html>"
    )


def test_extract_text_walks_nested_dict_values():
    node = {"outer": {"inner": {"simpleText": "nested"}}}

    assert _extract_text(node) == "nested"


def test_relative_to_yyyymmdd_handles_multiple_units():
    assert _relative_to_yyyymmdd("5 minutes ago")
    assert _relative_to_yyyymmdd("2 hours ago")
    assert _relative_to_yyyymmdd("3 weeks ago")
    assert _relative_to_yyyymmdd("1 month ago")
    assert _relative_to_yyyymmdd("1 year ago")


def test_duration_to_seconds_returns_zero_for_empty_string():
    assert _duration_to_seconds("") == 0

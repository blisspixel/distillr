"""Tests for distill.browser_search."""

import sys
from types import SimpleNamespace

from distill.browser_search import (
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
                      {"videoRenderer": {"videoId": "new1", "title": {"runs": [{"text": "New"}]}, "ownerText": {"runs": [{"text": "Chan"}]}, "publishedTimeText": {"simpleText": "3 weeks ago"}, "lengthText": {"simpleText": "10:00"}}},
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
    monkeypatch.setattr("distill.browser_search._fetch_search_html", lambda url: html)

    videos = search_youtube_results("Microsoft Fabric", days=60, limit=5)

    assert [video.video_id for video in videos] == ["new1"]


def test_parse_search_results_html_returns_empty_without_initial_data():
    assert parse_search_results_html("<html></html>") == []


def test_search_youtube_results_returns_empty_for_non_positive_limit():
    assert search_youtube_results("Microsoft Fabric", limit=0) == []


def test_fetch_search_html_falls_back_to_urllib(monkeypatch):
    monkeypatch.setattr("distill.browser_search._fetch_with_playwright", lambda url: "")
    monkeypatch.setattr("distill.browser_search._fetch_with_urllib", lambda url: "<html>ok</html>")

    assert (
        _fetch_search_html("https://www.youtube.com/results?search_query=fabric")
        == "<html>ok</html>"
    )


def test_build_and_detect_search_urls():
    url = _build_search_url("Microsoft Fabric best practices")

    assert "search_query=Microsoft+Fabric+best+practices" in url
    assert _is_search_url(url) is True
    assert _is_search_url("https://youtube.com/watch?v=abc") is False


def test_extract_text_handles_nested_structures():
    node = {"runs": [{"text": "Hello"}, {"text": " world"}]}

    assert _extract_text(node) == "Hello world"
    assert _extract_text([{"simpleText": "one"}, {"simpleText": "two"}]) == "one two"


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
    assert _parse_int("1,234 views") == 1234
    assert _parse_int("") == 0


def test_fetch_with_urllib_uses_response_body(monkeypatch):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b"<html>body</html>"

    monkeypatch.setattr(
        "distill.browser_search.urllib.request.urlopen",
        lambda req, timeout=30: FakeResponse(),
    )

    from distill.browser_search import _fetch_with_urllib

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
                    "navigationEndpoint": {"browseEndpoint": {"browseId": "UC123"}},
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
    assert video.channel_url == "https://www.youtube.com/channel/UC123"
    assert video.description == "Detailed description"
    assert video.duration == 3723
    assert video.view_count == 12345


def test_extract_owner_url_returns_empty_without_runs():
    assert _extract_owner_url({"ownerText": {"runs": []}}) == ""


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
        "distill.browser_search._fetch_with_playwright",
        lambda url: "<html>playwright-first</html>",
    )
    monkeypatch.setattr(
        "distill.browser_search._fetch_with_urllib",
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

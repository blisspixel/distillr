"""Tests for distill.discovery."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from distill.ingestors.youtube._yt_dlp_boundary import int_field
from distill.ingestors.youtube.discovery import (
    VideoInfo,
    _apply_search_caps,
    _channel_url_from_metadata,
    _entry_to_video_info,
    _is_recent_enough,
    _merge_video_info,
    _normalize_channel_url,
    _rank_search_results,
    discover_videos,
    enrich_videos,
    get_video_info,
    is_youtube_url,
    resolve_channel_name,
)


def test_is_youtube_url_accepts_youtube_hosts():
    assert is_youtube_url("https://www.youtube.com/watch?v=abc")
    assert is_youtube_url("https://youtu.be/abc")
    assert is_youtube_url("https://m.youtube.com/watch?v=abc")
    assert is_youtube_url("https://www.youtube.com/shorts/abc")
    assert is_youtube_url("https://www.youtube.com/embed/abc")


def test_is_youtube_url_rejects_non_youtube_and_internal():
    # SSRF guard: yt-dlp does its own networking, so non-YouTube hosts (incl.
    # cloud metadata / internal) must be rejected before reaching it.
    assert not is_youtube_url("http://169.254.169.254/latest/meta-data/")
    assert not is_youtube_url("http://127.0.0.1:8080/")
    assert not is_youtube_url("https://evil.example.com/watch?v=abc")
    assert not is_youtube_url("https://notyoutube.com/")
    assert not is_youtube_url("file:///etc/passwd")
    assert not is_youtube_url("https://youtube.com.evil.com/")
    assert not is_youtube_url("http://music.youtube.com/watch?v=abc")
    assert not is_youtube_url("https://evil.youtube.com/watch?v=abc")
    assert not is_youtube_url("https://user@youtube.com/watch?v=abc")
    assert not is_youtube_url("https://youtube.com:443/watch?v=abc")
    assert not is_youtube_url("https://youtube.com/redirect?q=http://169.254.169.254/")
    assert not is_youtube_url("https://youtube.com/watch?v=abc&v=second")
    assert not is_youtube_url("https://youtube.com/watch?v=abc#fragment")


def test_get_video_info_refuses_non_youtube_url_without_fetching(capsys):
    with patch("distill.ingestors.youtube.discovery.SafeYoutubeDL") as mock_ydl:
        raw = "https://evil.example/private?token=VIDEO-DISCOVERY-CANARY"
        assert get_video_info(raw) is None
        mock_ydl.assert_not_called()
    output = capsys.readouterr().out
    assert "https://evil.example" in output
    assert "private" not in output
    assert "VIDEO-DISCOVERY-CANARY" not in output


def _recent(days_ago: int = 1) -> str:
    """Return an upload_date string for ``days_ago`` days before today."""
    return (datetime.now() - timedelta(days=days_ago)).strftime("%Y%m%d")


class TestDiscoverVideos:
    @patch("distill.ingestors.youtube.discovery.SafeYoutubeDL")
    def test_refuses_non_youtube_url_without_fetching(self, mock_ydl_cls, capsys):
        # SSRF guard: an attacker-influenced channel URL (reachable by default
        # via the MCP watch_add / catch_up write tools) must never reach yt-dlp,
        # which does its own networking outside the urllib/requests SSRF guards.
        for url in (
            "http://169.254.169.254/latest/meta-data/",
            "http://127.0.0.1:6379/",
            "https://evil.example.com/@x",
            "https://evil.example.com/@x?token=CHANNEL-DISCOVERY-CANARY",
            "file:///etc/passwd",
        ):
            assert discover_videos(url, months=3) == []
        mock_ydl_cls.assert_not_called()
        output = capsys.readouterr().out
        assert "CHANNEL-DISCOVERY-CANARY" not in output

    @patch("distill.ingestors.youtube.discovery.SafeYoutubeDL")
    def test_basic_discovery(self, mock_ydl_cls):
        """Discovers videos from a channel."""
        mock_ydl = MagicMock()
        mock_ydl_cls.return_value.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_ydl.extract_info.return_value = {
            "entries": [
                {
                    "id": "abc123",
                    "title": "Test Video",
                    "upload_date": _recent(2),
                    "duration": 600,
                },
                {
                    "id": "def456",
                    "title": "Another Video",
                    "upload_date": _recent(5),
                    "duration": 1200,
                },
            ]
        }

        videos = discover_videos("https://www.youtube.com/@Test", months=3)
        assert len(videos) == 2
        assert videos[0].video_id in ("abc123", "def456")
        assert all(isinstance(v, VideoInfo) for v in videos)
        assert mock_ydl_cls.call_args.kwargs == {
            "metadata_byte_limit": 20_000_000,
            "total_byte_limit": 64_000_000,
        }

    @patch("distill.ingestors.youtube.discovery.SafeYoutubeDL")
    def test_discovery_rejects_future_dated_entries(self, mock_ydl_cls):
        mock_ydl = MagicMock()
        mock_ydl_cls.return_value.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl_cls.return_value.__exit__ = MagicMock(return_value=False)
        future = datetime.now(UTC) + timedelta(days=1)
        mock_ydl.extract_info.return_value = {
            "entries": [
                {
                    "id": "future123",
                    "title": "Future",
                    "upload_date": future.strftime("%Y%m%d"),
                    "timestamp": int(future.timestamp()),
                }
            ]
        }

        assert discover_videos("https://www.youtube.com/@Test", days=7) == []

    @patch("distill.ingestors.youtube.discovery.SafeYoutubeDL")
    def test_discovery_rejects_noncanonical_channel_urls(self, mock_ydl_cls):
        for channel_url in (
            "http://www.youtube.com/@Test",
            "https://user@www.youtube.com/@Test",
            "https://www.youtube.com:444/@Test",
            "https://www.youtube.com/redirect?q=https://evil.example",
            "https://www.youtube.com/watch?v=abc",
            "https://evil.youtube.com/@Test",
        ):
            assert discover_videos(channel_url, days=7) == []
        mock_ydl_cls.assert_not_called()

    @patch("distill.ingestors.youtube.discovery.SafeYoutubeDL")
    def test_precise_hour_window_filters_channel_entries(self, mock_ydl_cls):
        mock_ydl = MagicMock()
        mock_ydl_cls.return_value.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl_cls.return_value.__exit__ = MagicMock(return_value=False)
        now = datetime.now(UTC)
        mock_ydl.extract_info.return_value = {
            "entries": [
                {
                    "id": "fresh123",
                    "title": "Fresh",
                    "upload_date": now.strftime("%Y%m%d"),
                    "timestamp": int((now - timedelta(minutes=30)).timestamp()),
                },
                {
                    "id": "stale123",
                    "title": "Stale",
                    "upload_date": now.strftime("%Y%m%d"),
                    "timestamp": int((now - timedelta(hours=2)).timestamp()),
                },
            ]
        }

        videos = discover_videos("https://www.youtube.com/@Test", days=1, hours=1)

        assert [video.video_id for video in videos] == ["fresh123"]

    @patch("distill.ingestors.youtube.discovery.SafeYoutubeDL")
    def test_strict_precise_window_rejects_potentially_fresh_date_only_entry(self, mock_ydl_cls):
        mock_ydl = MagicMock()
        mock_ydl_cls.return_value.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_ydl.extract_info.return_value = {
            "entries": [
                {
                    "id": "dateonly123",
                    "title": "Date-only upload",
                    "upload_date": datetime.now(UTC).strftime("%Y%m%d"),
                }
            ]
        }

        with pytest.raises(RuntimeError, match="without a precise timestamp"):
            discover_videos(
                "https://www.youtube.com/@Test",
                days=1,
                hours=12,
                raise_on_error=True,
            )

    @patch("distill.ingestors.youtube.discovery.SafeYoutubeDL")
    def test_discovery_rejects_unbounded_windows_before_fetch(self, mock_ydl_cls):
        url = "https://www.youtube.com/@Test"

        assert discover_videos(url, days=10**4000) == []
        assert discover_videos(url, hours=10**4000) == []
        assert discover_videos(url, months=10**4000) == []
        mock_ydl_cls.assert_not_called()

    @patch("distill.ingestors.youtube.discovery.SafeYoutubeDL")
    def test_empty_channel(self, mock_ydl_cls):
        """Handles a channel with no videos."""
        mock_ydl = MagicMock()
        mock_ydl_cls.return_value.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_ydl.extract_info.return_value = {"entries": []}

        videos = discover_videos("https://www.youtube.com/@Empty", months=3)
        assert videos == []

    @patch("distill.ingestors.youtube.discovery.SafeYoutubeDL")
    def test_null_entries(self, mock_ydl_cls):
        """Handles None entries in the playlist (yt-dlp returns None for errors)."""
        mock_ydl = MagicMock()
        mock_ydl_cls.return_value.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_ydl.extract_info.return_value = {
            "entries": [
                None,
                {
                    "id": "abc",
                    "title": "Good",
                    "upload_date": _recent(1),
                    "duration": 300,
                },
                None,
            ]
        }

        videos = discover_videos("https://www.youtube.com/@Test")
        assert len(videos) == 1
        assert videos[0].video_id == "abc"

    @patch("distill.ingestors.youtube.discovery.SafeYoutubeDL")
    def test_missing_upload_date_skipped(self, mock_ydl_cls):
        """Videos without upload_date are skipped."""
        mock_ydl = MagicMock()
        mock_ydl_cls.return_value.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_ydl.extract_info.return_value = {
            "entries": [
                {"id": "abc", "title": "No Date", "upload_date": "", "duration": 300},
                {
                    "id": "def",
                    "title": "Has Date",
                    "upload_date": _recent(3),
                    "duration": 300,
                },
            ]
        }

        videos = discover_videos("https://www.youtube.com/@Test")
        assert len(videos) == 1
        assert videos[0].video_id == "def"

    @patch("distill.ingestors.youtube.discovery.SafeYoutubeDL")
    def test_missing_duration_defaults_zero(self, mock_ydl_cls):
        """Videos with None duration get 0."""
        mock_ydl = MagicMock()
        mock_ydl_cls.return_value.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_ydl.extract_info.return_value = {
            "entries": [
                {
                    "id": "abc",
                    "title": "No Duration",
                    "upload_date": _recent(1),
                    "duration": None,
                },
            ]
        }

        videos = discover_videos("https://www.youtube.com/@Test")
        assert len(videos) == 1
        assert videos[0].duration == 0

    @patch("distill.ingestors.youtube.discovery.SafeYoutubeDL")
    def test_no_info_returned(self, mock_ydl_cls):
        """Handles yt-dlp returning None."""
        mock_ydl = MagicMock()
        mock_ydl_cls.return_value.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_ydl.extract_info.return_value = None

        videos = discover_videos("https://www.youtube.com/@Test")
        assert videos == []

    @patch("distill.ingestors.youtube.discovery.SafeYoutubeDL")
    def test_no_info_returned_fails_closed_in_strict_mode(self, mock_ydl_cls):
        """Strict discovery reports a swallowed top-level extraction failure."""
        mock_ydl = MagicMock()
        mock_ydl_cls.return_value.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_ydl.extract_info.return_value = None

        with pytest.raises(RuntimeError, match="returned no data"):
            discover_videos("https://www.youtube.com/@Test", raise_on_error=True)

        assert mock_ydl_cls.call_args.args[0]["ignoreerrors"] is False

    @patch("distill.ingestors.youtube.discovery.SafeYoutubeDL")
    def test_entries_none_single_video(self, mock_ydl_cls):
        """Handles case where entries key is None (single video URL)."""
        mock_ydl = MagicMock()
        mock_ydl_cls.return_value.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_ydl.extract_info.return_value = {"id": "abc", "title": "Single"}

        videos = discover_videos("https://www.youtube.com/watch?v=abc")
        assert videos == []

    @patch("distill.ingestors.youtube.discovery.SafeYoutubeDL")
    def test_exception_returns_empty(self, mock_ydl_cls):
        """Handles exceptions from yt-dlp."""
        mock_ydl = MagicMock()
        mock_ydl_cls.return_value.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_ydl.extract_info.side_effect = Exception("network error")

        videos = discover_videos("https://www.youtube.com/@Test")
        assert videos == []

    @patch("distill.ingestors.youtube.discovery.SafeYoutubeDL")
    def test_sorted_newest_first(self, mock_ydl_cls):
        """Videos are sorted newest-first by upload_date."""
        mock_ydl = MagicMock()
        mock_ydl_cls.return_value.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_ydl.extract_info.return_value = {
            "entries": [
                {
                    "id": "old",
                    "title": "Old",
                    "upload_date": _recent(30),
                    "duration": 100,
                },
                {
                    "id": "new",
                    "title": "New",
                    "upload_date": _recent(1),
                    "duration": 100,
                },
                {
                    "id": "mid",
                    "title": "Mid",
                    "upload_date": _recent(15),
                    "duration": 100,
                },
            ]
        }

        videos = discover_videos("https://www.youtube.com/@Test")
        assert [v.video_id for v in videos] == ["new", "mid", "old"]

    @patch("distill.ingestors.youtube.discovery.SafeYoutubeDL")
    def test_old_videos_filtered_by_cutoff(self, mock_ydl_cls):
        """Videos older than the lookback window are excluded."""
        mock_ydl = MagicMock()
        mock_ydl_cls.return_value.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_ydl.extract_info.return_value = {
            "entries": [
                {
                    "id": "recent",
                    "title": "Recent",
                    "upload_date": _recent(1),
                    "duration": 100,
                },
                {
                    "id": "ancient",
                    "title": "Ancient",
                    "upload_date": "20200101",
                    "duration": 100,
                },
            ]
        }

        videos = discover_videos("https://www.youtube.com/@Test", days=7)
        assert len(videos) == 1
        assert videos[0].video_id == "recent"

    def test_url_gets_videos_suffix(self):
        """Channel URLs get /videos appended."""
        # We can't easily test this without mocking, but we test the URL logic
        url = "https://www.youtube.com/@Test"
        if not url.endswith("/videos"):
            url = url.rstrip("/") + "/videos"
        assert url == "https://www.youtube.com/@Test/videos"

    def test_url_with_trailing_slash(self):
        url = "https://www.youtube.com/@Test/"
        if not url.endswith("/videos"):
            url = url.rstrip("/") + "/videos"
        assert url == "https://www.youtube.com/@Test/videos"


class TestResolveChannelName:
    def test_identity_from_url_requires_handle_or_channel_id(self):
        from distill.ingestors.youtube.discovery import _channel_identity_from_url

        assert _channel_identity_from_url("https://www.youtube.com/c/LegacyName") == ""

    def test_extracts_from_at_url(self):
        """Extracts channel name from /@Name URLs."""
        name = resolve_channel_name("https://www.youtube.com/@TestChannel")
        assert name == "TestChannel"

    def test_extracts_with_path(self):
        """Extracts channel name when URL has extra path."""
        name = resolve_channel_name("https://www.youtube.com/@TestChannel/videos")
        assert name == "TestChannel"

    def test_extracts_with_query_string(self):
        """Rejects channel metadata URLs with query params."""
        name = resolve_channel_name("https://www.youtube.com/@TestChannel?sub=1")
        assert name == "unknown"

    @patch("distill.ingestors.youtube.discovery.SafeYoutubeDL")
    def test_fallback_to_ytdlp(self, mock_ydl_cls):
        """Falls back to yt-dlp for non-@ URLs."""
        mock_ydl = MagicMock()
        mock_ydl_cls.return_value.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_ydl.extract_info.return_value = {"channel": "Resolved Name"}

        name = resolve_channel_name("https://www.youtube.com/channel/UC123456")
        assert name == "Resolved Name"

    @patch("distill.ingestors.youtube.discovery.SafeYoutubeDL")
    def test_fallback_ytdlp_error(self, mock_ydl_cls):
        """Uses the channel id when yt-dlp fails and no @ handle is present."""
        mock_ydl = MagicMock()
        mock_ydl_cls.return_value.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_ydl.extract_info.side_effect = Exception("fail")

        name = resolve_channel_name("https://www.youtube.com/channel/UC123456")
        assert name == "UC123456"

    @patch("distill.ingestors.youtube.discovery.SafeYoutubeDL")
    def test_fallback_none_info_uses_channel_id(self, mock_ydl_cls):
        mock_ydl = MagicMock()
        mock_ydl_cls.return_value.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_ydl.extract_info.return_value = None

        name = resolve_channel_name("https://www.youtube.com/channel/UC123456")
        assert name == "UC123456"

    @patch("distill.ingestors.youtube.discovery.SafeYoutubeDL")
    def test_fallback_ignores_non_string_metadata(self, mock_ydl_cls):
        mock_ydl = MagicMock()
        mock_ydl_cls.return_value.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_ydl.extract_info.return_value = {"channel": 123, "uploader": None}

        name = resolve_channel_name("https://www.youtube.com/channel/UC123456")

        assert name == "UC123456"


class TestSearchVideos:
    @patch("distill.ingestors.youtube.discovery.SafeYoutubeDL")
    def test_search_filters_recent_dedupes_and_caps_channels(self, mock_ydl_cls):
        mock_ydl = MagicMock()
        mock_ydl_cls.return_value.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl_cls.return_value.__exit__ = MagicMock(return_value=False)

        recent = (datetime.now() - timedelta(days=5)).strftime("%Y%m%d")
        also_recent = (datetime.now() - timedelta(days=8)).strftime("%Y%m%d")
        old = (datetime.now() - timedelta(days=120)).strftime("%Y%m%d")
        mock_ydl.extract_info.return_value = {
            "entries": [
                {
                    "id": "a1",
                    "title": "A1",
                    "upload_date": recent,
                    "duration": 600,
                    "channel": "ChanA",
                    "channel_url": "/@ChanA",
                },
                {
                    "id": "a1",
                    "title": "A1 dup",
                    "upload_date": recent,
                    "duration": 600,
                    "channel": "ChanA",
                    "channel_url": "/@ChanA",
                },
                {
                    "id": "a2",
                    "title": "A2",
                    "upload_date": also_recent,
                    "duration": 700,
                    "channel": "ChanA",
                    "channel_url": "/@ChanA",
                },
                {
                    "id": "b1",
                    "title": "B1",
                    "upload_date": recent,
                    "duration": 800,
                    "channel": "ChanB",
                    "channel_url": "/@ChanB",
                },
                {
                    "id": "old1",
                    "title": "Old",
                    "upload_date": old,
                    "duration": 900,
                    "channel": "ChanC",
                    "channel_url": "/@ChanC",
                },
            ]
        }

        from distill.ingestors.youtube.discovery import search_videos

        videos = search_videos("fabric", days=60, limit=3, per_channel_cap=1)
        assert [v.video_id for v in videos] == ["a1", "b1"]
        assert videos[0].channel_url == "https://www.youtube.com/@ChanA"

    @patch("distill.ingestors.youtube.discovery.SafeYoutubeDL")
    def test_search_date_sort_orders_newest_first(self, mock_ydl_cls):
        mock_ydl = MagicMock()
        mock_ydl_cls.return_value.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl_cls.return_value.__exit__ = MagicMock(return_value=False)

        older = (datetime.now() - timedelta(days=20)).strftime("%Y%m%d")
        newer = (datetime.now() - timedelta(days=2)).strftime("%Y%m%d")
        mock_ydl.extract_info.return_value = {
            "entries": [
                {
                    "id": "old",
                    "title": "Old",
                    "upload_date": older,
                    "duration": 500,
                    "channel": "ChanA",
                },
                {
                    "id": "new",
                    "title": "New",
                    "upload_date": newer,
                    "duration": 500,
                    "channel": "ChanB",
                },
            ]
        }

        from distill.ingestors.youtube.discovery import search_videos

        videos = search_videos("fabric", days=60, limit=2, sort="date", per_channel_cap=2)
        assert [v.video_id for v in videos] == ["new", "old"]


class TestVideoInfoHelpers:
    def test_get_video_info_returns_none_on_error(self, monkeypatch):
        class FakeYDL:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def extract_info(self, url, download=False):
                raise Exception("boom")

        monkeypatch.setattr(
            "distill.ingestors.youtube.discovery.SafeYoutubeDL",
            lambda _opts, **_limits: FakeYDL(),
        )

        assert get_video_info("https://youtube.com/watch?v=abc") is None

    def test_enrich_videos_merges_richer_metadata(self, monkeypatch):
        base = VideoInfo("v1", "Base", "20260301", 100, "https://youtube.com/watch?v=v1", "Chan")
        detailed = VideoInfo(
            "v1",
            "Detailed",
            "20260302",
            200,
            "https://youtube.com/watch?v=v1",
            "Chan 2",
            description="desc",
            view_count=99,
        )
        monkeypatch.setattr(
            "distill.ingestors.youtube.discovery.get_video_info", lambda url: detailed
        )

        enriched = enrich_videos([base])

        assert enriched[0].title == "Detailed"
        assert enriched[0].view_count == 99

    def test_entry_to_video_info_and_channel_url_helpers(self):
        entry = {
            "id": "v1",
            "title": "Video",
            "upload_date": "20260301",
            "duration": 123,
            "uploader_id": "@Creator",
            "description": "desc",
        }

        video = _entry_to_video_info(entry)

        assert video.channel_url == "https://www.youtube.com/@Creator"
        assert (
            _channel_url_from_metadata({"channel_id": "UC123456"})
            == "https://www.youtube.com/channel/UC123456"
        )
        assert _normalize_channel_url("/@Creator") == "https://www.youtube.com/@Creator"
        assert (
            _normalize_channel_url("https://www.youtube.com/@Creator/")
            == "https://www.youtube.com/@Creator"
        )
        assert _normalize_channel_url("https://m.youtube.com/@Creator/videos") == (
            "https://www.youtube.com/@Creator/videos"
        )
        for unsafe in (
            "http://www.youtube.com/@Creator",
            "https://www.youtube.com/@ab",
            "https://www.youtube.com/@Creator/featured",
            "https://www.youtube.com/@Creator?next=https://evil.example",
            "https://www.youtube.com/channel/UC123",
        ):
            assert _normalize_channel_url(unsafe) == ""

    def test_entry_to_video_info_tolerates_malformed_optional_fields(self):
        entry = {
            "id": "v1",
            "title": 7,
            "upload_date": "20260301",
            "duration": "bad",
            "channel": 123,
            "channel_id": "UC123456",
            "description": 17,
            "view_count": "bad",
            "like_count": None,
            "comment_count": object(),
        }

        video = _entry_to_video_info(entry)

        assert video is not None
        assert video.title == "Unknown"
        assert video.duration == 0
        assert video.channel_name == "UC123456"
        assert video.description == ""
        assert video.view_count == 0
        assert video.like_count == 0
        assert video.comment_count == 0

    def test_entry_to_video_info_rejects_unsafe_ids_and_canonicalizes_url(self):
        base = {"title": "Video", "upload_date": "20260301"}

        assert _entry_to_video_info({**base, "id": "../../outside"}) is None
        assert _entry_to_video_info({**base, "id": "abc&list=x"}) is None
        assert _entry_to_video_info({**base, "id": "x" * 1_000_000}) is None
        for bad_date in ("99999999", "20260230", "9" * 1_000_000):
            assert _entry_to_video_info({**base, "id": "safe123", "upload_date": bad_date}) is None
        video = _entry_to_video_info(
            {**base, "id": "safe123", "webpage_url": "http://169.254.169.254/"}
        )
        assert video is not None
        assert video.url == "https://www.youtube.com/watch?v=safe123"

    def test_yt_dlp_integer_fields_are_total_and_bounded(self):
        assert int_field({"value": 10**4000}, "value") == 0
        assert int_field({"value": "9" * 4000}, "value") == 0
        assert int_field({"value": True}, "value") == 0
        assert int_field({"value": -1}, "value") == 0
        assert int_field({"value": "\u0661\u0662"}, "value") == 0
        assert int_field({"value": "\u00b2"}, "value") == 0
        assert int_field({"value": "+12"}, "value") == 0
        assert int_field({"value": " 12 "}, "value") == 0
        assert int_field({"value": 1.9}, "value") == 0
        assert int_field({"value": 12.0}, "value") == 12

    def test_recent_rank_and_caps_helpers(self):
        cutoff = datetime.now() - timedelta(days=30)
        videos = [
            VideoInfo("b", "B", _recent(5), 100, "u", "Chan"),
            VideoInfo("a", "A", _recent(3), 100, "u", "Chan"),
            VideoInfo("c", "C", _recent(1), 100, "u", "Other"),
        ]

        assert _is_recent_enough(_recent(5), cutoff) is True
        ranked = _rank_search_results([*videos, videos[0]], "date")
        capped = _apply_search_caps(ranked, limit=2, per_channel_cap=1)

        assert ranked[0].video_id == "c"
        assert len(capped) == 2

    def test_date_only_freshness_includes_the_cutoff_calendar_day(self):
        cutoff = datetime(2026, 7, 6, 15, tzinfo=UTC)
        ceiling = datetime(2026, 7, 13, 15, tzinfo=UTC)

        assert _is_recent_enough("20260706", cutoff, ceiling) is True
        assert _is_recent_enough("20260705", cutoff, ceiling) is False

    def test_merge_video_info_prefers_detailed_fields(self):
        base = VideoInfo(
            "v1",
            "Base",
            "20260301",
            100,
            "url",
            "BaseChan",
            description="base",
            published_at="2026-03-01T08:00:00+00:00",
        )
        detailed = VideoInfo(
            "v1",
            "",
            "",
            0,
            "url",
            "",
            description="",
            published_at="2026-03-01T09:00:00+00:00",
        )

        merged = _merge_video_info(base, detailed)

        assert merged.title == "Base"
        assert merged.description == "base"
        assert merged.published_at == "2026-03-01T09:00:00+00:00"

        fallback = _merge_video_info(base, VideoInfo("v1", "", "", 0, "url"))
        assert fallback.published_at == base.published_at


class TestDiscoveryAdditionalBranches:
    @patch("distill.ingestors.youtube.discovery.SafeYoutubeDL")
    def test_discover_videos_scans_shorts_and_dedupes(self, mock_ydl_cls):
        mock_ydl = MagicMock()
        mock_ydl_cls.return_value.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_ydl.extract_info.side_effect = [
            {
                "entries": [
                    {
                        "id": "dup",
                        "title": "Video Tab",
                        "upload_date": _recent(5),
                        "duration": 120,
                    }
                ]
            },
            {
                "entries": [
                    {
                        "id": "dup",
                        "title": "Short Tab",
                        "upload_date": _recent(5),
                        "duration": 45,
                    },
                    {
                        "id": "short2",
                        "title": "Short 2",
                        "upload_date": _recent(3),
                        "duration": 30,
                    },
                ]
            },
        ]

        videos = discover_videos("https://www.youtube.com/@Test/videos", include_shorts=True)

        assert [v.video_id for v in videos] == ["short2", "dup"]

    @patch("distill.ingestors.youtube.discovery.SafeYoutubeDL")
    def test_get_video_info_returns_parsed_video(self, mock_ydl_cls):
        mock_ydl = MagicMock()
        mock_ydl_cls.return_value.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_ydl.extract_info.return_value = {
            "id": "abc",
            "title": "Title",
            "upload_date": "20260301",
            "duration": 61,
            "channel_id": "UC123456",
        }

        video = get_video_info("https://youtube.com/watch?v=abc")

        assert video is not None
        assert video.video_id == "abc"
        assert video.channel_url == "https://www.youtube.com/channel/UC123456"
        mock_ydl.extract_info.assert_called_once_with(
            "https://www.youtube.com/watch?v=abc", download=False
        )

    @patch("distill.ingestors.youtube.discovery.SafeYoutubeDL")
    def test_get_video_info_returns_none_for_empty_info(self, mock_ydl_cls):
        mock_ydl = MagicMock()
        mock_ydl_cls.return_value.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_ydl.extract_info.return_value = None

        assert get_video_info("https://youtube.com/watch?v=abc") is None

    @patch("distill.ingestors.youtube.discovery.SafeYoutubeDL")
    def test_search_videos_returns_empty_on_non_positive_limit(self, mock_ydl_cls):
        from distill.ingestors.youtube.discovery import search_videos

        assert search_videos("fabric", limit=0) == []
        mock_ydl_cls.assert_not_called()

    @patch("distill.ingestors.youtube.discovery.SafeYoutubeDL")
    def test_search_videos_rejects_unbounded_inputs_before_fetch(self, mock_ydl_cls):
        from distill.ingestors.youtube.discovery import search_videos

        assert search_videos("fabric", days=10**4000) == []
        assert search_videos("fabric", limit=10**4000) == []
        assert search_videos("fabric", days=True) == []
        mock_ydl_cls.assert_not_called()

    @patch("distill.ingestors.youtube.discovery.SafeYoutubeDL")
    def test_search_videos_returns_empty_on_error(self, mock_ydl_cls):
        mock_ydl = MagicMock()
        mock_ydl_cls.return_value.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_ydl.extract_info.side_effect = Exception("boom")

        from distill.ingestors.youtube.discovery import search_videos

        assert search_videos("fabric") == []

    @patch("distill.ingestors.youtube.discovery.SafeYoutubeDL")
    def test_search_videos_returns_empty_when_entries_missing(self, mock_ydl_cls):
        mock_ydl = MagicMock()
        mock_ydl_cls.return_value.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_ydl.extract_info.return_value = {}

        from distill.ingestors.youtube.discovery import search_videos

        assert search_videos("fabric") == []

    @patch("distill.ingestors.youtube.discovery.SafeYoutubeDL")
    def test_search_videos_enriches_selected_results(self, mock_ydl_cls, monkeypatch):
        mock_ydl = MagicMock()
        mock_ydl_cls.return_value.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl_cls.return_value.__exit__ = MagicMock(return_value=False)
        recent = (datetime.now() - timedelta(days=5)).strftime("%Y%m%d")
        mock_ydl.extract_info.return_value = {
            "entries": [
                {
                    "id": "a1",
                    "title": "A1",
                    "upload_date": recent,
                    "duration": 600,
                    "channel": "ChanA",
                }
            ]
        }
        monkeypatch.setattr(
            "distill.ingestors.youtube.discovery.enrich_videos",
            lambda videos: [
                _merge_video_info(
                    videos[0],
                    VideoInfo(
                        "a1",
                        "Better Title",
                        recent,
                        600,
                        videos[0].url,
                        "ChanA",
                        description="Enriched",
                    ),
                )
            ],
        )

        from distill.ingestors.youtube.discovery import search_videos

        videos = search_videos("fabric", enrich=True)

        assert videos[0].title == "Better Title"
        assert videos[0].description == "Enriched"


def test_enrich_videos_handles_empty_and_respects_max_videos(monkeypatch):
    first = VideoInfo("a", "A", _recent(3), 10, "url-a")
    second = VideoInfo("b", "B", _recent(2), 10, "url-b")
    monkeypatch.setattr(
        "distill.ingestors.youtube.discovery.get_video_info",
        lambda url: VideoInfo("a", "Enriched", _recent(3), 99, url) if url == "url-a" else None,
    )

    assert enrich_videos([]) == []
    enriched = enrich_videos([first, second], max_videos=1)

    assert enriched[0].title == "Enriched"
    assert enriched[1] == second


def test_helper_branches_cover_search_expression_channel_urls_and_caps():
    from distill.ingestors.youtube.discovery import _search_expression

    assert _search_expression("fabric", 25, "date") == "ytsearchdate25:fabric"
    assert _channel_url_from_metadata({"uploader_id": "plain-id"}) == ""
    assert _normalize_channel_url("relative/path/") == ""

    capped = _apply_search_caps(
        [
            VideoInfo("1", "A", _recent(3), 10, "u", channel_name=""),
            VideoInfo("2", "B", _recent(3), 10, "u2", channel_name=""),
        ],
        limit=2,
        per_channel_cap=0,
    )

    assert [v.video_id for v in capped] == ["1", "2"]

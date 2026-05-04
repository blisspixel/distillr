"""Integration tests that hit real YouTube.

Run with: pytest -m integration tests/test_integration.py
"""

import pytest

from distill.ingestors.youtube.discovery import (
    VideoInfo,
    discover_videos,
    resolve_channel_name,
    search_videos,
)


@pytest.mark.integration
class TestDiscoverVideosReal:
    def test_discovers_from_real_channel(self):
        """discover_videos returns real VideoInfo objects from @YouTube."""
        videos = discover_videos(
            "https://www.youtube.com/@YouTube/videos",
            days=30,
            quiet=True,
        )
        # @YouTube posts regularly, should have at least 1 video in 30 days
        assert len(videos) >= 1
        assert all(isinstance(v, VideoInfo) for v in videos)

        # Verify fields are populated
        for v in videos:
            assert v.video_id
            assert v.title
            assert v.upload_date
            assert len(v.upload_date) == 8  # YYYYMMDD format

    def test_date_filtering_works(self):
        """Videos outside the lookback window are excluded."""
        # 1-day window should return fewer videos than 30-day window
        videos_1d = discover_videos(
            "https://www.youtube.com/@YouTube/videos",
            days=1,
            quiet=True,
        )
        videos_30d = discover_videos(
            "https://www.youtube.com/@YouTube/videos",
            days=30,
            quiet=True,
        )
        assert len(videos_30d) >= len(videos_1d)


@pytest.mark.integration
class TestResolveChannelNameReal:
    def test_at_url(self):
        name = resolve_channel_name("https://www.youtube.com/@YouTube")
        assert name == "YouTube"

    def test_at_url_with_path(self):
        name = resolve_channel_name("https://www.youtube.com/@YouTube/videos")
        assert name == "YouTube"


@pytest.mark.integration
class TestSearchVideosReal:
    def test_basic_search(self):
        videos = search_videos("python tutorial", days=30, limit=3)
        assert len(videos) >= 1
        assert all(isinstance(v, VideoInfo) for v in videos)

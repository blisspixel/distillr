"""Contract tests validating yt-dlp returns fields our code depends on.

Run with: pytest -m live_network tests/unit/ingestors/youtube/test_ytdlp_contract.py
"""

import pytest
import yt_dlp

pytestmark = pytest.mark.live_network


class TestChannelListingContract:
    """Verify yt-dlp channel tab extraction returns expected fields."""

    def test_extract_flat_false_returns_upload_date(self):
        """extract_flat=False must return upload_date — our date filter depends on it."""
        opts = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": False,
            "playlistend": 1,
            "ignoreerrors": True,
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info("https://www.youtube.com/@YouTube/videos", download=False)

        assert info is not None
        entries = list(info.get("entries", []))
        assert len(entries) >= 1

        entry = entries[0]
        # These are the fields _entry_to_video_info requires
        assert entry.get("id")
        assert entry.get("upload_date")
        assert "title" in entry
        assert "duration" in entry
        # At least one channel identifier should be present
        has_channel = any(entry.get(k) for k in ("channel", "uploader", "channel_id"))
        assert has_channel, f"No channel identifier in entry keys: {list(entry.keys())}"

    def test_extract_flat_in_playlist_lacks_upload_date(self):
        """extract_flat='in_playlist' does NOT return upload_date — documenting this."""
        opts = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": "in_playlist",
            "playlistend": 1,
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info("https://www.youtube.com/@YouTube/videos", download=False)

        entries = list(info.get("entries", []))
        assert len(entries) >= 1
        # Flat extraction should have id and title but NOT upload_date
        entry = entries[0]
        assert "id" in entry
        assert "title" in entry
        # upload_date is missing or None in flat mode — this is WHY we use extract_flat=False
        assert not entry.get("upload_date"), (
            "If yt-dlp now returns upload_date in flat mode, we can switch back to flat "
            "extraction for faster discovery!"
        )


class TestSingleVideoContract:
    """Verify single video extraction returns expected fields."""

    def test_known_video_fields(self):
        """'Me at the zoo' (jNQXAC9IVRw) — oldest YouTube video, stable target."""
        from distill.ingestors.youtube.discovery import get_video_info

        video = get_video_info("https://www.youtube.com/watch?v=jNQXAC9IVRw")

        assert video is not None
        assert video.video_id == "jNQXAC9IVRw"
        assert video.title  # should have a title
        assert video.upload_date == "20050424"
        assert video.duration > 0

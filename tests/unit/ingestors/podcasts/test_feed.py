"""Tests for distill.ingestors.podcasts.feed (RSS parsing + transcript ladder pieces)."""

from __future__ import annotations

import pytest

from distill.ingestors.net import NetworkError
from distill.ingestors.podcasts import feed as feed_mod
from distill.ingestors.podcasts import looks_like_feed_url, parse_feed


class _BytesResponse:
    def __init__(self, data: bytes):
        self._data = data

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self, size):
        return self._data


def _stub_urlopen(monkeypatch, data: bytes):
    def fake_urlopen(_request, timeout=60):
        return _BytesResponse(data)

    monkeypatch.setattr(feed_mod, "safe_urlopen", fake_urlopen)


class TestFetchErrorTranslation:
    def test_network_error_becomes_podcast_fetch_error(self, monkeypatch):
        """Regression: ``safe_urlopen`` wraps every failure in ``NetworkError``;
        ``fetch_feed`` must translate that into ``PodcastFetchError`` so a dead
        or rate-limited feed host degrades cleanly instead of raising a raw
        ``NetworkError`` past the CLI handler.
        """

        def boom(_request, timeout=60):
            raise NetworkError("HTTP 429 from feed: rate limited", status_code=429)

        monkeypatch.setattr(feed_mod, "safe_urlopen", boom)
        with pytest.raises(feed_mod.PodcastFetchError, match="Could not fetch feed"):
            feed_mod.fetch_feed("https://example.com/feed.xml")


_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"
     xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd"
     xmlns:podcast="https://podcastindex.org/namespace/1.0">
  <channel>
    <title>Research Pod</title>
    <link>https://example.com/pod</link>
    <description>A show about &lt;b&gt;research&lt;/b&gt; tooling.</description>
    <item>
      <title>Older episode</title>
      <guid>ep-1</guid>
      <pubDate>Mon, 02 Jun 2026 08:00:00 +0000</pubDate>
      <enclosure url="https://example.com/ep1.mp3" type="audio/mpeg" length="100"/>
      <itunes:duration>52:00</itunes:duration>
      <description>Old notes</description>
    </item>
    <item>
      <title>Newest episode</title>
      <guid>ep-2</guid>
      <pubDate>Tue, 10 Jun 2026 08:00:00 +0000</pubDate>
      <enclosure url="https://example.com/ep2.mp3" type="audio/mpeg" length="100"/>
      <itunes:duration>3120</itunes:duration>
      <podcast:transcript url="https://example.com/ep2.vtt" type="text/vtt"/>
      <description><![CDATA[Notes with <a href="x">markup</a> inside.]]></description>
    </item>
  </channel>
</rss>"""


class TestParseFeed:
    def test_parses_channel_and_episodes_newest_first(self):
        feed = parse_feed(_RSS)
        assert feed.title == "Research Pod"
        assert "research" in feed.description and "<b>" not in feed.description
        assert [e.guid for e in feed.episodes] == ["ep-2", "ep-1"]

    def test_episode_fields(self):
        ep = parse_feed(_RSS).episodes[0]
        assert ep.audio_url == "https://example.com/ep2.mp3"
        assert ep.duration_s == 3120
        assert ep.transcript_url == "https://example.com/ep2.vtt"
        assert ep.transcript_type == "text/vtt"
        assert "markup" in ep.description and "<a" not in ep.description

    def test_clock_duration_parsed(self):
        assert parse_feed(_RSS).episodes[1].duration_s == 52 * 60

    def test_not_rss_raises(self):
        with pytest.raises(feed_mod.PodcastFetchError, match="channel"):
            parse_feed("<html><body>nope</body></html>")
        with pytest.raises(feed_mod.PodcastFetchError, match="XML"):
            parse_feed("{json: true}")

    def test_non_episode_items_are_skipped(self):
        feed = parse_feed(
            """<rss><channel><title>Empty</title><item><description>not an episode</description></item></channel></rss>"""
        )

        assert feed.episodes == []

    def test_invalid_dates_and_durations_preserve_feed_order(self):
        feed = parse_feed(
            """<rss xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">
              <channel>
                <item>
                  <title>First in feed</title>
                  <guid>first</guid>
                  <pubDate>not a date</pubDate>
                  <enclosure url="https://example.com/first.mp3" type="audio/mpeg"/>
                  <itunes:duration></itunes:duration>
                </item>
                <item>
                  <title>Second in feed</title>
                  <guid>second</guid>
                  <enclosure url="https://example.com/second.mp3" type="audio/mpeg"/>
                  <itunes:duration>1:2:bad:4</itunes:duration>
                </item>
              </channel>
            </rss>"""
        )

        assert [ep.guid for ep in feed.episodes] == ["first", "second"]
        assert [ep.duration_s for ep in feed.episodes] == [0, 0]
        assert feed.episodes[0].published_dt() is None


class TestFetchSuccess:
    def test_fetch_feed_decodes_response(self, monkeypatch):
        _stub_urlopen(monkeypatch, _RSS.encode("utf-8"))

        feed = feed_mod.fetch_feed("https://example.com/feed.xml")

        assert feed.title == "Research Pod"
        assert [ep.guid for ep in feed.episodes] == ["ep-2", "ep-1"]

    def test_fetch_transcript_normalizes_vtt(self, monkeypatch):
        _stub_urlopen(
            monkeypatch,
            b"WEBVTT\n\n1\n00:00:01.000 --> 00:00:03.000\nhello\n\n",
        )

        transcript = feed_mod.fetch_transcript(
            "https://example.com/ep.vtt", transcript_type="text/vtt"
        )

        assert transcript == "hello"

    def test_fetch_transcript_strips_plain_text(self, monkeypatch):
        _stub_urlopen(monkeypatch, b"\n Plain transcript. \n")

        transcript = feed_mod.fetch_transcript("https://example.com/ep.txt")

        assert transcript == "Plain transcript."

    def test_fetch_transcript_size_cap_raises(self, monkeypatch):
        _stub_urlopen(monkeypatch, b"abcd")
        monkeypatch.setattr(feed_mod, "_MAX_TRANSCRIPT_BYTES", 3)

        with pytest.raises(feed_mod.PodcastFetchError, match="exceeds"):
            feed_mod.fetch_transcript("https://example.com/ep.txt")

    def test_download_audio_writes_file_with_default_suffix(self, monkeypatch, tmp_path):
        _stub_urlopen(monkeypatch, b"audio-bytes")

        path = feed_mod.download_audio("https://example.com/download", tmp_path / "audio")

        assert path.name == "episode.mp3"
        assert path.read_bytes() == b"audio-bytes"


class TestCaptionStripping:
    def test_vtt_cues_removed(self):
        vtt = "WEBVTT\n\n1\n00:00:01.000 --> 00:00:04.000\nHello there.\n\n2\n00:00:05.000 --> 00:00:08.000\nSecond line."
        out = feed_mod._strip_caption_cues(vtt)
        assert out == "Hello there.\nSecond line."

    def test_plain_text_untouched(self):
        assert feed_mod._strip_caption_cues("Just a transcript.") == "Just a transcript."


class TestFeedUrlHeuristic:
    @pytest.mark.parametrize(
        "url",
        [
            "https://example.com/show.rss",
            "https://example.com/podcast.xml",
            "https://example.com/show/feed",
            "https://feeds.example.com/feeds/show",
        ],
    )
    def test_feedish(self, url):
        assert looks_like_feed_url(url)

    @pytest.mark.parametrize(
        "url",
        ["https://example.com/article", "https://example.com/", "https://x.com/a/status/1"],
    )
    def test_not_feedish(self, url):
        assert not looks_like_feed_url(url)

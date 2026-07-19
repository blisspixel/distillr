"""Tests for distill.ingestors.podcasts.feed (RSS parsing + transcript ladder pieces)."""

from __future__ import annotations

import pytest

from distill.ingestors.net import NetworkError
from distill.ingestors.podcasts import (
    PodcastFetchError,
    feed_episode_identity,
    looks_like_feed_url,
    parse_feed,
    select_feed_episode,
)
from distill.ingestors.podcasts import feed as feed_mod


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

    def test_linkless_posts_receive_distinct_content_derived_identities(self):
        feed_url = "https://example.com/feed.xml"
        feed = parse_feed(
            """<rss xmlns:content="http://purl.org/rss/1.0/modules/content/"><channel>
              <item><title>First</title><pubDate>Tue, 10 Jun 2026 08:00:00 +0000</pubDate>
                <content:encoded><![CDATA[<p>First body</p>]]></content:encoded></item>
              <item><title>Second</title><pubDate>Mon, 09 Jun 2026 08:00:00 +0000</pubDate>
                <content:encoded><![CDATA[<p>Second body</p>]]></content:encoded></item>
            </channel></rss>"""
        )

        identities = [feed_episode_identity(feed_url, episode) for episode in feed.episodes]

        assert len(set(identities)) == 2
        assert select_feed_episode(feed_url, feed, identities[1]).episodes == [feed.episodes[1]]

    def test_exact_selector_rejects_duplicate_matches(self):
        feed_url = "https://example.com/feed.xml"
        feed = parse_feed(
            """<rss><channel>
              <item><title>First</title><guid>duplicate</guid></item>
              <item><title>Second</title><guid>duplicate</guid></item>
            </channel></rss>"""
        )
        episode_id = feed_episode_identity(feed_url, feed.episodes[0])

        with pytest.raises(PodcastFetchError, match="identity is ambiguous"):
            select_feed_episode(feed_url, feed, episode_id)

    def test_explicit_https_ports_are_preserved(self):
        feed = parse_feed(
            """<rss><channel><link>https://example.com:8443/show</link><item>
              <title>Portability</title><guid>port</guid>
              <link>https://example.com:8443/episodes/portability</link>
              <enclosure url="https://cdn.example.com:8443/episode.mp3" type="audio/mpeg"/>
            </item></channel></rss>"""
        )

        assert feed.link == "https://example.com:8443/show"
        assert feed.episodes[0].link == "https://example.com:8443/episodes/portability"
        assert feed.episodes[0].audio_url == "https://cdn.example.com:8443/episode.mp3"

    def test_zero_port_is_rejected(self):
        with pytest.raises(feed_mod.PodcastFetchError, match="valid HTTP URL"):
            parse_feed(
                """<rss><channel><item><title>Invalid</title>
                  <enclosure url="https://cdn.example.com:0/episode.mp3"/>
                </item></channel></rss>"""
            )

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

    def test_mixed_naive_and_aware_dates_sort_without_crashing(self):
        feed = parse_feed(
            """<rss><channel>
              <item><title>Aware</title><guid>aware</guid>
                <pubDate>Tue, 10 Jun 2026 08:00:00 +0000</pubDate></item>
              <item><title>Naive</title><guid>naive</guid>
                <pubDate>Wed, 11 Jun 2026 08:00:00</pubDate></item>
            </channel></rss>"""
        )

        assert [episode.guid for episode in feed.episodes] == ["naive", "aware"]
        assert all(episode.published_dt().tzinfo is not None for episode in feed.episodes)

    def test_overflowing_timezone_normalization_degrades_to_unknown(self):
        feed = parse_feed(
            """<rss><channel>
              <item><title>Overflow</title><guid>overflow</guid>
                <pubDate>Fri, 31 Dec 9999 23:59:59 -1400</pubDate></item>
              <item><title>Valid</title><guid>valid</guid>
                <pubDate>Tue, 10 Jun 2026 08:00:00 +0000</pubDate></item>
            </channel></rss>"""
        )

        assert [episode.guid for episode in feed.episodes] == ["valid", "overflow"]
        assert feed.episodes[1].published_dt() is None

    def test_oversized_duration_degrades_to_unknown(self):
        oversized = "9" * 5000
        feed = parse_feed(
            f"""<rss xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">
              <channel><item><title>Huge</title><guid>huge</guid>
                <itunes:duration>{oversized}</itunes:duration>
              </item></channel></rss>"""
        )

        assert feed.episodes[0].duration_s == 0

    @pytest.mark.parametrize(
        "duration",
        ["9" * 32, "9999999999999999999999999999:59"],
    )
    def test_large_within_length_duration_degrades_to_unknown(self, duration: str):
        feed = parse_feed(
            f"""<rss xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">
              <channel><item><title>Huge</title><guid>huge</guid>
                <itunes:duration>{duration}</itunes:duration>
              </item></channel></rss>"""
        )

        assert feed.episodes[0].duration_s == 0

    def test_episode_count_cap_stops_large_feeds(self, monkeypatch):
        monkeypatch.setattr(feed_mod, "_MAX_FEED_EPISODES", 2)
        items = "".join(
            f"<item><title>Episode {index}</title><guid>{index}</guid></item>" for index in range(3)
        )

        with pytest.raises(feed_mod.PodcastFetchError, match="2-record cap"):
            parse_feed(f"<rss><channel>{items}</channel></rss>")

    def test_xml_node_cap_stops_deep_feeds(self, monkeypatch):
        monkeypatch.setattr(feed_mod, "_MAX_FEED_XML_NODES", 4)

        with pytest.raises(feed_mod.PodcastFetchError, match="4-node cap"):
            parse_feed(
                "<rss><channel><item><title>Too deep</title><guid>5</guid></item></channel></rss>"
            )

    @pytest.mark.parametrize(
        ("element", "message"),
        [
            ("<title>" + "t" * 1_001 + "</title>", "episode title"),
            ("<guid>" + "g" * 4_097 + "</guid>", "episode GUID"),
            ("<link>https://example.com/" + "p" * 2_030 + "</link>", "episode link"),
        ],
    )
    def test_oversized_episode_fields_fail_closed(self, element: str, message: str):
        item_content = (
            element if element.startswith("<title>") else f"<title>Episode</title>{element}"
        )
        with pytest.raises(feed_mod.PodcastFetchError, match=message):
            parse_feed(f"<rss><channel><item>{item_content}</item></channel></rss>")

    def test_episode_guid_uses_shared_utf8_source_id_limit(self, monkeypatch):
        exact = "\U0001f600" * 4_096
        accepted = parse_feed(
            f"<rss><channel><item><title>Exact</title><guid>{exact}</guid></item></channel></rss>"
        )
        assert accepted.episodes[0].guid == exact

        monkeypatch.setattr(feed_mod, "_MAX_GUID_CHARS", 4_097)
        oversized = exact + "\U0001f600"
        with pytest.raises(feed_mod.PodcastFetchError, match="16,384-byte source-id limit"):
            parse_feed(
                "<rss><channel><item><title>Over</title>"
                f"<guid>{oversized}</guid></item></channel></rss>"
            )

    @pytest.mark.parametrize(
        "raw_duration",
        ["\u00b2", "1:\u00b2:03", "\u0661\u0662", "1:\u0661\u0662:03"],
    )
    def test_non_ascii_duration_digits_degrade_to_unknown(self, raw_duration: str):
        feed = parse_feed(
            f"""<rss xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">
              <channel><item><title>Unicode</title><guid>unicode</guid>
                <itunes:duration>{raw_duration}</itunes:duration>
              </item></channel></rss>"""
        )

        assert feed.episodes[0].duration_s == 0


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

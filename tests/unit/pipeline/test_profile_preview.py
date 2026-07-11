from __future__ import annotations

import shlex

import pytest

from distill.ingestors.podcasts.feed import PodcastEpisode, PodcastFeed
from distill.ingestors.youtube.discovery import VideoInfo
from distill.library.profiles import ResearchProfile
from distill.pipeline import profile_preview as _profile_preview
from distill.pipeline.profile_preview import build_profile_preview, command_text


def _profile(payload: dict) -> ResearchProfile:
    base = {
        "schema_version": "research-profile.v1",
        "name": "agent-loops",
        "topic": "agent-loops",
        "goal_file": "goals/agent-loops.md",
        "cost_mode": "no-metered",
        "limits": {"max_new_items": 3, "max_metered_usd": 0},
    }
    base.update(payload)
    return ResearchProfile.model_validate(base)


class _TextResponse:
    def __init__(self, body: bytes):
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _traceback):
        return False

    def read(self, _limit: int) -> bytes:
        return self._body


def _episode(
    title: str,
    guid: str,
    published: str,
    *,
    link: str = "",
    audio_url: str = "",
    audio_type: str = "",
    duration_s: int = 0,
) -> PodcastEpisode:
    return PodcastEpisode(
        title=title,
        guid=guid,
        published=published,
        audio_url=audio_url,
        audio_type=audio_type,
        duration_s=duration_s,
        description="",
        link=link,
    )


def test_profile_preview_expands_feed_items_and_source_seeds():
    profile = _profile(
        {
            "sources": {
                "feeds": [{"url": "https://example.com/feed.xml", "label": "Example Feed"}],
                "domains": ["docs.example.com"],
                "repositories": ["owner/repo"],
            },
            "queries": ["long running agent loops"],
        }
    )

    def fake_feed_fetcher(url: str) -> PodcastFeed:
        assert url == "https://example.com/feed.xml"
        return PodcastFeed(
            title="Example",
            link="https://example.com",
            description="",
            episodes=[
                _episode(
                    "Older post",
                    "old",
                    "Thu, 18 Jun 2026 10:00:00 GMT",
                    link="https://example.com/old",
                ),
                _episode(
                    "Newer post",
                    "new",
                    "Fri, 19 Jun 2026 10:00:00 GMT",
                    link="https://example.com/new",
                ),
            ],
        )

    result = build_profile_preview(profile, feed_fetcher=fake_feed_fetcher)

    assert [candidate.title for candidate in result.candidates[:2]] == [
        "Newer post",
        "Older post",
    ]
    kinds = {candidate.kind for candidate in result.candidates}
    assert {"domain", "repository", "query"}.issubset(kinds)
    query = next(candidate for candidate in result.candidates if candidate.kind == "query")
    newest = result.candidates[0]
    assert newest.command == [
        "distill",
        "--cost-mode",
        "no-metered",
        "site",
        "https://example.com/new",
        "--topic",
        "agent-loops",
        "--seed-only",
    ]
    assert query.command == [
        "distill",
        "--cost-mode",
        "no-metered",
        "latest",
        "long running agent loops",
        "--topic",
        "agent-loops",
        "--preview",
    ]
    assert result.to_dict()["fresh_item_count"] == 2
    assert [candidate.order for candidate in result.candidates] == list(
        range(len(result.candidates))
    )


def test_profile_preview_uses_youtube_atom_for_channel_id():
    profile = _profile(
        {
            "sources": {
                "youtube_channels": [
                    {
                        "channel_id": "UCabc123",
                        "label": "Example Channel",
                    }
                ]
            }
        }
    )
    atom = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:yt="http://www.youtube.com/xml/schemas/2015">
  <entry>
    <yt:videoId>video123</yt:videoId>
    <title>Loop demo</title>
    <link rel="alternate" href="https://www.youtube.com/watch?v=video123"/>
    <published>2026-06-19T12:00:00+00:00</published>
  </entry>
</feed>"""

    result = build_profile_preview(profile, text_fetcher=lambda _url: atom)

    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.kind == "youtube_video"
    assert candidate.title == "Loop demo"
    assert candidate.command == [
        "distill",
        "--cost-mode",
        "no-metered",
        "video",
        "https://www.youtube.com/watch?v=video123",
        "--topic",
        "agent-loops",
    ]


def test_profile_preview_uses_discovery_for_youtube_handle():
    profile = _profile(
        {
            "sources": {
                "youtube_channels": [{"handle": "@Example", "label": "Example"}],
            },
            "freshness": {"cadence": "daily", "stale_after": "PT12H"},
        }
    )
    calls: list[dict] = []

    def fake_discoverer(channel_url: str, **kwargs):
        calls.append({"channel_url": channel_url, **kwargs})
        return [
            VideoInfo(
                "v1",
                "Fresh video",
                "20260619",
                600,
                "https://youtube.com/watch?v=v1",
                "Example",
                published_at="2026-06-19T01:00:00+00:00",
            )
        ]

    result = build_profile_preview(profile, youtube_discoverer=fake_discoverer)

    assert calls == [
        {
            "channel_url": "https://www.youtube.com/@Example",
            "days": 1,
            "include_shorts": False,
            "quiet": True,
        }
    ]
    assert result.candidates[0].kind == "youtube_video"
    assert result.candidates[0].source_label == "Example"


def test_profile_preview_sorts_youtube_compact_dates_with_feed_dates():
    profile = _profile(
        {
            "sources": {
                "youtube_channels": [{"handle": "@Example", "label": "Example"}],
                "feeds": ["https://example.com/feed.xml"],
            },
            "limits": {"max_new_items": 5, "max_metered_usd": 0},
        }
    )

    def fake_discoverer(_channel_url: str, **_kwargs):
        return [
            VideoInfo(
                "v1",
                "Newer YouTube video",
                "20260619",
                600,
                "https://youtube.com/watch?v=v1",
                "Example",
            )
        ]

    def fake_feed_fetcher(_url: str) -> PodcastFeed:
        return PodcastFeed(
            title="Example",
            link="https://example.com",
            description="",
            episodes=[
                _episode(
                    "Older feed post",
                    "old",
                    "Thu, 18 Jun 2026 10:00:00 GMT",
                    link="https://example.com/old",
                )
            ],
        )

    result = build_profile_preview(
        profile,
        youtube_discoverer=fake_discoverer,
        feed_fetcher=fake_feed_fetcher,
    )

    assert [candidate.title for candidate in result.candidates[:2]] == [
        "Newer YouTube video",
        "Older feed post",
    ]


def test_profile_preview_falls_back_to_seed_when_fetch_fails():
    profile = _profile(
        {
            "sources": {
                "feeds": [{"url": "https://example.com/feed.xml"}],
            }
        }
    )

    def failing_feed_fetcher(_url: str) -> PodcastFeed:
        raise RuntimeError("network unavailable")

    result = build_profile_preview(profile, feed_fetcher=failing_feed_fetcher)

    assert result.warnings[0].message == "network unavailable"
    assert result.candidates[0].kind == "feed"
    assert result.candidates[0].command == [
        "distill",
        "--cost-mode",
        "no-metered",
        "ingest",
        "https://example.com/feed.xml",
        "--topic",
        "agent-loops",
        "--rss",
    ]


def test_profile_preview_no_fetch_emits_source_seeds():
    profile = _profile(
        {
            "sources": {
                "youtube_channels": [{"handle": "@Example"}],
                "feeds": ["https://example.com/feed.xml"],
            }
        }
    )

    result = build_profile_preview(profile, fetch_sources=False)

    assert [candidate.kind for candidate in result.candidates] == ["youtube_channel", "feed"]
    assert result.warnings == []


def test_profile_preview_auto_cost_mode_keeps_commands_short():
    profile = _profile(
        {
            "cost_mode": "auto",
            "limits": {"max_new_items": 3, "max_metered_usd": 0},
            "queries": ["agent loops"],
        }
    )

    result = build_profile_preview(profile, fetch_sources=False)

    assert result.candidates[0].command == [
        "distill",
        "latest",
        "agent loops",
        "--topic",
        "agent-loops",
        "--preview",
    ]


def test_profile_preview_rejects_negative_limit():
    profile = _profile({"queries": ["agent loops"]})

    with pytest.raises(ValueError, match="fresh_item_limit must be at least 1"):
        build_profile_preview(profile, fresh_item_limit=-1, fetch_sources=False)


def test_profile_preview_warning_dict_and_youtube_seed_when_atom_unreadable():
    profile = _profile({"sources": {"youtube_channels": [{"channel_id": "UCabc123"}]}})

    def failing_text_fetcher(_url: str) -> str:
        raise RuntimeError("feed unavailable")

    result = build_profile_preview(profile, text_fetcher=failing_text_fetcher)

    assert result.candidates[0].kind == "youtube_channel"
    assert result.candidates[0].url == "https://www.youtube.com/channel/UCabc123"
    assert result.to_dict()["warnings"] == [{"source": "UCabc123", "message": "feed unavailable"}]


def test_profile_preview_handles_feed_items_without_page_and_dedupes():
    profile = _profile({"sources": {"feeds": ["https://example.com/feed.xml"]}})

    def fake_feed_fetcher(_url: str) -> PodcastFeed:
        return PodcastFeed(
            title="Example",
            link="https://example.com",
            description="",
            episodes=[
                _episode(
                    "Audio only",
                    "same",
                    "Fri, 19 Jun 2026 10:00:00 GMT",
                    audio_url="https://cdn.example.com/audio.mp3",
                    audio_type="audio/mpeg",
                    duration_s=600,
                ),
                _episode(
                    "Duplicate audio",
                    "same",
                    "Fri, 20 Jun 2026 10:00:00 GMT",
                    audio_url="https://cdn.example.com/duplicate.mp3",
                    audio_type="audio/mpeg",
                    duration_s=600,
                ),
            ],
        )

    result = build_profile_preview(profile, feed_fetcher=fake_feed_fetcher)

    feed_items = [candidate for candidate in result.candidates if candidate.kind == "feed_item"]
    assert len(feed_items) == 1
    assert feed_items[0].title == "Audio only"
    assert feed_items[0].command == [
        "distill",
        "--cost-mode",
        "no-metered",
        "ingest",
        "https://example.com/feed.xml",
        "--topic",
        "agent-loops",
        "--rss",
        "--episodes",
        "1",
    ]
    assert feed_items[0].note.startswith("Feed item without a page link")


def test_profile_preview_youtube_atom_fallbacks_and_skips_unusable_entries():
    profile = _profile({"sources": {"youtube_channels": [{"channel_id": "UCabc123"}]}})
    atom = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:yt="http://www.youtube.com/xml/schemas/2015">
  <entry>
    <yt:videoId>fallback123</yt:videoId>
    <published>2026-06-19T12:00:00+00:00</published>
  </entry>
  <entry>
    <title>No usable URL</title>
  </entry>
</feed>"""

    result = build_profile_preview(profile, text_fetcher=lambda _url: atom)

    assert len(result.candidates) == 1
    assert result.candidates[0].title == "fallback123"
    assert result.candidates[0].url == "https://www.youtube.com/watch?v=fallback123"


def test_profile_preview_orders_unknown_and_naive_dates_after_dated_items():
    profile = _profile(
        {
            "sources": {"feeds": ["https://example.com/feed.xml"]},
            "limits": {"max_new_items": 5, "max_metered_usd": 0},
        }
    )

    def fake_feed_fetcher(_url: str) -> PodcastFeed:
        return PodcastFeed(
            title="Example",
            link="https://example.com",
            description="",
            episodes=[
                _episode(
                    "Missing date",
                    "missing",
                    "",
                    link="https://example.com/missing",
                ),
                _episode(
                    "Bad date",
                    "bad",
                    "not-a-date",
                    link="https://example.com/bad",
                ),
                _episode(
                    "Naive date",
                    "naive",
                    "2026-06-20T10:00:00",
                    link="https://example.com/naive",
                ),
            ],
        )

    result = build_profile_preview(profile, feed_fetcher=fake_feed_fetcher)

    assert [candidate.title for candidate in result.candidates] == [
        "Naive date",
        "Missing date",
        "Bad date",
    ]


def test_profile_preview_channel_url_seeds():
    profile = _profile(
        {
            "sources": {
                "youtube_channels": [
                    {"url": "https://www.youtube.com/@ByUrl"},
                    {"channel_id": "UCseed"},
                ]
            }
        }
    )

    result = build_profile_preview(profile, fetch_sources=False)

    assert [candidate.url for candidate in result.candidates] == [
        "https://www.youtube.com/@ByUrl",
        "https://www.youtube.com/channel/UCseed",
    ]


def test_command_text_powershell_quotes_shell_metacharacters_and_preserves_argv(monkeypatch):
    argv = [
        "distill",
        "latest",
        "",
        'quoted "value"',
        "$budget",
        "`tick",
        "https://example.test/feed?a=1&b=2",
        "semi;colon",
        "[brackets]",
        "O'Brien",
        "plain",
    ]
    original = list(argv)
    monkeypatch.setattr(_profile_preview, "_is_windows", lambda: True)

    rendered = command_text(argv)

    assert rendered == (
        "distill latest '' 'quoted \"value\"' '$budget' '`tick' "
        "'https://example.test/feed?a=1&b=2' 'semi;colon' '[brackets]' "
        "'O''Brien' plain"
    )
    assert argv == original
    assert command_text([r"C:\Program Files\distill.exe", "plain"]) == (
        r"& 'C:\Program Files\distill.exe' plain"
    )


def test_command_text_posix_uses_shell_safe_join_and_preserves_argv(monkeypatch):
    argv = [
        "distill",
        "latest",
        'quoted "value" with $budget and `tick',
        "https://example.test/feed?a=1&b=2",
        "semi;colon",
        "[brackets]",
    ]
    original = list(argv)
    monkeypatch.setattr(_profile_preview, "_is_windows", lambda: False)

    assert command_text(argv) == shlex.join(argv)
    assert argv == original


def test_profile_preview_default_text_fetcher_decodes_atom(monkeypatch):
    profile = _profile({"sources": {"youtube_channels": [{"channel_id": "UCabc123"}]}})
    atom = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:yt="http://www.youtube.com/xml/schemas/2015">
  <entry>
    <yt:videoId>video123</yt:videoId>
    <title>Fetched atom</title>
    <published>2026-06-19T12:00:00+00:00</published>
  </entry>
</feed>"""

    def safe_urlopen(_request, *, timeout: int):
        assert timeout == 30
        return _TextResponse(atom.encode("utf-8"))

    monkeypatch.setattr("distill.pipeline.profile_preview.safe_urlopen", safe_urlopen)

    result = build_profile_preview(profile)

    assert result.candidates[0].title == "Fetched atom"
    assert result.candidates[0].url == "https://www.youtube.com/watch?v=video123"


def test_profile_preview_default_text_fetcher_caps_large_feeds(monkeypatch):
    profile = _profile({"sources": {"youtube_channels": [{"channel_id": "UCabc123"}]}})

    def safe_urlopen(_request, *, timeout: int):
        assert timeout == 30
        return _TextResponse(b"too-large")

    monkeypatch.setattr("distill.pipeline.profile_preview._MAX_FEED_BYTES", 4)
    monkeypatch.setattr("distill.pipeline.profile_preview.safe_urlopen", safe_urlopen)

    result = build_profile_preview(profile)

    assert result.candidates[0].kind == "youtube_channel"
    assert "exceeds the 4-byte cap" in result.warnings[0].message


def test_profile_preview_default_text_fetcher_reports_open_errors(monkeypatch):
    profile = _profile({"sources": {"youtube_channels": [{"channel_id": "UCabc123"}]}})

    def safe_urlopen(_request, *, timeout: int):
        assert timeout == 30
        raise OSError("network unavailable")

    monkeypatch.setattr("distill.pipeline.profile_preview.safe_urlopen", safe_urlopen)

    result = build_profile_preview(profile)

    assert result.candidates[0].kind == "youtube_channel"
    assert "Could not fetch" in result.warnings[0].message


def test_profile_preview_invalid_youtube_atom_becomes_warning():
    profile = _profile({"sources": {"youtube_channels": [{"channel_id": "UCabc123"}]}})

    result = build_profile_preview(profile, text_fetcher=lambda _url: "<feed")

    assert result.candidates[0].kind == "youtube_channel"
    assert "YouTube feed is not parseable XML" in result.warnings[0].message


def test_profile_preview_invalid_stale_after_defaults_to_week():
    profile = _profile({"sources": {"youtube_channels": [{"handle": "@Example"}]}})
    profile = profile.model_copy(
        update={"freshness": profile.freshness.model_copy(update={"stale_after": "invalid"})}
    )
    calls: list[dict] = []

    def fake_discoverer(channel_url: str, **kwargs):
        calls.append({"channel_url": channel_url, **kwargs})
        return []

    result = build_profile_preview(profile, youtube_discoverer=fake_discoverer)

    assert calls[0]["days"] == 7
    assert result.candidates[0].kind == "youtube_channel"

from __future__ import annotations

from distill.ingestors.podcasts.feed import PodcastEpisode, PodcastFeed
from distill.ingestors.youtube.discovery import VideoInfo
from distill.library.profiles import ResearchProfile
from distill.pipeline.profile_preview import build_profile_preview


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
                PodcastEpisode(
                    title="Older post",
                    guid="old",
                    published="Thu, 18 Jun 2026 10:00:00 GMT",
                    audio_url="",
                    audio_type="",
                    duration_s=0,
                    description="",
                    link="https://example.com/old",
                ),
                PodcastEpisode(
                    title="Newer post",
                    guid="new",
                    published="Fri, 19 Jun 2026 10:00:00 GMT",
                    audio_url="",
                    audio_type="",
                    duration_s=0,
                    description="",
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
        "site",
        "https://example.com/new",
        "--topic",
        "agent-loops",
        "--seed-only",
    ]
    assert query.command == [
        "distill",
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
                PodcastEpisode(
                    title="Older feed post",
                    guid="old",
                    published="Thu, 18 Jun 2026 10:00:00 GMT",
                    audio_url="",
                    audio_type="",
                    duration_s=0,
                    description="",
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

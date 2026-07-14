from __future__ import annotations

import email.utils
import json
import shlex
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

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


def _fresh_iso() -> str:
    return datetime.now(UTC).isoformat()


def _recent_iso(*, minutes_ago: int) -> str:
    return (datetime.now(UTC) - timedelta(minutes=minutes_ago)).isoformat()


def _recent_rfc(*, minutes_ago: int) -> str:
    return email.utils.format_datetime(
        datetime.now(UTC) - timedelta(minutes=minutes_ago),
        usegmt=True,
    )


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
    content_html: str = "",
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
        content_html=content_html,
    )


def _stub_youtube_discovery(monkeypatch, extraction_result: object) -> MagicMock:
    mock_ydl = MagicMock()
    mock_ydl.extract_info.return_value = extraction_result
    mock_context = MagicMock()
    mock_context.__enter__.return_value = mock_ydl
    mock_context.__exit__.return_value = False
    youtube_dl = MagicMock(return_value=mock_context)
    monkeypatch.setattr("distill.ingestors.youtube.discovery.SafeYoutubeDL", youtube_dl)
    return youtube_dl


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
                    _recent_rfc(minutes_ago=20),
                    link="https://example.com/old",
                ),
                _episode(
                    "Newer post",
                    "new",
                    _recent_rfc(minutes_ago=10),
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


def test_profile_preview_rejects_overflowing_feed_date():
    profile = _profile({"sources": {"feeds": ["https://example.com/feed.xml"]}})

    def fake_feed_fetcher(_url: str) -> PodcastFeed:
        return PodcastFeed(
            title="Example",
            link="https://example.com",
            description="",
            episodes=[
                _episode(
                    "Overflowing date",
                    "overflow",
                    "Fri, 31 Dec 9999 23:59:59 -1400",
                    link="https://example.com/overflow",
                ),
                _episode(
                    "Valid date",
                    "valid",
                    _recent_rfc(minutes_ago=10),
                    link="https://example.com/valid",
                ),
            ],
        )

    result = build_profile_preview(profile, feed_fetcher=fake_feed_fetcher)

    assert [candidate.title for candidate in result.candidates] == ["Valid date"]


def test_profile_preview_filters_and_orders_feed_before_item_cap() -> None:
    profile = _profile(
        {
            "sources": {"feeds": ["https://example.com/feed.xml"]},
            "freshness": {"stale_after": "PT1H"},
            "limits": {"max_new_items": 1, "max_metered_usd": 0},
        }
    )

    def fake_feed_fetcher(_url: str) -> PodcastFeed:
        return PodcastFeed(
            title="Example",
            link="https://example.com",
            description="",
            episodes=[
                _episode(
                    "Stale first",
                    "stale",
                    _recent_rfc(minutes_ago=120),
                    link="https://example.com/stale",
                ),
                _episode(
                    "Missing date",
                    "missing",
                    "",
                    link="https://example.com/missing",
                ),
                _episode(
                    "Fresh later",
                    "fresh",
                    _recent_rfc(minutes_ago=10),
                    link="https://example.com/fresh",
                ),
            ],
        )

    result = build_profile_preview(profile, feed_fetcher=fake_feed_fetcher)

    assert [candidate.title for candidate in result.candidates] == ["Fresh later"]


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
    atom = f"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:yt="http://www.youtube.com/xml/schemas/2015">
  <entry>
    <yt:videoId>video123</yt:videoId>
    <title>Loop demo</title>
    <link rel="alternate" href="https://www.youtube.com/watch?v=video123"/>
    <published>{_fresh_iso()}</published>
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


def test_profile_preview_atom_entry_cap_becomes_warning_and_seed(monkeypatch):
    profile = _profile({"sources": {"youtube_channels": [{"channel_id": "UCabc123"}]}})
    monkeypatch.setattr(_profile_preview, "_MAX_ATOM_ENTRIES", 1)
    published = _fresh_iso()
    atom = f"""<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:yt="http://www.youtube.com/xml/schemas/2015">
      <entry><yt:videoId>first123</yt:videoId><title>First</title>
        <published>{published}</published></entry>
      <entry><yt:videoId>second123</yt:videoId><title>Second</title>
        <published>{published}</published></entry>
    </feed>"""

    result = build_profile_preview(profile, text_fetcher=lambda _url: atom)

    assert [candidate.kind for candidate in result.candidates] == ["youtube_channel"]
    assert "1-record cap" in result.warnings[0].message


def test_profile_preview_filters_atom_freshness_and_rejects_untrusted_video_ids():
    profile = _profile(
        {
            "sources": {"youtube_channels": [{"channel_id": "UCabc123"}]},
            "freshness": {"stale_after": "PT1H"},
            "limits": {"max_new_items": 1, "max_metered_usd": 0},
        }
    )
    fresh = (datetime.now(UTC) - timedelta(minutes=30)).isoformat()
    stale = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
    atom = f"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:yt="http://www.youtube.com/xml/schemas/2015">
  <entry>
    <yt:videoId>stale123</yt:videoId>
    <title>Stale</title>
    <published>{stale}</published>
  </entry>
  <entry>
    <yt:videoId>missing123</yt:videoId>
    <title>Missing date</title>
  </entry>
  <entry>
    <yt:videoId>bad&amp;list=private</yt:videoId>
    <title>Untrusted link</title>
    <link href="https://evil.example/private"/>
    <published>{fresh}</published>
  </entry>
  <entry>
    <yt:videoId>fresh123</yt:videoId>
    <title>Fresh</title>
    <published>{fresh}</published>
  </entry>
</feed>"""

    result = build_profile_preview(profile, text_fetcher=lambda _url: atom)

    assert [candidate.title for candidate in result.candidates] == ["Fresh"]
    assert result.candidates[0].url == "https://www.youtube.com/watch?v=fresh123"


def test_profile_preview_does_not_turn_all_stale_atom_rows_into_seed_work() -> None:
    profile = _profile(
        {
            "sources": {"youtube_channels": [{"channel_id": "UCabc123"}]},
            "freshness": {"stale_after": "PT1H"},
        }
    )
    stale = _recent_iso(minutes_ago=120)
    atom = f"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:yt="http://www.youtube.com/xml/schemas/2015">
  <entry>
    <yt:videoId>stale123</yt:videoId>
    <title>Stale</title>
    <published>{stale}</published>
  </entry>
</feed>"""

    result = build_profile_preview(profile, text_fetcher=lambda _url: atom)

    assert result.candidates == []


def test_profile_preview_does_not_turn_all_stale_feed_rows_into_seed_work() -> None:
    profile = _profile(
        {
            "sources": {"feeds": ["https://example.com/feed.xml"]},
            "freshness": {"stale_after": "PT1H"},
        }
    )

    def fake_feed_fetcher(_url: str) -> PodcastFeed:
        return PodcastFeed(
            title="Example",
            link="https://example.com",
            description="",
            episodes=[
                _episode(
                    "Stale",
                    "stale",
                    _recent_rfc(minutes_ago=120),
                    link="https://example.com/stale",
                )
            ],
        )

    result = build_profile_preview(profile, feed_fetcher=fake_feed_fetcher)

    assert result.candidates == []


def test_profile_preview_rejects_future_dated_atom_and_feed_rows() -> None:
    profile = _profile(
        {
            "sources": {
                "youtube_channels": [{"channel_id": "UCabc123"}],
                "feeds": ["https://example.com/feed.xml"],
            }
        }
    )
    atom = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:yt="http://www.youtube.com/xml/schemas/2015">
  <entry>
    <yt:videoId>future123</yt:videoId>
    <title>Future video</title>
    <published>9999-12-31T23:59:59Z</published>
  </entry>
</feed>"""

    def fake_feed_fetcher(_url: str) -> PodcastFeed:
        return PodcastFeed(
            title="Example",
            link="https://example.com",
            description="",
            episodes=[
                _episode(
                    "Future feed item",
                    "future",
                    "9999-12-31T23:59:59Z",
                    link="https://example.com/future",
                )
            ],
        )

    result = build_profile_preview(
        profile,
        text_fetcher=lambda _url: atom,
        feed_fetcher=fake_feed_fetcher,
    )

    assert result.candidates == []


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
                published_at=_fresh_iso(),
            )
        ]

    result = build_profile_preview(profile, youtube_discoverer=fake_discoverer)

    assert calls == [
        {
            "channel_url": "https://www.youtube.com/@Example",
            "days": 1,
            "hours": 12,
            "include_shorts": False,
            "quiet": True,
            "raise_on_error": True,
        }
    ]
    assert result.candidates[0].kind == "youtube_video"
    assert result.candidates[0].source_label == "Example"


def test_profile_preview_preserves_maximum_freshness_window_for_discovery():
    profile = _profile(
        {
            "sources": {"youtube_channels": [{"url": "https://youtube.com/@Example"}]},
            "freshness": {"stale_after": "P3650D"},
        }
    )
    calls: list[dict] = []

    def fake_discoverer(channel_url: str, **kwargs):
        calls.append({"channel_url": channel_url, **kwargs})
        return []

    build_profile_preview(profile, youtube_discoverer=fake_discoverer)

    assert calls[0]["days"] == 3_650
    assert calls[0]["hours"] is None


def test_profile_preview_applies_fresh_item_cap_after_fetching_all_sources():
    profile = _profile(
        {
            "sources": {
                "youtube_channels": [{"handle": "@One"}, {"handle": "@Two"}],
                "feeds": ["https://example.com/feed.xml"],
            },
            "limits": {"max_new_items": 1, "max_metered_usd": 0},
        }
    )
    youtube_calls: list[str] = []
    feed_calls: list[str] = []

    def fake_discoverer(channel_url: str, **_kwargs):
        youtube_calls.append(channel_url)
        minutes_ago = 3 if channel_url.endswith("@One") else 2
        return [
            VideoInfo(
                f"fresh{minutes_ago}",
                f"Fresh {minutes_ago}",
                datetime.now(UTC).strftime("%Y%m%d"),
                60,
                f"https://youtube.com/watch?v=fresh{minutes_ago}",
                published_at=_recent_iso(minutes_ago=minutes_ago),
            )
        ]

    def fake_feed_fetcher(url: str) -> PodcastFeed:
        feed_calls.append(url)
        return PodcastFeed(
            title="Feed",
            link="https://example.com",
            description="",
            episodes=[
                _episode(
                    "Fresh feed item",
                    "feed-fresh",
                    _recent_rfc(minutes_ago=1),
                    link="https://example.com/fresh",
                )
            ],
        )

    result = build_profile_preview(
        profile,
        youtube_discoverer=fake_discoverer,
        feed_fetcher=fake_feed_fetcher,
    )

    assert youtube_calls == ["https://www.youtube.com/@One", "https://www.youtube.com/@Two"]
    assert feed_calls == ["https://example.com/feed.xml"]
    assert [candidate.title for candidate in result.candidates] == ["Fresh feed item"]


def test_profile_preview_breaks_cross_source_timestamp_ties_by_declaration_order() -> None:
    profile = _profile(
        {
            "sources": {"youtube_channels": [{"handle": "@One"}, {"handle": "@Two"}]},
            "freshness": {"stale_after": "P1D"},
            "limits": {"max_new_items": 1, "max_metered_usd": 0},
        }
    )
    tied_timestamp = _recent_iso(minutes_ago=1)

    def fake_discoverer(channel_url: str, **_kwargs):
        if channel_url.endswith("@One"):
            return [
                VideoInfo(
                    "stale",
                    "Stale first",
                    (datetime.now(UTC) - timedelta(days=2)).strftime("%Y%m%d"),
                    60,
                    "https://youtube.com/watch?v=stale",
                    published_at=(datetime.now(UTC) - timedelta(days=2)).isoformat(),
                ),
                VideoInfo(
                    "first",
                    "First source",
                    datetime.now(UTC).strftime("%Y%m%d"),
                    60,
                    "https://youtube.com/watch?v=first",
                    published_at=tied_timestamp,
                ),
            ]
        return [
            VideoInfo(
                "second",
                "Second source",
                datetime.now(UTC).strftime("%Y%m%d"),
                60,
                "https://youtube.com/watch?v=second",
                published_at=tied_timestamp,
            )
        ]

    result = build_profile_preview(profile, youtube_discoverer=fake_discoverer)

    assert [candidate.title for candidate in result.candidates] == ["First source"]


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
                datetime.now(UTC).strftime("%Y%m%d"),
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
                    _recent_rfc(minutes_ago=1_440),
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


@pytest.mark.parametrize("limit", [0, True, 1_001])
def test_profile_preview_rejects_invalid_direct_limit(limit: int) -> None:
    profile = _profile({"queries": ["agent loops"]})

    with pytest.raises(ValueError, match="fresh_item_limit"):
        build_profile_preview(profile, fresh_item_limit=limit, fetch_sources=False)


def test_profile_preview_static_plan_is_bounded_by_declaration_cap() -> None:
    profile = _profile(
        {
            "queries": [f"query {index}" for index in range(100)],
            "limits": {"max_new_items": 1, "max_metered_usd": 0},
        }
    )

    result = build_profile_preview(profile, fetch_sources=False)

    assert len(result.candidates) == 100
    assert all(candidate.kind == "query" for candidate in result.candidates)


def test_fresh_candidate_top_k_has_bounded_internal_retention(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item_cap = 3
    peak_heap = 0
    peak_selected = 0
    original_remove = _profile_preview._remove_oldest_selected

    def observed_remove(heap, selected):
        nonlocal peak_heap, peak_selected
        peak_heap = max(peak_heap, len(heap))
        peak_selected = max(peak_selected, len(selected))
        original_remove(heap, selected)

    monkeypatch.setattr(_profile_preview, "_remove_oldest_selected", observed_remove)
    base = datetime.now(UTC) - timedelta(hours=3)

    def candidates():
        for index in range(10_000):
            yield _profile_preview.ProfilePreviewCandidate(
                kind="feed_item",
                title=f"Item {index}",
                url=f"https://example.com/{index}",
                source="https://example.com/feed.xml",
                source_label="Example",
                published_at=(base + timedelta(seconds=index)).isoformat(),
                identity=f"item:{index}",
                command=["distill", "site", f"https://example.com/{index}"],
                order=index,
            )

    selected = _profile_preview._fresh_candidates(
        candidates(),
        cutoff=base - timedelta(seconds=1),
        freshness_ceiling=base + timedelta(hours=4),
        item_cap=item_cap,
    )

    assert [candidate.title for candidate in selected] == [
        "Item 9999",
        "Item 9998",
        "Item 9997",
    ]
    assert peak_selected <= item_cap + 1
    assert peak_heap <= item_cap * 2 + 1


def test_fresh_candidates_use_calendar_day_policy_only_for_date_only_values() -> None:
    cutoff = datetime(2026, 7, 6, 15, tzinfo=UTC)
    ceiling = datetime(2026, 7, 13, 15, tzinfo=UTC)

    def candidate(identity: str, published_at: str) -> _profile_preview.ProfilePreviewCandidate:
        return _profile_preview.ProfilePreviewCandidate(
            kind="youtube_video",
            title=identity,
            url=f"https://www.youtube.com/watch?v={identity}",
            source="@Example",
            source_label="Example",
            published_at=published_at,
            identity=f"youtube:{identity}",
            command=["distill", "video", identity],
        )

    selected = _profile_preview._fresh_candidates(
        [
            candidate("dateonly", "20260706"),
            candidate("before", "2026-07-06T14:59:59+00:00"),
            candidate("after", "2026-07-06T20:00:00+00:00"),
        ],
        cutoff=cutoff,
        freshness_ceiling=ceiling,
        item_cap=3,
    )

    assert {item.title for item in selected} == {"dateonly", "after"}


def test_profile_preview_many_sources_retains_only_global_top_k() -> None:
    feed_urls = [f"https://feed{index}.example.com/rss" for index in range(100)]
    profile = _profile(
        {
            "sources": {"feeds": feed_urls},
            "limits": {"max_new_items": 3, "max_metered_usd": 0},
        }
    )
    base = datetime.now(UTC) - timedelta(hours=2)
    calls = 0

    def fake_feed_fetcher(url: str) -> PodcastFeed:
        nonlocal calls
        index = calls
        calls += 1
        return PodcastFeed(
            title=url,
            link=url,
            description="",
            episodes=[
                _episode(
                    f"Source {index}",
                    f"source-{index}",
                    (base + timedelta(minutes=index)).isoformat(),
                    link=f"{url}/item",
                )
            ],
        )

    result = build_profile_preview(profile, feed_fetcher=fake_feed_fetcher)

    assert calls == 100
    assert [candidate.title for candidate in result.candidates] == [
        "Source 99",
        "Source 98",
        "Source 97",
    ]


def test_profile_preview_warning_dict_and_youtube_seed_when_atom_unreadable():
    profile = _profile({"sources": {"youtube_channels": [{"channel_id": "UCabc123"}]}})

    def failing_text_fetcher(_url: str) -> str:
        raise RuntimeError("feed unavailable")

    result = build_profile_preview(profile, text_fetcher=failing_text_fetcher)

    assert result.candidates[0].kind == "youtube_channel"
    assert result.candidates[0].url == "https://www.youtube.com/channel/UCabc123"
    assert result.to_dict()["warnings"] == [{"source": "UCabc123", "message": "feed unavailable"}]


def test_profile_preview_skips_ambiguous_duplicate_feed_identities():
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
                    _recent_rfc(minutes_ago=20),
                    audio_url="https://cdn.example.com/audio.mp3",
                    audio_type="audio/mpeg",
                    duration_s=600,
                ),
                _episode(
                    "Duplicate audio",
                    "same",
                    _recent_rfc(minutes_ago=10),
                    audio_url="https://cdn.example.com/duplicate.mp3",
                    audio_type="audio/mpeg",
                    duration_s=600,
                ),
            ],
        )

    result = build_profile_preview(profile, feed_fetcher=fake_feed_fetcher)

    feed_items = [candidate for candidate in result.candidates if candidate.kind == "feed_item"]
    assert feed_items == []
    assert result.warnings[0].source == "https://example.com/feed.xml"
    assert "identities are ambiguous" in result.warnings[0].message


def test_profile_preview_audio_only_items_use_distinct_exact_episode_commands():
    profile = _profile({"sources": {"feeds": ["https://example.com/feed.xml"]}})

    def fake_feed_fetcher(_url: str) -> PodcastFeed:
        return PodcastFeed(
            title="Example",
            link="https://example.com",
            description="",
            episodes=[
                _episode(
                    "Newest",
                    "newest-guid",
                    _recent_rfc(minutes_ago=5),
                    audio_url="https://cdn.example.com/newest.mp3",
                ),
                _episode(
                    "Older",
                    "older-guid",
                    _recent_rfc(minutes_ago=10),
                    audio_url="https://cdn.example.com/older.mp3",
                ),
            ],
        )

    result = build_profile_preview(profile, feed_fetcher=fake_feed_fetcher)
    feed_items = [candidate for candidate in result.candidates if candidate.kind == "feed_item"]

    assert [candidate.title for candidate in feed_items] == ["Newest", "Older"]
    assert len({candidate.identity for candidate in feed_items}) == 2
    for candidate in feed_items:
        selector_index = candidate.command.index("--episode-id") + 1
        assert candidate.command[selector_index] == candidate.identity.removeprefix("feed:")


def test_profile_preview_linkless_posts_use_content_derived_exact_identities():
    profile = _profile({"sources": {"feeds": ["https://example.com/feed.xml"]}})

    def fake_feed_fetcher(_url: str) -> PodcastFeed:
        return PodcastFeed(
            title="Example",
            link="https://example.com",
            description="",
            episodes=[
                _episode(
                    "Newest post",
                    "",
                    _recent_rfc(minutes_ago=5),
                    content_html="<p>Newest body</p>",
                ),
                _episode(
                    "Older post",
                    "",
                    _recent_rfc(minutes_ago=10),
                    content_html="<p>Older body</p>",
                ),
            ],
        )

    result = build_profile_preview(profile, feed_fetcher=fake_feed_fetcher)
    feed_items = [candidate for candidate in result.candidates if candidate.kind == "feed_item"]

    assert [candidate.title for candidate in feed_items] == ["Newest post", "Older post"]
    assert len({candidate.identity for candidate in feed_items}) == 2


def test_profile_preview_uses_validated_feed_url_when_item_has_no_media_url():
    profile = _profile({"sources": {"feeds": ["https://example.com/feed.xml"]}})

    def fake_feed_fetcher(_url: str) -> PodcastFeed:
        return PodcastFeed(
            title="Example",
            link="https://example.com",
            description="",
            episodes=[
                _episode(
                    "URL-less item",
                    "url-less",
                    _recent_rfc(minutes_ago=1),
                )
            ],
        )

    result = build_profile_preview(profile, feed_fetcher=fake_feed_fetcher)

    assert [candidate.kind for candidate in result.candidates] == ["feed_item"]
    assert result.candidates[0].url == "https://example.com/feed.xml"


def test_profile_preview_preserves_explicit_https_port_in_feed_item_url():
    profile = _profile({"sources": {"feeds": ["https://example.com/feed.xml"]}})

    def fake_feed_fetcher(_url: str) -> PodcastFeed:
        return PodcastFeed(
            title="Example",
            link="https://example.com:8443",
            description="",
            episodes=[
                _episode(
                    "Portability",
                    "portability",
                    _recent_rfc(minutes_ago=10),
                    link="https://example.com:8443/episodes/portability",
                )
            ],
        )

    result = build_profile_preview(profile, feed_fetcher=fake_feed_fetcher)

    assert result.candidates[0].url == "https://example.com:8443/episodes/portability"
    assert "https://example.com:8443/episodes/portability" in result.candidates[0].command
    assert result.warnings == []


def test_profile_preview_hashes_large_feed_guids_before_serialization():
    profile = _profile({"sources": {"feeds": ["https://example.com/feed.xml"]}})

    def fake_feed_fetcher(_url: str) -> PodcastFeed:
        return PodcastFeed(
            title="Example",
            link="https://example.com",
            description="",
            episodes=[
                _episode(
                    "Bounded candidate",
                    "g" * 4_900_000,
                    _recent_rfc(minutes_ago=1),
                    link="https://example.com/item",
                )
            ],
        )

    result = build_profile_preview(profile, feed_fetcher=fake_feed_fetcher)

    assert len(result.candidates) == 1
    assert result.candidates[0].identity.startswith("feed:")
    assert len(result.candidates[0].identity) == 45
    assert len(json.dumps(result.to_dict()).encode("utf-8")) < 10_000


def test_profile_preview_rejects_oversized_dynamic_feed_fields():
    profile = _profile({"sources": {"feeds": ["https://example.com/feed.xml"]}})

    def fake_feed_fetcher(_url: str) -> PodcastFeed:
        return PodcastFeed(
            title="Example",
            link="https://example.com",
            description="",
            episodes=[
                _episode(
                    "t" * 1_001,
                    "oversized",
                    _recent_rfc(minutes_ago=1),
                    link="https://example.com/item",
                )
            ],
        )

    result = build_profile_preview(profile, feed_fetcher=fake_feed_fetcher)

    assert result.candidates == []


def test_profile_preview_youtube_atom_fallbacks_and_skips_unusable_entries():
    profile = _profile({"sources": {"youtube_channels": [{"channel_id": "UCabc123"}]}})
    atom = f"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:yt="http://www.youtube.com/xml/schemas/2015">
  <entry>
    <yt:videoId>fallback123</yt:videoId>
    <published>{_fresh_iso()}</published>
  </entry>
  <entry>
    <title>No usable URL</title>
  </entry>
</feed>"""

    result = build_profile_preview(profile, text_fetcher=lambda _url: atom)

    assert len(result.candidates) == 1
    assert result.candidates[0].title == "fallback123"
    assert result.candidates[0].url == "https://www.youtube.com/watch?v=fallback123"


def test_profile_preview_rejects_missing_and_malformed_feed_dates():
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
                    datetime.now(UTC).replace(tzinfo=None).isoformat(),
                    link="https://example.com/naive",
                ),
            ],
        )

    result = build_profile_preview(profile, feed_fetcher=fake_feed_fetcher)

    assert [candidate.title for candidate in result.candidates] == ["Naive date"]


def test_profile_preview_channel_url_seeds():
    profile = _profile(
        {
            "sources": {
                "youtube_channels": [
                    {"url": "https://www.youtube.com/@ByUrl"},
                    {"channel_id": "UCseed00"},
                ]
            }
        }
    )

    result = build_profile_preview(profile, fetch_sources=False)

    assert [candidate.url for candidate in result.candidates] == [
        "https://www.youtube.com/@ByUrl",
        "https://www.youtube.com/channel/UCseed00",
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
    atom = f"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:yt="http://www.youtube.com/xml/schemas/2015">
  <entry>
    <yt:videoId>video123</yt:videoId>
    <title>Fetched atom</title>
    <published>{_fresh_iso()}</published>
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


def test_profile_preview_default_youtube_adapter_failure_becomes_warning_and_seed(monkeypatch):
    profile = _profile({"sources": {"youtube_channels": [{"handle": "@Example"}]}})
    youtube_dl = _stub_youtube_discovery(monkeypatch, None)

    result = build_profile_preview(profile)

    assert [candidate.kind for candidate in result.candidates] == ["youtube_channel"]
    assert "returned no data" in result.warnings[0].message
    assert youtube_dl.call_args.args[0]["ignoreerrors"] is False


def test_profile_preview_whole_day_window_accepts_date_only_youtube_entry(monkeypatch):
    profile = _profile(
        {
            "sources": {"youtube_channels": [{"handle": "@Example"}]},
            "freshness": {"stale_after": "P7D"},
        }
    )
    _stub_youtube_discovery(
        monkeypatch,
        {
            "entries": [
                {
                    "id": "dateonly123",
                    "title": "Date-only upload",
                    "upload_date": datetime.now(UTC).strftime("%Y%m%d"),
                }
            ]
        },
    )

    result = build_profile_preview(profile)

    assert [candidate.kind for candidate in result.candidates] == ["youtube_video"]
    assert result.candidates[0].identity == "youtube:dateonly123"
    assert result.warnings == []


def test_profile_preview_subday_window_rejects_date_only_youtube_entry(monkeypatch):
    profile = _profile(
        {
            "sources": {"youtube_channels": [{"handle": "@Example"}]},
            "freshness": {"stale_after": "PT12H"},
        }
    )
    _stub_youtube_discovery(
        monkeypatch,
        {
            "entries": [
                {
                    "id": "dateonly123",
                    "title": "Date-only upload",
                    "upload_date": datetime.now(UTC).strftime("%Y%m%d"),
                }
            ]
        },
    )

    result = build_profile_preview(profile)

    assert [candidate.kind for candidate in result.candidates] == ["youtube_channel"]
    assert "without a precise timestamp" in result.warnings[0].message


@pytest.mark.parametrize(
    "stale_after",
    ["invalid", "P\u0661D", "P" + "9" * 100 + "D", "P" + "9" * 5000 + "D"],
)
def test_profile_preview_invalid_stale_after_defaults_to_week(stale_after: str):
    profile = _profile({"sources": {"youtube_channels": [{"handle": "@Example"}]}})
    profile = profile.model_copy(
        update={"freshness": profile.freshness.model_copy(update={"stale_after": stale_after})}
    )
    calls: list[dict] = []

    def fake_discoverer(channel_url: str, **kwargs):
        calls.append({"channel_url": channel_url, **kwargs})
        return []

    result = build_profile_preview(profile, youtube_discoverer=fake_discoverer)

    assert calls[0]["days"] == 7
    assert result.candidates == []

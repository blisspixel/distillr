"""Build a non-mutating preview for recurring research profiles."""

from __future__ import annotations

import email.utils
import math
import re
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any

from defusedxml.ElementTree import fromstring as xml_fromstring

from distill.ingestors.net import safe_urlopen
from distill.ingestors.podcasts.feed import PodcastFeed, fetch_feed
from distill.ingestors.youtube.discovery import VideoInfo, discover_videos
from distill.library.profiles import ResearchProfile, YouTubeChannelSource

__all__ = [
    "ProfilePreviewCandidate",
    "ProfilePreviewResult",
    "ProfilePreviewWarning",
    "build_profile_preview",
    "command_text",
]

_MAX_FEED_BYTES = 5_000_000
_ATOM_NS = "{http://www.w3.org/2005/Atom}"
_YT_NS = "{http://www.youtube.com/xml/schemas/2015}"
_DYNAMIC_KINDS = {"feed_item", "youtube_video"}


@dataclass(frozen=True)
class ProfilePreviewCandidate:
    """One work item that a profile run could consider."""

    kind: str
    title: str
    url: str
    source: str
    source_label: str
    command: list[str]
    published_at: str = ""
    identity: str = ""
    note: str = ""
    order: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "title": self.title,
            "url": self.url,
            "source": self.source,
            "source_label": self.source_label,
            "published_at": self.published_at,
            "identity": self.identity,
            "command": self.command,
            "command_text": command_text(self.command),
            "note": self.note,
            "order": self.order,
        }


@dataclass(frozen=True)
class ProfilePreviewWarning:
    """A source could not be expanded, but preview can continue."""

    source: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"source": self.source, "message": self.message}


@dataclass(frozen=True)
class ProfilePreviewResult:
    """Structured preview payload for CLI and agent loops."""

    schema_version: str
    profile: str
    topic: str
    cost_mode: str
    ordering: str
    fresh_item_limit: int
    candidates: list[ProfilePreviewCandidate] = field(default_factory=list)
    warnings: list[ProfilePreviewWarning] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        dynamic_count = sum(1 for candidate in self.candidates if candidate.kind in _DYNAMIC_KINDS)
        return {
            "schema_version": self.schema_version,
            "profile": self.profile,
            "topic": self.topic,
            "cost_mode": self.cost_mode,
            "ordering": self.ordering,
            "fresh_item_limit": self.fresh_item_limit,
            "fresh_item_count": dynamic_count,
            "candidate_count": len(self.candidates),
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "warnings": [warning.to_dict() for warning in self.warnings],
        }


@dataclass(frozen=True)
class _AtomVideo:
    title: str
    url: str
    published_at: str
    video_id: str


FeedFetcher = Callable[[str], PodcastFeed]
YoutubeDiscoverer = Callable[..., list[VideoInfo]]
TextFetcher = Callable[[str], str]


def command_text(command: Iterable[str]) -> str:
    """Render a command for display without changing the machine command list."""

    return " ".join(_quote_arg(part) for part in command)


def build_profile_preview(
    profile: ResearchProfile,
    *,
    fresh_item_limit: int | None = None,
    fetch_sources: bool = True,
    feed_fetcher: FeedFetcher = fetch_feed,
    youtube_discoverer: YoutubeDiscoverer = discover_videos,
    text_fetcher: TextFetcher | None = None,
) -> ProfilePreviewResult:
    """Resolve profile sources into candidate work items without ingesting anything."""

    limit = fresh_item_limit or profile.limits.max_new_items
    if limit < 1:
        raise ValueError("fresh_item_limit must be at least 1")

    warnings: list[ProfilePreviewWarning] = []
    candidates: list[ProfilePreviewCandidate] = []
    fetch_text = text_fetcher or _fetch_text
    lookback_days = _stale_after_days(profile.freshness.stale_after)

    order = _append_youtube_sources(
        profile,
        candidates=candidates,
        warnings=warnings,
        fetch_sources=fetch_sources,
        lookback_days=lookback_days,
        discoverer=youtube_discoverer,
        text_fetcher=fetch_text,
        start_order=0,
    )
    order = _append_feed_sources(
        profile,
        candidates=candidates,
        warnings=warnings,
        fetch_sources=fetch_sources,
        feed_fetcher=feed_fetcher,
        item_cap=limit,
        start_order=order,
    )
    _append_source_seeds(profile, candidates=candidates, start_order=order)

    ordered = _dedupe_and_order(candidates, fresh_item_limit=limit)
    return ProfilePreviewResult(
        schema_version="profile-preview.v1",
        profile=profile.name,
        topic=profile.topic,
        cost_mode=profile.cost_mode,
        ordering="fresh items newest first, source seeds in declaration order",
        fresh_item_limit=limit,
        candidates=ordered,
        warnings=warnings,
    )


def _append_youtube_sources(
    profile: ResearchProfile,
    *,
    candidates: list[ProfilePreviewCandidate],
    warnings: list[ProfilePreviewWarning],
    fetch_sources: bool,
    lookback_days: int,
    discoverer: YoutubeDiscoverer,
    text_fetcher: TextFetcher,
    start_order: int,
) -> int:
    order = start_order
    for source in profile.sources.youtube_channels:
        source_ref = _youtube_source_ref(source)
        source_label = source.label or source_ref
        videos: list[ProfilePreviewCandidate] = []
        if fetch_sources:
            try:
                videos = _youtube_candidates(
                    source,
                    source_label,
                    topic=profile.topic,
                    lookback_days=lookback_days,
                    discoverer=discoverer,
                    text_fetcher=text_fetcher,
                    start_order=order,
                    cost_mode=profile.cost_mode,
                )
            except Exception as exc:
                warnings.append(ProfilePreviewWarning(source=source_ref, message=str(exc)))
        if videos:
            candidates.extend(videos)
            order += len(videos)
        else:
            candidates.append(
                _channel_seed_candidate(
                    source,
                    source_label,
                    topic=profile.topic,
                    order=order,
                    note="Channel seed. Run preview with source fetching enabled to list videos.",
                    cost_mode=profile.cost_mode,
                )
            )
            order += 1
    return order


def _append_feed_sources(
    profile: ResearchProfile,
    *,
    candidates: list[ProfilePreviewCandidate],
    warnings: list[ProfilePreviewWarning],
    fetch_sources: bool,
    feed_fetcher: FeedFetcher,
    item_cap: int,
    start_order: int,
) -> int:
    order = start_order
    for source in profile.sources.feeds:
        source_label = source.label or source.url
        feed: PodcastFeed | None = None
        if fetch_sources:
            try:
                feed = feed_fetcher(source.url)
            except Exception as exc:
                warnings.append(ProfilePreviewWarning(source=source.url, message=str(exc)))
        if feed and feed.episodes:
            for episode in feed.episodes[:item_cap]:
                item_url = episode.link or episode.audio_url or source.url
                candidates.append(
                    ProfilePreviewCandidate(
                        kind="feed_item",
                        title=episode.title,
                        url=item_url,
                        source=source.url,
                        source_label=source_label or feed.title or source.url,
                        published_at=episode.published,
                        identity=f"feed:{source.url}:{episode.guid or item_url}",
                        command=_feed_item_command(
                            item_url,
                            feed_url=source.url,
                            topic=profile.topic,
                            has_page=bool(episode.link),
                            cost_mode=profile.cost_mode,
                        ),
                        note=_feed_item_note(bool(episode.link)),
                        order=order,
                    )
                )
                order += 1
        else:
            candidates.append(
                _feed_seed_candidate(
                    source.url,
                    source_label,
                    profile.topic,
                    order,
                    profile.cost_mode,
                )
            )
            order += 1
    return order


def _append_source_seeds(
    profile: ResearchProfile,
    *,
    candidates: list[ProfilePreviewCandidate],
    start_order: int,
) -> int:
    order = start_order
    for domain in profile.sources.domains:
        candidates.append(_domain_seed_candidate(domain, profile.topic, order, profile.cost_mode))
        order += 1
    for repository in profile.sources.repositories:
        candidates.append(
            _repository_seed_candidate(repository, profile.topic, order, profile.cost_mode)
        )
        order += 1
    for query in profile.queries:
        candidates.append(_query_seed_candidate(query, profile.topic, order, profile.cost_mode))
        order += 1
    return order


def _feed_item_command(
    item_url: str,
    *,
    feed_url: str,
    topic: str,
    has_page: bool,
    cost_mode: str,
) -> list[str]:
    if has_page:
        return _distill_command(cost_mode, "site", item_url, "--topic", topic, "--seed-only")
    return _distill_command(
        cost_mode, "ingest", feed_url, "--topic", topic, "--rss", "--episodes", "1"
    )


def _distill_command(cost_mode: str, *args: str) -> list[str]:
    if cost_mode == "auto":
        return ["distill", *args]
    return ["distill", "--cost-mode", cost_mode, *args]


def _feed_item_note(has_page: bool) -> str:
    if has_page:
        return "Feed item page. Captures this page without relying on a generic URL dispatcher."
    return "Feed item without a page link. Command ingests the latest feed item until exact feed-item replay lands."


def _feed_seed_candidate(
    url: str,
    source_label: str,
    topic: str,
    order: int,
    cost_mode: str,
) -> ProfilePreviewCandidate:
    return ProfilePreviewCandidate(
        kind="feed",
        title=source_label,
        url=url,
        source=url,
        source_label=source_label,
        identity=f"feed:{url}",
        command=_distill_command(cost_mode, "ingest", url, "--topic", topic, "--rss"),
        note="Feed seed. Run with --rss to ingest latest posts or episodes.",
        order=order,
    )


def _domain_seed_candidate(
    domain: str,
    topic: str,
    order: int,
    cost_mode: str,
) -> ProfilePreviewCandidate:
    url = f"https://{domain}"
    return ProfilePreviewCandidate(
        kind="domain",
        title=domain,
        url=url,
        source=domain,
        source_label=domain,
        identity=f"domain:{domain}",
        command=_distill_command(cost_mode, "site", url, "--topic", topic, "--seed-only"),
        note="Domain seed. This captures the landing page unless a later profile run expands it.",
        order=order,
    )


def _repository_seed_candidate(
    repository: str,
    topic: str,
    order: int,
    cost_mode: str,
) -> ProfilePreviewCandidate:
    url = f"https://github.com/{repository}"
    return ProfilePreviewCandidate(
        kind="repository",
        title=repository,
        url=url,
        source=repository,
        source_label=repository,
        identity=f"repository:{repository}",
        command=_distill_command(cost_mode, "ingest", url, "--topic", topic),
        note="Repository seed. GitHub ingestion can summarize current repo metadata.",
        order=order,
    )


def _query_seed_candidate(
    query: str,
    topic: str,
    order: int,
    cost_mode: str,
) -> ProfilePreviewCandidate:
    return ProfilePreviewCandidate(
        kind="query",
        title=query,
        url="",
        source=query,
        source_label="saved query",
        identity=f"query:{query.casefold()}",
        command=_distill_command(cost_mode, "latest", query, "--topic", topic, "--preview"),
        note="Saved query. Preview uses current web and YouTube discovery when run.",
        order=order,
    )


def _youtube_candidates(
    source: YouTubeChannelSource,
    source_label: str,
    *,
    topic: str,
    lookback_days: int,
    discoverer: YoutubeDiscoverer,
    text_fetcher: TextFetcher,
    start_order: int,
    cost_mode: str,
) -> list[ProfilePreviewCandidate]:
    if source.channel_id:
        videos = _parse_youtube_atom(text_fetcher(_youtube_atom_url(source.channel_id)))
        return [
            ProfilePreviewCandidate(
                kind="youtube_video",
                title=video.title,
                url=video.url,
                source=_youtube_source_ref(source),
                source_label=source_label,
                published_at=video.published_at,
                identity=f"youtube:{video.video_id or video.url}",
                command=_distill_command(cost_mode, "video", video.url, "--topic", topic),
                order=start_order + index,
            )
            for index, video in enumerate(videos)
        ]

    channel_url = _youtube_channel_url(source)
    videos = discoverer(channel_url, days=lookback_days, include_shorts=False, quiet=True)
    return [
        ProfilePreviewCandidate(
            kind="youtube_video",
            title=video.title,
            url=video.url,
            source=_youtube_source_ref(source),
            source_label=source_label or video.channel_name,
            published_at=video.published_at or video.upload_date,
            identity=f"youtube:{video.video_id or video.url}",
            command=_distill_command(cost_mode, "video", video.url, "--topic", topic),
            order=start_order + index,
        )
        for index, video in enumerate(videos)
    ]


def _channel_seed_candidate(
    source: YouTubeChannelSource,
    source_label: str,
    *,
    topic: str,
    order: int,
    note: str,
    cost_mode: str,
) -> ProfilePreviewCandidate:
    url = _youtube_channel_url(source)
    return ProfilePreviewCandidate(
        kind="youtube_channel",
        title=source_label,
        url=url,
        source=_youtube_source_ref(source),
        source_label=source_label,
        identity=f"youtube_channel:{_youtube_source_ref(source)}",
        command=_distill_command(cost_mode, "channel", url, "--topic", topic, "--limit", "5"),
        note=note,
        order=order,
    )


def _youtube_source_ref(source: YouTubeChannelSource) -> str:
    return source.channel_id or source.handle or source.url


def _youtube_channel_url(source: YouTubeChannelSource) -> str:
    if source.url:
        return source.url
    if source.handle:
        return f"https://www.youtube.com/{source.handle}"
    return f"https://www.youtube.com/channel/{source.channel_id}"


def _youtube_atom_url(channel_id: str) -> str:
    return f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"


def _fetch_text(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "distillr"})
    try:
        with safe_urlopen(request, timeout=30) as response:
            data = response.read(_MAX_FEED_BYTES + 1)
    except (
        urllib.error.URLError,
        urllib.error.HTTPError,
        TimeoutError,
        OSError,
        ValueError,
    ) as exc:
        raise RuntimeError(f"Could not fetch {url}: {exc}") from exc
    if len(data) > _MAX_FEED_BYTES:
        raise RuntimeError(f"Feed at {url} exceeds the {_MAX_FEED_BYTES:,}-byte cap.")
    return data.decode("utf-8", errors="replace")


def _parse_youtube_atom(xml_text: str) -> list[_AtomVideo]:
    try:
        root = xml_fromstring(xml_text)
    except Exception as exc:
        raise RuntimeError(f"YouTube feed is not parseable XML: {exc}") from exc

    videos: list[_AtomVideo] = []
    for entry in root.findall(f"{_ATOM_NS}entry"):
        video_id = _text(entry, f"{_YT_NS}videoId")
        title = _text(entry, f"{_ATOM_NS}title") or video_id or "(untitled video)"
        published_at = _text(entry, f"{_ATOM_NS}published")
        link = entry.find(f"{_ATOM_NS}link")
        url = link.get("href", "") if link is not None else ""
        if not url and video_id:
            url = f"https://www.youtube.com/watch?v={video_id}"
        if url:
            videos.append(
                _AtomVideo(
                    title=title,
                    url=url,
                    published_at=published_at,
                    video_id=video_id,
                )
            )
    return videos


def _text(elem: Any, tag: str) -> str:
    child = elem.find(tag)
    return (child.text or "").strip() if child is not None else ""


def _dedupe_and_order(
    candidates: list[ProfilePreviewCandidate], *, fresh_item_limit: int
) -> list[ProfilePreviewCandidate]:
    seen: set[str] = set()
    unique: list[ProfilePreviewCandidate] = []
    for candidate in candidates:
        key = candidate.identity or f"{candidate.kind}:{candidate.url}:{candidate.title}"
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)

    dynamic = [candidate for candidate in unique if candidate.kind in _DYNAMIC_KINDS]
    static = [candidate for candidate in unique if candidate.kind not in _DYNAMIC_KINDS]
    dynamic.sort(key=_dynamic_sort_key)
    static.sort(key=lambda candidate: candidate.order)
    ordered = dynamic[:fresh_item_limit] + static
    return [replace(candidate, order=index) for index, candidate in enumerate(ordered)]


def _dynamic_sort_key(candidate: ProfilePreviewCandidate) -> tuple[int, float, int]:
    parsed = _parse_datetime(candidate.published_at)
    if parsed is None:
        return (1, 0.0, candidate.order)
    return (0, -parsed.timestamp(), candidate.order)


def _parse_datetime(raw: str) -> datetime | None:
    text = raw.strip()
    if not text:
        return None
    try:
        parsed = email.utils.parsedate_to_datetime(text)
    except (TypeError, ValueError):
        parsed = None
    if parsed is None:
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _stale_after_days(raw: str) -> int:
    match = re.fullmatch(r"P(?:(?P<days>\d+)D)?(?:T(?P<hours>\d+)H)?", raw)
    if not match:
        return 7
    days = int(match.group("days") or 0)
    hours = int(match.group("hours") or 0)
    if hours:
        days += math.ceil(hours / 24)
    return max(1, days)


def _quote_arg(value: str) -> str:
    if not value:
        return '""'
    if not any(char.isspace() or char in {'"', "'"} for char in value):
        return value
    escaped = value.replace('"', '\\"')
    return f'"{escaped}"'

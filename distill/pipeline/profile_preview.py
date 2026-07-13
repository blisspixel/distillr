# pyright: strict
"""Build a non-mutating preview for recurring research profiles."""

from __future__ import annotations

import email.utils
import heapq
import os
import re
import shlex
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Any

from distill.ingestors.net import safe_urlopen
from distill.ingestors.podcasts.feed import (
    PodcastEpisode,
    PodcastFeed,
    feed_episode_identity,
    fetch_feed,
)
from distill.ingestors.youtube.discovery import VideoInfo, discover_videos
from distill.library.profiles import MAX_PROFILE_NEW_ITEMS, ResearchProfile, YouTubeChannelSource
from distill.parsing import parse_iso_day_hour_duration
from distill.xml_stream import iter_bounded_xml_events
from distill.youtube_urls import (
    normalize_video_id,
    normalize_youtube_video_url,
    youtube_video_id_from_url,
    youtube_watch_url,
)

__all__ = [
    "ProfilePreviewCandidate",
    "ProfilePreviewResult",
    "ProfilePreviewWarning",
    "build_profile_preview",
    "command_shell_label",
    "command_text",
]

_MAX_FEED_BYTES = 5_000_000
_ATOM_NS = "{http://www.w3.org/2005/Atom}"
_YT_NS = "{http://www.youtube.com/xml/schemas/2015}"
_DYNAMIC_KINDS = {"feed_item", "youtube_video"}
_MAX_FUTURE_CLOCK_SKEW = timedelta(minutes=5)
_MAX_DYNAMIC_TITLE_CHARS = 1_000
_MAX_DYNAMIC_DATE_CHARS = 128
_MAX_DYNAMIC_URL_CHARS = 2_048
_MAX_ATOM_NODES = 20_000
_MAX_ATOM_ENTRIES = 1_000
_DATE_ONLY_PUBLICATION = re.compile(r"(?:\d{8}|\d{4}-\d{2}-\d{2})\Z")


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
    max_metered_usd: float = 0.0
    okf_export_required: bool = False
    candidates: list[ProfilePreviewCandidate] = field(default_factory=list[ProfilePreviewCandidate])
    warnings: list[ProfilePreviewWarning] = field(default_factory=list[ProfilePreviewWarning])

    def to_dict(self) -> dict[str, Any]:
        dynamic_count = sum(1 for candidate in self.candidates if candidate.kind in _DYNAMIC_KINDS)
        return {
            "schema_version": self.schema_version,
            "profile": self.profile,
            "topic": self.topic,
            "cost_mode": self.cost_mode,
            "ordering": self.ordering,
            "fresh_item_limit": self.fresh_item_limit,
            "max_metered_usd": self.max_metered_usd,
            "okf_export_required": self.okf_export_required,
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
    """Render argv for PowerShell on Windows or a POSIX shell elsewhere."""

    argv = tuple(command)
    if not argv:
        return ""
    if _is_windows():
        return _powershell_command_text(argv)
    return shlex.join(argv)


def command_shell_label() -> str:
    """Name the shell syntax used by :func:`command_text`."""

    return "PowerShell" if _is_windows() else "POSIX shell"


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

    limit = profile.limits.max_new_items if fresh_item_limit is None else fresh_item_limit
    if type(limit) is not int or limit < 1:
        raise ValueError("fresh_item_limit must be at least 1")
    if limit > MAX_PROFILE_NEW_ITEMS:
        raise ValueError(f"fresh_item_limit cannot exceed {MAX_PROFILE_NEW_ITEMS}")

    warnings: list[ProfilePreviewWarning] = []
    candidates: list[ProfilePreviewCandidate] = []
    fetch_text = text_fetcher or _fetch_text
    freshness_window = _stale_after_window(profile.freshness.stale_after)
    now = datetime.now(UTC)
    cutoff = now - freshness_window
    freshness_ceiling = now + _MAX_FUTURE_CLOCK_SKEW
    lookback_seconds = max(1, int(freshness_window.total_seconds()))
    lookback_days = max(1, (lookback_seconds + 86_399) // 86_400)
    lookback_hours = (
        None if lookback_seconds % 86_400 == 0 else max(1, (lookback_seconds + 3_599) // 3_600)
    )

    order = _append_youtube_sources(
        profile,
        candidates=candidates,
        warnings=warnings,
        fetch_sources=fetch_sources,
        lookback_days=lookback_days,
        lookback_hours=lookback_hours,
        cutoff=cutoff,
        freshness_ceiling=freshness_ceiling,
        item_cap=limit,
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
        cutoff=cutoff,
        freshness_ceiling=freshness_ceiling,
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
        max_metered_usd=profile.limits.max_metered_usd,
        okf_export_required=profile.outputs.okf_export,
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
    lookback_hours: int | None,
    cutoff: datetime,
    freshness_ceiling: datetime,
    item_cap: int,
    discoverer: YoutubeDiscoverer,
    text_fetcher: TextFetcher,
    start_order: int,
) -> int:
    order = start_order
    for source in profile.sources.youtube_channels:
        source_ref = _youtube_source_ref(source)
        source_label = source.label or source_ref
        videos: list[ProfilePreviewCandidate] = []
        fetch_succeeded = False
        if fetch_sources:
            try:
                videos = _youtube_candidates(
                    source,
                    source_label,
                    topic=profile.topic,
                    lookback_days=lookback_days,
                    lookback_hours=lookback_hours,
                    cutoff=cutoff,
                    freshness_ceiling=freshness_ceiling,
                    item_cap=item_cap,
                    discoverer=discoverer,
                    text_fetcher=text_fetcher,
                    start_order=order,
                    cost_mode=profile.cost_mode,
                )
                fetch_succeeded = True
            except Exception as exc:
                warnings.append(ProfilePreviewWarning(source=source_ref, message=str(exc)))
        if videos:
            candidates.extend(videos)
            _trim_dynamic_candidates(
                candidates,
                cutoff=cutoff,
                freshness_ceiling=freshness_ceiling,
                item_cap=item_cap,
            )
            order = max(video.order for video in videos) + 1
        elif not fetch_succeeded:
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
    cutoff: datetime,
    freshness_ceiling: datetime,
    item_cap: int,
    start_order: int,
) -> int:
    order = start_order
    for source in profile.sources.feeds:
        source_label = source.label or source.url
        feed: PodcastFeed | None = None
        fetch_succeeded = False
        if fetch_sources:
            try:
                feed = feed_fetcher(source.url)
                fetch_succeeded = True
            except Exception as exc:
                warnings.append(ProfilePreviewWarning(source=source.url, message=str(exc)))
        feed_candidates: list[ProfilePreviewCandidate] = []
        if feed and feed.episodes:
            expanded_candidates = [
                candidate
                for index, episode in enumerate(feed.episodes)
                if (
                    candidate := _feed_episode_candidate(
                        episode,
                        feed_url=source.url,
                        source_label=source_label or feed.title or source.url,
                        topic=profile.topic,
                        cost_mode=profile.cost_mode,
                        order=order + index,
                    )
                )
                is not None
            ]
            feed_candidates = _fresh_candidates(
                _unambiguous_feed_candidates(
                    expanded_candidates,
                    source=source.url,
                    warnings=warnings,
                ),
                cutoff=cutoff,
                freshness_ceiling=freshness_ceiling,
                item_cap=item_cap,
            )
            order += len(feed.episodes)
            candidates.extend(feed_candidates)
            _trim_dynamic_candidates(
                candidates,
                cutoff=cutoff,
                freshness_ceiling=freshness_ceiling,
                item_cap=item_cap,
            )
        if not feed_candidates and not fetch_succeeded:
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


def _unambiguous_feed_candidates(
    candidates: list[ProfilePreviewCandidate],
    *,
    source: str,
    warnings: list[ProfilePreviewWarning],
) -> list[ProfilePreviewCandidate]:
    identity_counts = Counter(candidate.identity for candidate in candidates)
    ambiguous = {identity for identity, count in identity_counts.items() if count > 1}
    if ambiguous:
        warnings.append(
            ProfilePreviewWarning(
                source=source,
                message=(
                    f"Skipped {sum(identity_counts[value] for value in ambiguous)} feed items "
                    "whose exact identities are ambiguous."
                ),
            )
        )
    return [candidate for candidate in candidates if candidate.identity not in ambiguous]


def _feed_episode_candidate(
    episode: PodcastEpisode,
    *,
    feed_url: str,
    source_label: str,
    topic: str,
    cost_mode: str,
    order: int,
) -> ProfilePreviewCandidate | None:
    title = _bounded_dynamic_text(episode.title, maximum=_MAX_DYNAMIC_TITLE_CHARS)
    published = _bounded_dynamic_text(episode.published, maximum=_MAX_DYNAMIC_DATE_CHARS)
    if not title or not published:
        return None
    page_url = _validated_dynamic_url(episode.link)
    audio_url = _validated_dynamic_url(episode.audio_url)
    item_url = page_url or audio_url or _validated_dynamic_url(feed_url)
    if not item_url:
        return None
    identity_digest = feed_episode_identity(feed_url, episode)
    return ProfilePreviewCandidate(
        kind="feed_item",
        title=title,
        url=item_url,
        source=feed_url,
        source_label=source_label,
        published_at=published,
        identity=f"feed:{identity_digest}",
        command=_feed_item_command(
            item_url,
            feed_url=feed_url,
            topic=topic,
            has_page=bool(page_url),
            cost_mode=cost_mode,
            episode_id=identity_digest,
        ),
        note=_feed_item_note(bool(page_url)),
        order=order,
    )


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
    episode_id: str,
) -> list[str]:
    if has_page:
        return _distill_command(cost_mode, "site", item_url, "--topic", topic, "--seed-only")
    return _distill_command(
        cost_mode,
        "ingest",
        feed_url,
        "--topic",
        topic,
        "--rss",
        "--episodes",
        "1",
        "--episode-id",
        episode_id,
    )


def _distill_command(cost_mode: str, *args: str) -> list[str]:
    if cost_mode == "auto":
        return ["distill", *args]
    return ["distill", "--cost-mode", cost_mode, *args]


def _feed_item_note(has_page: bool) -> str:
    if has_page:
        return "Feed item page. Captures this page without relying on a generic URL dispatcher."
    return "Feed item without a page link. Command selects this exact feed item by identity."


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
        note="Saved query. Preview uses current YouTube discovery when run.",
        order=order,
    )


def _youtube_candidates(
    source: YouTubeChannelSource,
    source_label: str,
    *,
    topic: str,
    lookback_days: int,
    lookback_hours: int | None,
    cutoff: datetime,
    freshness_ceiling: datetime,
    item_cap: int,
    discoverer: YoutubeDiscoverer,
    text_fetcher: TextFetcher,
    start_order: int,
    cost_mode: str,
) -> list[ProfilePreviewCandidate]:
    if source.channel_id:
        videos = _parse_youtube_atom(text_fetcher(_youtube_atom_url(source.channel_id)))
        candidates = (
            candidate
            for index, video in enumerate(videos)
            if (
                candidate := _youtube_video_candidate(
                    video,
                    source=_youtube_source_ref(source),
                    source_label=source_label,
                    topic=topic,
                    cost_mode=cost_mode,
                    order=start_order + index,
                )
            )
            is not None
        )
        return _fresh_candidates(
            candidates,
            cutoff=cutoff,
            freshness_ceiling=freshness_ceiling,
            item_cap=item_cap,
        )

    channel_url = _youtube_channel_url(source)
    videos = discoverer(
        channel_url,
        days=lookback_days,
        hours=lookback_hours,
        include_shorts=False,
        quiet=True,
        raise_on_error=True,
    )
    candidates = (
        candidate
        for index, video in enumerate(videos)
        if (
            candidate := _youtube_video_candidate(
                video,
                source=_youtube_source_ref(source),
                source_label=source_label or video.channel_name,
                topic=topic,
                cost_mode=cost_mode,
                order=start_order + index,
            )
        )
        is not None
    )
    return _fresh_candidates(
        candidates,
        cutoff=cutoff,
        freshness_ceiling=freshness_ceiling,
        item_cap=item_cap,
    )


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
    videos: list[_AtomVideo] = []
    try:
        for event, element in iter_bounded_xml_events(
            xml_text,
            max_nodes=_MAX_ATOM_NODES,
            record_tags=frozenset({f"{_ATOM_NS}entry"}),
            max_records=_MAX_ATOM_ENTRIES,
        ):
            if event != "end" or element.tag != f"{_ATOM_NS}entry":
                continue
            video_id = normalize_video_id(_text(element, f"{_YT_NS}videoId", maximum=64))
            title = (
                _text(element, f"{_ATOM_NS}title", maximum=_MAX_DYNAMIC_TITLE_CHARS)
                or video_id
                or "(untitled video)"
            )
            published_at = _text(
                element,
                f"{_ATOM_NS}published",
                maximum=_MAX_DYNAMIC_DATE_CHARS,
            )
            url = youtube_watch_url(video_id)
            if url:
                videos.append(
                    _AtomVideo(
                        title=title,
                        url=url,
                        published_at=published_at,
                        video_id=video_id,
                    )
                )
            element.clear()
    except Exception as exc:
        raise RuntimeError(f"YouTube feed is not parseable XML: {exc}") from exc
    return videos


def _text(elem: Any, tag: str, *, maximum: int) -> str:
    child = elem.find(tag)
    raw = child.text or "" if child is not None else ""
    if len(raw) > maximum:
        raise ValueError(f"XML text exceeds the {maximum:,}-character cap")
    return raw.strip()


def _bounded_dynamic_text(value: object, *, maximum: int) -> str:
    return value if isinstance(value, str) and 0 < len(value) <= maximum else ""


def _validated_dynamic_url(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > _MAX_DYNAMIC_URL_CHARS:
        return ""
    if value != value.strip() or any(ord(character) < 32 for character in value):
        return ""
    try:
        parsed = urllib.parse.urlsplit(value)
        port = parsed.port
    except ValueError:
        return ""
    if (
        parsed.scheme.casefold() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or port == 0
    ):
        return ""
    return value


def _youtube_video_candidate(
    video: VideoInfo | _AtomVideo,
    *,
    source: str,
    source_label: str,
    topic: str,
    cost_mode: str,
    order: int,
) -> ProfilePreviewCandidate | None:
    video_id = normalize_video_id(video.video_id) or youtube_video_id_from_url(video.url)
    url = normalize_youtube_video_url(video.url) or youtube_watch_url(video_id)
    title = _bounded_dynamic_text(video.title, maximum=_MAX_DYNAMIC_TITLE_CHARS)
    published_at = _bounded_dynamic_text(
        video.published_at or (video.upload_date if isinstance(video, VideoInfo) else ""),
        maximum=_MAX_DYNAMIC_DATE_CHARS,
    )
    if not video_id or not url or not title or not published_at:
        return None
    return ProfilePreviewCandidate(
        kind="youtube_video",
        title=title,
        url=url,
        source=source,
        source_label=source_label[:_MAX_DYNAMIC_TITLE_CHARS],
        published_at=published_at,
        identity=f"youtube:{video_id}",
        command=_distill_command(cost_mode, "video", url, "--topic", topic),
        order=order,
    )


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


def _fresh_candidates(
    candidates: Iterable[ProfilePreviewCandidate],
    *,
    cutoff: datetime,
    freshness_ceiling: datetime,
    item_cap: int,
) -> list[ProfilePreviewCandidate]:
    heap: list[tuple[datetime, int, int, str]] = []
    selected: dict[str, tuple[datetime, int, ProfilePreviewCandidate]] = {}
    serial = 0
    for candidate in candidates:
        published = _published_at_or_none(candidate.published_at)
        if published is None:
            continue
        if _DATE_ONLY_PUBLICATION.fullmatch(candidate.published_at.strip()):
            within_window = cutoff.date() <= published.date() <= freshness_ceiling.date()
        else:
            within_window = cutoff <= published <= freshness_ceiling
        if not within_window:
            continue
        key = candidate.identity or f"{candidate.kind}:{candidate.url}:{candidate.title}"
        priority = (published, -candidate.order)
        previous = selected.get(key)
        if previous is not None and priority <= previous[:2]:
            continue
        selected[key] = (published, -candidate.order, candidate)
        heapq.heappush(heap, (published, -candidate.order, serial, key))
        serial += 1
        if len(selected) > item_cap:
            _remove_oldest_selected(heap, selected)
        if len(heap) > item_cap * 2:
            heap = [
                (item[0], item[1], index, item_key)
                for index, (item_key, item) in enumerate(selected.items())
            ]
            heapq.heapify(heap)
    ordered = sorted(selected.values(), key=lambda item: item[:2], reverse=True)
    return [item[2] for item in ordered]


def _remove_oldest_selected(
    heap: list[tuple[datetime, int, int, str]],
    selected: dict[str, tuple[datetime, int, ProfilePreviewCandidate]],
) -> None:
    while heap:
        published, inverse_order, _serial, key = heapq.heappop(heap)
        current = selected.get(key)
        if current is not None and current[:2] == (published, inverse_order):
            del selected[key]
            return


def _trim_dynamic_candidates(
    candidates: list[ProfilePreviewCandidate],
    *,
    cutoff: datetime,
    freshness_ceiling: datetime,
    item_cap: int,
) -> None:
    dynamic = _fresh_candidates(
        (candidate for candidate in candidates if candidate.kind in _DYNAMIC_KINDS),
        cutoff=cutoff,
        freshness_ceiling=freshness_ceiling,
        item_cap=item_cap,
    )
    static = [candidate for candidate in candidates if candidate.kind not in _DYNAMIC_KINDS]
    candidates[:] = [*dynamic, *static]


def _dynamic_sort_key(candidate: ProfilePreviewCandidate) -> tuple[int, float, int]:
    parsed = _parse_datetime(candidate.published_at)
    if parsed is None:
        return (1, 0.0, candidate.order)
    try:
        timestamp = parsed.timestamp()
    except (OSError, OverflowError, ValueError):
        return (1, 0.0, candidate.order)
    return (0, -timestamp, candidate.order)


def _parse_datetime(raw: str) -> datetime | None:
    text = raw.strip()
    if not text:
        return None
    try:
        parsed = email.utils.parsedate_to_datetime(text)
    except (OverflowError, TypeError, ValueError):
        parsed = None
    if parsed is None:
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except (OverflowError, ValueError):
            return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    try:
        return parsed.astimezone(UTC)
    except (OSError, OverflowError, ValueError):
        return None


def _stale_after_window(raw: str) -> timedelta:
    duration = parse_iso_day_hour_duration(raw)
    if duration is None:
        return timedelta(days=7)
    return duration


def _published_at_or_none(raw: str) -> datetime | None:
    return _parse_datetime(raw)


_POWERSHELL_BARE_ARG = re.compile(r"[A-Za-z0-9_./:\\=+\-]+")


def _is_windows() -> bool:
    return os.name == "nt"


def _powershell_quote_arg(value: str) -> str:
    """Quote one literal PowerShell argument, including shell metacharacters."""

    if value and _POWERSHELL_BARE_ARG.fullmatch(value):
        return value
    return "'" + value.replace("'", "''") + "'"


def _powershell_command_text(argv: tuple[str, ...]) -> str:
    """Render argv as a copyable PowerShell command line."""

    executable = _powershell_quote_arg(argv[0])
    if executable != argv[0]:
        executable = f"& {executable}"
    return " ".join((executable, *(_powershell_quote_arg(part) for part in argv[1:])))

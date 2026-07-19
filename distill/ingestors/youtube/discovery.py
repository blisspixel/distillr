"""Video discovery - list channel videos and search results via yt-dlp."""

import logging
import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from rich.markup import escape

from distill._console import console
from distill.ingestors.net import url_for_diagnostic
from distill.ingestors.youtube._yt_dlp_boundary import (
    YtDlpInfo,
    date_range,
    first_text,
    info_entries,
    info_mapping,
    int_field,
    text_field,
)
from distill.ingestors.youtube.safe_ytdlp import (
    YTDLP_METADATA_RESPONSE_BYTES,
    YTDLP_METADATA_TOTAL_BYTES,
    SafeYoutubeDL,
)
from distill.parsing import MAX_LOOKBACK_DAYS, MAX_LOOKBACK_HOURS
from distill.youtube_urls import (
    normalize_video_id,
    normalize_youtube_channel_url,
    normalize_youtube_video_url,
    youtube_channel_url,
    youtube_watch_url,
)

__all__ = [
    "VideoInfo",
    "discover_videos",
    "enrich_videos",
    "get_video_info",
    "is_valid_youtube_lookback",
    "resolve_channel_name",
    "search_videos",
]

MAX_YOUTUBE_SEARCH_RESULTS = 100
_MAX_FUTURE_CLOCK_SKEW = timedelta(minutes=5)

_EXTRACTOR_ERROR_HINTS = (
    "extractor",
    "unable to extract",
    "unable to download",
    "youtube said",
    "sign in to confirm",
    "http error 4",
)


def _looks_like_extractor_failure(message: str) -> bool:
    msg = message.lower()
    return any(hint in msg for hint in _EXTRACTOR_ERROR_HINTS)


def _print_extractor_hint() -> None:
    console.print(
        "  [yellow]hint: yt-dlp may be outdated; "
        "run [bold]distill doctor --update[/bold] to refresh.[/yellow]"
    )


class _QuietLogger(logging.Logger):
    """Swallow yt-dlp error messages (e.g. members-only videos) to keep output clean."""

    def debug(self, msg, *args, **kwargs):
        return None

    def info(self, msg, *args, **kwargs):
        return None

    def warning(self, msg, *args, **kwargs):
        return None

    def error(self, msg, *args, **kwargs):
        return None


@dataclass
class VideoInfo:
    video_id: str
    title: str
    upload_date: str  # YYYYMMDD
    duration: int  # seconds
    url: str
    channel_name: str = ""
    channel_url: str = ""
    description: str = ""
    view_count: int = 0
    like_count: int = 0
    comment_count: int = 0
    published_at: str = ""


def discover_videos(  # noqa: C901 — legacy, will refactor
    channel_url: str,
    months: int = 3,
    include_shorts: bool = False,
    days: int | None = None,
    quiet: bool = False,
    hours: int | None = None,
    raise_on_error: bool = False,
) -> list[VideoInfo]:
    """List videos from a channel within a lookback window.

    Use ``days`` for precise control or ``months`` (approximated as
    months * 30 days) for broader sweeps.  ``days`` takes priority when
    both are provided.

    By default, only full-length videos are discovered (the /videos tab).
    Shorts (<60s) are excluded because they rarely contain enough substance
    for meaningful 2-pass analysis. Set include_shorts=True to also scan
    the /shorts tab.
    """
    normalized_channel_url = normalize_youtube_channel_url(channel_url)
    if not normalized_channel_url:
        displayed_url = escape(url_for_diagnostic(channel_url))
        console.print(f"  [red]Refusing non-YouTube URL: {displayed_url}[/red]")
        return []

    if hours is not None:
        if not _bounded_nonnegative_int(hours, MAX_LOOKBACK_HOURS) or (
            days is not None and not _bounded_nonnegative_int(days, MAX_LOOKBACK_DAYS)
        ):
            return []
        lookback = timedelta(hours=hours)
    elif days is not None:
        if not _bounded_nonnegative_int(days, MAX_LOOKBACK_DAYS):
            return []
        lookback = timedelta(days=days)
    else:
        if not _bounded_nonnegative_int(months, MAX_LOOKBACK_DAYS // 30):
            return []
        lookback = timedelta(days=months * 30)
    lookback_days = max(1, math.ceil(lookback.total_seconds() / 86_400))
    now = datetime.now(UTC)
    cutoff = now - lookback
    freshness_ceiling = now + _MAX_FUTURE_CLOCK_SKEW
    cutoff_str = cutoff.strftime("%Y%m%d")

    base_url = normalized_channel_url.rstrip("/").removesuffix("/videos").removesuffix("/shorts")
    urls_to_scan = [base_url + "/videos"]
    if include_shorts:
        urls_to_scan.append(base_url + "/shorts")

    videos = []

    # Scale playlist depth to lookback window — most channels post ≤3/day.
    # Keeps short lookbacks fast while still catching prolific uploaders.
    playlist_depth = min(max(lookback_days * 5, 15), 200)

    seen_ids = set()
    for scan_url in urls_to_scan:
        tab = "shorts" if scan_url.endswith("/shorts") else "videos"
        if not quiet:
            console.print(f"  [dim]Scanning {tab} tab for content after {cutoff_str}...[/dim]")

        try:
            ydl_opts: dict[str, object] = {
                "daterange": date_range(cutoff_str),
                "quiet": True,
                "no_warnings": True,
                "extract_flat": False,
                "lazy_playlist": True,
                "ignoreerrors": not raise_on_error,
                "playlistend": playlist_depth,
                "logger": _QuietLogger("yt-dlp"),
            }
            with SafeYoutubeDL(
                ydl_opts,
                metadata_byte_limit=YTDLP_METADATA_RESPONSE_BYTES,
                total_byte_limit=YTDLP_METADATA_TOTAL_BYTES,
            ) as ydl:
                info = info_mapping(ydl.extract_info(scan_url, download=False))

                if info is None:
                    if raise_on_error:
                        raise RuntimeError(f"YouTube discovery returned no data for {scan_url}")
                    continue

                entries = info.get("entries")
                for entry in info_entries(entries):
                    video = _entry_to_video_info(entry)
                    if not video:
                        continue

                    # yt-dlp daterange doesn't reliably filter channel tabs —
                    # enforce cutoff ourselves.
                    if hours is not None:
                        if not video.published_at:
                            if raise_on_error and _upload_date_overlaps_window(
                                video.upload_date,
                                cutoff,
                                now,
                            ):
                                raise RuntimeError(
                                    "YouTube discovery returned a potentially fresh video "
                                    f"without a precise timestamp: {video.video_id}"
                                )
                            continue
                        if not _is_recent_enough_precise(video, cutoff, freshness_ceiling):
                            continue
                    elif not _is_recent_enough(video.upload_date, cutoff, now):
                        continue

                    if video.video_id in seen_ids:
                        continue
                    seen_ids.add(video.video_id)
                    videos.append(video)

        except Exception as e:
            console.print(f"  [red]Discovery error ({tab}): {e}[/red]")
            if _looks_like_extractor_failure(str(e)):
                _print_extractor_hint()
            if raise_on_error:
                raise RuntimeError(f"YouTube discovery failed for {scan_url}: {e}") from e

    videos.sort(key=lambda v: v.upload_date, reverse=True)
    if not quiet:
        console.print(f"  [dim]Found {len(videos)} videos in date range[/dim]")
    return videos


def is_youtube_url(url: str) -> bool:
    """Return whether a URL identifies a supported canonicalizable video."""

    return bool(normalize_youtube_video_url(url))


def get_video_info(video_url: str) -> VideoInfo | None:
    """Get metadata for a single video URL."""
    canonical_url = normalize_youtube_video_url(video_url)
    if not canonical_url:
        displayed_url = escape(url_for_diagnostic(video_url))
        console.print(f"[red]Refusing non-YouTube URL: {displayed_url}[/red]")
        return None
    ydl_opts: dict[str, object] = {
        "quiet": True,
        "no_warnings": True,
    }

    try:
        with SafeYoutubeDL(
            ydl_opts,
            metadata_byte_limit=YTDLP_METADATA_RESPONSE_BYTES,
            total_byte_limit=YTDLP_METADATA_TOTAL_BYTES,
        ) as ydl:
            info = info_mapping(ydl.extract_info(canonical_url, download=False))
            if info is None:
                return None
            return _entry_to_video_info(info)
    except Exception as e:
        console.print(f"[red]Failed to get video info: {e}[/red]")
        return None


def enrich_videos(videos: list[VideoInfo], max_videos: int | None = None) -> list[VideoInfo]:
    """Fetch richer metadata for candidate videos to improve ranking quality."""
    if not videos:
        return []

    enriched = []
    limit = len(videos) if max_videos is None else max_videos
    for idx, video in enumerate(videos):
        if idx >= limit:
            enriched.append(video)
            continue
        detailed = get_video_info(video.url)
        if not detailed:
            enriched.append(video)
            continue
        enriched.append(_merge_video_info(video, detailed))
    return enriched


def search_videos(
    query: str,
    days: int = 60,
    limit: int = 10,
    sort: str = "relevance",
    per_channel_cap: int = 2,
    enrich: bool = False,
) -> list[VideoInfo]:
    """Search YouTube for recent videos on a topic."""
    if not _bounded_positive_int(
        limit, MAX_YOUTUBE_SEARCH_RESULTS
    ) or not is_valid_youtube_lookback(days):
        return []

    search_limit = max(limit * 3, 25)
    search_expr = _search_expression(query, search_limit, sort)
    now = datetime.now(UTC)
    cutoff = now - timedelta(days=days)

    ydl_opts: dict[str, object] = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": False,
        "ignoreerrors": True,
        "playlistend": search_limit,
        "logger": _QuietLogger("yt-dlp"),
    }

    console.print(
        f"  [dim]Searching YouTube for '{query}' "
        f"({days}-day window, {sort} order, target {limit})...[/dim]"
    )

    try:
        with SafeYoutubeDL(
            ydl_opts,
            metadata_byte_limit=YTDLP_METADATA_RESPONSE_BYTES,
            total_byte_limit=YTDLP_METADATA_TOTAL_BYTES,
        ) as ydl:
            info = info_mapping(ydl.extract_info(search_expr, download=False))
    except Exception as e:
        console.print(f"  [red]Search error: {e}[/red]")
        if _looks_like_extractor_failure(str(e)):
            _print_extractor_hint()
        return []

    if info is None:
        return []

    candidates = []
    for entry in info_entries(info.get("entries")):
        video = _entry_to_video_info(entry)
        if not video:
            continue
        if not _is_recent_enough(video.upload_date, cutoff, now):
            continue
        candidates.append(video)

    ranked = _rank_search_results(candidates, sort)
    selected = _apply_search_caps(ranked, limit, per_channel_cap)
    if enrich:
        selected = enrich_videos(selected)
    console.print(f"  [dim]Selected {len(selected)} recent videos from search[/dim]")
    return selected


def resolve_channel_name(channel_url: str) -> str:
    """Extract channel name from URL or metadata."""
    normalized_channel_url = normalize_youtube_channel_url(channel_url)
    if not normalized_channel_url:
        return "unknown"
    if "/@" in normalized_channel_url:
        name = normalized_channel_url.split("/@")[1].split("/")[0]
        return name

    try:
        ydl_opts: dict[str, object] = {"quiet": True, "no_warnings": True, "extract_flat": True}
        with SafeYoutubeDL(
            ydl_opts,
            metadata_byte_limit=YTDLP_METADATA_RESPONSE_BYTES,
            total_byte_limit=YTDLP_METADATA_TOTAL_BYTES,
        ) as ydl:
            info = info_mapping(ydl.extract_info(normalized_channel_url, download=False))
            if info is None:
                return "unknown"
            return first_text(info, ("channel", "uploader"), "unknown")
    except Exception:
        return "unknown"


def _search_expression(query: str, limit: int, sort: str) -> str:
    prefix = "ytsearchdate" if sort == "date" else "ytsearch"
    return f"{prefix}{limit}:{query}"


def _entry_to_video_info(entry: YtDlpInfo | None) -> VideoInfo | None:
    if not entry:
        return None

    video_id = normalize_video_id(text_field(entry, "id"))
    upload_date = text_field(entry, "upload_date")
    if not video_id or not _valid_upload_date(upload_date):
        return None

    channel_name = first_text(entry, ("channel", "uploader", "channel_id"), "unknown")
    channel_url = _normalize_channel_url(
        first_text(entry, ("channel_url", "uploader_url")) or _channel_url_from_metadata(entry)
    )

    timestamp = int_field(entry, "timestamp")
    try:
        published_at = datetime.fromtimestamp(timestamp, UTC).isoformat() if timestamp > 0 else ""
    except (OSError, OverflowError, ValueError):
        published_at = ""

    return VideoInfo(
        video_id=video_id,
        title=text_field(entry, "title", "Unknown"),
        upload_date=upload_date,
        duration=int_field(entry, "duration"),
        url=youtube_watch_url(video_id),
        channel_name=channel_name,
        channel_url=channel_url,
        description=text_field(entry, "description").strip(),
        view_count=int_field(entry, "view_count"),
        like_count=int_field(entry, "like_count"),
        comment_count=int_field(entry, "comment_count"),
        published_at=published_at,
    )


def _merge_video_info(base: VideoInfo, detailed: VideoInfo) -> VideoInfo:
    return VideoInfo(
        video_id=base.video_id,
        title=detailed.title or base.title,
        upload_date=detailed.upload_date or base.upload_date,
        duration=detailed.duration or base.duration,
        url=base.url,
        channel_name=detailed.channel_name or base.channel_name,
        channel_url=detailed.channel_url or base.channel_url,
        description=detailed.description or base.description,
        view_count=detailed.view_count or base.view_count,
        like_count=detailed.like_count or base.like_count,
        comment_count=detailed.comment_count or base.comment_count,
        published_at=detailed.published_at or base.published_at,
    )


def _channel_url_from_metadata(entry: YtDlpInfo) -> str:
    uploader_id = first_text(entry, ("uploader_id", "channel_id"))
    return youtube_channel_url(uploader_id)


def _normalize_channel_url(channel_url: str) -> str:
    return normalize_youtube_channel_url(channel_url)


def _is_recent_enough(
    upload_date: str,
    cutoff: datetime,
    freshness_ceiling: datetime | None = None,
) -> bool:
    try:
        published = datetime.strptime(upload_date, "%Y%m%d").replace(tzinfo=UTC)
    except ValueError:
        return False
    normalized_cutoff = _as_utc(cutoff)
    ceiling = _as_utc(freshness_ceiling or datetime.now(UTC))
    return normalized_cutoff.date() <= published.date() <= ceiling.date()


def _valid_upload_date(value: str) -> bool:
    if len(value) != 8 or not value.isascii() or not value.isdecimal():
        return False
    try:
        datetime.strptime(value, "%Y%m%d")
    except ValueError:
        return False
    return True


def _is_recent_enough_precise(
    video: VideoInfo,
    cutoff: datetime,
    freshness_ceiling: datetime | None = None,
) -> bool:
    if not video.published_at:
        return False
    try:
        published = datetime.fromisoformat(video.published_at)
    except (OverflowError, ValueError):
        return False
    try:
        normalized_published = _as_utc(published)
        normalized_cutoff = _as_utc(cutoff)
        ceiling = _as_utc(freshness_ceiling or datetime.now(UTC) + _MAX_FUTURE_CLOCK_SKEW)
        return normalized_cutoff <= normalized_published <= ceiling
    except (OSError, OverflowError, ValueError):
        return False


def _upload_date_overlaps_window(
    upload_date: str,
    cutoff: datetime,
    freshness_ceiling: datetime,
) -> bool:
    try:
        day_start = datetime.strptime(upload_date, "%Y%m%d").replace(tzinfo=UTC)
    except ValueError:
        return False
    return _as_utc(cutoff).date() <= day_start.date() <= _as_utc(freshness_ceiling).date()


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _bounded_nonnegative_int(value: object, maximum: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= maximum


def _bounded_positive_int(value: object, maximum: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and 0 < value <= maximum


def is_valid_youtube_lookback(days: object, hours: object | None = None) -> bool:
    """Return whether browser and yt-dlp lookback inputs are safely bounded."""

    return _bounded_nonnegative_int(days, MAX_LOOKBACK_DAYS) and (
        hours is None or _bounded_nonnegative_int(hours, MAX_LOOKBACK_HOURS)
    )


def _rank_search_results(videos: list[VideoInfo], sort: str) -> list[VideoInfo]:
    deduped = []
    seen_ids = set()
    for video in videos:
        if video.video_id in seen_ids:
            continue
        seen_ids.add(video.video_id)
        deduped.append(video)

    if sort == "date":
        return sorted(deduped, key=lambda v: (v.upload_date, v.title.lower()), reverse=True)
    return deduped


def _apply_search_caps(
    videos: list[VideoInfo], limit: int, per_channel_cap: int
) -> list[VideoInfo]:
    if per_channel_cap <= 0:
        per_channel_cap = limit

    selected = []
    channel_counts = {}

    for video in videos:
        channel_key = (video.channel_name or "unknown").strip().lower() or "unknown"
        if channel_counts.get(channel_key, 0) >= per_channel_cap:
            continue
        selected.append(video)
        channel_counts[channel_key] = channel_counts.get(channel_key, 0) + 1
        if len(selected) >= limit:
            break

    return selected

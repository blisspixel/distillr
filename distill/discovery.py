"""Video discovery - list channel videos and search results via yt-dlp."""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

import yt_dlp
from rich.console import Console

console = Console()


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
        pass

    def info(self, msg, *args, **kwargs):
        pass

    def warning(self, msg, *args, **kwargs):
        pass

    def error(self, msg, *args, **kwargs):
        pass


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
    lookback_days = days if days is not None else months * 30
    cutoff = datetime.now() - timedelta(days=lookback_days)
    cutoff_str = cutoff.strftime("%Y%m%d")

    base_url = channel_url.rstrip("/").removesuffix("/videos").removesuffix("/shorts")
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
            ydl_opts = {
                "daterange": yt_dlp.utils.DateRange(cutoff_str),
                "quiet": True,
                "no_warnings": True,
                "extract_flat": False,
                "lazy_playlist": True,
                "ignoreerrors": True,
                "playlistend": playlist_depth,
                "logger": _QuietLogger("yt-dlp"),
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(scan_url, download=False)

                if not info:
                    continue

                entries = info.get("entries")
                if entries is None:
                    continue

                for entry in entries:
                    video = _entry_to_video_info(entry)
                    if not video:
                        continue

                    # yt-dlp daterange doesn't reliably filter channel tabs —
                    # enforce cutoff ourselves.
                    if video.upload_date < cutoff_str:
                        continue

                    if video.video_id in seen_ids:
                        continue
                    seen_ids.add(video.video_id)
                    videos.append(video)

        except Exception as e:
            console.print(f"  [red]Discovery error ({tab}): {e}[/red]")
            if _looks_like_extractor_failure(str(e)):
                _print_extractor_hint()

    videos.sort(key=lambda v: v.upload_date, reverse=True)
    if not quiet:
        console.print(f"  [dim]Found {len(videos)} videos in date range[/dim]")
    return videos


def get_video_info(video_url: str) -> VideoInfo | None:
    """Get metadata for a single video URL."""
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=False)
            if not info:
                return None
            return _entry_to_video_info(info, fallback_url=video_url)
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
    if limit <= 0:
        return []

    search_limit = max(limit * 3, 25)
    search_expr = _search_expression(query, search_limit, sort)
    cutoff = datetime.now() - timedelta(days=days)

    ydl_opts = {
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
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(search_expr, download=False)
    except Exception as e:
        console.print(f"  [red]Search error: {e}[/red]")
        if _looks_like_extractor_failure(str(e)):
            _print_extractor_hint()
        return []

    if not info or info.get("entries") is None:
        return []

    candidates = []
    for entry in info.get("entries") or []:
        video = _entry_to_video_info(entry)
        if not video:
            continue
        if not _is_recent_enough(video.upload_date, cutoff):
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
    if "/@" in channel_url:
        name = channel_url.split("/@")[1].split("/")[0].split("?")[0]
        return name

    try:
        with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "extract_flat": True}) as ydl:
            info = ydl.extract_info(channel_url, download=False)
            return info.get("channel", info.get("uploader", "unknown"))
    except Exception:
        return "unknown"


def _search_expression(query: str, limit: int, sort: str) -> str:
    prefix = "ytsearchdate" if sort == "date" else "ytsearch"
    return f"{prefix}{limit}:{query}"


def _entry_to_video_info(entry: dict | None, fallback_url: str = "") -> VideoInfo | None:
    if not entry:
        return None

    video_id = entry.get("id", "")
    upload_date = entry.get("upload_date", "")
    if not video_id or not upload_date:
        return None

    channel_name = (
        entry.get("channel") or entry.get("uploader") or entry.get("channel_id") or "unknown"
    )
    channel_url = _normalize_channel_url(
        entry.get("channel_url") or entry.get("uploader_url") or _channel_url_from_metadata(entry)
    )

    return VideoInfo(
        video_id=video_id,
        title=entry.get("title", "Unknown"),
        upload_date=upload_date,
        duration=int(entry.get("duration") or 0),
        url=entry.get("webpage_url")
        or fallback_url
        or f"https://www.youtube.com/watch?v={video_id}",
        channel_name=channel_name,
        channel_url=channel_url,
        description=(entry.get("description") or "").strip(),
        view_count=int(entry.get("view_count") or 0),
        like_count=int(entry.get("like_count") or 0),
        comment_count=int(entry.get("comment_count") or 0),
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
    )


def _channel_url_from_metadata(entry: dict) -> str:
    uploader_id = entry.get("uploader_id") or entry.get("channel_id") or ""
    if not uploader_id:
        return ""
    if uploader_id.startswith("@"):
        return f"https://www.youtube.com/{uploader_id}"
    if uploader_id.startswith("UC"):
        return f"https://www.youtube.com/channel/{uploader_id}"
    return ""


def _normalize_channel_url(channel_url: str) -> str:
    if not channel_url:
        return ""
    if channel_url.startswith("http://") or channel_url.startswith("https://"):
        return channel_url.rstrip("/")
    if channel_url.startswith("/"):
        return f"https://www.youtube.com{channel_url}".rstrip("/")
    return channel_url.rstrip("/")


def _is_recent_enough(upload_date: str, cutoff: datetime) -> bool:
    try:
        return datetime.strptime(upload_date, "%Y%m%d") >= cutoff
    except ValueError:
        return False


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

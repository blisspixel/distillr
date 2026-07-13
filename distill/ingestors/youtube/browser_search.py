"""Browser-based YouTube search discovery with fallback parsing."""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta

from distill._console import console
from distill.ingestors.net import NetworkError, safe_urlopen
from distill.ingestors.youtube.discovery import (
    MAX_YOUTUBE_SEARCH_RESULTS,
    VideoInfo,
    is_valid_youtube_lookback,
)
from distill.parsing import parse_ascii_uint, parse_bounded_json_int
from distill.youtube_urls import (
    normalize_video_id,
    normalize_youtube_channel_url,
    youtube_channel_url,
    youtube_watch_url,
)

__all__ = [
    "parse_search_results_html",
    "search_youtube_results",
]

_YT_INITIAL_DATA_RE = re.compile(r"var ytInitialData = (\{.*?\});</script>", re.DOTALL)
_MAX_INITIAL_DATA_NODES = 100_000
_MAX_SEARCH_HTML_BYTES = 10_000_000
_MAX_NUMERIC_LABEL_CHARS = 128
_MAX_TEXT_NODES = 10_000
_MAX_TEXT_CHARS = 4_096
_MAX_VIDEO_DURATION_SECONDS = 10 * 365 * 24 * 60 * 60
_MAX_VIEW_COUNT = 1_000_000_000_000_000
_MAX_FUTURE_CLOCK_SKEW = timedelta(minutes=5)
_RELATIVE_UNIT_DELTAS = {
    "minute": timedelta(minutes=1),
    "hour": timedelta(hours=1),
    "day": timedelta(days=1),
    "week": timedelta(weeks=1),
    "month": timedelta(days=30),
    "year": timedelta(days=365),
}


def search_youtube_results(
    query_or_url: str, days: int = 60, limit: int = 20, hours: int | None = None
) -> list[VideoInfo]:
    """Search YouTube using the actual results page and return video candidates."""
    if (
        isinstance(limit, bool)
        or not isinstance(limit, int)
        or limit <= 0
        or limit > MAX_YOUTUBE_SEARCH_RESULTS
        or not is_valid_youtube_lookback(days, hours)
    ):
        return []

    search_url = query_or_url if _is_search_url(query_or_url) else _build_search_url(query_or_url)
    html = _fetch_search_html(search_url)
    if not html:
        return []

    candidates = parse_search_results_html(html)
    now = datetime.now(UTC)
    cutoff = now - timedelta(hours=hours) if hours is not None else now - timedelta(days=days)
    freshness_ceiling = now + _MAX_FUTURE_CLOCK_SKEW
    results = []
    seen_ids = set()
    for video in candidates:
        if video.video_id in seen_ids:
            continue
        published_dt = _published_to_datetime(video)
        if published_dt is None or not cutoff <= published_dt <= freshness_ceiling:
            continue
        seen_ids.add(video.video_id)
        results.append(video)
        if len(results) >= limit:
            break
    return results


def parse_search_results_html(html: str) -> list[VideoInfo]:
    match = _YT_INITIAL_DATA_RE.search(html)
    if not match:
        return []
    try:
        # ytInitialData comes from an untrusted fetched page and the non-greedy
        # capture can truncate mid-object; a malformed body must degrade to "no
        # candidates", not abort the whole search/discover run.
        data = json.loads(match.group(1), parse_int=parse_bounded_json_int)
    except (RecursionError, ValueError):
        return []

    results: list[VideoInfo] = []
    stack = [data]
    visited = 0
    while stack:
        visited += 1
        if visited > _MAX_INITIAL_DATA_NODES:
            return []
        node = stack.pop()
        if isinstance(node, dict):
            renderer = node.get("videoRenderer")
            if isinstance(renderer, dict):
                video = _video_from_renderer(renderer)
                if video:
                    results.append(video)
            stack.extend(reversed(tuple(node.values())))
        elif isinstance(node, list):
            stack.extend(reversed(node))
    return results


def _video_from_renderer(renderer: dict[str, object]) -> VideoInfo | None:
    video_id = normalize_video_id(renderer.get("videoId"))
    if not video_id:
        return None

    title = _extract_text(renderer.get("title")) or "Unknown"
    channel_name = (
        _extract_text(renderer.get("ownerText"))
        or _extract_text(renderer.get("longBylineText"))
        or ""
    )
    channel_url = _extract_owner_url(renderer)
    published = _extract_text(renderer.get("publishedTimeText"))
    published_dt = _relative_to_datetime(published)
    upload_date = published_dt.strftime("%Y%m%d") if published_dt else ""
    duration = _duration_to_seconds(_extract_text(renderer.get("lengthText")))
    views = _parse_int(_extract_text(renderer.get("viewCountText")))
    description = (
        _extract_text(renderer.get("detailedMetadataSnippets"))
        or _extract_text(renderer.get("descriptionSnippet"))
        or ""
    )

    return VideoInfo(
        video_id=video_id,
        title=title,
        upload_date=upload_date,
        duration=duration,
        url=youtube_watch_url(video_id),
        channel_name=channel_name,
        channel_url=channel_url,
        description=description,
        view_count=views,
        published_at=published_dt.isoformat() if published_dt else "",
    )


def _published_to_datetime(video: VideoInfo) -> datetime | None:
    published_at = getattr(video, "published_at", "")
    if published_at:
        try:
            return datetime.fromisoformat(published_at)
        except ValueError:
            return _parse_upload_date(video.upload_date)
    return _parse_upload_date(video.upload_date)


def _fetch_search_html(search_url: str) -> str:
    html = _fetch_with_playwright(search_url)
    if html:
        return html
    try:
        return _fetch_with_urllib(search_url)
    except NetworkError:
        return ""


def _fetch_with_playwright(search_url: str) -> str:
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return ""

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(1500)
                dom_chars = page.evaluate("document.documentElement.outerHTML.length")
                if not isinstance(dom_chars, int) or dom_chars > _MAX_SEARCH_HTML_BYTES:
                    return ""
                html = page.content()
                if len(html.encode("utf-8")) > _MAX_SEARCH_HTML_BYTES:
                    return ""
                return html
            finally:
                browser.close()
    except Exception as e:
        console.print(f"  [dim]Browser search fallback: {e}[/dim]")
        return ""


def _fetch_with_urllib(search_url: str) -> str:
    req = urllib.request.Request(
        search_url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    with safe_urlopen(req) as resp:
        data = resp.read(_MAX_SEARCH_HTML_BYTES + 1)
    if len(data) > _MAX_SEARCH_HTML_BYTES:
        raise NetworkError(
            f"search response exceeds the {_MAX_SEARCH_HTML_BYTES:,}-byte cap", url=search_url
        )
    return data.decode("utf-8", "ignore")


def _build_search_url(query: str) -> str:
    return "https://www.youtube.com/results?search_query=" + urllib.parse.quote_plus(query)


def _is_search_url(value: str) -> bool:
    try:
        parsed = urllib.parse.urlsplit(value)
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and (parsed.hostname or "").lower() == "www.youtube.com"
        and parsed.username is None
        and parsed.password is None
        and port is None
        and parsed.path == "/results"
        and bool(parsed.query)
        and not parsed.fragment
    )


def _extract_text(node: object) -> str:
    if not node:
        return ""
    if not isinstance(node, list):
        return _first_text(node)
    parts: list[str] = []
    characters = 0
    for index, item in enumerate(node):
        if index >= _MAX_TEXT_NODES:
            break
        text = _first_text(item)
        if text:
            separator_chars = 1 if parts else 0
            remaining = _MAX_TEXT_CHARS - characters - separator_chars
            if remaining <= 0:
                break
            parts.append(text[:remaining])
            characters += separator_chars + min(len(text), remaining)
    return " ".join(parts)


def _first_text(node: object) -> str:
    pending = [node]
    visited = 0
    while pending:
        visited += 1
        if visited > _MAX_TEXT_NODES:
            return ""
        current = pending.pop()
        if isinstance(current, dict):
            if "simpleText" in current:
                simple_text = current.get("simpleText")
                return simple_text[:_MAX_TEXT_CHARS] if isinstance(simple_text, str) else ""
            runs = current.get("runs")
            if isinstance(runs, list):
                return _join_run_texts(runs)
            pending.extend(reversed(tuple(current.values())))
        elif isinstance(current, list):
            pending.extend(reversed(current))
    return ""


def _join_run_texts(runs: list[object]) -> str:
    parts: list[str] = []
    characters = 0
    for run in runs[:_MAX_TEXT_NODES]:
        if not isinstance(run, dict):
            continue
        text = run.get("text")
        if not isinstance(text, str):
            continue
        remaining = _MAX_TEXT_CHARS - characters
        if remaining <= 0:
            break
        parts.append(text[:remaining])
        characters += min(len(text), remaining)
    return "".join(parts)


def _extract_owner_url(renderer: dict[str, object]) -> str:
    for key in ("ownerText", "longBylineText"):
        owner = renderer.get(key)
        if not isinstance(owner, dict):
            continue
        runs = owner.get("runs")
        if not isinstance(runs, list) or not runs or not isinstance(runs[0], dict):
            continue
        nav = runs[0].get("navigationEndpoint", {})
        if not isinstance(nav, dict):
            continue
        browse = nav.get("browseEndpoint", {})
        if not isinstance(browse, dict):
            continue
        canonical = browse.get("canonicalBaseUrl")
        canonical_url = normalize_youtube_channel_url(canonical)
        if canonical_url:
            return canonical_url
        browse_id = browse.get("browseId")
        channel_url = youtube_channel_url(browse_id)
        if channel_url:
            return channel_url
    return ""


def _relative_to_yyyymmdd(text: str) -> str:
    dt = _relative_to_datetime(text)
    return dt.strftime("%Y%m%d") if dt else ""


def _relative_to_datetime(text: str) -> datetime | None:
    if not text or len(text) > _MAX_NUMERIC_LABEL_CHARS:
        return None
    text = text.lower().strip()
    for prefix in ("streamed ", "premiered "):
        if text.startswith(prefix):
            text = text.removeprefix(prefix).strip()
            break
    match = re.fullmatch(r"([0-9]+)\s+(minute|hour|day|week|month|year)s?\s+ago", text)
    if not match:
        return None
    value = parse_ascii_uint(match.group(1))
    if value is None:
        return None
    unit_delta = _RELATIVE_UNIT_DELTAS[match.group(2)]
    try:
        return datetime.now(UTC) - unit_delta * value
    except OverflowError:
        return None


def _duration_to_seconds(text: str) -> int:
    if not text or len(text) > _MAX_NUMERIC_LABEL_CHARS:
        return 0
    raw_parts = text.split(":")
    if len(raw_parts) not in {1, 2, 3}:
        return 0
    parts: list[int] = []
    for part in raw_parts:
        value = parse_ascii_uint(part)
        if value is None or value > _MAX_VIDEO_DURATION_SECONDS:
            return 0
        parts.append(value)
    if len(parts) == 3:
        duration = parts[0] * 3600 + parts[1] * 60 + parts[2]
        return duration if duration <= _MAX_VIDEO_DURATION_SECONDS else 0
    if len(parts) == 2:
        duration = parts[0] * 60 + parts[1]
        return duration if duration <= _MAX_VIDEO_DURATION_SECONDS else 0
    if len(parts) == 1:
        return parts[0]
    return 0


def _parse_int(text: str) -> int:
    if not text or len(text) > _MAX_NUMERIC_LABEL_CHARS:
        return 0
    match = re.fullmatch(r"([0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)\s+views?", text.strip(), re.I)
    if match is None:
        return 0
    value = parse_ascii_uint(match.group(1).replace(",", ""))
    return value if value is not None and value <= _MAX_VIEW_COUNT else 0


def _parse_upload_date(upload_date: str) -> datetime | None:
    try:
        return datetime.strptime(upload_date, "%Y%m%d").replace(tzinfo=UTC)
    except ValueError:
        return None

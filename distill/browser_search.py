"""Browser-based YouTube search discovery with fallback parsing."""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

from rich.console import Console

from distill.discovery import VideoInfo
from distill.net import safe_urlopen

console = Console()
_YT_INITIAL_DATA_RE = re.compile(r"var ytInitialData = (\{.*?\});</script>", re.DOTALL)


def search_youtube_results(
    query_or_url: str, days: int = 60, limit: int = 20, hours: int | None = None
) -> list[VideoInfo]:
    """Search YouTube using the actual results page and return video candidates."""
    if limit <= 0:
        return []

    search_url = query_or_url if _is_search_url(query_or_url) else _build_search_url(query_or_url)
    html = _fetch_search_html(search_url)
    if not html:
        return []

    candidates = parse_search_results_html(html)
    now = datetime.now()
    cutoff = now - timedelta(hours=hours) if hours is not None else now - timedelta(days=days)
    results = []
    seen_ids = set()
    for video in candidates:
        if video.video_id in seen_ids:
            continue
        published_dt = _published_to_datetime(video)
        if published_dt and published_dt < cutoff:
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
    data = json.loads(match.group(1))

    results: list[VideoInfo] = []

    def walk(node):
        if isinstance(node, dict):
            renderer = node.get("videoRenderer")
            if renderer:
                video = _video_from_renderer(renderer)
                if video:
                    results.append(video)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(data)
    return results


def _video_from_renderer(renderer: dict) -> VideoInfo | None:
    video_id = renderer.get("videoId") or ""
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
        url=f"https://www.youtube.com/watch?v={video_id}",
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
            pass
    return _parse_upload_date(video.upload_date)


def _fetch_search_html(search_url: str) -> str:
    html = _fetch_with_playwright(search_url)
    if html:
        return html
    return _fetch_with_urllib(search_url)


def _fetch_with_playwright(search_url: str) -> str:
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return ""

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(1500)
            html = page.content()
            browser.close()
            return html
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
        return resp.read().decode("utf-8", "ignore")


def _build_search_url(query: str) -> str:
    return "https://www.youtube.com/results?search_query=" + urllib.parse.quote_plus(query)


def _is_search_url(value: str) -> bool:
    return value.startswith("https://www.youtube.com/results?") or value.startswith(
        "http://www.youtube.com/results?"
    )


def _extract_text(node) -> str:
    if not node:
        return ""
    if isinstance(node, dict):
        if "simpleText" in node:
            return node.get("simpleText", "")
        runs = node.get("runs")
        if isinstance(runs, list):
            return "".join(run.get("text", "") for run in runs)
        for value in node.values():
            text = _extract_text(value)
            if text:
                return text
    elif isinstance(node, list):
        return " ".join(filter(None, (_extract_text(item) for item in node)))
    return ""


def _extract_owner_url(renderer: dict) -> str:
    for key in ("ownerText", "longBylineText"):
        runs = renderer.get(key, {}).get("runs", [])
        if not runs:
            continue
        nav = runs[0].get("navigationEndpoint", {})
        browse = nav.get("browseEndpoint", {})
        canonical = browse.get("canonicalBaseUrl")
        if canonical:
            return "https://www.youtube.com" + canonical
        browse_id = browse.get("browseId")
        if browse_id:
            return f"https://www.youtube.com/channel/{browse_id}"
    return ""


def _relative_to_yyyymmdd(text: str) -> str:
    dt = _relative_to_datetime(text)
    return dt.strftime("%Y%m%d") if dt else ""


def _relative_to_datetime(text: str) -> datetime | None:
    if not text:
        return None
    text = text.lower().strip()
    if "streamed" in text:
        text = text.replace("streamed", "").strip()
    match = re.search(r"(\d+)\s+(minute|hour|day|week|month|year)s?\s+ago", text)
    if not match:
        return None
    value = int(match.group(1))
    unit = match.group(2)
    now = datetime.now()
    if unit == "minute":
        return now - timedelta(minutes=value)
    if unit == "hour":
        return now - timedelta(hours=value)
    if unit == "day":
        return now - timedelta(days=value)
    if unit == "week":
        return now - timedelta(weeks=value)
    if unit == "month":
        return now - timedelta(days=value * 30)
    return now - timedelta(days=value * 365)


def _duration_to_seconds(text: str) -> int:
    if not text:
        return 0
    parts = [int(p) for p in text.split(":") if p.isdigit()]
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    if len(parts) == 1:
        return parts[0]
    return 0


def _parse_int(text: str) -> int:
    if not text:
        return 0
    cleaned = re.sub(r"[^0-9]", "", text)
    return int(cleaned) if cleaned else 0


def _parse_upload_date(upload_date: str) -> datetime | None:
    try:
        return datetime.strptime(upload_date, "%Y%m%d")
    except ValueError:
        return None

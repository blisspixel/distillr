"""RSS podcast feed parsing and episode-material fetching.

RSS is the durable path for podcast ingestion -- the platform-app routes churn
with anti-bot countermeasures; the open feed is the publisher's own
distribution channel. Capture follows the adapter contract: deterministic
function of public input, fetched through :func:`safe_urlopen`, parsed with
``defusedxml`` (untrusted XML; same hygiene as the arXiv Atom parser).

The transcript ladder prefers free text over paid audio: when a feed carries
a ``<podcast:transcript>`` tag (the Podcasting 2.0 namespace), the publisher's
own transcript is fetched instead of downloading and transcribing the audio.
"""

from __future__ import annotations

import email.utils
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from defusedxml.ElementTree import fromstring as xml_fromstring

from distill.ingestors.net import safe_urlopen

__all__ = [
    "PodcastEpisode",
    "PodcastFeed",
    "PodcastFetchError",
    "download_audio",
    "fetch_feed",
    "fetch_transcript",
    "looks_like_feed_url",
    "parse_feed",
]

_MAX_FEED_BYTES = 5_000_000
_MAX_TRANSCRIPT_BYTES = 5_000_000
_MAX_AUDIO_BYTES = 250_000_000
_ITUNES_NS = "{http://www.itunes.com/dtds/podcast-1.0.dtd}"
# The Podcasting 2.0 namespace appears with both schemes in the wild.
_PODCAST_NSES = (
    "{https://podcastindex.org/namespace/1.0}",
    "{http://podcastindex.org/namespace/1.0}",
)


class PodcastFetchError(RuntimeError):
    """A feed, transcript, or audio file could not be fetched or parsed."""


@dataclass(frozen=True)
class PodcastEpisode:
    title: str
    guid: str
    published: str  # RFC 2822 as published; may be ""
    audio_url: str
    audio_type: str
    duration_s: int
    description: str
    transcript_url: str = ""
    transcript_type: str = ""

    def published_dt(self) -> datetime | None:
        try:
            return email.utils.parsedate_to_datetime(self.published)
        except (TypeError, ValueError):
            return None


@dataclass(frozen=True)
class PodcastFeed:
    title: str
    link: str
    description: str
    episodes: list[PodcastEpisode] = field(default_factory=list)


def looks_like_feed_url(url: str) -> bool:
    """Heuristic: does this URL look like an RSS feed rather than a page?"""
    path = urllib.parse.urlparse(url).path.lower()
    return (
        path.endswith((".rss", ".xml"))
        or path.rstrip("/").endswith(("/rss", "/feed", "/podcast.xml"))
        or "/feeds/" in path
    )


def _text(elem, tag: str) -> str:
    child = elem.find(tag)
    return (child.text or "").strip() if child is not None else ""


def _parse_duration(raw: str) -> int:
    """itunes:duration is seconds ("3120") or clock form ("52:00" / "1:02:03")."""
    raw = raw.strip()
    if not raw:
        return 0
    if raw.isdigit():
        return int(raw)
    parts = raw.split(":")
    if not all(p.strip().isdigit() for p in parts) or len(parts) > 3:
        return 0
    seconds = 0
    for part in parts:
        seconds = seconds * 60 + int(part)
    return seconds


def _episode_from_item(item) -> PodcastEpisode | None:
    enclosure = item.find("enclosure")
    audio_url = enclosure.get("url", "") if enclosure is not None else ""
    transcript_url = ""
    transcript_type = ""
    for ns in _PODCAST_NSES:
        t = item.find(f"{ns}transcript")
        if t is not None and t.get("url"):
            transcript_url = t.get("url", "")
            transcript_type = t.get("type", "")
            break
    title = _text(item, "title")
    if not title and not audio_url:
        return None  # an item with neither a title nor audio is not an episode
    description = _text(item, "description") or _text(item, f"{_ITUNES_NS}summary")
    return PodcastEpisode(
        title=title or "(untitled episode)",
        guid=_text(item, "guid") or audio_url,
        published=_text(item, "pubDate"),
        audio_url=audio_url,
        audio_type=enclosure.get("type", "") if enclosure is not None else "",
        duration_s=_parse_duration(_text(item, f"{_ITUNES_NS}duration")),
        description=re.sub(r"<[^>]+>", " ", description)[:4000].strip(),
        transcript_url=transcript_url,
        transcript_type=transcript_type,
    )


def parse_feed(xml_text: str) -> PodcastFeed:
    """Parse an RSS 2.0 podcast feed. Raises :class:`PodcastFetchError` on junk."""
    try:
        root = xml_fromstring(xml_text)
    except Exception as exc:  # defusedxml raises several parse/defense errors
        raise PodcastFetchError(f"Feed is not parseable XML: {exc}") from exc
    channel = root.find("channel")
    if channel is None:
        raise PodcastFetchError("Not an RSS podcast feed (no <channel> element).")
    episodes = [ep for item in channel.findall("item") if (ep := _episode_from_item(item))]
    # Newest first: sort by parsed pubDate when available, else keep feed order
    # (RSS convention is already newest-first).
    if any(ep.published_dt() for ep in episodes):
        episodes.sort(
            key=lambda e: e.published_dt() or datetime.min.replace(tzinfo=None),
            reverse=True,
        )
    return PodcastFeed(
        title=_text(channel, "title"),
        link=_text(channel, "link"),
        description=re.sub(r"<[^>]+>", " ", _text(channel, "description"))[:2000].strip(),
        episodes=episodes,
    )


def _fetch_bytes(url: str, *, max_bytes: int, what: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "distillr"})
    try:
        with safe_urlopen(request, timeout=60) as resp:
            data = resp.read(max_bytes + 1)
    except (
        urllib.error.URLError,
        urllib.error.HTTPError,
        TimeoutError,
        OSError,
        ValueError,
    ) as exc:
        raise PodcastFetchError(f"Could not fetch {what} from {url}: {exc}") from exc
    if len(data) > max_bytes:
        raise PodcastFetchError(f"{what} at {url} exceeds the {max_bytes:,}-byte cap.")
    return data


def fetch_feed(url: str) -> PodcastFeed:
    """Fetch and parse a podcast RSS feed."""
    raw = _fetch_bytes(url, max_bytes=_MAX_FEED_BYTES, what="feed")
    return parse_feed(raw.decode("utf-8", errors="replace"))


_VTT_CUE_RE = re.compile(r"^\s*(WEBVTT.*|\d+|(?:\d{1,2}:)?\d{2}:\d{2}[.,]\d{3}\s*-->.*)\s*$")


def _strip_caption_cues(text: str) -> str:
    """Reduce VTT/SRT caption files to plain transcript text."""
    lines = [line for line in text.splitlines() if not _VTT_CUE_RE.match(line)]
    out: list[str] = []
    for line in lines:
        line = line.strip()
        if line:
            out.append(line)
    return "\n".join(out)


def fetch_transcript(url: str, *, transcript_type: str = "") -> str:
    """Fetch a publisher transcript, normalizing VTT/SRT cue files to text."""
    raw = _fetch_bytes(url, max_bytes=_MAX_TRANSCRIPT_BYTES, what="transcript")
    text = raw.decode("utf-8", errors="replace")
    if (
        "vtt" in transcript_type.lower()
        or "srt" in transcript_type.lower()
        or text.lstrip().startswith("WEBVTT")
    ):
        return _strip_caption_cues(text)
    return text.strip()


def download_audio(url: str, dest_dir: Path) -> Path:
    """Download an episode enclosure to *dest_dir*; returns the file path."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    suffix = Path(urllib.parse.urlparse(url).path).suffix or ".mp3"
    dest = dest_dir / f"episode{suffix}"
    data = _fetch_bytes(url, max_bytes=_MAX_AUDIO_BYTES, what="audio")
    dest.write_bytes(data)
    return dest

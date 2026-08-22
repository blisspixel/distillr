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
import hashlib
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from xml.etree.ElementTree import Element

from distill.ingestors.net import NetworkError, safe_urlopen, url_for_diagnostic
from distill.library.paths import atomic_write_bytes
from distill.library.source_ledger import validate_source_id
from distill.parsing import parse_ascii_uint
from distill.xml_stream import iter_bounded_xml_events

__all__ = [
    "PodcastEpisode",
    "PodcastFeed",
    "PodcastFetchError",
    "download_audio",
    "feed_episode_identity",
    "fetch_feed",
    "fetch_transcript",
    "looks_like_feed_url",
    "parse_feed",
    "select_feed_episode",
]

_MAX_FEED_BYTES = 5_000_000
_MAX_TRANSCRIPT_BYTES = 5_000_000
_MAX_AUDIO_BYTES = 250_000_000
_MAX_DURATION_CHARS = 32
_MAX_EPISODE_DURATION_SECONDS = 30 * 24 * 60 * 60
_MAX_FEED_XML_NODES = 100_000
_MAX_FEED_EPISODES = 5_000
_MAX_TITLE_CHARS = 1_000
_MAX_GUID_CHARS = 4_096
_MAX_DATE_CHARS = 128
_MAX_URL_CHARS = 2_048
_MAX_MEDIA_TYPE_CHARS = 256
_MAX_DESCRIPTION_SOURCE_CHARS = 100_000
_MAX_CONTENT_HTML_CHARS = 200_000
_ITUNES_NS = "{http://www.itunes.com/dtds/podcast-1.0.dtd}"
_CONTENT_NS = "{http://purl.org/rss/1.0/modules/content/}"
# The Podcasting 2.0 namespace appears with both schemes in the wild.
_PODCAST_NSES = (
    "{https://podcastindex.org/namespace/1.0}",
    "{http://podcastindex.org/namespace/1.0}",
)
_EPISODE_ID_RE = re.compile(r"[0-9a-f]{40}\Z")
_AUDIO_SUFFIXES = frozenset(
    {".aac", ".flac", ".m4a", ".mp3", ".mp4", ".oga", ".ogg", ".opus", ".wav", ".webm"}
)


class PodcastFetchError(RuntimeError):
    """A feed, transcript, or audio file could not be fetched or parsed."""


@dataclass(frozen=True)
class PodcastEpisode:
    """One RSS item -- a podcast episode or (when no enclosure) a newsletter post."""

    title: str
    guid: str
    published: str  # RFC 2822 as published; may be ""
    audio_url: str
    audio_type: str
    duration_s: int
    description: str
    transcript_url: str = ""
    transcript_type: str = ""
    link: str = ""
    content_html: str = ""  # full post body (content:encoded), newsletter feeds

    def published_dt(self) -> datetime | None:
        try:
            parsed = email.utils.parsedate_to_datetime(self.published)
            if parsed is None:
                return None
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=UTC)
            return parsed.astimezone(UTC)
        except (OverflowError, TypeError, ValueError):
            return None


@dataclass(frozen=True)
class PodcastFeed:
    title: str
    link: str
    description: str
    episodes: list[PodcastEpisode] = field(default_factory=list)


def feed_episode_identity(feed_url: str, episode: PodcastEpisode) -> str:
    """Return the stable exact-item identity shared by preview and ingest."""

    identity_material = (
        f"guid:{episode.guid}"
        if episode.guid
        else f"link:{episode.link}"
        if episode.link
        else f"audio:{episode.audio_url}"
        if episode.audio_url
        else "\0".join(
            (
                "fields",
                episode.title,
                episode.published,
                episode.transcript_url,
                episode.content_html,
                episode.description,
            )
        )
    )
    return hashlib.blake2s(
        f"{feed_url}\0{identity_material}".encode("utf-8", errors="replace"),
        digest_size=20,
    ).hexdigest()


def select_feed_episode(
    feed_url: str,
    feed: PodcastFeed,
    episode_id: str,
) -> PodcastFeed:
    """Return a feed containing only the requested exact episode."""

    if _EPISODE_ID_RE.fullmatch(episode_id) is None:
        raise PodcastFetchError("Feed episode id must be 40 lowercase hexadecimal characters")
    matches = [
        episode
        for episode in feed.episodes
        if feed_episode_identity(feed_url, episode) == episode_id
    ]
    if not matches:
        raise PodcastFetchError(
            "Requested feed episode is no longer present; refresh the profile preview"
        )
    if len(matches) > 1:
        raise PodcastFetchError(
            "Requested feed episode identity is ambiguous; refresh the profile preview"
        )
    selected = matches[0]
    return PodcastFeed(
        title=feed.title,
        link=feed.link,
        description=feed.description,
        episodes=[selected],
    )


def looks_like_feed_url(url: str) -> bool:
    """Heuristic: does this URL look like an RSS feed rather than a page?"""
    path = urllib.parse.urlparse(url).path.lower()
    return (
        path.endswith((".rss", ".xml"))
        or path.rstrip("/").endswith(("/rss", "/feed", "/podcast.xml"))
        or "/feeds/" in path
    )


def _text(elem, tag: str, *, maximum: int, field_name: str) -> str:
    child = elem.find(tag)
    raw = child.text or "" if child is not None else ""
    if len(raw) > maximum:
        raise PodcastFetchError(f"feed {field_name} exceeds the {maximum:,}-character cap")
    return raw.strip()


def _bounded_attribute(value: str, *, maximum: int, field_name: str) -> str:
    if len(value) > maximum:
        raise PodcastFetchError(f"feed {field_name} exceeds the {maximum:,}-character cap")
    return value


def _validated_item_url(value: str, *, field_name: str) -> str:
    value = _bounded_attribute(value, maximum=_MAX_URL_CHARS, field_name=field_name)
    if not value:
        return ""
    if value != value.strip() or any(ord(character) < 32 for character in value):
        raise PodcastFetchError(f"feed {field_name} is not a valid HTTP URL")
    try:
        parsed = urllib.parse.urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise PodcastFetchError(f"feed {field_name} is not a valid HTTP URL") from exc
    if (
        parsed.scheme.casefold() not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or port == 0
    ):
        raise PodcastFetchError(f"feed {field_name} is not a valid HTTP URL")
    return value


def _parse_duration(raw: str) -> int:
    """itunes:duration is seconds ("3120") or clock form ("52:00" / "1:02:03")."""
    if not raw or len(raw) > _MAX_DURATION_CHARS:
        return 0
    raw = raw.strip()
    duration = parse_ascii_uint(raw)
    if duration is not None:
        return duration if duration <= _MAX_EPISODE_DURATION_SECONDS else 0
    parts = [part.strip() for part in raw.split(":")]
    if len(parts) > 3:
        return 0
    seconds = 0
    for part in parts:
        value = parse_ascii_uint(part)
        if value is None:
            return 0
        seconds = seconds * 60 + value
        if seconds > _MAX_EPISODE_DURATION_SECONDS:
            return 0
    return seconds


def _episode_from_item(item) -> PodcastEpisode | None:
    enclosure = item.find("enclosure")
    audio_url = _validated_item_url(
        enclosure.get("url", "") if enclosure is not None else "",
        field_name="audio URL",
    )
    transcript_url = ""
    transcript_type = ""
    for ns in _PODCAST_NSES:
        t = item.find(f"{ns}transcript")
        if t is not None and t.get("url"):
            transcript_url = _validated_item_url(
                t.get("url", ""),
                field_name="transcript URL",
            )
            transcript_type = _bounded_attribute(
                t.get("type", ""),
                maximum=_MAX_MEDIA_TYPE_CHARS,
                field_name="transcript type",
            )
            break
    title = _text(item, "title", maximum=_MAX_TITLE_CHARS, field_name="episode title")
    if not title and not audio_url:
        return None  # an item with neither a title nor audio is not an episode
    description = _text(
        item,
        "description",
        maximum=_MAX_DESCRIPTION_SOURCE_CHARS,
        field_name="episode description",
    ) or _text(
        item,
        f"{_ITUNES_NS}summary",
        maximum=_MAX_DESCRIPTION_SOURCE_CHARS,
        field_name="episode summary",
    )
    link = _validated_item_url(
        _text(item, "link", maximum=_MAX_URL_CHARS, field_name="episode link"),
        field_name="episode link",
    )
    duration_element = item.find(f"{_ITUNES_NS}duration")
    duration_text = duration_element.text or "" if duration_element is not None else ""
    guid = (
        _text(item, "guid", maximum=_MAX_GUID_CHARS, field_name="episode GUID") or audio_url or link
    )
    if guid:
        try:
            validate_source_id(guid)
        except ValueError as exc:
            raise PodcastFetchError(f"feed episode GUID {exc}") from exc
    return PodcastEpisode(
        title=title or "(untitled episode)",
        guid=guid,
        published=_text(item, "pubDate", maximum=_MAX_DATE_CHARS, field_name="publish date"),
        audio_url=audio_url,
        audio_type=_bounded_attribute(
            enclosure.get("type", "") if enclosure is not None else "",
            maximum=_MAX_MEDIA_TYPE_CHARS,
            field_name="audio type",
        ),
        duration_s=_parse_duration(duration_text),
        description=re.sub(r"<[^>]+>", " ", description)[:4000].strip(),
        transcript_url=transcript_url,
        transcript_type=transcript_type,
        link=link,
        content_html=_text(
            item,
            f"{_CONTENT_NS}encoded",
            maximum=_MAX_CONTENT_HTML_CHARS,
            field_name="episode content",
        ),
    )


@dataclass
class _FeedParseState:
    episodes: list[PodcastEpisode] = field(default_factory=list)
    channel_found: bool = False
    channel_depth: int = 0
    feed_title: str = ""
    feed_link: str = ""
    feed_description: str = ""

    def consume(self, event: str, element: Element) -> None:
        if event == "start":
            if element.tag == "channel":
                self.channel_found = True
                self.channel_depth += 1
            return
        if element.tag == "item" and self.channel_depth:
            episode = _episode_from_item(element)
            if episode is not None:
                self.episodes.append(episode)
            element.clear()
            return
        if element.tag != "channel":
            return
        self.feed_title = _text(
            element,
            "title",
            maximum=_MAX_TITLE_CHARS,
            field_name="title",
        )
        self.feed_link = _validated_item_url(
            _text(element, "link", maximum=_MAX_URL_CHARS, field_name="link"),
            field_name="link",
        )
        raw_description = _text(
            element,
            "description",
            maximum=_MAX_DESCRIPTION_SOURCE_CHARS,
            field_name="description",
        )
        self.feed_description = re.sub(r"<[^>]+>", " ", raw_description)[:2000].strip()
        self.channel_depth -= 1
        element.clear()


def parse_feed(xml_text: str) -> PodcastFeed:
    """Parse an RSS 2.0 podcast feed. Raises :class:`PodcastFetchError` on junk."""
    if len(xml_text) > _MAX_FEED_BYTES or len(xml_text.encode("utf-8")) > _MAX_FEED_BYTES:
        raise PodcastFetchError(f"feed exceeds the {_MAX_FEED_BYTES:,}-byte cap")
    state = _FeedParseState()
    try:
        for event, element in iter_bounded_xml_events(
            xml_text,
            max_nodes=_MAX_FEED_XML_NODES,
            record_tags=frozenset({"item"}),
            max_records=_MAX_FEED_EPISODES,
        ):
            state.consume(event, element)
    except Exception as exc:  # defusedxml raises several parse/defense errors
        if isinstance(exc, PodcastFetchError):
            raise
        raise PodcastFetchError(f"Feed is not parseable XML: {exc}") from exc
    if not state.channel_found:
        raise PodcastFetchError("Not an RSS podcast feed (no <channel> element).")
    # Newest first: sort by parsed pubDate when available, else keep feed order
    # (RSS convention is already newest-first).
    if any(ep.published_dt() for ep in state.episodes):
        state.episodes.sort(
            key=lambda e: e.published_dt() or datetime.min.replace(tzinfo=UTC),
            reverse=True,
        )
    return PodcastFeed(
        title=state.feed_title,
        link=state.feed_link,
        description=state.feed_description,
        episodes=state.episodes,
    )


def _fetch_bytes(url: str, *, max_bytes: int, what: str) -> bytes:
    displayed_url = url_for_diagnostic(url)
    request = urllib.request.Request(url, headers={"User-Agent": "distillr"})
    try:
        with safe_urlopen(request, timeout=60) as resp:
            data = resp.read(max_bytes + 1)
    except (
        NetworkError,  # safe_urlopen wraps HTTP/network failures in this
        urllib.error.URLError,
        urllib.error.HTTPError,
        TimeoutError,
        OSError,
        ValueError,
    ) as exc:
        raise PodcastFetchError(f"Could not fetch {what} from {displayed_url}.") from exc
    if len(data) > max_bytes:
        raise PodcastFetchError(f"{what} at {displayed_url} exceeds the {max_bytes:,}-byte cap.")
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
    parsed_suffix = Path(urllib.parse.urlparse(url).path).suffix.lower()
    suffix = parsed_suffix if parsed_suffix in _AUDIO_SUFFIXES else ".mp3"
    dest = dest_dir / f"episode{suffix}"
    data = _fetch_bytes(url, max_bytes=_MAX_AUDIO_BYTES, what="audio")
    atomic_write_bytes(dest, data)
    return dest

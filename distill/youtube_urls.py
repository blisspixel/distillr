"""Canonical validation for YouTube channel, video, and identifier URLs."""

from __future__ import annotations

import re
import urllib.parse

__all__ = [
    "normalize_channel_handle",
    "normalize_channel_id",
    "normalize_video_id",
    "normalize_youtube_channel_url",
    "normalize_youtube_video_url",
    "youtube_channel_url",
    "youtube_video_id_from_url",
    "youtube_watch_url",
]

_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_CHANNEL_ID_RE = re.compile(r"^UC[A-Za-z0-9_-]{6,62}$")
_CHANNEL_HANDLE_RE = re.compile(r"^@[A-Za-z0-9][A-Za-z0-9._-]{1,28}[A-Za-z0-9]$")
_CHANNEL_PATH_RE = re.compile(
    r"^/(?:(?P<handle>@[A-Za-z0-9][A-Za-z0-9._-]{1,28}[A-Za-z0-9])"
    r"|channel/(?P<channel_id>UC[A-Za-z0-9_-]{6,62}))"
    r"(?P<tab>/(?:videos|shorts))?/?$"
)
_YOUTUBE_CHANNEL_HOSTS = frozenset({"youtube.com", "www.youtube.com", "m.youtube.com"})
_MAX_CHANNEL_URL_CHARS = 2_048
_YOUTUBE_VIDEO_HOSTS = frozenset(
    {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"}
)
_YOUTUBE_SHORT_HOSTS = frozenset({"youtu.be", "www.youtu.be"})
_VIDEO_PATH_RE = re.compile(r"^/(?:shorts|embed|live)/(?P<video_id>[A-Za-z0-9_-]{1,64})/?$")
_SHORT_VIDEO_PATH_RE = re.compile(r"^/(?P<video_id>[A-Za-z0-9_-]{1,64})/?$")
_MAX_VIDEO_URL_CHARS = 2_048
_MAX_VIDEO_QUERY_FIELDS = 20


def normalize_video_id(value: object) -> str:
    """Return a bounded canonical video id, or an empty string when invalid."""

    return value if isinstance(value, str) and _VIDEO_ID_RE.fullmatch(value) else ""


def normalize_channel_id(value: object) -> str:
    """Return a canonical YouTube channel id, or an empty string when invalid."""

    return value if isinstance(value, str) and _CHANNEL_ID_RE.fullmatch(value) else ""


def normalize_channel_handle(value: object) -> str:
    """Return a canonical YouTube handle, or an empty string when invalid."""

    return value if isinstance(value, str) and _CHANNEL_HANDLE_RE.fullmatch(value) else ""


def youtube_channel_url(value: object) -> str:
    """Build a canonical channel URL from a validated handle or channel id."""

    handle = normalize_channel_handle(value)
    if handle:
        return f"https://www.youtube.com/{handle}"
    channel_id = normalize_channel_id(value)
    return f"https://www.youtube.com/channel/{channel_id}" if channel_id else ""


def normalize_youtube_channel_url(value: object) -> str:
    """Return a bounded canonical HTTPS channel URL, or an empty string."""

    if not isinstance(value, str) or not value or len(value) > _MAX_CHANNEL_URL_CHARS:
        return ""
    candidate = f"https://www.youtube.com{value}" if value.startswith("/") else value
    try:
        parsed = urllib.parse.urlsplit(candidate)
        port = parsed.port
    except ValueError:
        return ""
    if (
        parsed.scheme != "https"
        or (parsed.hostname or "").lower() not in _YOUTUBE_CHANNEL_HOSTS
        or parsed.username is not None
        or parsed.password is not None
        or port is not None
        or parsed.query
        or parsed.fragment
    ):
        return ""
    match = _CHANNEL_PATH_RE.fullmatch(parsed.path)
    if match is None:
        return ""
    identity = match.group("handle") or match.group("channel_id") or ""
    base = youtube_channel_url(identity)
    return f"{base}{match.group('tab') or ''}" if base else ""


def youtube_watch_url(value: object) -> str:
    """Build a canonical watch URL only for a validated video id."""

    video_id = normalize_video_id(value)
    return f"https://www.youtube.com/watch?v={video_id}" if video_id else ""


def youtube_video_id_from_url(value: object) -> str:
    """Extract a validated id from a supported HTTPS YouTube video URL."""

    if not isinstance(value, str) or not value or len(value) > _MAX_VIDEO_URL_CHARS:
        return ""
    try:
        parsed = urllib.parse.urlsplit(value)
        port = parsed.port
    except ValueError:
        return ""
    host = (parsed.hostname or "").lower()
    if (
        parsed.scheme != "https"
        or parsed.username is not None
        or parsed.password is not None
        or port is not None
        or parsed.fragment
    ):
        return ""
    if host in _YOUTUBE_SHORT_HOSTS:
        match = _SHORT_VIDEO_PATH_RE.fullmatch(parsed.path)
        return normalize_video_id(match.group("video_id")) if match else ""
    if host not in _YOUTUBE_VIDEO_HOSTS:
        return ""
    if parsed.path == "/watch":
        try:
            fields = urllib.parse.parse_qsl(
                parsed.query,
                keep_blank_values=True,
                max_num_fields=_MAX_VIDEO_QUERY_FIELDS,
            )
        except ValueError:
            return ""
        video_ids = [field_value for field_name, field_value in fields if field_name == "v"]
        return normalize_video_id(video_ids[0]) if len(video_ids) == 1 else ""
    match = _VIDEO_PATH_RE.fullmatch(parsed.path)
    return normalize_video_id(match.group("video_id")) if match else ""


def normalize_youtube_video_url(value: object) -> str:
    """Return a canonical watch URL for a supported YouTube video URL."""

    return youtube_watch_url(youtube_video_id_from_url(value))

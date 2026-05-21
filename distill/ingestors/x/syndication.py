"""Tweet retrieval via the public X syndication endpoint."""

from __future__ import annotations

import random
import re
import string
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import httpx

__all__ = [
    "SYNDICATION_BASE",
    "TweetRecord",
    "fetch_tweet",
    "parse_tweet_url",
]

SYNDICATION_BASE = "https://cdn.syndication.twimg.com/tweet-result"

# Tweet URL forms we accept:
#   https://x.com/<user>/status/<id>
#   https://twitter.com/<user>/status/<id>
#   https://x.com/i/status/<id>
#   https://twitter.com/i/web/status/<id>
_TWEET_RE = re.compile(
    r"^https?://(?:www\.)?(?:x|twitter)\.com/(?:i/(?:web/)?status|[^/]+/status)/(?P<id>\d+)",
    re.IGNORECASE,
)


@dataclass(slots=True)
class TweetRecord:
    """Normalized tweet fields used downstream."""

    tweet_id: str
    url: str
    author_name: str
    author_handle: str
    author_verified: bool
    created_at: str
    text: str
    language: str
    like_count: int
    reply_count: int
    photo_urls: list[str] = field(default_factory=list)
    # Video info, when the tweet has an attached amplify_video.
    video_url: str = ""
    video_poster: str = ""
    video_duration_ms: int = 0
    # Optional long-form ("note tweet") body if present.
    note_text: str = ""
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def display_handle(self) -> str:
        return f"@{self.author_handle}" if self.author_handle else self.author_name

    @property
    def short_id(self) -> str:
        return self.tweet_id[-10:]

    @property
    def has_video(self) -> bool:
        return bool(self.video_url)

    @property
    def published_iso(self) -> str:
        """Normalize created_at to ISO-8601 UTC."""
        if not self.created_at:
            return ""
        try:
            dt = datetime.strptime(self.created_at, "%Y-%m-%dT%H:%M:%S.%fZ")
        except ValueError:
            try:
                dt = datetime.strptime(self.created_at, "%Y-%m-%dT%H:%M:%S.000Z")
            except ValueError:
                return self.created_at
        return dt.isoformat() + "Z"


def parse_tweet_url(url: str) -> str | None:
    """Return the tweet id if *url* is a recognizable tweet URL, else None."""
    m = _TWEET_RE.match(url.strip())
    return m.group("id") if m else None


def _syndication_token(tweet_id: str) -> str:
    """Mimic the obfuscated token publishers supply.

    The syndication endpoint accepts any string for the ``token`` parameter
    in practice; the published widget uses a derived alphanumeric. Keep
    deterministic enough that retries don't drift.
    """
    rng = random.Random(int(tweet_id))
    return "".join(rng.choices(string.ascii_lowercase + string.digits, k=11))


def fetch_tweet(url_or_id: str, *, timeout: float = 20.0) -> TweetRecord:
    """Fetch a tweet via the public syndication endpoint.

    Accepts either a full tweet URL or a bare tweet id. Raises
    :class:`httpx.HTTPError` on transport failure and ``ValueError`` if
    the URL is unrecognized or the response is empty.
    """
    tweet_id = url_or_id if url_or_id.isdigit() else parse_tweet_url(url_or_id)
    if not tweet_id:
        raise ValueError(f"Not a recognizable tweet URL or id: {url_or_id!r}")

    params = {
        "id": tweet_id,
        "lang": "en",
        "token": _syndication_token(tweet_id),
    }
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        ),
        "Accept": "application/json",
    }

    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        resp = client.get(SYNDICATION_BASE, params=params, headers=headers)
        resp.raise_for_status()
        data = resp.json()

    if not data or not isinstance(data, dict):
        raise ValueError(f"Empty or unexpected syndication payload for tweet {tweet_id}")

    return _record_from_payload(tweet_id, data)


def _record_from_payload(tweet_id: str, data: dict[str, Any]) -> TweetRecord:
    user = data.get("user") or {}
    handle = str(user.get("screen_name") or "")
    canonical_url = (
        f"https://x.com/{handle}/status/{tweet_id}"
        if handle
        else f"https://x.com/i/status/{tweet_id}"
    )

    photos = [
        str(p.get("url"))
        for p in (data.get("photos") or [])
        if isinstance(p, dict) and p.get("url")
    ]

    video_url = ""
    video_poster = ""
    video_duration_ms = 0
    video = data.get("video") or {}
    if isinstance(video, dict):
        video_poster = str(video.get("poster") or "")
        video_duration_ms = int(video.get("durationMs") or 0)
        # Pick the best MP4 variant by bitrate (skip HLS m3u8 — we want
        # a direct download for Whisper-friendly local handling).
        best_bitrate = -1
        for variant in video.get("variants") or []:
            if not isinstance(variant, dict):
                continue
            v_url = str(variant.get("src") or variant.get("url") or "")
            if not v_url.endswith(".mp4"):
                continue
            bitrate = int(variant.get("bitrate") or 0)
            if bitrate > best_bitrate:
                best_bitrate = bitrate
                video_url = v_url

    # note_tweet (long-form) sometimes carries the full text where the
    # primary `text` field is truncated.
    note_text = ""
    note_tweet = data.get("note_tweet")
    if isinstance(note_tweet, dict):
        note_results = note_tweet.get("note_tweet_results") or {}
        result = note_results.get("result") or {}
        note_text = str(result.get("text") or "")

    return TweetRecord(
        tweet_id=tweet_id,
        url=canonical_url,
        author_name=str(user.get("name") or ""),
        author_handle=handle,
        author_verified=bool(user.get("verified") or user.get("is_blue_verified")),
        created_at=str(data.get("created_at") or ""),
        text=str(data.get("text") or ""),
        language=str(data.get("lang") or ""),
        like_count=int(data.get("favorite_count") or 0),
        reply_count=int(data.get("conversation_count") or 0),
        photo_urls=photos,
        video_url=video_url,
        video_poster=video_poster,
        video_duration_ms=video_duration_ms,
        note_text=note_text,
        raw=data,
    )

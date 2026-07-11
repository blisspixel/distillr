"""Tweet retrieval via the public X syndication endpoint."""

from __future__ import annotations

import json
import random
import re
import string
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import httpx

# Cap the (httpx auto-decompressed) syndication body so a gzip/br bomb from a
# hostile or compromised endpoint can't exhaust memory at JSON-parse time.
_MAX_SYNDICATION_BYTES = 5 * 1024 * 1024

__all__ = [
    "SYNDICATION_BASE",
    "TweetRecord",
    "fetch_tweet",
    "parse_tweet_url",
]

SYNDICATION_BASE = "https://cdn.syndication.twimg.com/tweet-result"


def _safe_int(value: object, default: int = 0) -> int:
    """Coerce an untrusted syndication field to int; a non-numeric value (the
    endpoint is public and unauthenticated) must not abort the whole ingest."""
    try:
        return int(value)  # type: ignore[arg-type]  # int() rejects bad types -> default
    except (TypeError, ValueError):
        return default


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
    # Public syndication exposes preview metadata for X Articles and cards,
    # but not necessarily the linked body.
    link_preview_type: str = ""
    link_preview_title: str = ""
    link_preview_description: str = ""
    link_preview_domain: str = ""
    link_preview_url: str = ""
    # A complete top-level ``quoted_tweet`` is a distinct source receipt, not
    # just an opaque link. ``partial`` means only its reference was supplied.
    quoted_tweet_status: str = "none"
    quoted_tweet_id: str = ""
    quoted_tweet_url: str = ""
    quoted_tweet_author_name: str = ""
    quoted_tweet_author_handle: str = ""
    quoted_tweet_text: str = ""
    # ``partial`` means syndication identified a note, X Article, or quoted
    # post whose source text was not present. It never means that Distill
    # fetched or inferred the missing content.
    capture_status: str = "complete"
    capture_warning: str = ""
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
    def has_link_preview(self) -> bool:
        return any(
            (
                self.link_preview_title,
                self.link_preview_description,
                self.link_preview_domain,
                self.link_preview_url,
            )
        )

    @property
    def has_quoted_post(self) -> bool:
        return self.quoted_tweet_status != "none"

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

    with (
        httpx.Client(timeout=timeout, follow_redirects=True) as client,
        client.stream("GET", SYNDICATION_BASE, params=params, headers=headers) as resp,
    ):
        resp.raise_for_status()
        buf = bytearray()
        for chunk in resp.iter_bytes():
            buf += chunk
            if len(buf) > _MAX_SYNDICATION_BYTES:
                raise ValueError(f"syndication payload exceeds {_MAX_SYNDICATION_BYTES}-byte cap")
        data = json.loads(bytes(buf))

    if not data or not isinstance(data, dict):
        raise ValueError(f"Empty or unexpected syndication payload for tweet {tweet_id}")

    return _record_from_payload(tweet_id, data)


def _binding_string(value: object) -> str:
    """Return a string from either syndication card binding shape."""
    if isinstance(value, str):
        return value
    if not isinstance(value, dict):
        return ""
    direct = value.get("string_value")
    if isinstance(direct, str):
        return direct
    nested = value.get("value")
    if isinstance(nested, str):
        return nested
    if isinstance(nested, dict):
        nested_string = nested.get("string_value")
        if isinstance(nested_string, str):
            return nested_string
    return ""


def _card_binding_items(bindings: object) -> list[tuple[object, object]]:
    if isinstance(bindings, dict):
        return list(bindings.items())
    if isinstance(bindings, list):
        return [
            (binding.get("key"), binding.get("value"))
            for binding in bindings
            if isinstance(binding, dict)
        ]
    return []


def _card_preview(data: dict[str, Any]) -> dict[str, str]:
    card = data.get("card")
    if not isinstance(card, dict):
        return {}
    bindings = card.get("binding_values")
    values: dict[str, str] = {}
    for key, value in _card_binding_items(bindings):
        if not isinstance(key, str):
            continue
        text = _binding_string(value)
        if text:
            values[key.casefold()] = text
    preview = {
        "title": values.get("title", ""),
        "description": values.get("description", ""),
        "domain": values.get("domain", ""),
        "url": values.get("card_url", ""),
    }
    return preview if any(preview.values()) else {}


def _article_preview(data: dict[str, Any]) -> tuple[bool, dict[str, str]]:
    article = data.get("article")
    if not isinstance(article, dict) or not article:
        return False, {}

    candidates: list[dict[str, Any]] = []
    article_results = article.get("article_results")
    if isinstance(article_results, dict):
        result = article_results.get("result")
        if isinstance(result, dict):
            candidates.append(result)
    direct_result = article.get("result")
    if isinstance(direct_result, dict):
        candidates.append(direct_result)
    candidates.append(article)

    def first_string(*keys: str) -> str:
        for candidate in candidates:
            for key in keys:
                value = candidate.get(key)
                if isinstance(value, str) and value:
                    return value
        return ""

    return True, {
        "title": first_string("title"),
        "description": first_string("preview_text", "description"),
        "domain": first_string("domain"),
        "url": first_string("article_url", "url"),
    }


def _note_tweet_text(data: dict[str, Any]) -> tuple[bool, str]:
    """Return whether a note exists and its full body when syndication supplied it."""

    note_tweet = data.get("note_tweet")
    if not isinstance(note_tweet, dict) or not note_tweet:
        return False, ""

    direct_text = note_tweet.get("text")
    if isinstance(direct_text, str) and direct_text:
        return True, direct_text

    note_results = note_tweet.get("note_tweet_results")
    if not isinstance(note_results, dict):
        return True, ""
    result = note_results.get("result")
    if not isinstance(result, dict):
        return True, ""
    text = result.get("text")
    return True, text if isinstance(text, str) else ""


def _quoted_tweet_fields(data: dict[str, Any]) -> dict[str, str]:
    quoted = data.get("quoted_tweet")
    top_level_id = data.get("quoted_tweet_id_str") or data.get("quoted_tweet_id")
    if not isinstance(quoted, dict):
        quote_id = str(quoted or top_level_id or "")
        return (
            {
                "status": "partial",
                "id": quote_id,
                "url": f"https://x.com/i/status/{quote_id}",
            }
            if quote_id
            else {"status": "none"}
        )
    if not quoted:
        quote_id = str(top_level_id or "")
        return (
            {
                "status": "partial",
                "id": quote_id,
                "url": f"https://x.com/i/status/{quote_id}",
            }
            if quote_id
            else {"status": "none"}
        )

    user = quoted.get("user")
    if not isinstance(user, dict):
        user = {}
    quote_id = str(
        quoted.get("id_str") or quoted.get("rest_id") or quoted.get("id") or top_level_id or ""
    )
    author_handle = str(user.get("screen_name") or "")
    explicit_url = quoted.get("url")
    quote_url = str(explicit_url) if isinstance(explicit_url, str) else ""
    if not quote_url and quote_id:
        quote_url = (
            f"https://x.com/{author_handle}/status/{quote_id}"
            if author_handle
            else f"https://x.com/i/status/{quote_id}"
        )
    text = quoted.get("text")
    short_text = text if isinstance(text, str) else ""
    has_note, note_text = _note_tweet_text(quoted)
    quote_text = note_text or short_text
    capture_warning = ""
    if has_note and not note_text:
        text_detail = (
            "The 280-character quoted-post text below is the available receipt, not the "
            "complete note."
            if len(short_text) == 280
            else "The quoted-post text below is the available receipt, not the complete note."
        )
        capture_warning = (
            "Public syndication identified a long-form note in the quoted post but did not "
            f"provide its full body. {text_detail}"
        )
    elif not quote_text:
        capture_warning = (
            "Public syndication identified a quoted post but did not provide its text. Only "
            "the quoted-post reference metadata below was captured."
        )
    return {
        "status": "partial" if capture_warning else "available",
        "id": quote_id,
        "url": quote_url,
        "author_name": str(user.get("name") or ""),
        "author_handle": author_handle,
        "text": quote_text,
        "capture_warning": capture_warning,
    }


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
        video_duration_ms = _safe_int(video.get("durationMs"))
        # Pick the best MP4 variant by bitrate (skip HLS m3u8 — we want
        # a direct download for Whisper-friendly local handling).
        best_bitrate = -1
        for variant in video.get("variants") or []:
            if not isinstance(variant, dict):
                continue
            v_url = str(variant.get("src") or variant.get("url") or "")
            if not v_url.endswith(".mp4"):
                continue
            bitrate = _safe_int(variant.get("bitrate"))
            if bitrate > best_bitrate:
                best_bitrate = bitrate
                video_url = v_url

    # note_tweet (long-form) sometimes carries the full text where the
    # primary `text` field is truncated.
    has_note_tweet, note_text = _note_tweet_text(data)

    card_preview = _card_preview(data)
    has_article, article_preview = _article_preview(data)
    quoted_tweet = _quoted_tweet_fields(data)
    preview = {
        key: article_preview.get(key) or card_preview.get(key) or ""
        for key in ("title", "description", "domain", "url")
    }

    capture_limitations: list[str] = []
    has_unavailable_note = has_note_tweet and not note_text
    if has_unavailable_note:
        text_detail = (
            "The 280-character Tweet text below is the available receipt, not the complete note."
            if len(str(data.get("text") or "")) == 280
            else "The Tweet text below is the available receipt, not the complete note."
        )
        capture_limitations.append(
            "Public syndication identified a long-form note but did not provide its full body. "
            + text_detail
        )
    if has_article:
        capture_limitations.append(
            "Public syndication provided X Article preview metadata only; the full article body "
            "was not captured."
        )
    if quoted_tweet["status"] == "partial":
        capture_limitations.append(
            quoted_tweet.get("capture_warning")
            or "Public syndication identified a quoted post but did not provide its text. Only "
            "the quoted-post reference metadata below was captured."
        )

    return TweetRecord(
        tweet_id=tweet_id,
        url=canonical_url,
        author_name=str(user.get("name") or ""),
        author_handle=handle,
        author_verified=bool(user.get("verified") or user.get("is_blue_verified")),
        created_at=str(data.get("created_at") or ""),
        text=str(data.get("text") or ""),
        language=str(data.get("lang") or ""),
        like_count=_safe_int(data.get("favorite_count")),
        reply_count=_safe_int(data.get("conversation_count")),
        photo_urls=photos,
        video_url=video_url,
        video_poster=video_poster,
        video_duration_ms=video_duration_ms,
        note_text=note_text,
        link_preview_type="x_article" if has_article else ("card" if card_preview else ""),
        link_preview_title=preview["title"],
        link_preview_description=preview["description"],
        link_preview_domain=preview["domain"],
        link_preview_url=preview["url"],
        quoted_tweet_status=quoted_tweet["status"],
        quoted_tweet_id=quoted_tweet.get("id", ""),
        quoted_tweet_url=quoted_tweet.get("url", ""),
        quoted_tweet_author_name=quoted_tweet.get("author_name", ""),
        quoted_tweet_author_handle=quoted_tweet.get("author_handle", ""),
        quoted_tweet_text=quoted_tweet.get("text", ""),
        capture_status="partial" if capture_limitations else "complete",
        capture_warning=" ".join(capture_limitations),
        raw=data,
    )

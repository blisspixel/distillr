"""Tweet retrieval via the public X syndication endpoint."""

from __future__ import annotations

import json
import math
import random
import re
import string
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from distill.parsing import parse_ascii_uint, parse_bounded_json_int


def __getattr__(name: str) -> object:
    """Lazily expose ``httpx`` so importing this module stays cheap.

    Only the live fetch path needs ``httpx``; deferring it keeps the library
    off the CLI startup path. Tests that patch
    ``distill.ingestors.x.syndication.httpx.Client`` keep working: this hook
    resolves ``httpx`` to the real module on first attribute access.
    """
    if name == "httpx":
        import httpx

        return httpx
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# Cap the (httpx auto-decompressed) syndication body so a gzip/br bomb from a
# hostile or compromised endpoint can't exhaust memory at JSON-parse time.
_MAX_SYNDICATION_BYTES = 5 * 1024 * 1024
_MAX_SYNDICATION_FIELD_INT = 2_147_483_647
_MAX_TWEET_ID = (1 << 64) - 1
_MAX_MEDIA_URL_CHARS = 2_048
_MAX_AUTHOR_NAME_CHARS = 256
_MAX_CREATED_AT_CHARS = 64
_MAX_LANGUAGE_CHARS = 32
_MAX_TWEET_TEXT_CHARS = 50_000
_MAX_PREVIEW_TITLE_CHARS = 2_000
_MAX_PREVIEW_DESCRIPTION_CHARS = 10_000
_MAX_PREVIEW_DOMAIN_CHARS = 253
_MAX_LINK_URL_CHARS = 2_048
_MAX_CARD_BINDINGS = 100
_MAX_PHOTOS = 16
_MAX_VIDEO_VARIANTS = 64
_MAX_NORMALIZED_SOURCE_CHARS = 100_000
_X_HANDLE_RE = re.compile(r"[A-Za-z0-9_]{1,15}")

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
    if isinstance(value, str):
        parsed = parse_ascii_uint(value)
    elif isinstance(value, int) and not isinstance(value, bool):
        parsed = value
    elif isinstance(value, float) and math.isfinite(value) and value.is_integer():
        parsed = int(value)
    else:
        parsed = None
    if parsed is None:
        return default
    return parsed if 0 <= parsed <= _MAX_SYNDICATION_FIELD_INT else default


def _parse_tweet_id(value: str) -> str | None:
    if len(value) > 20:
        return None
    parsed = parse_ascii_uint(value)
    if parsed is None or not 0 < parsed <= _MAX_TWEET_ID:
        return None
    return str(parsed)


# Tweet URL forms we accept:
#   https://x.com/<user>/status/<id>
#   https://twitter.com/<user>/status/<id>
#   https://x.com/i/status/<id>
#   https://twitter.com/i/web/status/<id>
_TWEET_PATH_RE = re.compile(
    r"^/(?:i/(?:web/)?status|[^/]+/status)/(?P<id>[0-9]+)(?=$|/)",
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
    try:
        parsed = urllib.parse.urlsplit(url.strip())
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme.casefold() not in {"http", "https"}
        or (parsed.hostname or "").casefold()
        not in {"x.com", "www.x.com", "twitter.com", "www.twitter.com"}
        or parsed.username is not None
        or parsed.password is not None
        or port is not None
    ):
        return None
    m = _TWEET_PATH_RE.match(parsed.path)
    if m is None:
        return None
    return _parse_tweet_id(m.group("id"))


def _syndication_token(tweet_id: str) -> str:
    """Mimic the obfuscated token publishers supply.

    The syndication endpoint accepts any string for the ``token`` parameter
    in practice; the published widget uses a derived alphanumeric. Keep
    deterministic enough that retries don't drift.
    """
    valid_id = _parse_tweet_id(tweet_id)
    if valid_id is None:
        raise ValueError("tweet_id must be a positive uint64 decimal identifier")
    rng = random.Random(int(valid_id))
    return "".join(rng.choices(string.ascii_lowercase + string.digits, k=11))


def fetch_tweet(url_or_id: str, *, timeout: float = 20.0) -> TweetRecord:
    """Fetch a tweet via the public syndication endpoint.

    Accepts either a full tweet URL or a bare tweet id. Raises
    :class:`httpx.HTTPError` on transport failure and ``ValueError`` if
    the URL is unrecognized or the response is empty.
    """
    import httpx

    tweet_id = _parse_tweet_id(url_or_id) or parse_tweet_url(url_or_id)
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
        "Accept-Encoding": "identity",
    }

    with (
        httpx.Client(timeout=timeout, follow_redirects=False, trust_env=False) as client,
        client.stream("GET", SYNDICATION_BASE, params=params, headers=headers) as resp,
    ):
        resp.raise_for_status()
        content_encoding = resp.headers.get("Content-Encoding", "").strip().casefold()
        if content_encoding not in {"", "identity"}:
            raise ValueError(f"unsupported syndication content encoding: {content_encoding}")
        declared_size = parse_ascii_uint(resp.headers.get("Content-Length", ""))
        if declared_size is not None and declared_size > _MAX_SYNDICATION_BYTES:
            raise ValueError(f"syndication payload exceeds {_MAX_SYNDICATION_BYTES}-byte cap")
        buf = bytearray()
        for chunk in resp.iter_raw(chunk_size=64 * 1024):
            if len(chunk) > _MAX_SYNDICATION_BYTES - len(buf):
                raise ValueError(f"syndication payload exceeds {_MAX_SYNDICATION_BYTES}-byte cap")
            buf.extend(chunk)
        data = json.loads(bytes(buf), parse_int=parse_bounded_json_int)

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


def _bounded_semantic_text(value: object, *, field_name: str, maximum: int) -> str:
    if not isinstance(value, str):
        return ""
    if len(value) > maximum:
        raise ValueError(f"syndication {field_name} exceeds the {maximum:,}-character cap")
    return value


def _card_binding_items(bindings: object) -> list[tuple[object, object]]:
    if isinstance(bindings, dict):
        if len(bindings) > _MAX_CARD_BINDINGS:
            raise ValueError("syndication card has too many binding values")
        return list(bindings.items())
    if isinstance(bindings, list):
        if len(bindings) > _MAX_CARD_BINDINGS:
            raise ValueError("syndication card has too many binding values")
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
        if not isinstance(key, str) or len(key) > 64:
            continue
        text = _binding_string(value)
        if text:
            normalized_key = key.casefold()
            maximum = {
                "title": _MAX_PREVIEW_TITLE_CHARS,
                "description": _MAX_PREVIEW_DESCRIPTION_CHARS,
                "domain": _MAX_PREVIEW_DOMAIN_CHARS,
                "card_url": _MAX_LINK_URL_CHARS,
            }.get(normalized_key)
            if maximum is not None:
                values[normalized_key] = _bounded_semantic_text(
                    text,
                    field_name=f"card {normalized_key}",
                    maximum=maximum,
                )
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
                    maximum = (
                        _MAX_PREVIEW_TITLE_CHARS
                        if key == "title"
                        else _MAX_PREVIEW_DESCRIPTION_CHARS
                        if key in {"preview_text", "description"}
                        else _MAX_PREVIEW_DOMAIN_CHARS
                        if key == "domain"
                        else _MAX_LINK_URL_CHARS
                    )
                    return _bounded_semantic_text(
                        value,
                        field_name=f"article {key}",
                        maximum=maximum,
                    )
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
        return True, _bounded_semantic_text(
            direct_text,
            field_name="note text",
            maximum=_MAX_TWEET_TEXT_CHARS,
        )

    note_results = note_tweet.get("note_tweet_results")
    if not isinstance(note_results, dict):
        return True, ""
    result = note_results.get("result")
    if not isinstance(result, dict):
        return True, ""
    text = result.get("text")
    return True, _bounded_semantic_text(
        text,
        field_name="note text",
        maximum=_MAX_TWEET_TEXT_CHARS,
    )


def _quoted_tweet_fields(data: dict[str, Any]) -> dict[str, str]:
    quoted = data.get("quoted_tweet")
    top_level_id = _first_tweet_id(data.get("quoted_tweet_id_str"), data.get("quoted_tweet_id"))
    if not isinstance(quoted, dict):
        quote_id = _first_tweet_id(quoted, top_level_id)
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
        quote_id = top_level_id
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
    quote_id = _first_tweet_id(
        quoted.get("id_str"),
        quoted.get("rest_id"),
        quoted.get("id"),
        top_level_id,
    )
    raw_explicit_url = quoted.get("url")
    explicit_url = _bounded_semantic_text(
        raw_explicit_url,
        field_name="quoted tweet URL",
        maximum=_MAX_LINK_URL_CHARS,
    )
    explicit_quote_id = parse_tweet_url(explicit_url) if explicit_url else None
    if not quote_id:
        quote_id = explicit_quote_id or ""
    if not quote_id:
        return {"status": "none"}
    raw_handle = user.get("screen_name")
    author_handle = (
        raw_handle if isinstance(raw_handle, str) and _X_HANDLE_RE.fullmatch(raw_handle) else ""
    )
    quote_url = explicit_url if explicit_quote_id == quote_id else ""
    if not quote_url and quote_id:
        quote_url = (
            f"https://x.com/{author_handle}/status/{quote_id}"
            if author_handle
            else f"https://x.com/i/status/{quote_id}"
        )
    text = quoted.get("text")
    short_text = _bounded_semantic_text(
        text,
        field_name="quoted tweet text",
        maximum=_MAX_TWEET_TEXT_CHARS,
    )
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
        "author_name": _bounded_semantic_text(
            user.get("name"),
            field_name="quoted author name",
            maximum=_MAX_AUTHOR_NAME_CHARS,
        ),
        "author_handle": author_handle,
        "text": quote_text,
        "capture_warning": capture_warning,
    }


def _first_tweet_id(*values: object) -> str:
    for value in values:
        if isinstance(value, str):
            candidate = value
        elif isinstance(value, int) and not isinstance(value, bool):
            candidate = str(value)
        else:
            continue
        parsed = _parse_tweet_id(candidate)
        if parsed is not None:
            return parsed
    return ""


def _media_url(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > _MAX_MEDIA_URL_CHARS:
        return ""
    if value != value.strip() or any(ord(character) < 32 for character in value):
        return ""
    try:
        parsed = urllib.parse.urlsplit(value)
        port = parsed.port
    except ValueError:
        return ""
    host = (parsed.hostname or "").casefold()
    if (
        parsed.scheme.casefold() != "https"
        or not (host == "twimg.com" or host.endswith(".twimg.com"))
        or parsed.username is not None
        or parsed.password is not None
        or port is not None
        or not parsed.path
        or parsed.fragment
    ):
        return ""
    return value


def _photo_urls(data: dict[str, Any]) -> list[str]:
    photos_value = data.get("photos")
    photo_items = photos_value if isinstance(photos_value, list) else []
    if len(photo_items) > _MAX_PHOTOS:
        raise ValueError("syndication payload has too many photos")
    return [
        url
        for item in photo_items
        if isinstance(item, dict)
        if (url := _media_url(item.get("url")))
    ]


def _video_fields(data: dict[str, Any]) -> tuple[str, str, int]:
    video = data.get("video") or {}
    if not isinstance(video, dict):
        return "", "", 0
    poster = _media_url(video.get("poster"))
    duration_ms = _safe_int(video.get("durationMs"))
    variants_value = video.get("variants")
    variants = variants_value if isinstance(variants_value, list) else []
    if len(variants) > _MAX_VIDEO_VARIANTS:
        raise ValueError("syndication video has too many variants")
    best_url = ""
    best_bitrate = -1
    for variant in variants:
        if not isinstance(variant, dict):
            continue
        url = _media_url(variant.get("src") or variant.get("url"))
        if not url or not urllib.parse.urlsplit(url).path.casefold().endswith(".mp4"):
            continue
        bitrate = _safe_int(variant.get("bitrate"))
        if bitrate > best_bitrate:
            best_bitrate = bitrate
            best_url = url
    return best_url, poster, duration_ms


def _capture_limitations(
    *,
    has_note_tweet: bool,
    note_text: str,
    primary_text: str,
    has_article: bool,
    quoted_tweet: dict[str, str],
) -> list[str]:
    limitations: list[str] = []
    if has_note_tweet and not note_text:
        text_detail = (
            "The 280-character Tweet text below is the available receipt, not the complete note."
            if len(primary_text) == 280
            else "The Tweet text below is the available receipt, not the complete note."
        )
        limitations.append(
            "Public syndication identified a long-form note but did not provide its full body. "
            + text_detail
        )
    if has_article:
        limitations.append(
            "Public syndication provided X Article preview metadata only; the full article body "
            "was not captured."
        )
    if quoted_tweet["status"] == "partial":
        limitations.append(
            quoted_tweet.get("capture_warning")
            or "Public syndication identified a quoted post but did not provide its text. Only "
            "the quoted-post reference metadata below was captured."
        )
    return limitations


def _record_from_payload(tweet_id: str, data: dict[str, Any]) -> TweetRecord:
    valid_tweet_id = _parse_tweet_id(tweet_id)
    if valid_tweet_id is None:
        raise ValueError("tweet_id must be a positive uint64 decimal identifier")
    user_value = data.get("user")
    user = user_value if isinstance(user_value, dict) else {}
    raw_handle = user.get("screen_name")
    handle = (
        raw_handle if isinstance(raw_handle, str) and _X_HANDLE_RE.fullmatch(raw_handle) else ""
    )
    canonical_url = (
        f"https://x.com/{handle}/status/{valid_tweet_id}"
        if handle
        else f"https://x.com/i/status/{valid_tweet_id}"
    )

    photos = _photo_urls(data)
    video_url, video_poster, video_duration_ms = _video_fields(data)

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

    primary_text = _bounded_semantic_text(
        data.get("text"),
        field_name="tweet text",
        maximum=_MAX_TWEET_TEXT_CHARS,
    )
    capture_limitations = _capture_limitations(
        has_note_tweet=has_note_tweet,
        note_text=note_text,
        primary_text=primary_text,
        has_article=has_article,
        quoted_tweet=quoted_tweet,
    )

    record = TweetRecord(
        tweet_id=valid_tweet_id,
        url=canonical_url,
        author_name=_bounded_semantic_text(
            user.get("name"),
            field_name="author name",
            maximum=_MAX_AUTHOR_NAME_CHARS,
        ),
        author_handle=handle,
        author_verified=user.get("verified") is True or user.get("is_blue_verified") is True,
        created_at=_bounded_semantic_text(
            data.get("created_at"),
            field_name="created_at",
            maximum=_MAX_CREATED_AT_CHARS,
        ),
        text=primary_text,
        language=_bounded_semantic_text(
            data.get("lang"),
            field_name="language",
            maximum=_MAX_LANGUAGE_CHARS,
        ),
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
    _enforce_normalized_source_budget(record)
    return record


def _enforce_normalized_source_budget(record: TweetRecord) -> None:
    semantic_values = (
        record.author_name,
        record.author_handle,
        record.created_at,
        record.text,
        record.language,
        record.note_text,
        record.link_preview_title,
        record.link_preview_description,
        record.link_preview_domain,
        record.link_preview_url,
        record.quoted_tweet_url,
        record.quoted_tweet_author_name,
        record.quoted_tweet_author_handle,
        record.quoted_tweet_text,
        *record.photo_urls,
    )
    if sum(len(value) for value in semantic_values) > _MAX_NORMALIZED_SOURCE_CHARS:
        raise ValueError(
            "normalized syndication source exceeds the "
            f"{_MAX_NORMALIZED_SOURCE_CHARS:,}-character cap"
        )

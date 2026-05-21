"""Tests for distill.ingestors.x.syndication."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import httpx
import pytest

from distill.ingestors.x.syndication import (
    TweetRecord,
    _record_from_payload,
    _syndication_token,
    fetch_tweet,
    parse_tweet_url,
)

# ---------------------------------------------------------------------------
# parse_tweet_url
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://x.com/CryptoTony__/status/2055709363701264550", "2055709363701264550"),
        ("https://twitter.com/Jouhatsu_ai/status/2055666094967320773", "2055666094967320773"),
        ("https://x.com/i/status/2055709363701264550", "2055709363701264550"),
        ("https://twitter.com/i/web/status/2055709363701264550", "2055709363701264550"),
        ("http://x.com/u/status/12345", "12345"),
        ("https://www.x.com/user/status/9876543210", "9876543210"),
        ("https://example.com/post/123", None),
        ("https://x.com/user/likes", None),
        ("not a url at all", None),
        ("", None),
    ],
)
def test_parse_tweet_url(url: str, expected: str | None) -> None:
    assert parse_tweet_url(url) == expected


def test_parse_tweet_url_strips_whitespace() -> None:
    assert parse_tweet_url("  https://x.com/u/status/123  ") == "123"


# ---------------------------------------------------------------------------
# _syndication_token
# ---------------------------------------------------------------------------


def test_syndication_token_deterministic() -> None:
    """Same tweet id should always produce same token (so retries don't drift)."""
    assert _syndication_token("1234567890") == _syndication_token("1234567890")
    assert _syndication_token("1234567890") != _syndication_token("9876543210")


def test_syndication_token_format() -> None:
    token = _syndication_token("2055709363701264550")
    assert len(token) == 11
    assert token.isalnum()
    assert token == token.lower()  # no uppercase


# ---------------------------------------------------------------------------
# _record_from_payload
# ---------------------------------------------------------------------------


def _payload(
    *,
    text: str = "Hello world",
    handle: str = "alice",
    name: str = "Alice Example",
    verified: bool = True,
    created_at: str = "2026-05-16T12:00:00.000Z",
    lang: str = "en",
    likes: int = 5,
    replies: int = 2,
    photos: list[dict[str, Any]] | None = None,
    video: dict[str, Any] | None = None,
    note_tweet: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "user": {"screen_name": handle, "name": name, "verified": verified},
        "text": text,
        "lang": lang,
        "favorite_count": likes,
        "conversation_count": replies,
        "created_at": created_at,
    }
    if photos is not None:
        payload["photos"] = photos
    if video is not None:
        payload["video"] = video
    if note_tweet is not None:
        payload["note_tweet"] = note_tweet
    return payload


def test_record_from_payload_minimal() -> None:
    rec = _record_from_payload("123", _payload(text="hi"))
    assert rec.tweet_id == "123"
    assert rec.author_handle == "alice"
    assert rec.author_name == "Alice Example"
    assert rec.author_verified is True
    assert rec.text == "hi"
    assert rec.like_count == 5
    assert rec.reply_count == 2
    assert rec.has_video is False
    assert rec.photo_urls == []
    assert rec.note_text == ""
    assert rec.url == "https://x.com/alice/status/123"


def test_record_from_payload_no_handle_uses_i_status_url() -> None:
    payload = _payload()
    payload["user"]["screen_name"] = ""
    rec = _record_from_payload("999", payload)
    assert rec.url == "https://x.com/i/status/999"


def test_record_from_payload_blue_verified_falls_through() -> None:
    payload = _payload(verified=False)
    payload["user"]["is_blue_verified"] = True
    rec = _record_from_payload("1", payload)
    assert rec.author_verified is True


def test_record_from_payload_photos() -> None:
    payload = _payload(
        photos=[
            {"url": "https://pbs.twimg.com/a.jpg"},
            {"url": "https://pbs.twimg.com/b.jpg"},
            {"not_a_url": "skip"},
        ]
    )
    rec = _record_from_payload("1", payload)
    assert rec.photo_urls == [
        "https://pbs.twimg.com/a.jpg",
        "https://pbs.twimg.com/b.jpg",
    ]


def test_record_from_payload_picks_highest_bitrate_mp4() -> None:
    video = {
        "poster": "https://pbs.twimg.com/poster.jpg",
        "durationMs": 60000,
        "variants": [
            {"src": "https://video.twimg.com/low.mp4", "bitrate": 200_000},
            {"src": "https://video.twimg.com/high.mp4", "bitrate": 832_000},
            {"src": "https://video.twimg.com/playlist.m3u8"},
            {"src": "https://video.twimg.com/mid.mp4", "bitrate": 400_000},
        ],
    }
    rec = _record_from_payload("1", _payload(video=video))
    assert rec.has_video is True
    assert rec.video_url == "https://video.twimg.com/high.mp4"
    assert rec.video_poster == "https://pbs.twimg.com/poster.jpg"
    assert rec.video_duration_ms == 60000


def test_record_from_payload_video_without_mp4_variants() -> None:
    video = {"variants": [{"src": "https://video.twimg.com/only.m3u8"}]}
    rec = _record_from_payload("1", _payload(video=video))
    assert rec.has_video is False
    assert rec.video_url == ""


def test_record_from_payload_note_tweet_extraction() -> None:
    note = {
        "note_tweet_results": {"result": {"text": "Long-form body text that exceeds 280 chars."}}
    }
    rec = _record_from_payload("1", _payload(note_tweet=note))
    assert rec.note_text.startswith("Long-form body")


def test_record_from_payload_empty_or_missing_user() -> None:
    """No user key should not crash; defaults to empty strings."""
    rec = _record_from_payload("42", {"text": "stub"})
    assert rec.author_handle == ""
    assert rec.author_name == ""
    assert rec.author_verified is False


# ---------------------------------------------------------------------------
# TweetRecord properties
# ---------------------------------------------------------------------------


def _record(**kwargs: Any) -> TweetRecord:
    defaults: dict[str, Any] = {
        "tweet_id": "1234567890",
        "url": "https://x.com/u/status/1234567890",
        "author_name": "Alice",
        "author_handle": "alice",
        "author_verified": False,
        "created_at": "2026-05-16T12:00:00.000Z",
        "text": "hi",
        "language": "en",
        "like_count": 0,
        "reply_count": 0,
    }
    defaults.update(kwargs)
    return TweetRecord(**defaults)


def test_display_handle_uses_at_prefix() -> None:
    assert _record(author_handle="alice").display_handle == "@alice"


def test_display_handle_falls_back_to_author_name_if_no_handle() -> None:
    assert _record(author_handle="", author_name="Bob").display_handle == "Bob"


def test_short_id_last_ten_chars() -> None:
    assert _record(tweet_id="2055709363701264550").short_id == "3701264550"


def test_published_iso_with_dotms_format() -> None:
    rec = _record(created_at="2026-05-16T17:58:00.000Z")
    assert rec.published_iso == "2026-05-16T17:58:00Z"


def test_published_iso_with_microseconds_format() -> None:
    """123 in .123Z is parsed as 123000 microseconds (i.e. milliseconds)."""
    rec = _record(created_at="2026-05-16T17:58:00.123Z")
    assert rec.published_iso == "2026-05-16T17:58:00.123000Z"


def test_published_iso_falls_back_to_raw_when_unparseable() -> None:
    rec = _record(created_at="not a date")
    assert rec.published_iso == "not a date"


def test_published_iso_empty_when_no_date() -> None:
    assert _record(created_at="").published_iso == ""


# ---------------------------------------------------------------------------
# fetch_tweet (network mocked)
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, data: dict[str, Any], status_code: int = 200) -> None:
        self._data = data
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("err", request=None, response=None)  # type: ignore[arg-type]

    def json(self) -> Any:
        return self._data


class _FakeClient:
    def __init__(self, data: Any) -> None:
        self._data = data
        self.get_calls: list[tuple[str, dict, dict]] = []

    def __enter__(self) -> _FakeClient:
        return self

    def __exit__(self, *_: Any) -> None:
        pass

    def get(self, url: str, params: dict, headers: dict) -> _FakeResponse:
        self.get_calls.append((url, params, headers))
        return _FakeResponse(self._data)


def test_fetch_tweet_accepts_bare_id() -> None:
    payload = _payload(text="raw id path")
    fake = _FakeClient(payload)
    with patch("distill.ingestors.x.syndication.httpx.Client", return_value=fake):
        rec = fetch_tweet("2055709363701264550")
    assert rec.tweet_id == "2055709363701264550"
    assert rec.text == "raw id path"
    # Token was supplied (any string is fine, just verify it's there)
    assert "token" in fake.get_calls[0][1]


def test_fetch_tweet_unrecognized_url_raises() -> None:
    with pytest.raises(ValueError, match="recognizable"):
        fetch_tweet("https://example.com/not-a-tweet")


def test_fetch_tweet_empty_payload_raises() -> None:
    fake = _FakeClient(None)
    with (
        patch("distill.ingestors.x.syndication.httpx.Client", return_value=fake),
        pytest.raises(ValueError, match="syndication payload"),
    ):
        fetch_tweet("https://x.com/u/status/1")

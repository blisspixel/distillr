"""Tests for distill.ingestors.x.syndication."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

import httpx
import pytest

from distill.ingestors.x.syndication import (
    TweetRecord,
    _record_from_payload,
    _safe_int,
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
        ("https://x.com/u/status/123?lang=en", "123"),
        ("https://x.com/u/status/000123", "123"),
        ("https://x.com/u/status/123/analytics", "123"),
        ("https://x.com/user?next=/status/123", None),
        ("https://x.com/user#frag/status/123", None),
        ("https://x.com/?next=/status/123", None),
        ("https://user@x.com/u/status/123", None),
        ("https://x.com:443/u/status/123", None),
        ("https://x.com/u/status/123abc", None),
        ("https://x.com/u/status/" + "9" * 5000, None),
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


@pytest.mark.parametrize(
    "value",
    [
        float("inf"),
        10**4000,
        "9" * 4000,
        "\u0661\u0662",
        "\u00b2",
        "+12",
        " 12 ",
        1.9,
        True,
        -1,
        2_147_483_648,
    ],
)
def test_safe_int_rejects_unbounded_or_non_count_values(value: object) -> None:
    assert _safe_int(value) == 0


def test_safe_int_accepts_ascii_and_integral_values_at_the_boundary() -> None:
    assert _safe_int("12") == 12
    assert _safe_int(12.0) == 12
    assert _safe_int(2_147_483_647) == 2_147_483_647


# ---------------------------------------------------------------------------
# _record_from_payload
# ---------------------------------------------------------------------------


_FIXTURE_DIR = Path(__file__).parents[3] / "fixtures" / "x"


def _fixture(name: str) -> dict[str, Any]:
    payload = json.loads((_FIXTURE_DIR / name).read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


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


def test_record_from_payload_non_numeric_video_fields_do_not_crash() -> None:
    # The public syndication endpoint is untrusted; a non-numeric durationMs or
    # bitrate must coerce to 0, not abort ingest with ValueError.
    payload = _payload()
    payload["video"] = {
        "durationMs": "not-a-number",
        "variants": [{"src": "https://video.twimg.com/x.mp4", "bitrate": "lots"}],
    }
    rec = _record_from_payload("7", payload)
    assert rec.has_video is True
    assert rec.video_duration_ms == 0


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


@pytest.mark.parametrize(
    "url",
    [
        "http://[",
        "https://example.com/a.jpg",
        "https://user@pbs.twimg.com/a.jpg",
        "https://pbs.twimg.com:443/a.jpg",
        "https://pbs.twimg.com/a.jpg#fragment",
        " https://pbs.twimg.com/a.jpg",
        "https://pbs.twimg.com/" + "a" * 2_048,
    ],
)
def test_record_from_payload_omits_malformed_or_untrusted_media_urls(url: str) -> None:
    payload = _payload(photos=[{"url": url}])
    payload["video"] = {
        "poster": url,
        "variants": [{"src": url, "bitrate": 100}],
    }

    record = _record_from_payload("42", payload)

    assert record.photo_urls == []
    assert record.video_poster == ""
    assert record.video_url == ""


@pytest.mark.parametrize("handle", ["bad/handle", "a" * 16, "@alice", {"x": 1}])
def test_record_from_payload_rejects_malformed_primary_handle(handle: object) -> None:
    payload = _payload()
    payload["user"]["screen_name"] = handle

    record = _record_from_payload("42", payload)

    assert record.author_handle == ""
    assert record.url == "https://x.com/i/status/42"


def test_record_from_payload_rejects_near_body_cap_semantic_text() -> None:
    payload = _payload(text="x" * 4_900_000)

    with pytest.raises(ValueError, match="tweet text exceeds"):
        _record_from_payload("42", payload)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("photos", [{}] * 17, "too many photos"),
        ("video", {"variants": [{}] * 65}, "too many variants"),
        (
            "card",
            {"binding_values": {f"key-{index}": "x" for index in range(101)}},
            "too many binding values",
        ),
    ],
)
def test_record_from_payload_rejects_oversized_semantic_collections(
    field: str,
    value: object,
    message: str,
) -> None:
    payload = _payload()
    payload[field] = value

    with pytest.raises(ValueError, match=message):
        _record_from_payload("42", payload)


def test_record_from_payload_does_not_stringify_nonstring_core_fields() -> None:
    payload = _payload()
    payload["text"] = {"hostile": "text"}
    payload["created_at"] = ["hostile"]
    payload["lang"] = {"value": "en"}
    payload["user"] = {
        "screen_name": "alice",
        "name": {"hostile": "name"},
        "verified": {"truthy": True},
    }

    record = _record_from_payload("42", payload)

    assert record.text == ""
    assert record.created_at == ""
    assert record.language == ""
    assert record.author_name == ""
    assert record.author_verified is False


def test_record_from_payload_enforces_total_normalized_source_budget() -> None:
    payload = _payload(
        text="t" * 50_000,
        note_tweet={"text": "n" * 50_000},
        name="A",
    )

    with pytest.raises(ValueError, match="normalized syndication source"):
        _record_from_payload("42", payload)


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


def test_record_from_payload_accepts_direct_note_text() -> None:
    rec = _record_from_payload("1", _payload(note_tweet={"text": "Direct long-form body."}))

    assert rec.note_text == "Direct long-form body."
    assert rec.capture_status == "complete"


def test_record_from_live_shape_marks_id_only_280_char_note_partial() -> None:
    payload = _fixture("note_tweet_id_only.json")
    assert len(payload["text"]) == 280

    rec = _record_from_payload("2045000000000000001", payload)

    assert rec.note_text == ""
    assert rec.capture_status == "partial"
    assert "did not provide its full body" in rec.capture_warning
    assert "280-character Tweet text" in rec.capture_warning
    assert rec.has_link_preview is False


def test_record_from_live_shape_extracts_article_and_card_fallback_metadata() -> None:
    rec = _record_from_payload(
        "2045000000000000002",
        _fixture("article_preview.json"),
    )

    assert rec.text == "https://t.co/article-only"
    assert rec.link_preview_type == "x_article"
    assert rec.link_preview_title == "Designing durable agent queues"
    assert rec.link_preview_description.startswith("A practical look")
    assert rec.link_preview_domain == "x.com"
    assert rec.link_preview_url == "https://x.com/i/article/2045000000000000002"
    assert rec.capture_status == "partial"
    assert "preview metadata only" in rec.capture_warning
    assert rec.has_link_preview is True


def test_record_from_live_shape_extracts_card_binding_values() -> None:
    rec = _record_from_payload(
        "2045000000000000003",
        _fixture("card_preview.json"),
    )

    assert rec.link_preview_type == "card"
    assert rec.link_preview_title == "Testing long-running agent loops"
    assert rec.link_preview_description.startswith("Failure injection")
    assert rec.link_preview_domain == "example.org"
    assert rec.link_preview_url == "https://example.org/agent-loop-qa"
    assert rec.capture_status == "complete"
    assert rec.capture_warning == ""


def test_record_from_live_shape_preserves_complete_quoted_tweet() -> None:
    rec = _record_from_payload(
        "2045000000000000004",
        _fixture("quoted_tweet_complete.json"),
    )

    assert rec.quoted_tweet_status == "available"
    assert rec.quoted_tweet_id == "2032727335074722216"
    assert rec.quoted_tweet_author_name == "François Chollet"
    assert rec.quoted_tweet_author_handle == "fchollet"
    assert rec.quoted_tweet_url == "https://x.com/fchollet/status/2032727335074722216"
    assert len(rec.quoted_tweet_text) == 268
    assert rec.has_quoted_post is True
    assert rec.capture_status == "complete"
    assert "quoted post" not in rec.capture_warning


def test_record_from_live_shape_uses_complete_nested_quoted_note_body() -> None:
    payload = _fixture("quoted_tweet_note_complete.json")

    rec = _record_from_payload("2045000000000000006", payload)

    assert rec.quoted_tweet_status == "available"
    assert rec.quoted_tweet_id == "2032727335074722218"
    assert rec.quoted_tweet_text.startswith("Full quoted long-form body")
    assert rec.quoted_tweet_text != payload["quoted_tweet"]["text"]
    assert rec.capture_status == "complete"
    assert rec.capture_warning == ""


def test_record_from_live_shape_marks_id_only_nested_quoted_note_partial() -> None:
    payload = _fixture("quoted_tweet_note_id_only.json")
    assert len(payload["quoted_tweet"]["text"]) == 280

    rec = _record_from_payload("2045000000000000007", payload)

    assert rec.quoted_tweet_status == "partial"
    assert rec.quoted_tweet_id == "2032727335074722217"
    assert rec.quoted_tweet_text == payload["quoted_tweet"]["text"]
    assert rec.capture_status == "partial"
    assert "long-form note in the quoted post" in rec.capture_warning
    assert "280-character quoted-post text" in rec.capture_warning
    assert "Only the quoted-post reference metadata" not in rec.capture_warning


def test_record_from_live_shape_marks_quoted_tweet_reference_partial() -> None:
    rec = _record_from_payload(
        "2045000000000000005",
        _fixture("quoted_tweet_reference_only.json"),
    )

    assert rec.quoted_tweet_status == "partial"
    assert rec.quoted_tweet_id == "2032727335074722216"
    assert rec.quoted_tweet_text == ""
    assert rec.capture_status == "partial"
    assert "did not provide its text" in rec.capture_warning
    assert rec.has_quoted_post is True


def test_record_from_payload_accepts_top_level_quote_reference_and_explicit_url() -> None:
    reference_payload = _payload()
    reference_payload["quoted_tweet_id_str"] = "00091"
    reference = _record_from_payload("9", reference_payload)
    assert reference.quoted_tweet_status == "partial"
    assert reference.quoted_tweet_id == "91"
    assert reference.quoted_tweet_url == "https://x.com/i/status/91"

    explicit_payload = _payload()
    explicit_payload["quoted_tweet"] = {
        "id_str": "92",
        "url": "https://twitter.com/source/status/92",
        "text": "quoted body",
    }
    explicit = _record_from_payload("10", explicit_payload)
    assert explicit.quoted_tweet_status == "available"
    assert explicit.quoted_tweet_url == "https://twitter.com/source/status/92"


def test_record_from_payload_accepts_list_card_bindings_and_nested_article_result() -> None:
    payload = _payload(text="https://t.co/nested")
    payload["article"] = {
        "article_results": {
            "result": {
                "title": "Nested article title",
                "preview_text": "Nested article preview",
            }
        }
    }
    payload["card"] = {
        "binding_values": [
            {"key": "domain", "value": {"string_value": "nested.example"}},
            {"key": "card_url", "value": "https://nested.example/article"},
            {"key": 4, "value": {"string_value": "ignored"}},
            "ignored",
        ]
    }

    rec = _record_from_payload("4", payload)

    assert rec.link_preview_title == "Nested article title"
    assert rec.link_preview_description == "Nested article preview"
    assert rec.link_preview_domain == "nested.example"
    assert rec.link_preview_url == "https://nested.example/article"


def test_record_from_payload_accepts_direct_article_result_and_ignores_bad_card_values() -> None:
    payload = _payload()
    payload["article"] = {"result": {"title": "Direct result title"}}
    payload["card"] = {
        "binding_values": {
            "description": 7,
            9: {"string_value": "ignored"},
        }
    }

    rec = _record_from_payload("5", payload)

    assert rec.link_preview_title == "Direct result title"
    assert rec.link_preview_description == ""
    assert rec.capture_status == "partial"


def test_record_from_payload_accepts_alternate_card_value_wrappers() -> None:
    payload = _payload()
    payload["card"] = {
        "binding_values": {
            "title": {"value": "Nested string title"},
            "description": {"value": {"string_value": "Nested dictionary description"}},
            "domain": {"value": {}},
        }
    }

    rec = _record_from_payload("6", payload)

    assert rec.link_preview_title == "Nested string title"
    assert rec.link_preview_description == "Nested dictionary description"
    assert rec.link_preview_domain == ""


def test_record_from_payload_ignores_malformed_card_and_article_results() -> None:
    payload = _payload()
    payload["card"] = {"binding_values": 7}
    payload["article"] = {
        "article_results": {"result": "not a result"},
        "title": "Direct fallback title",
    }

    rec = _record_from_payload("7", payload)

    assert rec.link_preview_title == "Direct fallback title"
    assert rec.link_preview_type == "x_article"


def test_record_from_payload_id_only_short_note_uses_generic_partial_warning() -> None:
    rec = _record_from_payload(
        "8",
        _payload(text="short receipt", note_tweet={"id": "NT-8"}),
    )

    assert rec.capture_status == "partial"
    assert "Tweet text below is the available receipt" in rec.capture_warning
    assert "280-character" not in rec.capture_warning


def test_record_from_payload_empty_or_missing_user() -> None:
    """No user key should not crash; defaults to empty strings."""
    rec = _record_from_payload("42", {"text": "stub"})
    assert rec.author_handle == ""
    assert rec.author_name == ""
    assert rec.author_verified is False


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("user", "not-an-object"),
        ("user", ["not-an-object"]),
        ("photos", {"url": "https://pbs.twimg.com/a.jpg"}),
        ("photos", "not-an-array"),
        ("video", {"variants": {"src": "https://video.twimg.com/a.mp4"}}),
        ("video", {"variants": "not-an-array"}),
    ],
)
def test_record_from_payload_ignores_malformed_nested_containers(field: str, value: object) -> None:
    payload = _payload()
    payload[field] = value

    record = _record_from_payload("42", payload)

    assert record.tweet_id == "42"
    if field == "user":
        assert record.author_handle == ""
    if field == "photos":
        assert record.photo_urls == []
    if field == "video":
        assert record.video_url == ""


@pytest.mark.parametrize(
    "quote_id",
    ["0", "\u0661", str(1 << 64), True, {"id": "91"}, ["91"]],
)
def test_record_from_payload_rejects_invalid_quote_identifiers(quote_id: object) -> None:
    payload = _payload()
    payload["quoted_tweet_id_str"] = quote_id

    record = _record_from_payload("42", payload)

    assert record.quoted_tweet_status == "none"
    assert record.quoted_tweet_id == ""
    assert record.quoted_tweet_url == ""


@pytest.mark.parametrize(
    "explicit_url",
    [
        "https://example.com/source/status/92",
        "https://x.com/source/status/93",
        "https://user@x.com/source/status/92",
        "not a url",
    ],
)
def test_record_from_payload_does_not_trust_mismatched_quote_url(
    explicit_url: str,
) -> None:
    payload = _payload()
    payload["quoted_tweet"] = {
        "id_str": "92",
        "url": explicit_url,
        "text": "quoted body",
    }

    record = _record_from_payload("42", payload)

    assert record.quoted_tweet_id == "92"
    assert record.quoted_tweet_url == "https://x.com/i/status/92"


def test_record_from_payload_derives_quote_id_from_valid_explicit_url() -> None:
    payload = _payload()
    payload["quoted_tweet"] = {
        "url": "https://twitter.com/source/status/92",
        "text": "quoted body",
    }

    record = _record_from_payload("42", payload)

    assert record.quoted_tweet_id == "92"
    assert record.quoted_tweet_url == "https://twitter.com/source/status/92"


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
    def __init__(self, data: Any, status_code: int = 200) -> None:
        self._data = data
        self.status_code = status_code

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *_: Any) -> None:
        pass

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("err", request=None, response=None)  # type: ignore[arg-type]

    def iter_bytes(self) -> list[bytes]:
        if isinstance(self._data, bytes):
            return [self._data]
        return [json.dumps(self._data).encode("utf-8")]


class _FakeClient:
    def __init__(self, data: Any) -> None:
        self._data = data
        self.stream_calls: list[tuple[str, dict, dict]] = []

    def __enter__(self) -> _FakeClient:
        return self

    def __exit__(self, *_: Any) -> None:
        pass

    def stream(self, method: str, url: str, params: dict, headers: dict) -> _FakeResponse:
        self.stream_calls.append((url, params, headers))
        return _FakeResponse(self._data)


def test_fetch_tweet_accepts_bare_id() -> None:
    payload = _payload(text="raw id path")
    fake = _FakeClient(payload)
    with patch("distill.ingestors.x.syndication.httpx.Client", return_value=fake):
        rec = fetch_tweet("2055709363701264550")
    assert rec.tweet_id == "2055709363701264550"
    assert rec.text == "raw id path"
    # Token was supplied (any string is fine, just verify it's there)
    assert "token" in fake.stream_calls[0][1]


def test_fetch_tweet_canonicalizes_zero_padded_bare_id() -> None:
    fake = _FakeClient(_payload())
    with patch("distill.ingestors.x.syndication.httpx.Client", return_value=fake):
        record = fetch_tweet("00042")

    assert record.tweet_id == "42"
    assert fake.stream_calls[0][1]["id"] == "42"


def test_fetch_tweet_disables_redirects_and_environment_proxies() -> None:
    fake = _FakeClient({})
    with (
        patch("distill.ingestors.x.syndication.httpx.Client", return_value=fake) as client,
        pytest.raises(ValueError, match="syndication payload"),
    ):
        fetch_tweet("42")

    client.assert_called_once_with(timeout=20.0, follow_redirects=False, trust_env=False)
    assert len(fake.stream_calls) == 1


def test_fetch_tweet_bounds_json_integers_when_interpreter_cap_is_disabled() -> None:
    fake = _FakeClient(b'{"id":' + b"9" * 1_000_000 + b"}")
    previous = sys.get_int_max_str_digits()
    try:
        sys.set_int_max_str_digits(0)
        with (
            patch("distill.ingestors.x.syndication.httpx.Client", return_value=fake),
            pytest.raises(ValueError, match="digit bound"),
        ):
            fetch_tweet("42")
    finally:
        sys.set_int_max_str_digits(previous)


@pytest.mark.parametrize("value", ["\u00b2", "\u0661\u0662", "9" * 5000])
def test_fetch_tweet_rejects_non_ascii_or_oversized_bare_id(value: str) -> None:
    with pytest.raises(ValueError, match="recognizable"):
        fetch_tweet(value)


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/not-a-tweet",
        "https://x.com/u/status/123abc",
        "https://x.com/u/status/" + "9" * 5000,
    ],
)
def test_fetch_tweet_unrecognized_url_raises_without_network(url: str) -> None:
    with (
        patch("distill.ingestors.x.syndication.httpx.Client") as client,
        pytest.raises(ValueError, match="recognizable"),
    ):
        fetch_tweet(url)
    client.assert_not_called()


def test_fetch_tweet_empty_payload_raises() -> None:
    fake = _FakeClient(None)
    with (
        patch("distill.ingestors.x.syndication.httpx.Client", return_value=fake),
        pytest.raises(ValueError, match="syndication payload"),
    ):
        fetch_tweet("https://x.com/u/status/1")

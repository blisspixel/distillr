"""Tests for distill.llm.grok_stt."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from distill.llm.grok_stt import (
    STT_ENDPOINT,
    _keyterm_list,
    keyterms_from_hint,
    transcribe_with_grok,
)


def _audio(tmp_path: Path) -> Path:
    p = tmp_path / "clip.mp3"
    p.write_bytes(b"audio bytes")
    return p


def test_endpoint_constant_is_xai() -> None:
    assert STT_ENDPOINT == "https://api.x.ai/v1/stt"


def test_keyterm_preview_forwards_limits_and_joins_terms() -> None:
    hint = "Alpha, Longer, Beta, Gamma"
    assert keyterms_from_hint(hint, max_terms=2, max_term_chars=5) == "Alpha, Beta"


def test_keyterm_filter_rejects_empty_long_url_sentence_and_duplicate_terms() -> None:
    hint = (
        ","
        + "x" * 51
        + ",httpserver,ftp://example.com,"
        + "one two three four five six seven eight,"
        + "MCP,mcp,Valid,one two three four five six seven"
    )

    assert _keyterm_list(hint) == ["MCP", "Valid", "one two three four five six seven"]


def test_keyterm_filter_stops_at_limit() -> None:
    assert _keyterm_list("") == []
    assert _keyterm_list("Alpha,Beta,Gamma", max_terms=2) == ["Alpha", "Beta"]


def test_requires_api_key(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="XAI_API_KEY not configured"):
        transcribe_with_grok(_audio(tmp_path), api_key="")


def test_requires_existing_media(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        transcribe_with_grok(tmp_path / "missing.mp3", api_key="xai-x")


def _fake_response(text: str = "hello world", status: int = 200, body: str = "") -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.reason_phrase = "OK" if status < 400 else "Bad Request"
    resp.text = body
    resp.json.return_value = {"text": text, "language": "English", "duration": 1.0}
    return resp


def _data_dict(data: Any) -> dict[str, list[str]]:
    """Normalize either a dict (with possible list values) or list-of-tuples
    multipart form data into {name: [values]} for assertions."""
    out: dict[str, list[str]] = {}
    if isinstance(data, dict):
        for k, v in data.items():
            if isinstance(v, list):
                out.setdefault(k, []).extend(str(x) for x in v)
            else:
                out.setdefault(k, []).append(str(v))
    else:
        for k, v in data:
            out.setdefault(k, []).append(str(v))
    return out


def test_happy_path_returns_text(tmp_path: Path) -> None:
    captured: dict[str, Any] = {}

    def _fake_post(url: str, **kwargs: Any) -> MagicMock:
        captured["url"] = url
        captured["headers"] = kwargs.get("headers")
        captured["data"] = kwargs.get("data")
        captured["files"] = kwargs.get("files")
        captured["timeout"] = kwargs.get("timeout")
        captured["audio"] = kwargs["files"]["file"][1].read()
        return _fake_response(text="hello there")

    with patch("distill.llm.grok_stt.httpx.post", side_effect=_fake_post):
        text = transcribe_with_grok(_audio(tmp_path), api_key="xai-k", language="en", timeout=12.5)

    assert text == "hello there"
    assert captured["url"] == STT_ENDPOINT
    assert captured["headers"]["Authorization"] == "Bearer xai-k"
    assert captured["timeout"] == 12.5
    assert captured["audio"] == b"audio bytes"
    fields = _data_dict(captured["data"])
    assert fields == {"language": ["en"], "format": ["true"]}


def test_omits_format_flag_when_no_language(tmp_path: Path) -> None:
    """Grok STT rejects format=true without language; verify we don't send it."""
    captured: dict[str, Any] = {}

    def _fake_post(url: str, **kwargs: Any) -> MagicMock:
        captured["data"] = kwargs.get("data")
        return _fake_response()

    with patch("distill.llm.grok_stt.httpx.post", side_effect=_fake_post):
        transcribe_with_grok(_audio(tmp_path), api_key="xai-k", language="")

    fields = _data_dict(captured["data"])
    assert fields == {}


def test_vocab_hint_becomes_repeated_keyterm_fields(tmp_path: Path) -> None:
    """Each individual term should be a separate ``keyterm`` form field —
    Grok STT does not accept a single comma-joined string."""
    captured: dict[str, Any] = {}

    def _fake_post(url: str, **kwargs: Any) -> MagicMock:
        captured["data"] = kwargs.get("data")
        return _fake_response()

    with patch("distill.llm.grok_stt.httpx.post", side_effect=_fake_post):
        transcribe_with_grok(
            _audio(tmp_path),
            api_key="xai-k",
            vocabulary_hint="Claude Code, Anthropic, MCP",
        )

    fields = _data_dict(captured["data"])
    assert fields == {"keyterm": ["Claude Code", "Anthropic", "MCP"]}


def test_keyterm_omitted_when_no_valid_terms(tmp_path: Path) -> None:
    """If the hint contains only long sentences / URLs, no keyterm is sent."""
    captured: dict[str, Any] = {}

    def _fake_post(url: str, **kwargs: Any) -> MagicMock:
        captured["data"] = kwargs.get("data")
        return _fake_response()

    long_only = "This is a long sentence that should not become a keyterm."
    with patch("distill.llm.grok_stt.httpx.post", side_effect=_fake_post):
        transcribe_with_grok(_audio(tmp_path), api_key="xai-k", vocabulary_hint=long_only)

    fields = _data_dict(captured["data"])
    assert "keyterm" not in fields


def test_error_response_surfaces_body(tmp_path: Path) -> None:
    """A 400 with a JSON error body should include that body in the exception."""

    def _fake_post(url: str, **kwargs: Any) -> MagicMock:
        return _fake_response(
            status=400,
            body='{"error":"Field \\"language\\" is required when \\"format\\" is true"}',
        )

    with (
        patch("distill.llm.grok_stt.httpx.post", side_effect=_fake_post),
        pytest.raises(RuntimeError, match=r"language.*required"),
    ):
        transcribe_with_grok(_audio(tmp_path), api_key="xai-k", language="")


def test_error_response_without_body_uses_explicit_placeholder(tmp_path: Path) -> None:
    with (
        patch(
            "distill.llm.grok_stt.httpx.post",
            return_value=_fake_response(status=503, body=""),
        ),
        pytest.raises(RuntimeError, match=r"503 Bad Request: \(empty body\)"),
    ):
        transcribe_with_grok(_audio(tmp_path), api_key="xai-k")


def test_picks_content_type_from_extension(tmp_path: Path) -> None:
    captured: dict[str, Any] = {}

    def _fake_post(url: str, **kwargs: Any) -> MagicMock:
        files = kwargs.get("files") or {}
        # files["file"] = (name, fh, content_type)
        captured["content_type"] = files["file"][2]
        return _fake_response()

    p = tmp_path / "voice.m4a"
    p.write_bytes(b"x")
    with patch("distill.llm.grok_stt.httpx.post", side_effect=_fake_post):
        transcribe_with_grok(p, api_key="xai-k")

    assert captured["content_type"] == "audio/mp4"


def test_unknown_extension_falls_back_to_octet_stream(tmp_path: Path) -> None:
    captured: dict[str, Any] = {}

    def _fake_post(url: str, **kwargs: Any) -> MagicMock:
        captured["content_type"] = (kwargs.get("files") or {})["file"][2]
        return _fake_response()

    p = tmp_path / "weird.xyz"
    p.write_bytes(b"x")
    with patch("distill.llm.grok_stt.httpx.post", side_effect=_fake_post):
        transcribe_with_grok(p, api_key="xai-k")

    assert captured["content_type"] == "application/octet-stream"


def test_response_missing_text_field_raises(tmp_path: Path) -> None:
    def _fake_post(url: str, **kwargs: Any) -> MagicMock:
        resp = MagicMock()
        resp.status_code = 200
        resp.text = ""
        resp.json.return_value = {"language": "English"}  # no 'text' field
        return resp

    with (
        patch("distill.llm.grok_stt.httpx.post", side_effect=_fake_post),
        pytest.raises(RuntimeError, match="missing 'text'"),
    ):
        transcribe_with_grok(_audio(tmp_path), api_key="xai-k")


def test_response_rejects_present_non_string_text(tmp_path: Path) -> None:
    response = _fake_response()
    response.json.return_value = {"text": 123}

    with (
        patch("distill.llm.grok_stt.httpx.post", return_value=response),
        pytest.raises(RuntimeError, match="missing 'text' field"),
    ):
        transcribe_with_grok(_audio(tmp_path), api_key="xai-k")


def test_response_rejects_non_object_payload(tmp_path: Path) -> None:
    response = _fake_response()
    response.json.return_value = ["unexpected"]

    with (
        patch("distill.llm.grok_stt.httpx.post", return_value=response),
        pytest.raises(RuntimeError, match="Unexpected Grok STT payload shape: list"),
    ):
        transcribe_with_grok(_audio(tmp_path), api_key="xai-k")

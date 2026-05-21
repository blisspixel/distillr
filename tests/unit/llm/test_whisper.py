"""Tests for distill.llm.whisper."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from distill.llm.whisper import transcribe_with_openai


def test_transcribe_with_openai_requires_api_key(tmp_path: Path) -> None:
    media = tmp_path / "m.mp4"
    media.write_bytes(b"x")
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY not configured"):
        transcribe_with_openai(media, api_key="")


def test_transcribe_with_openai_rejects_oversized_file(tmp_path: Path) -> None:
    """OpenAI Whisper-1 has a hard 25 MB upload cap. Surface that locally
    instead of waiting for an HTTP 413 from the API."""
    media = tmp_path / "huge.mp4"
    media.write_bytes(b"x" * (25 * 1024 * 1024 + 1))
    with pytest.raises(ValueError, match="25 MB"):
        transcribe_with_openai(media, api_key="sk-test")


def test_transcribe_with_openai_calls_audio_transcriptions(tmp_path: Path) -> None:
    media = tmp_path / "m.mp4"
    media.write_bytes(b"audio bytes")

    mock_client = MagicMock()
    mock_client.audio.transcriptions.create.return_value = "transcribed text"

    with patch("distill.llm.whisper.OpenAI", return_value=mock_client) as openai_ctor:
        text = transcribe_with_openai(media, api_key="sk-test")

    assert text == "transcribed text"
    openai_ctor.assert_called_once_with(api_key="sk-test")
    create_call = mock_client.audio.transcriptions.create.call_args
    assert create_call.kwargs["model"] == "whisper-1"
    assert create_call.kwargs["response_format"] == "text"
    assert "prompt" not in create_call.kwargs  # no hint passed


def test_transcribe_with_openai_passes_vocab_hint_as_prompt(tmp_path: Path) -> None:
    media = tmp_path / "m.mp4"
    media.write_bytes(b"x")

    mock_client = MagicMock()
    mock_client.audio.transcriptions.create.return_value = "ok"

    with patch("distill.llm.whisper.OpenAI", return_value=mock_client):
        transcribe_with_openai(media, api_key="sk-test", vocabulary_hint="Claude Anthropic")

    create_call = mock_client.audio.transcriptions.create.call_args
    assert create_call.kwargs["prompt"] == "Claude Anthropic"


def test_transcribe_with_openai_handles_object_response(tmp_path: Path) -> None:
    """The OpenAI SDK can return either str or an object with .text."""
    media = tmp_path / "m.mp4"
    media.write_bytes(b"x")

    class _Resp:
        text = "object-style response"

    mock_client = MagicMock()
    mock_client.audio.transcriptions.create.return_value = _Resp()

    with patch("distill.llm.whisper.OpenAI", return_value=mock_client):
        out = transcribe_with_openai(media, api_key="sk-test")

    assert out == "object-style response"


def test_transcribe_with_openai_custom_model(tmp_path: Path) -> None:
    media = tmp_path / "m.mp4"
    media.write_bytes(b"x")

    mock_client = MagicMock()
    mock_client.audio.transcriptions.create.return_value = "ok"

    with patch("distill.llm.whisper.OpenAI", return_value=mock_client):
        transcribe_with_openai(media, api_key="sk-test", model="whisper-2")

    assert mock_client.audio.transcriptions.create.call_args.kwargs["model"] == "whisper-2"

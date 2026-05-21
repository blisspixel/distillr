"""Tests for distill.ingestors.transcribe."""

from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from distill.config import DistillConfig
from distill.ingestors.transcribe import (
    TranscriptionError,
    TranscriptionResult,
    _clip_for_whisper,
    _pick_device,
    transcribe_media,
)

# ---------------------------------------------------------------------------
# _clip_for_whisper
# ---------------------------------------------------------------------------


def test_clip_for_whisper_passthrough_short_text() -> None:
    assert _clip_for_whisper("short hint") == "short hint"


def test_clip_for_whisper_collapses_whitespace() -> None:
    assert _clip_for_whisper("a    b\n\tc") == "a b c"


def test_clip_for_whisper_clips_at_word_boundary() -> None:
    long_text = "alpha beta gamma " * 200  # 3,400+ chars
    clipped = _clip_for_whisper(long_text, max_chars=20)
    assert len(clipped) <= 20
    # Must end on a word boundary (no trailing partial word)
    assert not clipped.endswith("alph")
    assert clipped.split(" ")[-1] in {"alpha", "beta", "gamma"}


def test_clip_for_whisper_no_space_clips_hard() -> None:
    clipped = _clip_for_whisper("x" * 50, max_chars=10)
    assert len(clipped) == 10


# ---------------------------------------------------------------------------
# _pick_device
# ---------------------------------------------------------------------------


def test_pick_device_no_ctranslate2_falls_back_to_cpu() -> None:
    # Remove ctranslate2 from sys.modules if present so the import inside
    # _pick_device raises ImportError on the way in.
    saved = sys.modules.pop("ctranslate2", None)
    sys.modules["ctranslate2"] = None  # type: ignore[assignment]
    try:
        assert _pick_device() == ("cpu", "int8")
    finally:
        if saved is not None:
            sys.modules["ctranslate2"] = saved
        else:
            sys.modules.pop("ctranslate2", None)


def test_pick_device_cuda_returns_float16() -> None:
    fake_ct = types.SimpleNamespace(get_cuda_device_count=lambda: 1)
    with patch.dict(sys.modules, {"ctranslate2": fake_ct}):
        assert _pick_device() == ("cuda", "float16")


def test_pick_device_no_cuda_returns_cpu_int8() -> None:
    fake_ct = types.SimpleNamespace(get_cuda_device_count=lambda: 0)
    with patch.dict(sys.modules, {"ctranslate2": fake_ct}):
        assert _pick_device() == ("cpu", "int8")


def test_pick_device_cuda_probe_exception_returns_cpu() -> None:
    def _raise() -> int:
        raise RuntimeError("CUDA driver mismatch")

    fake_ct = types.SimpleNamespace(get_cuda_device_count=_raise)
    with patch.dict(sys.modules, {"ctranslate2": fake_ct}):
        assert _pick_device() == ("cpu", "int8")


# ---------------------------------------------------------------------------
# transcribe_media — provider routing
# ---------------------------------------------------------------------------


def _config(*, openai_key: str = "sk-test") -> DistillConfig:
    return DistillConfig(openai_api_key=openai_key, xai_api_key="x")


def test_transcribe_media_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(TranscriptionError, match="Media file not found"):
        transcribe_media(tmp_path / "nope.mp4", _config())


def _make_local_returns(text: str = "local says hi") -> Any:
    def _fake(media_path: Path, **kwargs: Any) -> TranscriptionResult:
        model_name = kwargs.get("model_name", "large-v3")
        return TranscriptionResult(text=text, provider="faster-whisper", model=model_name)

    return _fake


def _make_local_raises(exc: Exception) -> Any:
    def _fake(*args: Any, **kwargs: Any) -> TranscriptionResult:
        raise exc

    return _fake


def test_transcribe_media_auto_uses_local_when_available(tmp_path: Path) -> None:
    media = tmp_path / "m.mp4"
    media.write_bytes(b"x")

    with patch(
        "distill.ingestors.transcribe._transcribe_local",
        _make_local_returns("local OK"),
    ):
        result = transcribe_media(media, _config())

    assert result.provider == "faster-whisper"
    assert result.text == "local OK"


def test_transcribe_media_auto_falls_back_to_cloud(tmp_path: Path) -> None:
    media = tmp_path / "m.mp4"
    media.write_bytes(b"x")

    from distill.ingestors.transcribe import _LocalUnavailable

    def _cloud(
        media_path: Path, config: DistillConfig, *, vocabulary_hint: str = ""
    ) -> TranscriptionResult:
        return TranscriptionResult(text="cloud OK", provider="openai", model="whisper-1")

    with (
        patch(
            "distill.ingestors.transcribe._transcribe_local",
            _make_local_raises(_LocalUnavailable("not installed")),
        ),
        patch("distill.ingestors.transcribe._transcribe_openai", _cloud),
    ):
        result = transcribe_media(media, _config())

    assert result.provider == "openai"
    assert result.text == "cloud OK"


def test_transcribe_media_local_only_raises_when_unavailable(tmp_path: Path) -> None:
    media = tmp_path / "m.mp4"
    media.write_bytes(b"x")

    from distill.ingestors.transcribe import _LocalUnavailable

    with (
        patch(
            "distill.ingestors.transcribe._transcribe_local",
            _make_local_raises(_LocalUnavailable("not installed")),
        ),
        pytest.raises(TranscriptionError, match="not installed"),
    ):
        transcribe_media(media, _config(), prefer="local")


def test_transcribe_media_cloud_only_skips_local(tmp_path: Path) -> None:
    from unittest.mock import MagicMock

    media = tmp_path / "m.mp4"
    media.write_bytes(b"x")

    local_mock = MagicMock(
        return_value=TranscriptionResult(text="!", provider="faster-whisper", model="x")
    )
    cloud_mock = MagicMock(
        return_value=TranscriptionResult(text="cloud only", provider="openai", model="whisper-1")
    )

    with (
        patch("distill.ingestors.transcribe._transcribe_local", local_mock),
        patch("distill.ingestors.transcribe._transcribe_openai", cloud_mock),
    ):
        result = transcribe_media(media, _config(), prefer="cloud")

    assert cloud_mock.call_count == 1
    assert local_mock.call_count == 0
    assert result.provider == "openai"


def test_transcribe_media_both_providers_fail_raises_combined_error(tmp_path: Path) -> None:
    media = tmp_path / "m.mp4"
    media.write_bytes(b"x")

    def _cloud_fail(*args: Any, **kwargs: Any) -> TranscriptionResult:
        raise RuntimeError("openai 401")

    with (
        patch(
            "distill.ingestors.transcribe._transcribe_local",
            _make_local_raises(RuntimeError("cuda OOM")),
        ),
        patch("distill.ingestors.transcribe._transcribe_openai", _cloud_fail),
        pytest.raises(TranscriptionError) as ei,
    ):
        transcribe_media(media, _config())

    # Both error messages preserved
    assert "cuda OOM" in str(ei.value)
    assert "openai 401" in str(ei.value)


def test_transcribe_media_progress_callback_threads_through(tmp_path: Path) -> None:
    """Progress callback + interval should be forwarded to the local provider."""
    media = tmp_path / "m.mp4"
    media.write_bytes(b"x")
    captured: dict[str, Any] = {}

    def _local(media_path: Path, **kwargs: Any) -> TranscriptionResult:
        captured["progress"] = kwargs.get("progress")
        captured["interval"] = kwargs.get("progress_interval_s")
        return TranscriptionResult(text="ok", provider="faster-whisper", model="x")

    my_progress = lambda a, t, w: None  # noqa: E731
    with patch("distill.ingestors.transcribe._transcribe_local", _local):
        transcribe_media(media, _config(), progress=my_progress, progress_interval_s=15.0)

    assert captured["progress"] is my_progress
    assert captured["interval"] == 15.0


def test_default_progress_callback_writes_to_stderr(capsys: Any) -> None:
    """The default progress callback should write a single line to stderr."""
    from distill.ingestors.transcribe import _default_progress

    _default_progress(audio_seconds=120.0, total_audio_s=600.0, words=200)
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "120s of 600s" in captured.err
    assert "20%" in captured.err
    assert "200 words" in captured.err


def test_default_progress_callback_handles_unknown_total(capsys: Any) -> None:
    from distill.ingestors.transcribe import _default_progress

    _default_progress(audio_seconds=30.0, total_audio_s=0.0, words=50)
    captured = capsys.readouterr()
    assert "30s" in captured.err
    assert "50 words" in captured.err
    assert "%" not in captured.err  # no percentage when total unknown


def test_transcribe_media_vocab_hint_threads_through_to_local(tmp_path: Path) -> None:
    media = tmp_path / "m.mp4"
    media.write_bytes(b"x")
    captured: dict[str, Any] = {}

    def _local(media_path: Path, **kwargs: Any) -> TranscriptionResult:
        captured["hint"] = kwargs.get("vocabulary_hint", "")
        model_name = kwargs.get("model_name", "large-v3")
        return TranscriptionResult(text="ok", provider="faster-whisper", model=model_name)

    with patch("distill.ingestors.transcribe._transcribe_local", _local):
        transcribe_media(media, _config(), vocabulary_hint="Claude, Anthropic")

    assert captured["hint"] == "Claude, Anthropic"

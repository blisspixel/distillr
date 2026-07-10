"""Tests for distill.ingestors.transcribe."""

from __future__ import annotations

import subprocess
import sys
import types
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from distill.config import DistillConfig
from distill.ingestors.transcribe import (
    TranscriptionError,
    TranscriptionResult,
    _clip_for_whisper,
    _drain_segments,
    _pick_batch_size,
    _pick_device,
    _probe_media_duration,
    _run_transcription,
    _transcribe_grok,
    _transcribe_local,
    _transcribe_openai,
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


def _config(
    *,
    openai_key: str = "sk-test",
    xai_key: str = "x",
    cost_mode: str = "auto",
) -> DistillConfig:
    return DistillConfig(
        openai_api_key=openai_key,
        xai_api_key=xai_key,
        distill_cost_mode=cost_mode,
    )


def test_transcribe_media_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(TranscriptionError, match="Media file not found"):
        transcribe_media(tmp_path / "nope.mp4", _config())


def test_transcribe_media_rejects_unknown_preference(tmp_path: Path) -> None:
    media = tmp_path / "m.mp4"
    media.write_bytes(b"x")

    with pytest.raises(TranscriptionError, match="unknown prefer='satellite'"):
        transcribe_media(media, _config(), prefer="satellite")


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


def test_transcribe_media_records_completed_empty_result_with_duration_hint(
    tmp_path: Path,
) -> None:
    media = tmp_path / "m.mp4"
    media.write_bytes(b"x")
    tracker = MagicMock()

    with patch(
        "distill.ingestors.transcribe._transcribe_local",
        _make_local_returns(""),
    ):
        result = transcribe_media(
            media,
            _config(),
            tracker=tracker,
            duration_hint_s=42.5,
        )

    assert result.duration_s == 42.5
    tracker.record_transcription.assert_called_once_with("faster-whisper", 42.5, model="large-v3")


def test_transcribe_media_does_not_fall_through_after_ledger_refusal(tmp_path: Path) -> None:
    media = tmp_path / "m.mp4"
    media.write_bytes(b"x")
    tracker = MagicMock()
    tracker.record_transcription.side_effect = RuntimeError("budget exceeded")
    grok = MagicMock()

    with (
        patch(
            "distill.ingestors.transcribe._transcribe_local",
            _make_local_returns(),
        ),
        patch("distill.ingestors.transcribe._transcribe_grok", grok),
        pytest.raises(RuntimeError, match="budget exceeded"),
    ):
        transcribe_media(media, _config(), tracker=tracker)

    grok.assert_not_called()


def test_transcribe_media_refuses_cloud_call_without_billable_duration(tmp_path: Path) -> None:
    from distill.ingestors.transcribe import _LocalUnavailable

    media = tmp_path / "m.mp4"
    media.write_bytes(b"x")
    tracker = MagicMock()
    grok = MagicMock()

    with (
        patch(
            "distill.ingestors.transcribe._transcribe_local",
            _make_local_raises(_LocalUnavailable("not installed")),
        ),
        patch("distill.ingestors.transcribe._probe_media_duration", return_value=0.0),
        patch("distill.ingestors.transcribe._transcribe_grok", grok),
        pytest.raises(TranscriptionError, match="media duration is unavailable"),
    ):
        transcribe_media(media, _config(), tracker=tracker)

    grok.assert_not_called()
    tracker.record_transcription.assert_not_called()


def test_transcribe_media_probes_duration_before_tracked_cloud_call(tmp_path: Path) -> None:
    from distill.ingestors.transcribe import _LocalUnavailable

    media = tmp_path / "m.mp4"
    media.write_bytes(b"x")
    tracker = MagicMock()
    result = TranscriptionResult(text="cloud", provider="xai-grok-stt", model="grok-stt")

    with (
        patch(
            "distill.ingestors.transcribe._transcribe_local",
            _make_local_raises(_LocalUnavailable("not installed")),
        ),
        patch("distill.ingestors.transcribe._probe_media_duration", return_value=63.0),
        patch("distill.ingestors.transcribe._transcribe_grok", return_value=result),
    ):
        returned = transcribe_media(
            media,
            _config(),
            tracker=tracker,
            duration_hint_s=1.0,
        )

    assert returned.duration_s == 63.0
    tracker.record_transcription.assert_called_once_with("xai-grok-stt", 63.0, model="grok-stt")


def test_probe_media_duration_parses_ffprobe_output(tmp_path: Path) -> None:
    completed = types.SimpleNamespace(returncode=0, stdout="12.75\n")

    with patch("distill.ingestors.transcribe.subprocess.run", return_value=completed):
        assert _probe_media_duration(tmp_path / "m.mp4") == 12.75


@pytest.mark.parametrize(
    "side_effect",
    [OSError("missing"), subprocess.TimeoutExpired("ffprobe", 10)],
)
def test_probe_media_duration_handles_unavailable_probe(
    tmp_path: Path, side_effect: Exception
) -> None:
    with patch("distill.ingestors.transcribe.subprocess.run", side_effect=side_effect):
        assert _probe_media_duration(tmp_path / "m.mp4") == 0.0


@pytest.mark.parametrize(
    "completed",
    [
        types.SimpleNamespace(returncode=1, stdout="12.0"),
        types.SimpleNamespace(returncode=0, stdout="not-a-duration"),
    ],
)
def test_probe_media_duration_rejects_invalid_output(tmp_path: Path, completed: Any) -> None:
    with patch("distill.ingestors.transcribe.subprocess.run", return_value=completed):
        assert _probe_media_duration(tmp_path / "m.mp4") == 0.0


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


def test_transcribe_media_grok_only_routes_to_grok(tmp_path: Path) -> None:
    media = tmp_path / "m.mp4"
    media.write_bytes(b"x")
    grok = MagicMock(
        return_value=TranscriptionResult(text="g", provider="xai-grok-stt", model="grok-stt")
    )
    local = MagicMock()
    openai = MagicMock()

    with (
        patch("distill.ingestors.transcribe._transcribe_local", local),
        patch("distill.ingestors.transcribe._transcribe_grok", grok),
        patch("distill.ingestors.transcribe._transcribe_openai", openai),
    ):
        result = transcribe_media(media, _config(), prefer="grok")

    assert result.provider == "xai-grok-stt"
    assert grok.call_count == 1
    assert local.call_count == 0
    assert openai.call_count == 0


def test_transcribe_media_auto_falls_back_to_grok_before_openai(tmp_path: Path) -> None:
    media = tmp_path / "m.mp4"
    media.write_bytes(b"x")

    from distill.ingestors.transcribe import _LocalUnavailable

    grok = MagicMock(
        return_value=TranscriptionResult(text="grok", provider="xai-grok-stt", model="grok-stt")
    )
    openai = MagicMock()

    with (
        patch(
            "distill.ingestors.transcribe._transcribe_local",
            _make_local_raises(_LocalUnavailable("no local")),
        ),
        patch("distill.ingestors.transcribe._transcribe_grok", grok),
        patch("distill.ingestors.transcribe._transcribe_openai", openai),
    ):
        result = transcribe_media(media, _config())

    assert result.provider == "xai-grok-stt"
    assert grok.call_count == 1
    assert openai.call_count == 0  # grok succeeded; openai never tried


# ---------------------------------------------------------------------------
# _pick_device — compute-type preference
# ---------------------------------------------------------------------------


def test_pick_device_prefers_int8_float16_when_float16_absent() -> None:
    fake_ct = types.SimpleNamespace(
        get_cuda_device_count=lambda: 1,
        get_supported_compute_types=lambda dev: {"int8_float16", "float32"},
    )
    with patch.dict(sys.modules, {"ctranslate2": fake_ct}):
        assert _pick_device() == ("cuda", "int8_float16")


def test_pick_device_unknown_compute_types_falls_back_to_float16() -> None:
    fake_ct = types.SimpleNamespace(
        get_cuda_device_count=lambda: 1,
        get_supported_compute_types=lambda dev: {"int8"},
    )
    with patch.dict(sys.modules, {"ctranslate2": fake_ct}):
        assert _pick_device() == ("cuda", "float16")


# ---------------------------------------------------------------------------
# _pick_batch_size
# ---------------------------------------------------------------------------


def test_pick_batch_size_cpu_returns_small() -> None:
    assert _pick_batch_size("cpu") == 4


def test_pick_batch_size_cuda_without_ctranslate2_returns_small() -> None:
    with patch.dict(sys.modules, {"ctranslate2": None}):
        assert _pick_batch_size("cuda") == 4


def test_pick_batch_size_cuda_without_torch_returns_small() -> None:
    with patch.dict(sys.modules, {"ctranslate2": types.SimpleNamespace(), "torch": None}):
        assert _pick_batch_size("cuda") == 4


def test_pick_batch_size_cuda_with_torch_computes_from_free_vram() -> None:
    fake_torch = types.SimpleNamespace(
        cuda=types.SimpleNamespace(
            is_available=lambda: True,
            mem_get_info=lambda: (11 * 1024**3, 16 * 1024**3),
        )
    )
    with patch.dict(sys.modules, {"ctranslate2": types.SimpleNamespace(), "torch": fake_torch}):
        # usable = (11 - 3) * 0.7 = 5.6 GB; slots = int(5.6 / 0.25) = 22
        assert _pick_batch_size("cuda") == 22


def test_pick_batch_size_clamps_to_ceiling() -> None:
    fake_torch = types.SimpleNamespace(
        cuda=types.SimpleNamespace(
            is_available=lambda: True,
            mem_get_info=lambda: (80 * 1024**3, 80 * 1024**3),
        )
    )
    with patch.dict(sys.modules, {"ctranslate2": types.SimpleNamespace(), "torch": fake_torch}):
        assert _pick_batch_size("cuda") == 32  # clamped, not 200+


# ---------------------------------------------------------------------------
# _run_transcription — kwargs for batched vs serial
# ---------------------------------------------------------------------------


class _RecordingTranscriber:
    def __init__(self) -> None:
        self.kwargs: dict[str, Any] = {}
        self.path = ""

    def transcribe(self, media_path: str, **kwargs: Any) -> tuple[str, str]:
        self.path = media_path
        self.kwargs = kwargs
        return ("SEGMENTS", "INFO")


def test_run_transcription_batched_includes_batch_size() -> None:
    t = _RecordingTranscriber()
    segments, info = _run_transcription(
        t, "a.mp4", initial_prompt="hint", batch_size=8, batched=True
    )
    assert (segments, info) == ("SEGMENTS", "INFO")
    assert t.path == "a.mp4"
    assert t.kwargs["batch_size"] == 8
    assert t.kwargs["beam_size"] == 1
    assert t.kwargs["vad_filter"] is True
    assert t.kwargs["without_timestamps"] is True
    assert t.kwargs["initial_prompt"] == "hint"


def test_run_transcription_serial_omits_batch_size() -> None:
    t = _RecordingTranscriber()
    _run_transcription(t, "a.mp4", initial_prompt=None, batch_size=None, batched=False)
    assert "batch_size" not in t.kwargs
    assert t.kwargs["initial_prompt"] is None


# ---------------------------------------------------------------------------
# _drain_segments
# ---------------------------------------------------------------------------


def _seg(text: str, end: float) -> Any:
    return types.SimpleNamespace(text=text, end=end)


def test_drain_segments_accumulates_text_and_word_count() -> None:
    segments = [_seg(" hello world ", 1.0), _seg("foo", 2.5), _seg("   ", 3.0)]
    parts, words, last_end = _drain_segments(
        segments, progress=None, progress_interval_s=30.0, total_audio_s=3.0
    )
    assert parts == ["hello world", "foo"]  # blank segment dropped
    assert words == 3
    assert last_end == 3.0


def test_drain_segments_emits_progress_each_segment_when_interval_zero() -> None:
    calls: list[tuple[float, float, int]] = []
    segments = [_seg("a", 1.0), _seg("b", 2.0)]
    _drain_segments(
        segments,
        progress=lambda a, t, w: calls.append((a, t, w)),
        progress_interval_s=0.0,
        total_audio_s=5.0,
    )
    assert calls == [(1.0, 5.0, 1), (2.0, 5.0, 2)]


def test_drain_segments_cuda_oom_raises_local_unavailable() -> None:
    from distill.ingestors.transcribe import _LocalUnavailable

    def _segments() -> Any:
        yield _seg("partial", 1.0)
        raise RuntimeError("CUDA failed with error out of memory")

    with pytest.raises(_LocalUnavailable, match="out of memory"):
        _drain_segments(_segments(), progress=None, progress_interval_s=30.0, total_audio_s=5.0)


def test_drain_segments_non_cuda_runtime_error_is_reraised() -> None:
    def _segments() -> Any:
        yield _seg("partial", 1.0)
        raise RuntimeError("disk full")

    with pytest.raises(RuntimeError, match="disk full"):
        _drain_segments(_segments(), progress=None, progress_interval_s=30.0, total_audio_s=5.0)


# ---------------------------------------------------------------------------
# _transcribe_grok / _transcribe_openai
# ---------------------------------------------------------------------------


def test_transcribe_grok_without_key_raises_provider_unavailable() -> None:
    from distill.ingestors.transcribe import _ProviderUnavailable

    config = _config(openai_key="", xai_key="")
    with pytest.raises(_ProviderUnavailable, match="XAI_API_KEY"):
        _transcribe_grok(Path("a.mp4"), config)


def test_transcribe_grok_success_builds_result(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "distill.llm.grok_stt.transcribe_with_grok",
        lambda media_path, **kwargs: "grok transcript",
    )
    config = _config(openai_key="", xai_key="xk")
    result = _transcribe_grok(Path("a.mp4"), config, vocabulary_hint="Anthropic")

    assert result.provider == "xai-grok-stt"
    assert result.model == "grok-stt"
    assert result.text == "grok transcript"
    assert any("vocab_hint" in note for note in result.notes)
    assert any("language=en" in note for note in result.notes)


def test_transcribe_grok_passes_clipped_hint_and_language(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, Any] = {}

    def _fake(media_path: Path, **kwargs: Any) -> str:
        seen.update(kwargs)
        return "ok"

    monkeypatch.setattr("distill.llm.grok_stt.transcribe_with_grok", _fake)
    config = _config(openai_key="", xai_key="xk")
    _transcribe_grok(Path("a.mp4"), config, vocabulary_hint="Claude", language="")

    assert seen["api_key"] == "xk"
    assert seen["vocabulary_hint"] == "Claude"
    assert seen["language"] == ""


def test_transcribe_grok_refuses_no_metered_route(monkeypatch: pytest.MonkeyPatch) -> None:
    from distill.llm.cost_policy import CostPolicyError

    client = MagicMock(return_value="unexpected")
    monkeypatch.setattr("distill.llm.grok_stt.transcribe_with_grok", client)

    with pytest.raises(CostPolicyError, match="Route blocked by no-metered cost policy"):
        _transcribe_grok(
            Path("a.mp4"),
            _config(openai_key="", xai_key="xk", cost_mode="no-metered"),
        )

    client.assert_not_called()


def test_transcribe_openai_without_key_raises_provider_unavailable() -> None:
    from distill.ingestors.transcribe import _ProviderUnavailable

    config = _config(openai_key="", xai_key="")
    with pytest.raises(_ProviderUnavailable, match="OPENAI_API_KEY"):
        _transcribe_openai(Path("a.mp4"), config)


def test_transcribe_openai_success_builds_result(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "distill.llm.whisper.transcribe_with_openai",
        lambda media_path, **kwargs: "openai transcript",
    )
    config = _config(openai_key="sk", xai_key="")
    result = _transcribe_openai(Path("a.mp4"), config, vocabulary_hint="Anthropic")

    assert result.provider == "openai"
    assert result.model == "whisper-1"
    assert result.text == "openai transcript"
    assert any("vocab_hint" in note for note in result.notes)


def test_transcribe_openai_success_without_hint_has_no_notes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "distill.llm.whisper.transcribe_with_openai", lambda media_path, **kwargs: "t"
    )
    config = _config(openai_key="sk", xai_key="")
    result = _transcribe_openai(Path("a.mp4"), config)
    assert result.notes == []


def test_transcribe_openai_refuses_no_metered_route(monkeypatch: pytest.MonkeyPatch) -> None:
    from distill.llm.cost_policy import CostPolicyError

    client = MagicMock(return_value="unexpected")
    monkeypatch.setattr("distill.llm.whisper.transcribe_with_openai", client)

    with pytest.raises(CostPolicyError, match="Route blocked by no-metered cost policy"):
        _transcribe_openai(
            Path("a.mp4"),
            _config(openai_key="sk", xai_key="", cost_mode="no-metered"),
        )

    client.assert_not_called()


# ---------------------------------------------------------------------------
# _transcribe_local — faster-whisper path (fake module injected)
# ---------------------------------------------------------------------------


def _fake_faster_whisper(
    *,
    with_batched: bool = True,
    batched_raises: bool = False,
    segments: list[Any] | None = None,
    info: Any | None = None,
) -> types.ModuleType:
    """Build a stand-in ``faster_whisper`` module for the local path tests."""
    seg_list = segments if segments is not None else [_seg("hello", 1.0)]
    info_obj = info if info is not None else types.SimpleNamespace(duration=1.0, language="en")

    class _Model:
        def __init__(self, model_name: str, device: str = "", compute_type: str = "") -> None:
            self.model_name = model_name

        def transcribe(self, media_path: str, **kwargs: Any) -> tuple[Any, Any]:
            return iter(seg_list), info_obj

    module = types.ModuleType("faster_whisper")
    module.WhisperModel = _Model  # type: ignore[attr-defined]

    if with_batched:

        class _Batched:
            def __init__(self, model: Any = None) -> None:
                self.model = model

            def transcribe(self, media_path: str, **kwargs: Any) -> tuple[Any, Any]:
                if batched_raises:
                    raise RuntimeError("batched kernel failed")
                return iter(seg_list), info_obj

        module.BatchedInferencePipeline = _Batched  # type: ignore[attr-defined]

    return module


def test_transcribe_local_missing_dependency_raises_local_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from distill.ingestors.transcribe import _LocalUnavailable

    monkeypatch.setitem(sys.modules, "faster_whisper", None)
    with pytest.raises(_LocalUnavailable, match="faster-whisper not installed"):
        _transcribe_local(Path("a.mp4"), model_name="large-v3")


def test_transcribe_local_batched_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("distill.ingestors.transcribe._pick_device", lambda: ("cpu", "int8"))
    monkeypatch.setattr("distill.ingestors.transcribe._pick_batch_size", lambda device: 8)
    monkeypatch.setitem(sys.modules, "faster_whisper", _fake_faster_whisper())

    final_progress: list[tuple[float, float, int]] = []
    result = _transcribe_local(
        Path("a.mp4"),
        model_name="large-v3",
        vocabulary_hint="Anthropic",
        progress=lambda a, t, w: final_progress.append((a, t, w)),
    )

    assert result.provider == "faster-whisper"
    assert result.model == "large-v3"
    assert result.text == "hello"
    assert result.language == "en"
    assert result.duration_s == 1.0
    assert any("batched(size=8)" in note for note in result.notes)
    assert any("vocab_hint" in note for note in result.notes)
    assert final_progress  # final 100% heartbeat fired


def test_transcribe_local_serial_when_batched_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("distill.ingestors.transcribe._pick_device", lambda: ("cpu", "int8"))
    monkeypatch.setattr("distill.ingestors.transcribe._pick_batch_size", lambda device: 4)
    monkeypatch.setitem(sys.modules, "faster_whisper", _fake_faster_whisper(with_batched=False))

    result = _transcribe_local(Path("a.mp4"), model_name="large-v3", progress=None)

    assert "serial" in result.notes
    assert result.text == "hello"


def test_transcribe_local_degrades_to_serial_when_batched_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("distill.ingestors.transcribe._pick_device", lambda: ("cpu", "int8"))
    monkeypatch.setattr("distill.ingestors.transcribe._pick_batch_size", lambda device: 8)
    monkeypatch.setitem(sys.modules, "faster_whisper", _fake_faster_whisper(batched_raises=True))

    result = _transcribe_local(Path("a.mp4"), model_name="large-v3", progress=None)

    assert any("batched_failed:RuntimeError" in note for note in result.notes)
    assert "serial" in result.notes
    assert result.text == "hello"

"""Tests for the private faster-whisper worker contract."""

from __future__ import annotations

import io
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from distill.ingestors import _transcribe_worker as worker
from distill.ingestors.transcribe import TranscriptionResult


def _worker_paths(tmp_path: Path) -> tuple[Path, Path, Path]:
    return (
        tmp_path / "request.json",
        tmp_path / "result.json",
        tmp_path / "progress.json",
    )


def _request(media_path: Path) -> dict[str, object]:
    return {
        "media_path": str(media_path.resolve()),
        "model_name": "large-v3",
        "vocabulary_hint": "Anthropic",
        "progress_interval_s": 30.0,
    }


def test_worker_main_runs_core_and_writes_bounded_result_and_progress(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    media = tmp_path / "media.wav"
    media.write_bytes(b"media")
    request_path, result_path, progress_path = _worker_paths(tmp_path)
    request_path.write_text(json.dumps(_request(media)), encoding="utf-8")
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(buffer=io.BytesIO(b"1")))

    def transcribe(
        media_path,
        *,
        model_name,
        vocabulary_hint,
        progress,
        progress_interval_s,
    ):
        assert media_path == media
        assert model_name == "large-v3"
        assert vocabulary_hint == "Anthropic"
        assert progress_interval_s == 30.0
        progress(5.0, 10.0, 3)
        return TranscriptionResult(
            text="transcript",
            provider="faster-whisper",
            model=model_name,
            language="en",
            duration_s=10.0,
            notes=["isolated"],
        )

    monkeypatch.setattr(worker, "_transcribe_local_core", transcribe)

    assert worker.main([str(request_path), str(result_path), str(progress_path)]) == 0
    assert json.loads(result_path.read_text(encoding="utf-8"))["text"] == "transcript"
    assert json.loads(progress_path.read_text(encoding="utf-8")) == {
        "audio_seconds": 5.0,
        "total_audio_s": 10.0,
        "words": 3,
    }


def test_worker_rejects_wrong_start_token_without_model_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    media = tmp_path / "media.wav"
    media.write_bytes(b"media")
    request_path, result_path, progress_path = _worker_paths(tmp_path)
    request_path.write_text(json.dumps(_request(media)), encoding="utf-8")
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(buffer=io.BytesIO(b"0")))

    def core(*_args, **_kwargs):
        pytest.fail("model must not run")

    monkeypatch.setattr(worker, "_transcribe_local_core", core)

    assert worker.main([str(request_path), str(result_path), str(progress_path)]) == 1
    assert "start token" in capsys.readouterr().err
    assert not result_path.exists()


def test_worker_rejects_paths_outside_fixed_scratch_contract(tmp_path: Path) -> None:
    _request_path, result_path, progress_path = _worker_paths(tmp_path)

    with pytest.raises(ValueError, match="scratch contract"):
        worker._fixed_worker_paths(
            [str(tmp_path / "other.json"), str(result_path), str(progress_path)]
        )

    with pytest.raises(ValueError, match="expected request"):
        worker._fixed_worker_paths([])


def test_worker_request_reader_rejects_missing_and_non_object_payloads(tmp_path: Path) -> None:
    request_path = tmp_path / "request.json"

    with pytest.raises(ValueError, match="missing or unsafe"):
        worker._read_request(request_path, tmp_path)

    request_path.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="must be an object"):
        worker._read_request(request_path, tmp_path)


def test_worker_request_fields_reject_invalid_and_relative_media(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="fields are invalid"):
        worker._request_fields({})

    payload = _request(tmp_path / "media.wav")
    payload["media_path"] = "relative.wav"
    with pytest.raises(ValueError, match="absolute direct file"):
        worker._request_fields(payload)


def test_worker_rejects_hardlinked_media(tmp_path: Path) -> None:
    media = tmp_path / "media.wav"
    media.write_bytes(b"media")
    alias = tmp_path / "alias.wav"
    os.link(media, alias)

    with pytest.raises(ValueError, match="single-link"):
        worker._request_fields(_request(media))


def test_worker_result_rejects_oversized_text(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(worker, "_MAX_RESULT_BYTES", 4)
    result = TranscriptionResult(
        text="large",
        provider="faster-whisper",
        model="large-v3",
    )

    with pytest.raises(ValueError, match="byte limit"):
        worker._write_result(tmp_path / "result.json", result)


def test_worker_result_rejects_oversized_envelope_after_text_check(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(worker, "_MAX_RESULT_BYTES", 80)
    result = TranscriptionResult(
        text="",
        provider="faster-whisper",
        model="large-v3",
        notes=["metadata"],
    )

    with pytest.raises(ValueError, match="worker result"):
        worker._write_result(tmp_path / "result.json", result)


def test_worker_main_uses_process_arguments_when_none_are_supplied(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    request_path, result_path, progress_path = _worker_paths(tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        ["worker", str(request_path), str(result_path), str(progress_path)],
    )
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(buffer=io.BytesIO(b"0")))

    assert worker.main() == 1
    assert "start token" in capsys.readouterr().err

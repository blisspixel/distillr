"""Private faster-whisper worker entered through the bounded parent boundary."""

from __future__ import annotations

import json
import math
import stat
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

from distill.ingestors.transcribe import TranscriptionResult, _transcribe_local_core
from distill.library.confined import read_confined_text, validate_confined_path
from distill.library.paths import atomic_write_text

_MAX_REQUEST_BYTES = 4 * 1024
_MAX_RESULT_BYTES = 20 * 1024 * 1024


def _fixed_worker_paths(arguments: list[str]) -> tuple[Path, Path, Path, Path]:
    if len(arguments) != 3:
        raise ValueError("expected request, result, and progress paths")
    request_path, result_path, progress_path = map(Path, arguments)
    root = result_path.parent.resolve(strict=True)
    expected = (
        root / "request.json",
        root / "result.json",
        root / "progress.json",
    )
    supplied = (request_path, result_path, progress_path)
    if any(
        path.resolve(strict=False) != target
        for path, target in zip(supplied, expected, strict=True)
    ):
        raise ValueError("worker paths do not match the private scratch contract")
    return expected[0], expected[1], expected[2], root


def _read_request(request_path: Path, root: Path) -> dict[str, Any]:
    raw = read_confined_text(request_path, root, max_bytes=_MAX_REQUEST_BYTES)
    if raw is None:
        raise ValueError("request is missing or unsafe")
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("request must be an object")
    return payload


def _request_fields(payload: dict[str, Any]) -> tuple[Path, str, str, float]:
    media_value = payload.get("media_path")
    model_name = payload.get("model_name")
    vocabulary_hint = payload.get("vocabulary_hint")
    progress_interval = payload.get("progress_interval_s")
    if (
        not isinstance(media_value, str)
        or not isinstance(model_name, str)
        or not model_name
        or len(model_name) > 128
        or any(ord(char) < 32 for char in model_name)
        or not isinstance(vocabulary_hint, str)
        or len(vocabulary_hint) > 900
        or isinstance(progress_interval, bool)
        or not isinstance(progress_interval, int | float)
        or not math.isfinite(float(progress_interval))
        or float(progress_interval) <= 0
    ):
        raise ValueError("request fields are invalid")
    media_path = Path(media_value)
    if not media_path.is_absolute() or media_path.is_symlink():
        raise ValueError("media path is not an absolute direct file")
    validated = validate_confined_path(
        media_path,
        media_path.parent,
        expect_directory=False,
    )
    if validated is None or not stat.S_ISREG(validated[1].st_mode) or validated[1].st_nlink != 1:
        raise ValueError("media path is not a stable single-link regular file")
    return media_path, model_name, vocabulary_hint, float(progress_interval)


def _write_progress(path: Path, audio_seconds: float, total_audio_s: float, words: int) -> None:
    atomic_write_text(
        path,
        json.dumps(
            {
                "audio_seconds": audio_seconds,
                "total_audio_s": total_audio_s,
                "words": words,
            },
            allow_nan=False,
            separators=(",", ":"),
        ),
    )


def _write_result(path: Path, result: TranscriptionResult) -> None:
    if len(result.text.encode("utf-8")) > _MAX_RESULT_BYTES:
        raise ValueError("transcript exceeds the worker result byte limit")
    encoded = json.dumps(
        asdict(result),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    )
    if len(encoded.encode("utf-8")) > _MAX_RESULT_BYTES:
        raise ValueError("worker result exceeds its byte limit")
    atomic_write_text(path, encoded)


def main(arguments: list[str] | None = None) -> int:
    try:
        request_path, result_path, progress_path, root = _fixed_worker_paths(
            sys.argv[1:] if arguments is None else arguments
        )
        if sys.stdin.buffer.read(1) != b"1":
            raise ValueError("worker start token was not received")
        payload = _read_request(request_path, root)
        media_path, model_name, vocabulary_hint, progress_interval = _request_fields(payload)
        result = _transcribe_local_core(
            media_path,
            model_name=model_name,
            vocabulary_hint=vocabulary_hint,
            progress=lambda audio, total, words: _write_progress(
                progress_path,
                audio,
                total,
                words,
            ),
            progress_interval_s=progress_interval,
        )
        _write_result(result_path, result)
        return 0
    except Exception as exc:
        detail = " ".join(str(exc).split())[-500:]
        sys.stderr.write(f"{type(exc).__name__}: {detail}\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

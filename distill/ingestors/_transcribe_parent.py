"""Resource-bounded parent process for local transcription workers."""

from __future__ import annotations

import contextlib
import json
import logging
import math
import os
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path

from distill.ingestors._transcribe_types import (
    LocalTranscriptionUnavailable as _LocalUnavailable,
)
from distill.ingestors._transcribe_types import ProgressCallback, TranscriptionResult
from distill.library.confined import read_confined_text
from distill.process_resources import (
    ProcessBudgetExceeded,
    assign_windows_memory_job,
    close_windows_job,
    start_bounded_pipe_drain,
    terminate_isolated_process_tree,
    wait_for_process_budget,
)
from distill.process_security import package_install_context

_log = logging.getLogger("distill.ingestors.transcribe")

_LOCAL_WORKER_MEMORY_BYTES = 16 * 1024 * 1024 * 1024
_LOCAL_WORKER_MAX_SECONDS = 6 * 60 * 60
_LOCAL_WORKER_DIAGNOSTIC_BYTES = 32 * 1024
_LOCAL_WORKER_RESULT_BYTES = 20 * 1024 * 1024
_LOCAL_WORKER_PROGRESS_BYTES = 1024
_LOCAL_WORKER_POLL_SECONDS = 0.25


def _local_worker_timeout(duration_s: float) -> float:
    return min(
        float(_LOCAL_WORKER_MAX_SECONDS),
        max(600.0, 300.0 + (duration_s * 4.0)),
    )


def _clean_worker_diagnostic(raw: bytes) -> str:
    decoded = raw.decode("utf-8", errors="replace")
    return " ".join(decoded.split())[-500:]


def _forward_local_progress(
    progress_path: Path,
    root: Path,
    callback: ProgressCallback,
    previous: str,
) -> str:
    raw = read_confined_text(progress_path, root, max_bytes=_LOCAL_WORKER_PROGRESS_BYTES)
    if raw is None or raw == previous:
        return previous
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("local worker progress is not an object")
    audio_seconds = payload.get("audio_seconds")
    total_audio_s = payload.get("total_audio_s")
    words = payload.get("words")
    if (
        isinstance(audio_seconds, bool)
        or not isinstance(audio_seconds, int | float)
        or not math.isfinite(float(audio_seconds))
        or float(audio_seconds) < 0
        or isinstance(total_audio_s, bool)
        or not isinstance(total_audio_s, int | float)
        or not math.isfinite(float(total_audio_s))
        or float(total_audio_s) < 0
        or isinstance(words, bool)
        or not isinstance(words, int)
        or words < 0
    ):
        raise ValueError("local worker progress contains invalid counters")
    callback(float(audio_seconds), float(total_audio_s), words)
    return raw


@dataclass(slots=True)
class _LocalProgressWatcher:
    stop: threading.Event
    errors: list[BaseException]
    thread: threading.Thread | None

    def close(self) -> None:
        self.stop.set()
        if self.thread is not None:
            self.thread.join(timeout=2)


def _start_local_progress_watcher(
    progress_path: Path,
    root: Path,
    callback: ProgressCallback | None,
) -> _LocalProgressWatcher:
    stop = threading.Event()
    errors: list[BaseException] = []
    if callback is None:
        return _LocalProgressWatcher(stop, errors, None)

    def watch() -> None:
        previous = ""
        try:
            while not stop.wait(_LOCAL_WORKER_POLL_SECONDS):
                previous = _forward_local_progress(
                    progress_path,
                    root,
                    callback,
                    previous,
                )
            _forward_local_progress(progress_path, root, callback, previous)
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(
        target=watch,
        daemon=True,
        name="distill-local-transcription-progress",
    )
    thread.start()
    return _LocalProgressWatcher(stop, errors, thread)


def _read_local_worker_result(
    result_path: Path,
    root: Path,
    *,
    expected_model: str,
) -> TranscriptionResult:
    raw = read_confined_text(result_path, root, max_bytes=_LOCAL_WORKER_RESULT_BYTES)
    if raw is None:
        raise _LocalUnavailable("local transcription worker returned no safe result")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise _LocalUnavailable("local transcription worker returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise _LocalUnavailable("local transcription worker returned an invalid result")
    text = payload.get("text")
    provider = payload.get("provider")
    model = payload.get("model")
    language = payload.get("language", "")
    duration = payload.get("duration_s", 0.0)
    notes = payload.get("notes", [])
    if (
        not isinstance(text, str)
        or len(text.encode("utf-8")) > _LOCAL_WORKER_RESULT_BYTES
        or provider != "faster-whisper"
        or not isinstance(model, str)
        or model != expected_model
        or not isinstance(language, str)
        or len(language) > 32
        or isinstance(duration, bool)
        or not isinstance(duration, int | float)
        or not math.isfinite(float(duration))
        or float(duration) < 0
        or not isinstance(notes, list)
        or len(notes) > 32
        or any(not isinstance(note, str) or len(note) > 256 for note in notes)
    ):
        raise _LocalUnavailable("local transcription worker returned invalid fields")
    return TranscriptionResult(
        text=text,
        provider=provider,
        model=model,
        language=language,
        duration_s=float(duration),
        notes=notes,
    )


def _run_local_worker_process(
    request_path: Path,
    result_path: Path,
    progress_path: Path,
    root: Path,
    *,
    timeout_seconds: float,
    progress: ProgressCallback | None,
) -> None:
    trusted_cwd, child_env = package_install_context()
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    process = subprocess.Popen(
        [
            str(Path(sys.executable).resolve(strict=True)),
            "-P",
            "-m",
            "distill.ingestors._transcribe_worker",
            str(request_path),
            str(result_path),
            str(progress_path),
        ],
        cwd=trusted_cwd,
        env=child_env,
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        creationflags=creationflags,
        start_new_session=os.name != "nt",
    )
    stderr_stream = process.stderr
    if stderr_stream is None:
        terminate_isolated_process_tree(process)
        raise _LocalUnavailable("local worker did not expose a diagnostic pipe")
    diagnostic_tail, diagnostic_thread = start_bounded_pipe_drain(
        stderr_stream,
        limit=_LOCAL_WORKER_DIAGNOSTIC_BYTES,
        thread_name="distill-local-transcription-diagnostics",
    )
    watcher = _start_local_progress_watcher(progress_path, root, progress)
    job_handle: int | None = None
    try:
        job_handle = assign_windows_memory_job(
            process,
            job_memory_bytes=_LOCAL_WORKER_MEMORY_BYTES,
        )
        worker_stdin = process.stdin
        if worker_stdin is None:
            raise _LocalUnavailable("local worker did not expose a control pipe")
        worker_stdin.write(b"1")
        worker_stdin.close()
        process.stdin = None
        wait_for_process_budget(
            process,
            timeout_seconds=timeout_seconds,
            memory_limit_bytes=_LOCAL_WORKER_MEMORY_BYTES,
        )
    except ProcessBudgetExceeded as exc:
        raise _LocalUnavailable(f"local transcription exceeded its {exc.kind} budget") from exc
    finally:
        terminate_isolated_process_tree(process)
        close_windows_job(job_handle)
        watcher.close()
        diagnostic_thread.join(timeout=1)
        with contextlib.suppress(OSError):
            stderr_stream.close()
        diagnostic_thread.join(timeout=1)
    if watcher.errors:
        raise watcher.errors[0]
    if process.returncode != 0:
        detail = _clean_worker_diagnostic(diagnostic_tail.bytes())
        if detail:
            _log.warning("local transcription worker failed: %s", detail)
        raise _LocalUnavailable(
            f"local transcription worker exited with status {process.returncode}"
        )

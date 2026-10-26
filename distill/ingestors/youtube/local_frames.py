# pyright: strict
"""Bounded, opt-in local frame acquisition with inspectable restart evidence."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import struct
import subprocess
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from decimal import ROUND_CEILING, Decimal, InvalidOperation
from itertools import pairwise
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from distill.library.confined import read_confined_bytes
from distill.library.confined_state import (
    atomic_write_confined_bytes,
    atomic_write_confined_text,
    confined_file_identity,
    confined_state_lock_path,
    ensure_confined_parent,
)
from distill.library.locking import exclusive_path_lock
from distill.library.paths import text_write_lock
from distill.process_resources import (
    BoundedByteHead,
    ProcessBudgetExceeded,
    assign_windows_memory_job,
    close_windows_job,
    start_bounded_pipe_drain,
    start_bounded_pipe_head_drain,
    terminate_isolated_process_tree,
    wait_for_process_budget,
)
from distill.process_security import resolve_executable, sanitized_package_env

MAX_SOURCE_BYTES = 100 * 1024 * 1024
_SOURCE_BYTES = MAX_SOURCE_BYTES
_FRAME_BYTES = 4 * 1024 * 1024
_DURATION_MS = 180_000
_MEMORY_BYTES = 512 * 1024 * 1024
_OUTPUT_BYTES = 16 * 1024
_SUFFIXES = frozenset({".mp4", ".m4v", ".mov", ".mkv", ".webm", ".avi", ".ts"})
_FORMATS = "mov,matroska,webm,avi,mpegts"
_TIMESTAMP_BASIS = "requested_seek_not_measured_pts"
_monotonic = time.monotonic


@dataclass(frozen=True, slots=True)
class SampledFrame:
    timestamp_ms: int
    relative_path: str
    sha256: str
    selection_reason: str = "requested"


@dataclass(frozen=True, slots=True)
class LocalVideoFrames:
    source_sha256: str
    source_relative_path: str
    duration_ms: int
    frames: tuple[SampledFrame, ...]
    blind_intervals_ms: tuple[tuple[int, int], ...]
    status: Literal["complete", "cancelled"] = "complete"
    timestamp_basis: Literal["requested_seek_not_measured_pts"] = _TIMESTAMP_BASIS


class _StoredFrame(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    timestamp_ms: int
    relative_path: str
    sha256: str
    selection_reason: Literal["requested"]


class _StoredCapture(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal["local-video-frames.v1"]
    recipe_sha256: str
    source_sha256: str
    source_relative_path: str
    duration_ms: int
    requested_timestamps_ms: list[int]
    frames: list[_StoredFrame]
    blind_intervals_ms: list[tuple[int, int]]
    status: Literal["complete", "cancelled", "in_progress"]
    timestamp_basis: Literal["requested_seek_not_measured_pts"]


class _CaptureCancelled(Exception):
    """Internal cancellation control; completed samples remain durable."""


def _remaining(deadline: float) -> float:
    remaining = deadline - _monotonic()
    if remaining <= 0:
        raise ValueError("Local frame capture exceeded its whole-tool deadline")
    return remaining


def _run_media_tool(
    command: list[str],
    root: Path,
    *,
    deadline: float,
    cancelled: Callable[[], bool] | None,
    output_limit: int = _OUTPUT_BYTES,
) -> bytes:
    """Run one local-only decoder with bounded pipes, time, memory and cleanup."""
    _remaining(deadline)
    if cancelled is not None and cancelled():
        raise _CaptureCancelled
    process = subprocess.Popen(
        command,
        cwd=str(root),
        env={
            key: value
            for key, value in sanitized_package_env().items()
            if key.upper() != "FFREPORT"
        },
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        start_new_session=os.name != "nt",
    )
    stdout, stderr = process.stdout, process.stderr
    if stdout is None or stderr is None:
        terminate_isolated_process_tree(process)
        raise ValueError("Local media tool did not expose bounded diagnostic pipes")
    output, output_thread = start_bounded_pipe_head_drain(
        stdout, limit=output_limit, thread_name="distill-frame-output"
    )
    _diagnostic, diagnostic_thread = start_bounded_pipe_drain(
        stderr, limit=_OUTPUT_BYTES, thread_name="distill-frame-diagnostics"
    )
    job: int | None = None
    try:
        job = assign_windows_memory_job(process, job_memory_bytes=_MEMORY_BYTES)
        _wait_for_tool(process, output, deadline, cancelled)
    finally:
        terminate_isolated_process_tree(process)
        close_windows_job(job)
        for stream, thread in ((stdout, output_thread), (stderr, diagnostic_thread)):
            thread.join(timeout=1)
            with contextlib.suppress(OSError):
                stream.close()
            thread.join(timeout=1)
    if output.truncated:
        raise ValueError("Local media tool exceeded its diagnostic output limit")
    if process.returncode != 0:
        # Do not persist raw tool diagnostics, source paths or private payloads.
        raise ValueError(f"Local media tool failed with exit status {process.returncode}")
    _remaining(deadline)
    return output.bytes()


def _wait_for_tool(
    process: subprocess.Popen[bytes],
    output: BoundedByteHead,
    deadline: float,
    cancelled: Callable[[], bool] | None,
) -> None:
    while process.poll() is None:
        if output.truncated:
            raise ValueError("Local media tool exceeded its bounded output limit")
        if cancelled is not None and cancelled():
            raise _CaptureCancelled
        try:
            wait_for_process_budget(
                process,
                timeout_seconds=min(_remaining(deadline), 0.25),
                memory_limit_bytes=_MEMORY_BYTES,
            )
        except ProcessBudgetExceeded as exc:
            if exc.kind != "time":
                raise ValueError("Local media tool exceeded its memory budget") from exc
            _remaining(deadline)


def _validate_request(source: Path, timestamps: tuple[int, ...], timeout: int) -> None:
    if source.suffix.lower() not in _SUFFIXES:
        raise ValueError("Local frame capture requires an explicitly supported video file")
    if not 1 <= len(timestamps) <= 4 or len(set(timestamps)) != len(timestamps):
        raise ValueError("Local frame capture requires one to four unique requested timestamps")
    if any(
        type(timestamp) is not int or not 0 <= timestamp < _DURATION_MS for timestamp in timestamps
    ):
        raise ValueError("Frame timestamps must be integer milliseconds within the duration limit")
    if type(timeout) is not int or not 1 <= timeout <= 120:
        raise ValueError("Local frame capture timeout must be an integer from 1 to 120 seconds")


def _retain_bytes(path: Path, content: bytes, root: Path, limit: int) -> None:
    with text_write_lock(path):
        if confined_file_identity(path, root) is None:
            atomic_write_confined_bytes(path, content, root, exclusive=True)
        elif read_confined_bytes(path, root, max_bytes=limit) != content:
            raise ValueError("Retained local frame evidence is corrupt")


def _snapshot(source: Path, root: Path) -> tuple[str, str]:
    absolute = source.absolute()
    content = read_confined_bytes(absolute, Path(absolute.anchor), max_bytes=_SOURCE_BYTES)
    if content is None or not content:
        raise ValueError("Source video must be a stable private file no larger than 100 MiB")
    digest = hashlib.sha256(content).hexdigest()
    filename = f"source-{digest}{source.suffix.lower()}"
    _retain_bytes(root / filename, content, root, _SOURCE_BYTES)
    return digest, filename


def _tools_recipe(timestamps: tuple[int, ...]) -> tuple[str, str, str]:
    tools: list[str] = []
    identities: list[dict[str, str | int]] = []
    for name in ("ffprobe", "ffmpeg"):
        executable = resolve_executable(name)
        if executable is None:
            raise ValueError(
                f"Local frame capture requires existing {name}; no installation attempted"
            )
        file_stat = Path(executable).stat()
        tools.append(executable)
        identities.append(
            {"path": executable, "size": file_stat.st_size, "mtime_ns": file_stat.st_mtime_ns}
        )
    recipe = json.dumps(
        {
            "schema": "local-frame-recipe.v1",
            "timestamps_ms": timestamps,
            "scale": [1280, 720],
            "source_bytes": _SOURCE_BYTES,
            "frame_bytes": _FRAME_BYTES,
            "frame_transport": "bounded_stdout_png",
            "duration_ms": _DURATION_MS,
            "formats": _FORMATS,
            "protocols": "file,pipe",
            "tool_identity_basis": "resolved_path_size_mtime",
            "tools": identities,
        },
        sort_keys=True,
    )
    return tools[0], tools[1], hashlib.sha256(recipe.encode("utf-8")).hexdigest()


def _probe_duration(
    executable: str,
    snapshot: Path,
    root: Path,
    deadline: float,
    cancelled: Callable[[], bool] | None,
) -> int:
    output = _run_media_tool(
        [
            executable,
            "-v",
            "error",
            "-protocol_whitelist",
            "file,pipe",
            "-format_whitelist",
            _FORMATS,
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(snapshot),
        ],
        root,
        deadline=deadline,
        cancelled=cancelled,
    )
    try:
        seconds = Decimal(output.decode("ascii").strip())
        if not seconds.is_finite() or seconds <= 0 or seconds > Decimal(180):
            raise ValueError("Video duration must be finite, positive and at most 180 seconds")
        return int((seconds * 1000).to_integral_value(rounding=ROUND_CEILING))
    except (InvalidOperation, UnicodeError) as exc:
        raise ValueError("Local video duration is unavailable") from exc


def _blind_intervals(
    frames: tuple[SampledFrame, ...], duration: int
) -> tuple[tuple[int, int], ...]:
    anchors = sorted({0, duration, *(frame.timestamp_ms for frame in frames)})
    return tuple((left, right) for left, right in pairwise(anchors) if left < right)


def _frame_bytes(path: Path, root: Path) -> bytes:
    content = read_confined_bytes(path, root, max_bytes=_FRAME_BYTES)
    if content is None:
        raise ValueError("Requested frame did not materialize as a bounded PNG")
    _validate_png(content)
    return content


def _validate_png(content: bytes) -> None:
    if not 33 <= len(content) <= _FRAME_BYTES or content[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("Requested frame did not materialize as a bounded PNG")
    if content[12:16] != b"IHDR":
        raise ValueError("Requested frame has no PNG image header")
    width, height = struct.unpack(">II", content[16:24])
    if not (0 < width <= 1280 and 0 < height <= 720):
        raise ValueError("Requested PNG frame exceeds its image dimensions")


def _capture_frame(
    executable: str,
    snapshot: Path,
    root: Path,
    timestamp: int,
    deadline: float,
    cancelled: Callable[[], bool] | None,
) -> SampledFrame:
    content = _run_media_tool(
        [
            executable,
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-protocol_whitelist",
            "file,pipe",
            "-format_whitelist",
            _FORMATS,
            "-ss",
            f"{timestamp // 1000}.{timestamp % 1000:03d}",
            "-i",
            str(snapshot),
            "-map",
            "0:v:0",
            "-map_metadata",
            "-1",
            "-an",
            "-sn",
            "-dn",
            "-frames:v",
            "1",
            "-vf",
            "scale=w=1280:h=720:force_original_aspect_ratio=decrease:force_divisible_by=2",
            "-threads",
            "1",
            "-pix_fmt",
            "rgb24",
            "-c:v",
            "png",
            "-f",
            "image2pipe",
            "pipe:1",
        ],
        root,
        deadline=deadline,
        cancelled=cancelled,
        output_limit=_FRAME_BYTES,
    )
    _validate_png(content)
    digest = hashlib.sha256(content).hexdigest()
    filename = f"frame-{digest}.png"
    _retain_bytes(root / filename, content, root, _FRAME_BYTES)
    return SampledFrame(timestamp, filename, digest)


def _load_progress(
    path: Path,
    root: Path,
    source_sha: str,
    source_name: str,
    recipe: str,
    timestamps: tuple[int, ...],
    duration: int,
) -> tuple[SampledFrame, ...]:
    encoded = read_confined_bytes(path, root, max_bytes=32 * 1024)
    if encoded is None:
        return ()
    stored = _StoredCapture.model_validate_json(encoded)
    if (
        stored.source_sha256 != source_sha
        or stored.source_relative_path != source_name
        or stored.recipe_sha256 != recipe
        or tuple(stored.requested_timestamps_ms) != timestamps
        or stored.duration_ms != duration
        or len(stored.frames) > len(timestamps)
        or tuple(frame.timestamp_ms for frame in stored.frames) != timestamps[: len(stored.frames)]
    ):
        raise ValueError("Retained local frame manifest does not match source, recipe or timing")
    frames: list[SampledFrame] = []
    for frame in stored.frames:
        if frame.relative_path != f"frame-{frame.sha256}.png":
            raise ValueError("Retained frame has an invalid content-addressed path")
        content = _frame_bytes(root / frame.relative_path, root)
        if hashlib.sha256(content).hexdigest() != frame.sha256:
            raise ValueError("Retained frame bytes do not match their recorded hash")
        frames.append(SampledFrame(frame.timestamp_ms, frame.relative_path, frame.sha256))
    result = tuple(frames)
    if tuple(stored.blind_intervals_ms) != _blind_intervals(result, duration):
        raise ValueError("Retained frame manifest has invalid blind intervals")
    if stored.status == "complete" and len(result) != len(timestamps):
        raise ValueError("Retained complete frame manifest omits requested samples")
    return result


def _save_progress(
    path: Path,
    root: Path,
    source_sha: str,
    source_name: str,
    recipe: str,
    timestamps: tuple[int, ...],
    duration: int,
    frames: tuple[SampledFrame, ...],
    status: Literal["complete", "cancelled", "in_progress"],
) -> None:
    payload = {
        "schema_version": "local-video-frames.v1",
        "recipe_sha256": recipe,
        "source_sha256": source_sha,
        "source_relative_path": source_name,
        "duration_ms": duration,
        "requested_timestamps_ms": timestamps,
        "frames": [asdict(frame) for frame in frames],
        "blind_intervals_ms": _blind_intervals(frames, duration),
        "status": status,
        "timestamp_basis": _TIMESTAMP_BASIS,
    }
    atomic_write_confined_text(path, json.dumps(payload, sort_keys=True) + "\n", root)


def capture_local_video_frames(
    source: Path,
    output_dir: Path,
    *,
    timestamps_ms: tuple[int, ...],
    timeout_seconds: int = 30,
    cancelled: Callable[[], bool] | None = None,
) -> LocalVideoFrames:
    """Capture at most four local samples. Requested seeks are not measured PTS."""
    _validate_request(source, timestamps_ms, timeout_seconds)
    deadline = _monotonic() + timeout_seconds
    root = output_dir.absolute()
    ensure_confined_parent(root / ".capture", Path(root.anchor), create=True)
    lock = confined_state_lock_path(root / ".local-frame-capture", root, "local-frames")
    with exclusive_path_lock(
        lock,
        timeout_seconds=_remaining(deadline),
        timeout_message="Local frame capture exceeded its deadline waiting for publication",
    ):
        source_sha, source_name = _snapshot(source, root)
        if cancelled is not None and cancelled():
            return LocalVideoFrames(source_sha, source_name, 0, (), (), "cancelled")
        ffprobe, ffmpeg, recipe = _tools_recipe(timestamps_ms)
        path = root / f"local-frames-{source_sha}-{recipe}.json"
        try:
            duration = _probe_duration(ffprobe, root / source_name, root, deadline, cancelled)
        except _CaptureCancelled:
            return LocalVideoFrames(source_sha, source_name, 0, (), (), "cancelled")
        if any(timestamp >= duration for timestamp in timestamps_ms):
            raise ValueError("Requested frame timestamp is outside the measured source duration")
        frames = _load_progress(
            path, root, source_sha, source_name, recipe, timestamps_ms, duration
        )
        try:
            for timestamp in timestamps_ms[len(frames) :]:
                if cancelled is not None and cancelled():
                    raise _CaptureCancelled
                frames = (
                    *frames,
                    _capture_frame(
                        ffmpeg, root / source_name, root, timestamp, deadline, cancelled
                    ),
                )
                _save_progress(
                    path,
                    root,
                    source_sha,
                    source_name,
                    recipe,
                    timestamps_ms,
                    duration,
                    frames,
                    "in_progress",
                )
        except _CaptureCancelled:
            _save_progress(
                path,
                root,
                source_sha,
                source_name,
                recipe,
                timestamps_ms,
                duration,
                frames,
                "cancelled",
            )
            return LocalVideoFrames(
                source_sha,
                source_name,
                duration,
                frames,
                _blind_intervals(frames, duration),
                "cancelled",
            )
        _remaining(deadline)
        _save_progress(
            path, root, source_sha, source_name, recipe, timestamps_ms, duration, frames, "complete"
        )
        return LocalVideoFrames(
            source_sha, source_name, duration, frames, _blind_intervals(frames, duration)
        )

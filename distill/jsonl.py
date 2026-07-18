# pyright: strict
"""Serialized append primitives for local JSONL histories."""

from __future__ import annotations

import contextlib
import os
from collections.abc import Generator
from pathlib import Path
from typing import BinaryIO, Protocol

from distill.library.locking import exclusive_path_lock

JSONL_LOCK_TIMEOUT_SECONDS = 30.0


class _BinaryWriter(Protocol):
    def write(self, data: bytes | memoryview, /) -> int | None: ...


def bounded_jsonl_lines(
    stream: BinaryIO,
    *,
    max_row_bytes: int,
) -> Generator[bytes | None]:
    """Yield bounded row payloads, using ``None`` for one oversized row."""

    if max_row_bytes < 1:
        raise ValueError("max_row_bytes must be positive")
    limit = max_row_bytes + 2
    while True:
        raw = stream.readline(limit)
        if not raw:
            return
        terminated = raw.endswith(b"\n")
        payload = raw[:-1] if terminated else raw
        if payload.endswith(b"\r"):
            payload = payload[:-1]
        if len(payload) > max_row_bytes:
            while raw and not raw.endswith(b"\n"):
                raw = stream.readline(limit)
            yield None
            continue
        yield payload


def _lock_path(path: Path) -> Path:
    return path.with_name(f".{path.name}.lock")


@contextlib.contextmanager
def jsonl_append_lock(
    path: Path,
    *,
    timeout_seconds: float = JSONL_LOCK_TIMEOUT_SECONDS,
) -> Generator[None]:
    """Serialize cooperating writers for one append-only JSONL path."""

    with exclusive_path_lock(
        _lock_path(path),
        timeout_seconds=timeout_seconds,
        timeout_message=f"Timed out waiting to append structured history: {path}",
    ):
        yield


def _write_all(writer: _BinaryWriter, payload: bytes) -> None:
    """Write every byte or fail instead of accepting a short append."""

    remaining = memoryview(payload)
    while remaining:
        written = writer.write(remaining)
        if written is None or written <= 0 or written > len(remaining):
            raise OSError("Unable to write a complete JSONL row")
        remaining = remaining[written:]


def append_jsonl_line_locked(
    path: Path,
    line: str,
    *,
    durable: bool,
) -> None:
    """Append one line while the caller holds :func:`jsonl_append_lock`."""

    if not line or "\n" in line or "\r" in line:
        raise ValueError("A JSONL record must be one nonempty line")
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = line.encode("utf-8") + b"\n"
    with path.open("a+b", buffering=0) as stream:
        stream.seek(0, os.SEEK_END)
        if stream.tell() > 0:
            stream.seek(-1, os.SEEK_END)
            terminated = stream.read(1) == b"\n"
            stream.seek(0, os.SEEK_END)
            if not terminated:
                _write_all(stream, b"\n")
        _write_all(stream, encoded)
        if durable:
            os.fsync(stream.fileno())


def append_jsonl_line(
    path: Path,
    line: str,
    *,
    durable: bool = False,
    timeout_seconds: float = JSONL_LOCK_TIMEOUT_SECONDS,
) -> None:
    """Append one complete line under a per-target cross-process lock."""

    if not line or "\n" in line or "\r" in line:
        raise ValueError("A JSONL record must be one nonempty line")
    with jsonl_append_lock(path, timeout_seconds=timeout_seconds):
        append_jsonl_line_locked(path, line, durable=durable)

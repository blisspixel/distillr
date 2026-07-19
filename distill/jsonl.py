# pyright: strict
"""Serialized, bounded primitives for local JSONL histories."""

from __future__ import annotations

import contextlib
import os
import stat
from collections.abc import Generator, Iterable
from errno import ELOOP
from pathlib import Path
from typing import BinaryIO, Protocol, cast

from distill.library.confined_state import (
    ConfinedStateError,
    PathRevision,
    confined_file_identity,
    confined_state_lock_path,
    ensure_confined_parent,
)
from distill.library.locking import exclusive_path_lock
from distill.parsing import strict_json_loads

JSONL_LOCK_TIMEOUT_SECONDS = 30.0
_TARGET_OPEN_RETRIES = 3
_TARGET_FILE_MODE = 0o600


class JsonlIntegrityError(ValueError):
    """A canonical JSONL history cannot be read without losing evidence."""

    def __init__(self, path: Path, reason: str) -> None:
        self.path = path
        self.reason = reason
        super().__init__(f"Invalid JSONL history at {path}: {reason}")


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


def _lock_path(path: Path, confinement_root: Path | None = None) -> Path:
    if confinement_root is not None:
        return confined_state_lock_path(path, confinement_root, "jsonl")
    return path.with_name(f".{path.name}.lock")


@contextlib.contextmanager
def jsonl_append_lock(
    path: Path,
    *,
    timeout_seconds: float = JSONL_LOCK_TIMEOUT_SECONDS,
    confinement_root: Path | None = None,
) -> Generator[None]:
    """Serialize cooperating writers for one append-only JSONL path."""

    lock_path = _lock_path(path, confinement_root)
    if confinement_root is not None:
        ensure_confined_parent(lock_path, confinement_root, create=False)
    with exclusive_path_lock(
        lock_path,
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


def _is_link_like(path: Path, file_stat: os.stat_result) -> bool:
    if stat.S_ISLNK(file_stat.st_mode):
        return True
    reparse_flag = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))
    attributes = int(getattr(file_stat, "st_file_attributes", 0))
    return bool(reparse_flag and attributes & reparse_flag) or (
        hasattr(path, "is_junction") and path.is_junction()
    )


def _validate_target_stat(path: Path, file_stat: os.stat_result) -> None:
    if _is_link_like(path, file_stat):
        raise ValueError(f"Refusing to use a link as a JSONL history: {path}")
    if not stat.S_ISREG(file_stat.st_mode):
        raise ValueError(f"Refusing to use a non-file JSONL history: {path}")
    if file_stat.st_nlink != 1:
        raise ValueError(f"Refusing to use a multiply linked JSONL history: {path}")


def _initial_target_stat(path: Path) -> os.stat_result | None:
    try:
        initial_stat = path.lstat()
    except FileNotFoundError:
        return None
    _validate_target_stat(path, initial_stat)
    return initial_stat


def _target_identity(file_stat: os.stat_result) -> tuple[int, int]:
    return (file_stat.st_dev, file_stat.st_ino)


def _target_revision(file_stat: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        file_stat.st_dev,
        file_stat.st_ino,
        file_stat.st_nlink,
        file_stat.st_size,
        file_stat.st_mtime_ns,
        file_stat.st_ctime_ns,
    )


def _try_open_target_descriptor(
    path: Path,
    flags: int,
    initial_stat: os.stat_result | None,
) -> int | None:
    if initial_stat is None:
        flags |= os.O_CREAT | os.O_EXCL
    try:
        return os.open(path, flags, _TARGET_FILE_MODE)
    except (FileExistsError, FileNotFoundError):
        return None
    except OSError as exc:
        if exc.errno == ELOOP:
            raise ValueError(f"Refusing to use a link as a JSONL history: {path}") from exc
        raise


def _validate_opened_descriptor(
    path: Path,
    descriptor: int,
    initial_stat: os.stat_result | None,
) -> os.stat_result:
    descriptor_stat = os.fstat(descriptor)
    current_stat = path.lstat()
    _validate_target_stat(path, descriptor_stat)
    _validate_target_stat(path, current_stat)
    identities = {
        _target_identity(descriptor_stat),
        _target_identity(current_stat),
    }
    if initial_stat is not None:
        identities.add(_target_identity(initial_stat))
    if len(identities) != 1:
        raise ValueError(f"JSONL history changed while it was being opened: {path}")
    return descriptor_stat


def _open_target_descriptor(  # noqa: C901
    path: Path,
    *,
    create: bool,
    write: bool,
    confinement_root: Path | None = None,
) -> tuple[int, os.stat_result, PathRevision | None] | None:
    """Open and validate one regular single-link target without following links."""

    parent_revision: PathRevision | None = None
    if confinement_root is not None:
        prepared = ensure_confined_parent(path, confinement_root, create=create)
        if prepared is None:
            return None
        parent_revision = prepared[1]
    elif create:
        path.parent.mkdir(parents=True, exist_ok=True)
    base_flags = (
        (os.O_RDWR | os.O_APPEND if write else os.O_RDONLY)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    for _ in range(_TARGET_OPEN_RETRIES):
        initial_stat = _initial_target_stat(path)
        if initial_stat is None and not create:
            return None
        descriptor = _try_open_target_descriptor(path, base_flags, initial_stat)
        if descriptor is None:
            continue
        try:
            descriptor_stat = _validate_opened_descriptor(path, descriptor, initial_stat)
            if confinement_root is not None:
                current_parent = ensure_confined_parent(path, confinement_root, create=False)
                current_identity = confined_file_identity(path, confinement_root)
                if (
                    current_parent is None
                    or current_parent[1] != parent_revision
                    or current_identity is None
                    or current_identity[:2] != _target_identity(descriptor_stat)
                ):
                    raise ValueError(f"JSONL history escaped its confinement root: {path}")
            if write and initial_stat is None and os.name == "posix":
                os.fchmod(descriptor, _TARGET_FILE_MODE)
            return descriptor, descriptor_stat, parent_revision
        except BaseException:
            descriptor_identity = _target_identity(os.fstat(descriptor))
            os.close(descriptor)
            if initial_stat is None:
                with contextlib.suppress(OSError, ValueError, ConfinedStateError):
                    current_stat = path.lstat()
                    if _target_identity(current_stat) == descriptor_identity:
                        path.unlink()
            raise
    raise OSError(f"JSONL history changed repeatedly while it was being opened: {path}")


def _validate_open_target(
    path: Path,
    descriptor: int,
    *,
    confinement_root: Path | None = None,
    parent_revision: PathRevision | None = None,
) -> os.stat_result:
    descriptor_stat = os.fstat(descriptor)
    current_stat = path.lstat()
    _validate_target_stat(path, descriptor_stat)
    _validate_target_stat(path, current_stat)
    if _target_identity(descriptor_stat) != _target_identity(current_stat):
        raise ValueError(f"JSONL history changed while it was open: {path}")
    if confinement_root is not None:
        current_parent = ensure_confined_parent(path, confinement_root, create=False)
        current_identity = confined_file_identity(path, confinement_root)
        if (
            current_parent is None
            or current_parent[1] != parent_revision
            or current_identity is None
            or current_identity[:2] != _target_identity(descriptor_stat)
        ):
            raise ValueError(f"JSONL history escaped its confinement root: {path}")
    return descriptor_stat


def _encoded_lines(lines: Iterable[str]) -> list[bytes]:
    encoded: list[bytes] = []
    for index, line in enumerate(lines, 1):
        if not line or "\n" in line or "\r" in line:
            raise ValueError("A JSONL record must be one nonempty line")
        try:
            value = strict_json_loads(line)
        except (RecursionError, UnicodeDecodeError, ValueError) as exc:
            raise ValueError(f"JSONL record {index} must be strict JSON: {exc}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"JSONL record {index} must be a JSON object")
        encoded.append(line.encode("utf-8") + b"\n")
    return encoded


def append_jsonl_lines_locked(
    path: Path,
    lines: Iterable[str],
    *,
    durable: bool,
    confinement_root: Path | None = None,
) -> None:
    """Append one validated batch while the caller holds ``jsonl_append_lock``."""

    encoded = _encoded_lines(lines)
    if not encoded:
        return
    opened = _open_target_descriptor(
        path,
        create=True,
        write=True,
        confinement_root=confinement_root,
    )
    if opened is None:  # pragma: no cover - create=True always returns or raises
        raise OSError(f"Unable to open JSONL history: {path}")
    descriptor, _, parent_revision = opened
    try:
        with os.fdopen(descriptor, "r+b", buffering=0) as stream:
            descriptor = -1
            stream.seek(0, os.SEEK_END)
            if stream.tell() > 0:
                stream.seek(-1, os.SEEK_END)
                terminated = stream.read(1) == b"\n"
                if not terminated:
                    _write_all(stream, b"\n")
            _write_all(stream, b"".join(encoded))
            if durable:
                os.fsync(stream.fileno())
            _validate_open_target(
                path,
                stream.fileno(),
                confinement_root=confinement_root,
                parent_revision=parent_revision,
            )
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def append_jsonl_lines(
    path: Path,
    lines: Iterable[str],
    *,
    durable: bool = False,
    timeout_seconds: float = JSONL_LOCK_TIMEOUT_SECONDS,
    confinement_root: Path | None = None,
) -> None:
    """Append one complete batch under a per-target cross-process lock."""

    materialized = list(lines)
    _encoded_lines(materialized)
    if not materialized:
        return
    with jsonl_append_lock(
        path,
        timeout_seconds=timeout_seconds,
        confinement_root=confinement_root,
    ):
        append_jsonl_lines_locked(
            path,
            materialized,
            durable=durable,
            confinement_root=confinement_root,
        )


def append_jsonl_line_locked(
    path: Path,
    line: str,
    *,
    durable: bool,
    confinement_root: Path | None = None,
) -> None:
    """Append one line while the caller holds :func:`jsonl_append_lock`."""

    append_jsonl_lines_locked(
        path,
        [line],
        durable=durable,
        confinement_root=confinement_root,
    )


def append_jsonl_line(
    path: Path,
    line: str,
    *,
    durable: bool = False,
    timeout_seconds: float = JSONL_LOCK_TIMEOUT_SECONDS,
    confinement_root: Path | None = None,
) -> None:
    """Append one complete line under a per-target cross-process lock."""

    append_jsonl_lines(
        path,
        [line],
        durable=durable,
        timeout_seconds=timeout_seconds,
        confinement_root=confinement_root,
    )


def _strict_object_row(path: Path, raw: bytes, index: int) -> dict[str, object]:
    if not raw:
        raise JsonlIntegrityError(path, f"row {index} is empty")
    try:
        loaded = strict_json_loads(raw)
    except (RecursionError, UnicodeDecodeError, ValueError) as exc:
        raise JsonlIntegrityError(path, f"row {index} is not strict JSON: {exc}") from exc
    if not isinstance(loaded, dict):
        raise JsonlIntegrityError(path, f"row {index} is not a JSON object")
    return cast("dict[str, object]", loaded)


def _read_strict_rows(
    path: Path,
    stream: BinaryIO,
    *,
    max_file_bytes: int,
    max_row_bytes: int,
    max_rows: int,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for index, raw in enumerate(
        bounded_jsonl_lines(stream, max_row_bytes=max_row_bytes),
        start=1,
    ):
        if stream.tell() > max_file_bytes:
            raise JsonlIntegrityError(path, f"file exceeds the {max_file_bytes:,}-byte limit")
        if index > max_rows:
            raise JsonlIntegrityError(path, f"history exceeds the {max_rows:,}-row limit")
        if raw is None:
            raise JsonlIntegrityError(
                path,
                f"row {index} exceeds the {max_row_bytes:,}-byte limit",
            )
        rows.append(_strict_object_row(path, raw, index))
    return rows


def _ensure_complete_history(
    path: Path,
    stream: BinaryIO,
    initial_stat: os.stat_result,
) -> None:
    if not initial_stat.st_size:
        return
    stream.seek(-1, os.SEEK_END)
    if stream.read(1) != b"\n":
        raise JsonlIntegrityError(path, "final record is not newline-terminated")
    stream.seek(0)


def read_jsonl_objects_strict(
    path: Path,
    *,
    max_file_bytes: int,
    max_row_bytes: int,
    max_rows: int,
    confinement_root: Path | None = None,
) -> list[dict[str, object]]:
    """Read a complete bounded object history or raise with its exact path."""

    if max_file_bytes < 1 or max_row_bytes < 1 or max_rows < 1:
        raise ValueError("JSONL read limits must be positive")
    try:
        opened = _open_target_descriptor(
            path,
            create=False,
            write=False,
            confinement_root=confinement_root,
        )
    except (OSError, ValueError) as exc:
        raise JsonlIntegrityError(path, str(exc)) from exc
    if opened is None:
        return []
    descriptor, initial_stat, parent_revision = opened
    try:
        if initial_stat.st_size > max_file_bytes:
            raise JsonlIntegrityError(path, f"file exceeds the {max_file_bytes:,}-byte limit")
        rows: list[dict[str, object]] = []
        with os.fdopen(descriptor, "rb", buffering=0) as stream:
            descriptor = -1
            _ensure_complete_history(path, stream, initial_stat)
            rows = _read_strict_rows(
                path,
                stream,
                max_file_bytes=max_file_bytes,
                max_row_bytes=max_row_bytes,
                max_rows=max_rows,
            )
            final_stat = _validate_open_target(
                path,
                stream.fileno(),
                confinement_root=confinement_root,
                parent_revision=parent_revision,
            )
            if _target_revision(final_stat) != _target_revision(initial_stat):
                raise JsonlIntegrityError(path, "history changed while it was being read")
        return rows
    except JsonlIntegrityError:
        raise
    except (OSError, ValueError) as exc:
        raise JsonlIntegrityError(path, str(exc)) from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)

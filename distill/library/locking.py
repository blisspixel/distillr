# pyright: strict
"""Portable advisory locking for already-open single-byte lock files."""

from __future__ import annotations

import contextlib
import os
import stat
import time
from collections.abc import Generator
from errno import ELOOP
from pathlib import Path
from typing import BinaryIO

_LOCK_OPEN_RETRIES = 3
_LOCK_FILE_MODE = 0o600


def _validate_lock_stat(path: Path, file_stat: os.stat_result) -> None:
    if stat.S_ISLNK(file_stat.st_mode):
        raise ValueError(f"Refusing to use a symbolic link as a lock file: {path}")
    if not stat.S_ISREG(file_stat.st_mode):
        raise ValueError(f"Refusing to use a non-file lock path: {path}")
    if file_stat.st_nlink != 1:
        raise ValueError(f"Refusing to use a multiply linked lock file: {path}")


def _initial_lock_stat(path: Path) -> os.stat_result | None:
    try:
        initial_stat = path.lstat()
    except FileNotFoundError:
        return None
    _validate_lock_stat(path, initial_stat)
    return initial_stat


def _try_open_lock_descriptor(
    path: Path,
    base_flags: int,
    initial_stat: os.stat_result | None,
) -> int | None:
    flags = base_flags
    if initial_stat is None:
        flags |= os.O_CREAT | os.O_EXCL
    try:
        return os.open(path, flags, _LOCK_FILE_MODE)
    except (FileExistsError, FileNotFoundError):
        return None
    except OSError as exc:
        if exc.errno == ELOOP:
            raise ValueError(f"Refusing to use a symbolic link as a lock file: {path}") from exc
        raise


def _validate_opened_lock(
    path: Path,
    descriptor: int,
    initial_stat: os.stat_result | None,
) -> None:
    descriptor_stat = os.fstat(descriptor)
    current_stat = path.lstat()
    _validate_lock_stat(path, descriptor_stat)
    _validate_lock_stat(path, current_stat)
    identities = {
        (descriptor_stat.st_dev, descriptor_stat.st_ino),
        (current_stat.st_dev, current_stat.st_ino),
    }
    if initial_stat is not None:
        identities.add((initial_stat.st_dev, initial_stat.st_ino))
    if len(identities) != 1:
        raise ValueError(f"Lock file changed while it was being opened: {path}")


def _open_lock_descriptor(path: Path) -> int:
    """Open or atomically create a regular lock file without following links."""

    path.parent.mkdir(parents=True, exist_ok=True)
    base_flags = (
        os.O_RDWR
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    for _ in range(_LOCK_OPEN_RETRIES):
        initial_stat = _initial_lock_stat(path)
        descriptor = _try_open_lock_descriptor(path, base_flags, initial_stat)
        if descriptor is None:
            continue
        try:
            _validate_opened_lock(path, descriptor, initial_stat)
            if os.name == "posix":
                os.fchmod(descriptor, _LOCK_FILE_MODE)
            return descriptor
        except BaseException:
            os.close(descriptor)
            raise
    raise OSError(f"Lock path changed repeatedly while it was being opened: {path}")


def open_lock_file(path: Path) -> BinaryIO:
    """Return a validated read-write binary stream for a lock file."""

    descriptor = _open_lock_descriptor(path)
    try:
        return os.fdopen(descriptor, "r+b")
    except BaseException:
        os.close(descriptor)
        raise


@contextlib.contextmanager
def exclusive_file_lock(
    lock_file: BinaryIO,
    *,
    timeout_seconds: float,
    timeout_message: str,
) -> Generator[None]:
    """Hold an exclusive OS lock on byte zero of ``lock_file`` until exit."""

    lock_file.seek(0, os.SEEK_END)
    if lock_file.tell() == 0:
        lock_file.write(b"\0")
        lock_file.flush()
    lock_file.seek(0)
    if os.name == "nt":
        with _windows_file_lock(lock_file, timeout_seconds, timeout_message):
            yield
    else:
        with _posix_file_lock(lock_file, timeout_seconds, timeout_message):
            yield


@contextlib.contextmanager
def exclusive_path_lock(
    path: Path,
    *,
    timeout_seconds: float,
    timeout_message: str,
) -> Generator[None]:
    """Open, validate, and exclusively hold one advisory lock path."""

    with (
        open_lock_file(path) as lock_file,
        exclusive_file_lock(
            lock_file,
            timeout_seconds=timeout_seconds,
            timeout_message=timeout_message,
        ),
    ):
        yield


@contextlib.contextmanager
def _windows_file_lock(
    lock_file: BinaryIO,
    timeout_seconds: float,
    timeout_message: str,
) -> Generator[None]:
    import msvcrt

    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
            break
        except OSError:
            if time.monotonic() >= deadline:
                raise TimeoutError(timeout_message) from None
            time.sleep(0.05)
    try:
        yield
    finally:
        lock_file.seek(0)
        msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)


@contextlib.contextmanager
def _posix_file_lock(
    lock_file: BinaryIO,
    timeout_seconds: float,
    timeout_message: str,
) -> Generator[None]:
    import fcntl

    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except BlockingIOError:
            if time.monotonic() >= deadline:
                raise TimeoutError(timeout_message) from None
            time.sleep(0.05)
    try:
        yield
    finally:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

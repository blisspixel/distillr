"""Tests for portable advisory file locking."""

from __future__ import annotations

import errno
import os
import sys
from types import SimpleNamespace

import pytest

from distill.library import locking


def test_open_lock_file_rejects_directory(tmp_path):
    lock_path = tmp_path / "directory.lock"
    lock_path.mkdir()

    with pytest.raises(ValueError, match="non-file lock path"):
        locking.open_lock_file(lock_path)


@pytest.mark.parametrize("race_error", [FileExistsError(), FileNotFoundError()])
def test_try_open_lock_descriptor_reports_transient_race(tmp_path, monkeypatch, race_error):
    lock_path = tmp_path / "racing.lock"

    def raise_race(*args, **kwargs):
        raise race_error

    monkeypatch.setattr(locking.os, "open", raise_race)

    assert locking._try_open_lock_descriptor(lock_path, os.O_RDWR, None) is None


def test_try_open_lock_descriptor_rejects_symlink_loop(tmp_path, monkeypatch):
    lock_path = tmp_path / "loop.lock"

    def raise_loop(*args, **kwargs):
        raise OSError(errno.ELOOP, "symbolic-link loop")

    monkeypatch.setattr(locking.os, "open", raise_loop)

    with pytest.raises(ValueError, match="symbolic link"):
        locking._try_open_lock_descriptor(lock_path, os.O_RDWR, None)


def test_try_open_lock_descriptor_preserves_unrelated_os_error(tmp_path, monkeypatch):
    lock_path = tmp_path / "denied.lock"
    denied = PermissionError(errno.EACCES, "denied")

    def raise_denied(*args, **kwargs):
        raise denied

    monkeypatch.setattr(locking.os, "open", raise_denied)

    with pytest.raises(PermissionError) as raised:
        locking._try_open_lock_descriptor(lock_path, os.O_RDWR, None)

    assert raised.value is denied


def test_open_lock_file_retries_transient_create_race(tmp_path, monkeypatch):
    lock_path = tmp_path / "retry.lock"
    original = locking._try_open_lock_descriptor
    attempts = 0

    def race_once(path, base_flags, initial_stat):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return None
        return original(path, base_flags, initial_stat)

    monkeypatch.setattr(locking, "_try_open_lock_descriptor", race_once)

    with locking.open_lock_file(lock_path):
        assert lock_path.is_file()

    assert attempts == 2


def test_open_lock_file_bounds_repeated_create_races(tmp_path, monkeypatch):
    lock_path = tmp_path / "unstable.lock"
    attempts = 0

    def always_race(path, base_flags, initial_stat):
        nonlocal attempts
        attempts += 1

    monkeypatch.setattr(locking, "_LOCK_OPEN_RETRIES", 2)
    monkeypatch.setattr(locking, "_try_open_lock_descriptor", always_race)

    with pytest.raises(OSError, match="changed repeatedly"):
        locking.open_lock_file(lock_path)

    assert attempts == 2


def test_open_lock_file_closes_descriptor_when_identity_changes(tmp_path, monkeypatch):
    lock_path = tmp_path / "expected.lock"
    replacement_path = tmp_path / "replacement.lock"
    lock_path.touch()
    replacement_path.touch()
    replacement_descriptor = os.open(replacement_path, os.O_RDWR)
    monkeypatch.setattr(
        locking,
        "_try_open_lock_descriptor",
        lambda path, base_flags, initial_stat: replacement_descriptor,
    )

    with pytest.raises(ValueError, match="changed while it was being opened"):
        locking.open_lock_file(lock_path)

    with pytest.raises(OSError):
        os.fstat(replacement_descriptor)


def test_open_lock_file_closes_descriptor_when_stream_creation_fails(tmp_path, monkeypatch):
    lock_path = tmp_path / "stream-error.lock"
    descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_EXCL)
    stream_error = OSError("stream creation failed")
    monkeypatch.setattr(locking, "_open_lock_descriptor", lambda path: descriptor)

    def raise_stream_error(*args, **kwargs):
        raise stream_error

    monkeypatch.setattr(locking.os, "fdopen", raise_stream_error)

    with pytest.raises(OSError) as raised:
        locking.open_lock_file(lock_path)

    assert raised.value is stream_error
    with pytest.raises(OSError):
        os.fstat(descriptor)


def test_open_lock_file_enforces_private_mode_on_posix(tmp_path, monkeypatch):
    lock_path = tmp_path / "private.lock"
    chmod_calls = []
    monkeypatch.setattr(locking.os, "name", "posix")
    monkeypatch.setattr(
        locking.os,
        "fchmod",
        lambda descriptor, mode: chmod_calls.append((descriptor, mode)),
        raising=False,
    )

    with locking.open_lock_file(lock_path):
        assert len(chmod_calls) == 1

    assert chmod_calls[0][1] == 0o600


def test_windows_lock_initializes_byte_and_unlocks(tmp_path, monkeypatch):
    lock_path = tmp_path / "windows.lock"
    lock_file = lock_path.open("w+b")
    calls = []

    def record_lock(descriptor, mode, count):
        calls.append((descriptor, mode, count, os.fstat(descriptor).st_size))

    fake_msvcrt = SimpleNamespace(
        LK_NBLCK=1,
        LK_UNLCK=2,
        locking=record_lock,
    )
    monkeypatch.setattr(locking.os, "name", "nt")
    monkeypatch.setitem(sys.modules, "msvcrt", fake_msvcrt)
    try:
        with locking.exclusive_file_lock(
            lock_file,
            timeout_seconds=1,
            timeout_message="timeout",
        ):
            assert lock_file.tell() == 0
    finally:
        lock_file.close()

    assert [(mode, size) for _, mode, _, size in calls] == [(1, 0), (2, 1)]
    assert lock_path.read_bytes() == b"\0"


def test_open_lock_file_supports_preexisting_empty_file(tmp_path):
    lock_path = tmp_path / "empty.lock"
    lock_path.touch()

    with (
        locking.open_lock_file(lock_path) as lock_file,
        locking.exclusive_file_lock(
            lock_file,
            timeout_seconds=1,
            timeout_message="timeout",
        ),
    ):
        lock_file.seek(0)
        assert lock_file.read(1) == b"\0"


def test_open_lock_file_rejects_symlink_without_touching_target(tmp_path):
    target = tmp_path / "target.txt"
    target.write_bytes(b"")
    lock_path = tmp_path / "unsafe.lock"
    try:
        lock_path.symlink_to(target)
    except OSError as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")

    with pytest.raises(ValueError, match="symbolic link"):
        locking.open_lock_file(lock_path)

    assert target.read_bytes() == b""


def test_open_lock_file_rejects_hardlink_without_touching_target(tmp_path):
    target = tmp_path / "target.txt"
    target.write_bytes(b"")
    lock_path = tmp_path / "unsafe.lock"
    try:
        lock_path.hardlink_to(target)
    except OSError as exc:
        pytest.skip(f"hard-link creation unavailable: {exc}")

    with pytest.raises(ValueError, match="multiply linked"):
        locking.open_lock_file(lock_path)

    assert target.read_bytes() == b""


def test_windows_lock_timeout_is_bounded(tmp_path, monkeypatch):
    lock_file = (tmp_path / "windows-timeout.lock").open("w+b")

    def refuse_lock(descriptor, mode, count):
        raise OSError("busy")

    fake_msvcrt = SimpleNamespace(LK_NBLCK=1, LK_UNLCK=2, locking=refuse_lock)
    clock = iter([0.0, 2.0])
    monkeypatch.setattr(locking.os, "name", "nt")
    monkeypatch.setattr(locking.time, "monotonic", lambda: next(clock))
    monkeypatch.setitem(sys.modules, "msvcrt", fake_msvcrt)
    try:
        with (
            pytest.raises(TimeoutError, match="windows timeout"),
            locking.exclusive_file_lock(
                lock_file,
                timeout_seconds=1,
                timeout_message="windows timeout",
            ),
        ):
            pytest.fail("timed-out lock must not enter its protected section")
    finally:
        lock_file.close()


def test_posix_lock_unlocks(tmp_path, monkeypatch):
    lock_file = (tmp_path / "posix.lock").open("w+b")
    calls = []
    fake_fcntl = SimpleNamespace(
        LOCK_EX=1,
        LOCK_NB=2,
        LOCK_UN=4,
        flock=lambda descriptor, operation: calls.append((descriptor, operation)),
    )
    monkeypatch.setattr(locking.os, "name", "posix")
    monkeypatch.setitem(sys.modules, "fcntl", fake_fcntl)
    try:
        with locking.exclusive_file_lock(
            lock_file,
            timeout_seconds=1,
            timeout_message="timeout",
        ):
            lock_file.seek(0)
            assert lock_file.read(1) == b"\0"
    finally:
        lock_file.close()

    assert [operation for _, operation in calls] == [3, 4]


def test_posix_lock_timeout_is_bounded(tmp_path, monkeypatch):
    lock_file = (tmp_path / "posix-timeout.lock").open("w+b")

    def refuse_lock(descriptor, operation):
        raise BlockingIOError("busy")

    fake_fcntl = SimpleNamespace(LOCK_EX=1, LOCK_NB=2, LOCK_UN=4, flock=refuse_lock)
    clock = iter([0.0, 2.0])
    monkeypatch.setattr(locking.os, "name", "posix")
    monkeypatch.setattr(locking.time, "monotonic", lambda: next(clock))
    monkeypatch.setitem(sys.modules, "fcntl", fake_fcntl)
    try:
        with (
            pytest.raises(TimeoutError, match="posix timeout"),
            locking.exclusive_file_lock(
                lock_file,
                timeout_seconds=1,
                timeout_message="posix timeout",
            ),
        ):
            pytest.fail("timed-out lock must not enter its protected section")
    finally:
        lock_file.close()


def test_posix_lock_retries_before_success(tmp_path, monkeypatch):
    lock_file = (tmp_path / "posix-retry.lock").open("w+b")
    operations = []
    sleeps = []

    def lock_after_retry(descriptor, operation):
        operations.append(operation)
        if len(operations) == 1:
            raise BlockingIOError("busy")

    fake_fcntl = SimpleNamespace(
        LOCK_EX=1,
        LOCK_NB=2,
        LOCK_UN=4,
        flock=lock_after_retry,
    )
    clock = iter([0.0, 0.5])
    monkeypatch.setattr(locking.os, "name", "posix")
    monkeypatch.setattr(locking.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(locking.time, "sleep", sleeps.append)
    monkeypatch.setitem(sys.modules, "fcntl", fake_fcntl)
    try:
        with locking.exclusive_file_lock(
            lock_file,
            timeout_seconds=1,
            timeout_message="timeout",
        ):
            assert sleeps == [0.05]
    finally:
        lock_file.close()

    assert operations == [3, 3, 4]

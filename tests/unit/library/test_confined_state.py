"""Concurrency and platform contracts for confined state mutation."""

from __future__ import annotations

import os
import threading
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from pathlib import Path

import pytest

from distill.library import confined_state
from distill.library.confined_state import (
    ConfinedStateError,
    atomic_write_confined_bytes,
    atomic_write_confined_text,
    confined_file_identity,
    confined_state_lock_path,
    read_confined_state_text,
    unlink_confined_file,
)
from distill.library.paths import atomic_write_text


@pytest.mark.skipif(os.name != "nt", reason="NTFS paths are case-insensitive")
def test_confined_lock_path_normalizes_windows_case_aliases(tmp_path: Path) -> None:
    parent = tmp_path / "Concepts"
    parent.mkdir()
    target = parent / "Note.md"
    target.write_text("content", encoding="utf-8")

    canonical = confined_state_lock_path(target, tmp_path, "note")
    alias = confined_state_lock_path(tmp_path / "concepts" / "note.md", tmp_path, "note")

    assert canonical == alias


@pytest.mark.parametrize("purpose", ["", "two words", "unsafe_path"])
def test_confined_lock_path_rejects_invalid_purpose(tmp_path: Path, purpose: str) -> None:
    with pytest.raises(ValueError, match="lock purpose"):
        confined_state_lock_path(tmp_path / "state.json", tmp_path, purpose)


def test_confined_state_rejects_invalid_roots_and_root_target(tmp_path: Path) -> None:
    missing_root = tmp_path / "missing"
    file_root = tmp_path / "file-root"
    file_root.write_text("not a directory", encoding="utf-8")

    with pytest.raises(ConfinedStateError, match="safe child"):
        confined_state_lock_path(tmp_path, tmp_path, "state")
    with pytest.raises(ConfinedStateError, match="root is unavailable"):
        confined_state_lock_path(missing_root / "state.json", missing_root, "state")
    with pytest.raises(ConfinedStateError, match="private directory"):
        confined_state_lock_path(file_root / "state.json", file_root, "state")


def test_confined_parent_reports_unavailable_component(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    blocked = tmp_path / "blocked"
    blocked.mkdir()
    target = blocked / "state.json"
    original_lstat = Path.lstat

    def failing_lstat(path: Path):
        if path == blocked:
            raise OSError("unavailable")
        return original_lstat(path)

    monkeypatch.setattr(Path, "lstat", failing_lstat)

    with pytest.raises(ConfinedStateError, match="directory is unavailable"):
        confined_state.ensure_confined_parent(target, tmp_path, create=False)


def test_confined_parent_revision_and_text_decoding_fail_closed(tmp_path: Path) -> None:
    target = tmp_path / "state.json"

    with pytest.raises(ConfinedStateError, match="changed during mutation"):
        confined_state._require_parent_revision(target, tmp_path, (-1, -1))
    assert read_confined_state_text(target, tmp_path, max_bytes=16) is None

    target.write_bytes(b"\xff")
    with pytest.raises(ConfinedStateError, match="not valid UTF-8"):
        read_confined_state_text(target, tmp_path, max_bytes=16)


def test_confined_write_all_rejects_non_progress(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(confined_state.os, "write", lambda _descriptor, _content: 0)

    with pytest.raises(OSError, match="complete confined state"):
        confined_state._write_all(1, b"content")


def test_confined_replace_retry_policy_matches_platform() -> None:
    assert confined_state._is_retryable_replace_error(PermissionError()) is (os.name == "nt")


def test_confined_replace_validation_detects_target_and_temp_changes(tmp_path: Path) -> None:
    target = tmp_path / "state.json"
    temp = tmp_path / "state.tmp"
    target.write_text("initial", encoding="utf-8")
    temp.write_text("temporary", encoding="utf-8")
    parent = confined_state.ensure_confined_parent(target, tmp_path, create=False)
    initial = confined_file_identity(target, tmp_path)
    temp_revision = confined_state._file_identity(temp.lstat())
    assert parent is not None and initial is not None

    target.write_text("changed during validation", encoding="utf-8")
    with pytest.raises(ConfinedStateError, match="target changed during mutation"):
        confined_state._validate_replace_attempt(
            target,
            temp,
            tmp_path,
            parent_revision=parent[1],
            initial_identity=initial,
            temp_revision=temp_revision,
            exclusive=False,
            expected=None,
        )

    current = confined_file_identity(target, tmp_path)
    assert current is not None
    temp.unlink()
    with pytest.raises(ConfinedStateError, match="Temporary state file changed"):
        confined_state._validate_replace_attempt(
            target,
            temp,
            tmp_path,
            parent_revision=parent[1],
            initial_identity=current,
            temp_revision=temp_revision,
            exclusive=False,
            expected=None,
        )

    temp.write_text("replacement", encoding="utf-8")
    mismatched_revision = list(confined_state._file_identity(temp.lstat()))
    mismatched_revision[3] += 1
    with pytest.raises(ConfinedStateError, match="Temporary state file changed"):
        confined_state._validate_replace_attempt(
            target,
            temp,
            tmp_path,
            parent_revision=parent[1],
            initial_identity=current,
            temp_revision=tuple(mismatched_revision),
            exclusive=False,
            expected=None,
        )


def test_confined_atomic_write_rejects_incompatible_guards(tmp_path: Path) -> None:
    target = tmp_path / "state.json"

    with pytest.raises(ValueError, match="cannot be combined"):
        atomic_write_confined_bytes(
            target,
            b"content",
            tmp_path,
            exclusive=True,
            expected=(0, 0, 0, 0, 0, 0),
        )


def test_confined_atomic_write_rejects_unsafe_temporary_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "state.json"
    monkeypatch.setattr(confined_state, "validate_confined_path", lambda *args, **kwargs: None)

    with pytest.raises(ConfinedStateError, match="Temporary state path escaped"):
        atomic_write_confined_bytes(target, b"content", tmp_path)

    assert not target.exists()
    assert list(tmp_path.glob(".state.json.*.tmp")) == []


def test_confined_atomic_write_detects_temporary_identity_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "state.json"

    def changed_identity(file_stat: os.stat_result):
        identity = list(confined_state._node_identity(file_stat))
        return (identity[0] + 1, identity[1], 1, 0, 0, 0)

    monkeypatch.setattr(confined_state, "_file_identity", changed_identity)

    with pytest.raises(ConfinedStateError, match="Temporary state file changed"):
        atomic_write_confined_bytes(target, b"content", tmp_path)

    assert not target.exists()


def test_confined_atomic_write_detects_missing_final_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "state.json"
    monkeypatch.setattr(
        confined_state, "_replace_confined_with_retry", lambda *args, **kwargs: None
    )

    with pytest.raises(ConfinedStateError, match="target escaped confinement"):
        atomic_write_confined_bytes(target, b"content", tmp_path)

    assert not target.exists()
    assert list(tmp_path.glob(".state.json.*.tmp")) == []


def test_confined_unlink_reports_missing_parent_before_and_during_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    missing = tmp_path / "missing" / "state.json"
    with pytest.raises(FileNotFoundError):
        unlink_confined_file(missing, tmp_path, expected=(0, 0, 0, 0, 0, 0))

    target = tmp_path / "state.json"
    target.write_text("content", encoding="utf-8")
    expected = confined_file_identity(target, tmp_path)
    parent = confined_state.ensure_confined_parent(target, tmp_path, create=False)
    assert expected is not None and parent is not None
    calls = 0

    def disappearing_parent(path: Path, root: Path, *, create: bool):
        nonlocal calls
        calls += 1
        return parent if calls == 1 else None

    monkeypatch.setattr(confined_state, "ensure_confined_parent", disappearing_parent)

    with pytest.raises(FileNotFoundError):
        unlink_confined_file(target, tmp_path, expected=expected)

    assert target.exists()


def test_confined_write_retries_transient_replace_conflict(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "state.json"
    target.write_text("old", encoding="utf-8")
    original_replace = Path.replace
    attempts = 0

    def transient_replace(source: Path, destination: Path) -> Path:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise PermissionError("reader still owns a sharing handle")
        return original_replace(source, destination)

    monkeypatch.setattr(Path, "replace", transient_replace)
    monkeypatch.setattr(confined_state, "_is_retryable_replace_error", lambda _error: True)
    monkeypatch.setattr(confined_state.time, "sleep", lambda _seconds: None)

    atomic_write_confined_text(target, "new", tmp_path)

    assert attempts == 3
    assert target.read_text(encoding="utf-8") == "new"
    assert list(tmp_path.glob(".state.json.*.tmp")) == []


def test_confined_write_bounds_replace_retry_and_cleans_temp(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "state.json"
    target.write_text("old", encoding="utf-8")

    def blocked_replace(_source: Path, _destination: Path) -> Path:
        raise PermissionError("reader never released its sharing handle")

    monkeypatch.setattr(Path, "replace", blocked_replace)
    monkeypatch.setattr(confined_state, "_is_retryable_replace_error", lambda _error: True)
    monkeypatch.setattr(confined_state, "_ATOMIC_REPLACE_TIMEOUT_SECONDS", 0.0)

    with pytest.raises(PermissionError, match="reader never released"):
        atomic_write_confined_text(target, "new", tmp_path)

    assert target.read_text(encoding="utf-8") == "old"
    assert list(tmp_path.glob(".state.json.*.tmp")) == []


def test_expected_revision_rejects_in_place_edit(tmp_path: Path) -> None:
    target = tmp_path / "state.json"
    target.write_text("old", encoding="utf-8")
    expected = confined_file_identity(target, tmp_path)
    assert expected is not None

    target.write_text("concurrent in-place update", encoding="utf-8")

    with pytest.raises(ConfinedStateError, match="changed before mutation"):
        atomic_write_confined_text(target, "stale replacement", tmp_path, expected=expected)
    assert target.read_text(encoding="utf-8") == "concurrent in-place update"


def test_expected_revision_rejects_unlink_after_in_place_edit(tmp_path: Path) -> None:
    target = tmp_path / "state.json"
    target.write_text("old", encoding="utf-8")
    expected = confined_file_identity(target, tmp_path)
    assert expected is not None

    target.write_text("concurrent in-place update", encoding="utf-8")

    with pytest.raises(ConfinedStateError, match="changed before deletion"):
        unlink_confined_file(target, tmp_path, expected=expected)
    assert target.read_text(encoding="utf-8") == "concurrent in-place update"


def test_confined_replace_does_not_overwrite_concurrent_atomic_writer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "state.json"
    target.write_text("old", encoding="utf-8")
    replace_reached = threading.Event()
    release_replace = threading.Event()
    original_replace = Path.replace
    intercepted = False
    intercept_lock = threading.Lock()

    def blocking_replace(source: Path, destination: Path) -> Path:
        nonlocal intercepted
        should_intercept = False
        if destination.absolute() == target.absolute() and source.name.startswith(
            f".{target.name}."
        ):
            with intercept_lock:
                should_intercept = not intercepted
                intercepted = True
        if should_intercept:
            replace_reached.set()
            assert release_replace.wait(timeout=5)
        return original_replace(source, destination)

    monkeypatch.setattr(Path, "replace", blocking_replace)
    with ThreadPoolExecutor(max_workers=2) as executor:
        confined = executor.submit(atomic_write_confined_text, target, "confined", tmp_path)
        assert replace_reached.wait(timeout=5)
        ordinary = executor.submit(atomic_write_text, target, "concurrent")
        with pytest.raises(FutureTimeoutError):
            ordinary.result(timeout=0.25)
        release_replace.set()
        confined.result(timeout=5)
        ordinary.result(timeout=5)

    assert target.read_text(encoding="utf-8") == "concurrent"


def test_confined_unlink_does_not_delete_concurrent_atomic_writer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "state.json"
    target.write_text("old", encoding="utf-8")
    expected = confined_file_identity(target, tmp_path)
    assert expected is not None
    unlink_reached = threading.Event()
    release_unlink = threading.Event()
    original_unlink = Path.unlink

    def blocking_unlink(path: Path, *args: object, **kwargs: object) -> None:
        if path.absolute() == target.absolute():
            unlink_reached.set()
            assert release_unlink.wait(timeout=5)
        original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", blocking_unlink)
    with ThreadPoolExecutor(max_workers=2) as executor:
        confined = executor.submit(unlink_confined_file, target, tmp_path, expected=expected)
        assert unlink_reached.wait(timeout=5)
        ordinary = executor.submit(atomic_write_text, target, "concurrent")
        with pytest.raises(FutureTimeoutError):
            ordinary.result(timeout=0.25)
        release_unlink.set()
        confined.result(timeout=5)
        ordinary.result(timeout=5)

    assert target.read_text(encoding="utf-8") == "concurrent"

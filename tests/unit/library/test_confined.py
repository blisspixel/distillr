"""Direct boundary tests for race-aware confined filesystem reads."""

from __future__ import annotations

import os
import stat
from pathlib import Path
from types import SimpleNamespace
from typing import Never, cast

import pytest

from distill.library import confined


def _stat_with_inode(file_stat: os.stat_result, inode: int) -> os.stat_result:
    values = list(file_stat)
    values[1] = inode
    return os.stat_result(values)


def test_candidate_rejects_missing_root_outside_path_and_root_itself(tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    assert confined._candidate_under_root(missing / "note.md", missing) is None

    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("outside", encoding="utf-8")
    assert confined._candidate_under_root(outside, root) is None
    assert confined.validate_confined_path(outside, root, expect_directory=False) is None
    assert confined._candidate_under_root(root, root) is None


def test_link_like_detects_reparse_metadata_and_junctions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reparse_flag = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)) or 0x400
    reparse_stat = cast(
        os.stat_result,
        SimpleNamespace(st_mode=stat.S_IFREG, st_file_attributes=reparse_flag),
    )
    monkeypatch.setattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", reparse_flag, raising=False)
    assert confined._is_link_like(tmp_path / "file", reparse_stat)

    ordinary_stat = cast(
        os.stat_result,
        SimpleNamespace(st_mode=stat.S_IFREG, st_file_attributes=0),
    )
    monkeypatch.setattr(Path, "is_junction", lambda _path: True, raising=False)
    assert confined._is_link_like(tmp_path / "junction", ordinary_stat)


def test_validate_rejects_non_directory_root_intermediate_file_and_wrong_final_type(
    tmp_path: Path,
) -> None:
    root_file = tmp_path / "root-file"
    root_file.write_text("not a directory", encoding="utf-8")
    assert (
        confined.validate_confined_path(
            root_file / "child",
            root_file,
            expect_directory=False,
        )
        is None
    )

    root = tmp_path / "root"
    root.mkdir()
    intermediate = root / "intermediate"
    intermediate.write_text("file", encoding="utf-8")
    assert (
        confined.validate_confined_path(
            intermediate / "child.md",
            root,
            expect_directory=False,
        )
        is None
    )
    assert confined.validate_confined_path(intermediate, root, expect_directory=True) is None
    assert (
        confined.validate_confined_path(root / "missing.md", root, expect_directory=False) is None
    )


def test_read_rejects_open_errors_invalid_utf8_and_final_identity_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    note = root / "note.md"
    note.write_text("safe", encoding="utf-8")

    real_open = confined.os.open

    def fail_open(_path: Path, _flags: int) -> int:
        raise OSError("denied")

    monkeypatch.setattr(confined.os, "open", fail_open)
    assert confined.read_confined_text(note, root, max_bytes=100) is None
    monkeypatch.setattr(confined.os, "open", real_open)

    note.write_bytes(b"\xff")
    assert confined.read_confined_text(note, root, max_bytes=100) is None

    note.write_text("safe", encoding="utf-8")
    real_validate = confined.validate_confined_path
    calls = 0

    def changed_on_final(
        path: Path,
        trusted_root: Path,
        *,
        expect_directory: bool,
    ) -> tuple[Path, os.stat_result] | None:
        nonlocal calls
        calls += 1
        result = real_validate(path, trusted_root, expect_directory=expect_directory)
        if calls == 3 and result is not None:
            return result[0], _stat_with_inode(result[1], result[1].st_ino + 1)
        return result

    monkeypatch.setattr(confined, "validate_confined_path", changed_on_final)
    assert confined.read_confined_text(note, root, max_bytes=100) is None


def test_read_bytes_rejects_negative_limit(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    note = root / "note.md"
    note.write_text("safe", encoding="utf-8")

    assert confined.read_confined_bytes(note, root, max_bytes=-1) is None


def test_read_closes_descriptor_when_descriptor_setup_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    note = root / "note.md"
    note.write_text("safe", encoding="utf-8")
    closed: list[int] = []

    monkeypatch.setattr(confined.os, "fstat", lambda _descriptor: (_ for _ in ()).throw(OSError()))
    monkeypatch.setattr(confined.os, "close", closed.append)

    assert confined.read_confined_text(note, root, max_bytes=100) is None
    assert len(closed) == 1


def test_scan_bounds_entries_files_suffixes_and_file_size(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "a.txt").write_text("skip", encoding="utf-8")
    (root / "b.md").write_text("b", encoding="utf-8")
    (root / "c.md").write_text("cc", encoding="utf-8")

    assert (
        confined._scan_confined_files(
            root,
            root,
            suffix=".json",
            max_entries=10,
            max_files=10,
            max_file_bytes=10,
        )
        == []
    )
    assert (
        confined._scan_confined_files(
            root,
            root,
            suffix=".md",
            max_entries=1,
            max_files=10,
            max_file_bytes=10,
        )
        is None
    )
    assert (
        confined._scan_confined_files(
            root,
            root,
            suffix=".md",
            max_entries=10,
            max_files=0,
            max_file_bytes=10,
        )
        is None
    )
    assert (
        confined._scan_confined_files(
            root,
            root,
            suffix=".md",
            max_entries=10,
            max_files=10,
            max_file_bytes=1,
        )
        is None
    )


def test_list_handles_missing_and_unreadable_directories(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    missing = root / "missing"
    options = {
        "suffix": ".md",
        "max_entries": 10,
        "max_files": 10,
        "max_file_bytes": 100,
    }
    assert confined.list_confined_files(missing, root, **options) == []

    unreadable = root / "unreadable"
    unreadable.mkdir()
    real_lstat = Path.lstat

    def fail_target_lstat(path: Path) -> os.stat_result:
        if path == unreadable:
            raise OSError("denied")
        return real_lstat(path)

    monkeypatch.setattr(Path, "lstat", fail_target_lstat)
    assert confined.list_confined_files(unreadable, root, **options) is None


def test_list_rejects_scan_errors_limits_and_directory_identity_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    directory = root / "notes"
    directory.mkdir()
    options = {
        "suffix": ".md",
        "max_entries": 10,
        "max_files": 10,
        "max_file_bytes": 100,
    }

    def fail_scandir(_directory: Path) -> Never:
        raise OSError("denied")

    monkeypatch.setattr(confined.os, "scandir", fail_scandir)
    assert confined.list_confined_files(directory, root, **options) is None
    monkeypatch.undo()

    (directory / "a.md").write_text("a", encoding="utf-8")
    assert (
        confined.list_confined_files(
            directory,
            root,
            suffix=".md",
            max_entries=10,
            max_files=0,
            max_file_bytes=100,
        )
        is None
    )

    (directory / "a.md").unlink()
    real_validate = confined.validate_confined_path
    calls = 0

    def changed_directory(
        path: Path,
        trusted_root: Path,
        *,
        expect_directory: bool,
    ) -> tuple[Path, os.stat_result] | None:
        nonlocal calls
        result = real_validate(path, trusted_root, expect_directory=expect_directory)
        calls += 1
        if calls == 2 and result is not None:
            return result[0], _stat_with_inode(result[1], result[1].st_ino + 1)
        return result

    monkeypatch.setattr(confined, "validate_confined_path", changed_directory)
    assert confined.list_confined_files(directory, root, **options) is None


def test_list_confined_directories_sorts_and_enforces_both_limits(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    parent = root / "topics"
    parent.mkdir()
    (parent / "zeta").mkdir()
    (parent / "alpha").mkdir()
    (parent / "ordinary.txt").write_text("ignored", encoding="utf-8")

    assert confined.list_confined_directories(
        parent,
        root,
        max_entries=10,
        max_directories=10,
    ) == [parent / "alpha", parent / "zeta"]
    assert (
        confined.list_confined_directories(
            parent,
            root,
            max_entries=1,
            max_directories=10,
        )
        is None
    )
    assert (
        confined.list_confined_directories(
            parent,
            root,
            max_entries=10,
            max_directories=1,
        )
        is None
    )


def test_list_confined_directories_rejects_unreadable_and_wrong_type(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    directory = root / "topics"
    directory.mkdir()
    ordinary_file = root / "topics.txt"
    ordinary_file.write_text("not a directory", encoding="utf-8")
    real_lstat = Path.lstat

    def fail_target_lstat(path: Path) -> os.stat_result:
        if path == directory:
            raise OSError("denied")
        return real_lstat(path)

    monkeypatch.setattr(Path, "lstat", fail_target_lstat)
    assert (
        confined.list_confined_directories(
            directory,
            root,
            max_entries=10,
            max_directories=10,
        )
        is None
    )
    monkeypatch.undo()
    assert (
        confined.list_confined_directories(
            ordinary_file,
            root,
            max_entries=10,
            max_directories=10,
        )
        is None
    )


def test_list_confined_directories_rejects_scan_and_identity_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    directory = root / "topics"
    directory.mkdir()
    options = {"max_entries": 10, "max_directories": 10}

    def fail_scandir(_directory: Path) -> Never:
        raise OSError("denied")

    monkeypatch.setattr(confined.os, "scandir", fail_scandir)
    assert confined.list_confined_directories(directory, root, **options) is None
    monkeypatch.undo()

    monkeypatch.setattr(confined, "_scan_confined_directories", lambda *_args, **_kwargs: None)
    assert confined.list_confined_directories(directory, root, **options) is None
    monkeypatch.undo()

    real_validate = confined.validate_confined_path
    calls = 0

    def changed_directory(
        path: Path,
        trusted_root: Path,
        *,
        expect_directory: bool,
    ) -> tuple[Path, os.stat_result] | None:
        nonlocal calls
        result = real_validate(path, trusted_root, expect_directory=expect_directory)
        calls += 1
        if calls == 2 and result is not None:
            return result[0], _stat_with_inode(result[1], result[1].st_ino + 1)
        return result

    monkeypatch.setattr(confined, "validate_confined_path", changed_directory)
    assert confined.list_confined_directories(directory, root, **options) is None

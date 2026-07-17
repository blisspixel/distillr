"""Tests for bound filesystem operations used by host workers."""

from __future__ import annotations

from pathlib import Path

import pytest

from distill.llm.providers import _agent_directories as directories
from distill.llm.providers import _agent_files as files


def _root(tmp_path: Path) -> tuple[Path, tuple[int, int]]:
    root = tmp_path / "tasks"
    root.mkdir()
    validated = files.validated_task_root(root)
    assert validated is not None
    return validated


def test_create_and_remove_bound_task_directory(tmp_path: Path) -> None:
    root, identity = _root(tmp_path)
    child, child_identity = directories.create_task_directory(root, identity, "workspace")
    assert child == root / "workspace"
    assert child.is_dir()

    with pytest.raises(FileExistsError):
        directories.create_task_directory(root, identity, "workspace")
    assert not directories.remove_task_directory(
        child,
        root,
        identity,
        (child_identity[0], child_identity[1] + 1),
    )
    (child / "result.md").write_text("busy", encoding="utf-8")
    assert not directories.remove_task_directory(child, root, identity, child_identity)
    (child / "result.md").unlink()
    assert directories.remove_task_directory(child, root, identity, child_identity)
    assert not child.exists()


@pytest.mark.parametrize("name", ["", ".", "..", "../escape", "nested/path"])
def test_create_task_directory_rejects_unsafe_child_names(tmp_path: Path, name: str) -> None:
    root, identity = _root(tmp_path)
    with pytest.raises(OSError, match="safe direct child"):
        directories.create_task_directory(root, identity, name)


def test_remove_task_file_requires_exact_unchanged_content(tmp_path: Path) -> None:
    root, identity = _root(tmp_path)
    path = root / "claim"
    files.write_task_bytes(path, root, identity, b"claim receipt")
    assert not files.remove_task_file(
        path,
        root,
        identity,
        expected_content=b"wrong",
    )
    assert path.exists()
    assert not files.remove_task_file(
        tmp_path / "outside",
        root,
        identity,
        expected_content=b"claim receipt",
    )
    assert files.remove_task_file(
        path,
        root,
        identity,
        expected_content=b"claim receipt",
    )
    assert not path.exists()


def test_bound_removals_reject_replaced_root(tmp_path: Path) -> None:
    root, identity = _root(tmp_path)
    path = root / "claim"
    files.write_task_bytes(path, root, identity, b"receipt")
    old_root = tmp_path / "old-tasks"
    root.rename(old_root)
    root.mkdir()

    assert not files.remove_task_file(
        root / "claim",
        root,
        identity,
        expected_content=b"receipt",
    )
    old_validated = files.validated_task_root(old_root)
    assert old_validated is not None
    child, child_identity = directories.create_task_directory(
        old_validated[0], old_validated[1], "workspace"
    )
    assert not directories.remove_task_directory(
        child,
        root,
        identity,
        child_identity,
    )


def test_workspace_creation_rolls_back_on_post_create_root_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, identity = _root(tmp_path)
    checks = iter([True, False, True])
    monkeypatch.setattr(directories, "_open_bound_directory", lambda *_args: -1)
    monkeypatch.setattr(
        directories,
        "task_root_is_unchanged",
        lambda *_args: next(checks),
    )

    with pytest.raises(OSError, match="changed during directory creation"):
        directories.create_task_directory(root, identity, "workspace")
    assert not (root / "workspace").exists()


def test_workspace_creation_rolls_back_unvalidated_child(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, identity = _root(tmp_path)
    monkeypatch.setattr(directories, "_open_bound_directory", lambda *_args: -1)
    monkeypatch.setattr(directories, "task_root_is_unchanged", lambda *_args: True)
    monkeypatch.setattr(directories, "validated_task_root", lambda *_args: None)

    with pytest.raises(OSError, match="safe direct child"):
        directories.create_task_directory(root, identity, "workspace")
    assert not (root / "workspace").exists()


def test_directory_helpers_cover_bound_descriptor_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, identity = _root(tmp_path)
    calls: list[tuple[str, int]] = []

    def fake_mkdir(name: str, _mode: int, *, dir_fd: int) -> None:
        calls.append((name, dir_fd))

    monkeypatch.setattr(directories.os, "mkdir", fake_mkdir)
    monkeypatch.setattr(directories.os, "supports_dir_fd", {fake_mkdir})
    directories._mkdir_bound_child(root, identity, root / "child", "child", 7)
    assert calls == [("child", 7)]

    def fake_rmdir(name: str, *, dir_fd: int) -> None:
        calls.append((name, dir_fd))

    monkeypatch.setattr(directories.os, "rmdir", fake_rmdir)
    monkeypatch.setattr(directories.os, "supports_dir_fd", {fake_rmdir})
    monkeypatch.setattr(directories, "_open_bound_directory", lambda *_args: 9)
    monkeypatch.setattr(directories, "_close_task_descriptors", lambda *_args: None)
    monkeypatch.setattr(directories, "task_root_is_unchanged", lambda *_args: True)
    monkeypatch.setattr(
        directories,
        "validated_task_root",
        lambda path: (path, (3, 4)),
    )
    assert directories.remove_task_directory(root / "child", root, identity, (3, 4))
    assert calls[-1] == ("child", 9)


def test_directory_helpers_fail_closed_on_fallback_races(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, identity = _root(tmp_path)
    monkeypatch.setattr(directories, "task_root_is_unchanged", lambda *_args: False)
    with pytest.raises(OSError, match="changed before directory creation"):
        directories._mkdir_bound_child(root, identity, root / "child", "child", -1)

    monkeypatch.setattr(directories, "task_root_is_unchanged", lambda *_args: True)
    directories._remove_bound_child_directory(
        root,
        identity,
        root / "missing",
        "missing",
        -1,
    )

    child = root / "child"
    child.mkdir()
    validated_child = files.validated_task_root(child)
    assert validated_child is not None
    checks = iter([True, False])
    monkeypatch.setattr(
        directories,
        "task_root_is_unchanged",
        lambda *_args: next(checks),
    )
    monkeypatch.setattr(directories, "_open_bound_directory", lambda *_args: -1)
    assert not directories.remove_task_directory(
        child,
        root,
        identity,
        validated_child[1],
    )

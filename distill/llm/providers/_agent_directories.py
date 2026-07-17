# pyright: strict, reportPrivateUsage=false
"""Identity-bound directory operations for deferred agent workspaces."""

from __future__ import annotations

import os
from pathlib import Path

from distill.llm.providers._agent_files import (
    _close_task_descriptors,
    _open_bound_directory,
    _safe_child_name,
    _same_path,
    task_root_is_unchanged,
    validated_task_root,
)


def create_task_directory(
    root: Path,
    root_identity: tuple[int, int],
    name: str,
) -> tuple[Path, tuple[int, int]]:
    """Create and bind one direct child directory beneath a task root."""

    if not _safe_child_name(name):
        raise OSError("agent task directory name is not a safe direct child")
    directory_descriptor = _open_bound_directory(root, root_identity)
    child = root / name
    created = False
    try:
        _mkdir_bound_child(root, root_identity, child, name, directory_descriptor)
        created = True
        if not task_root_is_unchanged(root, root_identity):
            raise OSError("agent task root changed during directory creation")
        validated = validated_task_root(child)
        if validated is None or not _same_path(validated[0].parent, root):
            raise OSError("agent task workspace is not a safe direct child")
        return validated
    except Exception:
        if created:
            _remove_bound_child_directory(
                root,
                root_identity,
                child,
                name,
                directory_descriptor,
            )
        raise
    finally:
        _close_task_descriptors(directory_descriptor)


def _mkdir_bound_child(
    root: Path,
    root_identity: tuple[int, int],
    child: Path,
    name: str,
    directory_descriptor: int,
) -> None:
    if directory_descriptor >= 0 and os.mkdir in os.supports_dir_fd:
        os.mkdir(name, 0o700, dir_fd=directory_descriptor)
        return
    if not task_root_is_unchanged(root, root_identity):
        raise OSError("agent task root changed before directory creation")
    child.mkdir(mode=0o700)


def _remove_bound_child_directory(
    root: Path,
    root_identity: tuple[int, int],
    child: Path,
    name: str,
    directory_descriptor: int,
) -> None:
    try:
        if directory_descriptor >= 0 and os.rmdir in os.supports_dir_fd:
            os.rmdir(name, dir_fd=directory_descriptor)
        elif task_root_is_unchanged(root, root_identity):
            child.rmdir()
    except OSError:
        pass


def remove_task_directory(
    path: Path,
    root: Path,
    root_identity: tuple[int, int],
    child_identity: tuple[int, int],
) -> bool:
    """Remove one empty bound child directory when both identities still match."""

    if not _same_path(path.parent, root) or not _safe_child_name(path.name):
        return False
    current = validated_task_root(path)
    if (
        current is None
        or current[1] != child_identity
        or not task_root_is_unchanged(root, root_identity)
    ):
        return False
    directory_descriptor = -1
    try:
        directory_descriptor = _open_bound_directory(root, root_identity)
        if directory_descriptor >= 0 and os.rmdir in os.supports_dir_fd:
            os.rmdir(path.name, dir_fd=directory_descriptor)
        elif task_root_is_unchanged(root, root_identity):
            path.rmdir()
        else:
            return False
        return True
    except OSError:
        return False
    finally:
        _close_task_descriptors(directory_descriptor)

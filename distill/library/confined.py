# pyright: strict
"""Race-aware bounded reads for regular files confined below a trusted root."""

from __future__ import annotations

import os
import stat
from pathlib import Path


def _is_link_like(path: Path, file_stat: os.stat_result) -> bool:
    if stat.S_ISLNK(file_stat.st_mode):
        return True
    reparse_flag = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))
    attributes = int(getattr(file_stat, "st_file_attributes", 0))
    return bool(reparse_flag and attributes & reparse_flag) or (
        hasattr(path, "is_junction") and path.is_junction()
    )


def _candidate_under_root(path: Path, root: Path) -> tuple[Path, Path] | None:
    try:
        root_resolved = root.resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    for base in (root, root_resolved):
        try:
            relative = path.relative_to(base)
        except ValueError:
            continue
        if relative.parts and all(part not in {"", ".", ".."} for part in relative.parts):
            return root_resolved, root_resolved.joinpath(*relative.parts)
    return None


def validate_confined_path(
    path: Path,
    root: Path,
    *,
    expect_directory: bool,
) -> tuple[Path, os.stat_result] | None:
    """Validate every child component without accepting links or special files."""

    confined = _candidate_under_root(path, root)
    if confined is None:
        return None
    root_resolved, candidate = confined
    try:
        root_stat = root_resolved.lstat()
        if _is_link_like(root_resolved, root_stat) or not stat.S_ISDIR(root_stat.st_mode):
            return None
        relative_parts = candidate.relative_to(root_resolved).parts
        current = root_resolved
        final_stat = root_stat
        for index, part in enumerate(relative_parts):
            current /= part
            final_stat = current.lstat()
            if _is_link_like(current, final_stat):
                return None
            if index < len(relative_parts) - 1 and not stat.S_ISDIR(final_stat.st_mode):
                return None
    except (OSError, RuntimeError, ValueError):
        return None
    expected_type = stat.S_ISDIR if expect_directory else stat.S_ISREG
    if not expected_type(final_stat.st_mode):
        return None
    return candidate, final_stat


def _file_revision(file_stat: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        file_stat.st_dev,
        file_stat.st_ino,
        file_stat.st_nlink,
        file_stat.st_size,
        file_stat.st_mtime_ns,
    )


def read_confined_text(path: Path, root: Path, *, max_bytes: int) -> str | None:
    """Read one bounded regular UTF-8 file while detecting path and inode swaps."""

    validated = validate_confined_path(path, root, expect_directory=False)
    if validated is None:
        return None
    candidate, initial_stat = validated
    if initial_stat.st_nlink != 1 or initial_stat.st_size > max_bytes:
        return None
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    try:
        descriptor = os.open(candidate, flags)
    except (OSError, ValueError):
        return None
    try:
        descriptor_stat = os.fstat(descriptor)
        current = validate_confined_path(candidate, root, expect_directory=False)
        if (
            current is None
            or descriptor_stat.st_nlink != 1
            or _file_revision(descriptor_stat) != _file_revision(initial_stat)
            or _file_revision(current[1]) != _file_revision(initial_stat)
        ):
            return None
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = -1
            content = stream.read(max_bytes + 1)
            descriptor_after = os.fstat(stream.fileno())
        final = validate_confined_path(candidate, root, expect_directory=False)
        if (
            len(content) > max_bytes
            or final is None
            or _file_revision(descriptor_after) != _file_revision(initial_stat)
            or _file_revision(final[1]) != _file_revision(initial_stat)
        ):
            return None
        return content.decode("utf-8")
    except (OSError, UnicodeDecodeError, ValueError):
        return None
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _scan_confined_files(
    directory: Path,
    root: Path,
    *,
    suffix: str,
    max_entries: int,
    max_files: int,
    max_file_bytes: int,
) -> list[Path] | None:
    paths: list[Path] = []
    with os.scandir(directory) as entries:
        for entry_count, entry in enumerate(entries, start=1):
            if entry_count > max_entries:
                return None
            if not entry.name.endswith(suffix):
                continue
            if len(paths) >= max_files:
                return None
            path = directory / entry.name
            validated = validate_confined_path(path, root, expect_directory=False)
            if (
                validated is None
                or validated[1].st_nlink != 1
                or validated[1].st_size > max_file_bytes
            ):
                return None
            paths.append(path)
    return paths


def list_confined_files(
    directory: Path,
    root: Path,
    *,
    suffix: str,
    max_entries: int,
    max_files: int,
    max_file_bytes: int,
) -> list[Path] | None:
    """List bounded regular files, returning ``None`` for any unsafe directory state."""

    try:
        directory.lstat()
    except FileNotFoundError:
        return []
    except OSError:
        return None
    initial = validate_confined_path(directory, root, expect_directory=True)
    if initial is None:
        return None
    try:
        paths = _scan_confined_files(
            directory,
            root,
            suffix=suffix,
            max_entries=max_entries,
            max_files=max_files,
            max_file_bytes=max_file_bytes,
        )
    except OSError:
        return None
    if paths is None:
        return None
    final = validate_confined_path(directory, root, expect_directory=True)
    if final is None or (initial[1].st_dev, initial[1].st_ino) != (
        final[1].st_dev,
        final[1].st_ino,
    ):
        return None
    return sorted(paths, key=lambda item: item.name)

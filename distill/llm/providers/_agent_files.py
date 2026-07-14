# pyright: strict
"""Race-resistant reads for files exchanged with deferred agent workers."""

from __future__ import annotations

import os
import stat
import uuid
from pathlib import Path

_OPEN_SUPPORTS_DIR_FD = os.open in os.supports_dir_fd


def _task_file_revision(file_stat: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        file_stat.st_dev,
        file_stat.st_ino,
        file_stat.st_nlink,
        file_stat.st_size,
        file_stat.st_mtime_ns,
    )


def _unsafe_task_file(path: Path, file_stat: os.stat_result) -> bool:
    reparse_flag = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))
    attributes = int(getattr(file_stat, "st_file_attributes", 0))
    return (
        stat.S_ISLNK(file_stat.st_mode)
        or not stat.S_ISREG(file_stat.st_mode)
        or file_stat.st_nlink != 1
        or bool(reparse_flag and attributes & reparse_flag)
        or (hasattr(path, "is_junction") and path.is_junction())
    )


def _unsafe_task_directory(path: Path, directory_stat: os.stat_result) -> bool:
    reparse_flag = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))
    attributes = int(getattr(directory_stat, "st_file_attributes", 0))
    return (
        stat.S_ISLNK(directory_stat.st_mode)
        or not stat.S_ISDIR(directory_stat.st_mode)
        or bool(reparse_flag and attributes & reparse_flag)
        or (hasattr(path, "is_junction") and path.is_junction())
    )


def _directory_identity(directory_stat: os.stat_result) -> tuple[int, int]:
    return directory_stat.st_dev, directory_stat.st_ino


def _same_path(left: Path, right: Path) -> bool:
    return os.path.normcase(str(left.absolute())) == os.path.normcase(str(right.absolute()))


def validated_task_root(root: Path) -> tuple[Path, tuple[int, int]] | None:
    """Resolve a stable, non-link task root and return its directory identity."""

    try:
        root_absolute = root.absolute()
        initial_stat = root_absolute.lstat()
        if _unsafe_task_directory(root_absolute, initial_stat):
            return None
        identity = _directory_identity(initial_stat)
        root_resolved = root_absolute.resolve(strict=True)
        current_stat = root_absolute.lstat()
    except (OSError, RuntimeError, ValueError):
        return None
    if (
        not _same_path(root_resolved, root_absolute)
        or _unsafe_task_directory(root_absolute, current_stat)
        or _directory_identity(current_stat) != identity
    ):
        return None
    return root_absolute, identity


def task_root_is_unchanged(root: Path, identity: tuple[int, int]) -> bool:
    current = validated_task_root(root)
    return current is not None and current[1] == identity


def _close_task_descriptors(*descriptors: int) -> None:
    for descriptor in descriptors:
        if descriptor >= 0:
            os.close(descriptor)


def _open_task_file(
    path: Path,
    root: Path,
    root_identity: tuple[int, int],
    *,
    max_bytes: int,
) -> tuple[int, int, tuple[int, int, int, int, int]] | None:
    descriptor = -1
    directory_descriptor = -1
    accepted = False
    try:
        if not _same_path(path.parent, root) or not task_root_is_unchanged(root, root_identity):
            return None
        initial_stat = path.lstat()
        if _unsafe_task_file(path, initial_stat) or initial_stat.st_size > max_bytes:
            return None
        revision = _task_file_revision(initial_stat)
        directory_flags = (
            os.O_RDONLY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        supports_openat = os.open in os.supports_dir_fd
        if supports_openat:
            directory_descriptor = os.open(root, directory_flags)
            if _directory_identity(os.fstat(directory_descriptor)) != root_identity:
                return None
        flags = (
            os.O_RDONLY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_NONBLOCK", 0)
        )
        if supports_openat:
            descriptor = os.open(path.name, flags, dir_fd=directory_descriptor)
        else:
            descriptor = os.open(path, flags)
        descriptor_stat = os.fstat(descriptor)
        current_stat = path.lstat()
        if (
            not task_root_is_unchanged(root, root_identity)
            or _unsafe_task_file(path, descriptor_stat)
            or _task_file_revision(descriptor_stat) != revision
            or _task_file_revision(current_stat) != revision
        ):
            return None
        accepted = True
        return descriptor, directory_descriptor, revision
    except (OSError, RuntimeError, ValueError):
        return None
    finally:
        if not accepted:
            _close_task_descriptors(descriptor, directory_descriptor)


def read_task_text(
    path: Path,
    root: Path,
    *,
    max_bytes: int,
    root_identity: tuple[int, int] | None = None,
) -> str | None:
    """Read one direct task child while detecting links, swaps, and size overruns."""

    if max_bytes < 0:
        return None
    if root_identity is None:
        validated_root = validated_task_root(root)
        if validated_root is None:
            return None
        root_path, accepted_identity = validated_root
    else:
        root_path = root
        accepted_identity = root_identity
        if not task_root_is_unchanged(root_path, accepted_identity):
            return None
    opened = _open_task_file(path, root_path, accepted_identity, max_bytes=max_bytes)
    if opened is None:
        return None
    descriptor, directory_descriptor, revision = opened
    try:
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = -1
            content = stream.read(max_bytes + 1)
            descriptor_after = os.fstat(stream.fileno())
        final_stat = path.lstat()
        if (
            len(content) > max_bytes
            or not task_root_is_unchanged(root_path, accepted_identity)
            or _task_file_revision(descriptor_after) != revision
            or _task_file_revision(final_stat) != revision
        ):
            return None
        return content.decode("utf-8")
    except (OSError, UnicodeDecodeError, ValueError):
        return None
    finally:
        _close_task_descriptors(descriptor, directory_descriptor)


def _unlink_bound_child(
    root: Path,
    root_identity: tuple[int, int],
    name: str,
    directory_descriptor: int,
) -> bool:
    try:
        if directory_descriptor >= 0 and os.unlink in os.supports_dir_fd:
            os.unlink(name, dir_fd=directory_descriptor)
        elif task_root_is_unchanged(root, root_identity):
            (root / name).unlink(missing_ok=True)
        else:
            return False
    except OSError:
        return False
    return True


def _open_bound_directory(root: Path, root_identity: tuple[int, int]) -> int:
    if not task_root_is_unchanged(root, root_identity):
        raise OSError("agent task root changed before task creation")
    if not _OPEN_SUPPORTS_DIR_FD:
        return -1
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptor = os.open(root, flags)
    if _directory_identity(os.fstat(descriptor)) == root_identity:
        return descriptor
    os.close(descriptor)
    raise OSError("agent task root changed before task creation")


def _open_temporary_task(
    temporary_path: Path,
    root: Path,
    root_identity: tuple[int, int],
    directory_descriptor: int,
) -> tuple[int, tuple[int, int, int, int, int]]:
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_TEMPORARY", 0)
    )
    if directory_descriptor >= 0:
        descriptor = os.open(
            temporary_path.name,
            flags,
            0o600,
            dir_fd=directory_descriptor,
        )
    else:
        descriptor = os.open(temporary_path, flags, 0o600)
    try:
        descriptor_stat = os.fstat(descriptor)
        try:
            path_stat = temporary_path.lstat()
        except FileNotFoundError as exc:
            raise OSError("agent task root changed during task creation") from exc
        if (
            _unsafe_task_file(temporary_path, descriptor_stat)
            or _task_file_revision(descriptor_stat) != _task_file_revision(path_stat)
            or not task_root_is_unchanged(root, root_identity)
        ):
            raise OSError("agent task root changed during task creation")
        if os.name != "nt" and stat.S_IMODE(path_stat.st_mode) & 0o077:
            raise OSError("agent task temporary file is not owner-only")
        return descriptor, _task_file_revision(descriptor_stat)
    except Exception:
        os.close(descriptor)
        _unlink_bound_child(root, root_identity, temporary_path.name, directory_descriptor)
        raise


def _write_task_content(
    descriptor: int,
    content: bytes,
) -> tuple[int, int, int, int, int]:
    remaining = memoryview(content)
    while remaining:
        written = os.write(descriptor, remaining)
        if written <= 0:
            raise OSError("agent task write made no progress")
        remaining = remaining[written:]
    os.fsync(descriptor)
    written_stat = os.fstat(descriptor)
    if written_stat.st_size != len(content):
        raise OSError(
            f"agent task write was incomplete: {written_stat.st_size} of {len(content)} bytes"
        )
    return _task_file_revision(written_stat)


def _publish_task(
    temporary_path: Path,
    path: Path,
    root: Path,
    root_identity: tuple[int, int],
    directory_descriptor: int,
    descriptor: int,
    written_revision: tuple[int, int, int, int, int],
) -> None:
    published = False
    try:
        if os.link in os.supports_dir_fd and directory_descriptor >= 0:
            os.link(
                temporary_path.name,
                path.name,
                src_dir_fd=directory_descriptor,
                dst_dir_fd=directory_descriptor,
                follow_symlinks=False,
            )
        else:
            if not task_root_is_unchanged(root, root_identity):
                raise OSError("agent task root changed before task publication")
            os.link(temporary_path, path, follow_symlinks=False)
        published = True
        os.close(descriptor)
        descriptor = -1
        deletes_on_close = os.name == "nt" and bool(getattr(os, "O_TEMPORARY", 0))
        if not deletes_on_close and not _unlink_bound_child(
            root, root_identity, temporary_path.name, directory_descriptor
        ):
            raise OSError("agent task temporary file could not be removed")
        final_stat = path.lstat()
        if (
            not task_root_is_unchanged(root, root_identity)
            or _unsafe_task_file(path, final_stat)
            or _task_file_revision(final_stat) != written_revision
        ):
            raise OSError("agent task root changed during task publication")
        if directory_descriptor >= 0:
            os.fsync(directory_descriptor)
    except Exception:
        if published:
            _unlink_bound_child(root, root_identity, path.name, directory_descriptor)
        _unlink_bound_child(root, root_identity, temporary_path.name, directory_descriptor)
        raise
    finally:
        _close_task_descriptors(descriptor)


def write_task_bytes(
    path: Path,
    root: Path,
    root_identity: tuple[int, int],
    content: bytes,
) -> int:
    """Atomically publish one owner-only task beneath a bound directory root."""

    if not _same_path(path.parent, root):
        raise OSError("agent task path is not a direct child of its root")
    temporary_path = root / f".{path.name}.{uuid.uuid4().hex}.tmp"
    directory_descriptor = _open_bound_directory(root, root_identity)
    descriptor = -1
    try:
        descriptor, initial_revision = _open_temporary_task(
            temporary_path,
            root,
            root_identity,
            directory_descriptor,
        )
        written_revision = _write_task_content(descriptor, content)
        if written_revision[:3] != initial_revision[:3]:
            raise OSError("agent task file changed during write")
        publish_descriptor = descriptor
        descriptor = -1
        _publish_task(
            temporary_path,
            path,
            root,
            root_identity,
            directory_descriptor,
            publish_descriptor,
            written_revision,
        )
        return len(content)
    except Exception:
        _unlink_bound_child(root, root_identity, temporary_path.name, directory_descriptor)
        raise
    finally:
        _close_task_descriptors(descriptor, directory_descriptor)

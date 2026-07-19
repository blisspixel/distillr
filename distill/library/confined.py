# pyright: strict
"""Race-aware bounded reads for regular files confined below a trusted root."""

from __future__ import annotations

import codecs
import contextlib
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


def _path_file_revision(file_stat: os.stat_result) -> tuple[int, int, int, int, int, int]:
    """Fingerprint two path stats, where ctime has consistent platform semantics."""

    return (*_file_revision(file_stat), file_stat.st_ctime_ns)


def _open_confined_descriptor(
    path: Path,
    root: Path,
    *,
    max_bytes: int,
) -> tuple[int, Path, os.stat_result] | None:
    if max_bytes < 0:
        return None
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
    descriptor = -1
    try:
        descriptor = os.open(candidate, flags)
        descriptor_stat = os.fstat(descriptor)
        current = validate_confined_path(candidate, root, expect_directory=False)
        if (
            current is None
            or descriptor_stat.st_nlink != 1
            or _file_revision(descriptor_stat) != _file_revision(initial_stat)
            or _path_file_revision(current[1]) != _path_file_revision(initial_stat)
        ):
            with contextlib.suppress(OSError):
                os.close(descriptor)
            return None
    except (OSError, ValueError):
        if descriptor >= 0:
            with contextlib.suppress(OSError):
                os.close(descriptor)
        return None
    return descriptor, candidate, initial_stat


def _descriptor_read_stayed_stable(
    candidate: Path,
    root: Path,
    initial_stat: os.stat_result,
    descriptor_stat: os.stat_result,
) -> bool:
    final = validate_confined_path(candidate, root, expect_directory=False)
    return bool(
        final is not None
        and _file_revision(descriptor_stat) == _file_revision(initial_stat)
        and _path_file_revision(final[1]) == _path_file_revision(initial_stat)
    )


def read_confined_bytes(path: Path, root: Path, *, max_bytes: int) -> bytes | None:
    """Read one bounded regular file while detecting path and inode swaps."""

    opened = _open_confined_descriptor(path, root, max_bytes=max_bytes)
    if opened is None:
        return None
    descriptor, candidate, initial_stat = opened
    try:
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = -1
            content = stream.read(max_bytes + 1)
            descriptor_after = os.fstat(stream.fileno())
        if len(content) > max_bytes or not _descriptor_read_stayed_stable(
            candidate,
            root,
            initial_stat,
            descriptor_after,
        ):
            return None
        return content
    except (OSError, ValueError):
        return None
    finally:
        if descriptor >= 0:
            _close_descriptor(descriptor)


def read_confined_text(path: Path, root: Path, *, max_bytes: int) -> str | None:
    """Read one bounded regular UTF-8 file while detecting path and inode swaps."""

    content = read_confined_bytes(path, root, max_bytes=max_bytes)
    if content is None:
        return None
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        return None


def read_confined_text_prefix(
    path: Path,
    root: Path,
    *,
    max_file_bytes: int,
    max_chars: int,
) -> str | None:
    """Read only a bounded UTF-8 prefix from one stable confined file."""

    if max_chars < 0:
        return None
    opened = _open_confined_descriptor(path, root, max_bytes=max_file_bytes)
    if opened is None:
        return None
    descriptor, candidate, initial_stat = opened
    try:
        with os.fdopen(descriptor, "rb") as raw_stream:
            descriptor = -1
            decoder = codecs.getincrementaldecoder("utf-8")(errors="strict")
            retained: list[str] = []
            retained_chars = 0
            total_bytes = 0
            while chunk := raw_stream.read(min(8192, max_file_bytes - total_bytes + 1)):
                total_bytes += len(chunk)
                if total_bytes > max_file_bytes:
                    return None
                decoded = decoder.decode(chunk, final=False)
                if retained_chars < max_chars:
                    prefix = decoded[: max_chars - retained_chars]
                    retained.append(prefix)
                    retained_chars += len(prefix)
            decoded = decoder.decode(b"", final=True)
            if retained_chars < max_chars:
                retained.append(decoded[: max_chars - retained_chars])
            descriptor_after = os.fstat(raw_stream.fileno())
        if not _descriptor_read_stayed_stable(
            candidate,
            root,
            initial_stat,
            descriptor_after,
        ):
            return None
        return "".join(retained)
    except (OSError, UnicodeError, ValueError):
        return None
    finally:
        if descriptor >= 0:
            _close_descriptor(descriptor)


def _close_descriptor(descriptor: int) -> None:
    with contextlib.suppress(OSError):
        os.close(descriptor)


def _remove_file_with_identity(path: Path, identity: tuple[int, int]) -> None:
    with contextlib.suppress(OSError):
        current = path.lstat()
        if (current.st_dev, current.st_ino) == identity:
            path.unlink()


def _open_snapshot_destination(destination: Path) -> tuple[int, tuple[int, int]] | None:
    descriptor = -1
    identity: tuple[int, int] | None = None
    try:
        descriptor = os.open(
            destination,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        descriptor_stat = os.fstat(descriptor)
        identity = (descriptor_stat.st_dev, descriptor_stat.st_ino)
        if not stat.S_ISREG(descriptor_stat.st_mode) or descriptor_stat.st_nlink != 1:
            raise OSError("snapshot destination is not a private regular file")
        return descriptor, identity
    except (OSError, ValueError):
        if descriptor >= 0:
            _close_descriptor(descriptor)
        if identity is not None:
            _remove_file_with_identity(destination, identity)
        return None


def _stream_snapshot(
    source_descriptor: int,
    destination_descriptor: int,
    *,
    max_bytes: int,
) -> tuple[os.stat_result, os.stat_result] | None:
    source_stream = None
    destination_stream = None
    try:
        source_stream = os.fdopen(source_descriptor, "rb")
        source_descriptor = -1
        destination_stream = os.fdopen(destination_descriptor, "wb")
        destination_descriptor = -1
        with source_stream, destination_stream:
            total = 0
            while chunk := source_stream.read(min(1024 * 1024, max_bytes - total + 1)):
                total += len(chunk)
                if total > max_bytes:
                    return None
                if destination_stream.write(chunk) != len(chunk):
                    return None
            destination_stream.flush()
            return os.fstat(source_stream.fileno()), os.fstat(destination_stream.fileno())
    except (OSError, ValueError):
        return None
    finally:
        if source_descriptor >= 0:
            _close_descriptor(source_descriptor)
        if destination_descriptor >= 0:
            _close_descriptor(destination_descriptor)
        if source_stream is not None and not source_stream.closed:
            with contextlib.suppress(OSError):
                source_stream.close()
        if destination_stream is not None and not destination_stream.closed:
            with contextlib.suppress(OSError):
                destination_stream.close()


def _snapshot_destination_stayed_stable(
    destination: Path,
    identity: tuple[int, int],
    descriptor_stat: os.stat_result,
) -> bool:
    try:
        final_stat = destination.lstat()
    except OSError:
        return False
    return bool(
        stat.S_ISREG(descriptor_stat.st_mode)
        and descriptor_stat.st_nlink == 1
        and _file_revision(descriptor_stat) == _file_revision(final_stat)
        and (descriptor_stat.st_dev, descriptor_stat.st_ino) == identity
    )


def _copy_opened_source(
    opened: tuple[int, Path, os.stat_result],
    root: Path,
    destination: Path,
    *,
    max_bytes: int,
) -> bool:
    source_descriptor, candidate, initial_stat = opened
    created = _open_snapshot_destination(destination)
    if created is None:
        _close_descriptor(source_descriptor)
        return False
    destination_descriptor, destination_identity = created
    copied = _stream_snapshot(
        source_descriptor,
        destination_descriptor,
        max_bytes=max_bytes,
    )
    if copied is None:
        _remove_file_with_identity(destination, destination_identity)
        return False
    source_after, destination_after = copied
    stable = _descriptor_read_stayed_stable(
        candidate,
        root,
        initial_stat,
        source_after,
    ) and _snapshot_destination_stayed_stable(
        destination,
        destination_identity,
        destination_after,
    )
    if not stable:
        _remove_file_with_identity(destination, destination_identity)
    return stable


def copy_confined_file(
    path: Path,
    root: Path,
    destination: Path,
    *,
    max_bytes: int,
) -> bool:
    """Stream one stable confined file into a new owner-only destination."""

    opened = _open_confined_descriptor(path, root, max_bytes=max_bytes)
    if opened is None:
        return False
    return _copy_opened_source(opened, root, destination, max_bytes=max_bytes)


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


def _scan_confined_directories(
    directory: Path,
    root: Path,
    *,
    max_entries: int,
    max_directories: int,
) -> list[Path] | None:
    directories: list[Path] = []
    with os.scandir(directory) as entries:
        for entry_count, entry in enumerate(entries, start=1):
            if entry_count > max_entries:
                return None
            try:
                is_directory = entry.is_dir(follow_symlinks=False)
            except OSError:
                return None
            if not is_directory:
                continue
            if len(directories) >= max_directories:
                return None
            path = directory / entry.name
            if validate_confined_path(path, root, expect_directory=True) is None:
                return None
            directories.append(path)
    return directories


def list_confined_directories(
    directory: Path,
    root: Path,
    *,
    max_entries: int,
    max_directories: int,
) -> list[Path] | None:
    """List bounded no-follow child directories under one trusted root."""

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
        directories = _scan_confined_directories(
            directory,
            root,
            max_entries=max_entries,
            max_directories=max_directories,
        )
    except OSError:
        return None
    if directories is None:
        return None
    final = validate_confined_path(directory, root, expect_directory=True)
    if final is None or (initial[1].st_dev, initial[1].st_ino) != (
        final[1].st_dev,
        final[1].st_ino,
    ):
        return None
    return sorted(directories, key=lambda item: item.name)

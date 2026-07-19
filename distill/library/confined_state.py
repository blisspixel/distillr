# pyright: strict
"""Stable-root helpers for durable state below an application-owned directory."""

from __future__ import annotations

import contextlib
import hashlib
import os
import stat
import tempfile
import time
from pathlib import Path

from distill.library.confined import read_confined_bytes, validate_confined_path
from distill.library.paths import text_write_lock

FileIdentity = tuple[int, int, int, int, int, int]
PathRevision = tuple[int, int]
_NodeIdentity = tuple[int, int]

_ATOMIC_REPLACE_TIMEOUT_SECONDS = 2.0
_ATOMIC_REPLACE_RETRY_SECONDS = 0.05


class ConfinedStateError(ValueError):
    """A state path cannot be read or mutated below its declared root."""


def confined_state_lock_path(path: Path, root: Path, purpose: str) -> Path:
    """Return a stable root-level lock path for one confined state target."""

    if not purpose or any(not (character.isalnum() or character == "-") for character in purpose):
        raise ValueError(f"Invalid confined state lock purpose: {purpose!r}")
    root_absolute, relative_parts = _root_and_relative(path, root)
    identity = "/".join(os.path.normcase(part) for part in relative_parts)
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    return root_absolute / f".distill-{purpose}-{digest}.lock"


def _is_link_like(path: Path, file_stat: os.stat_result) -> bool:
    if stat.S_ISLNK(file_stat.st_mode):
        return True
    reparse_flag = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))
    attributes = int(getattr(file_stat, "st_file_attributes", 0))
    return bool(reparse_flag and attributes & reparse_flag) or (
        hasattr(path, "is_junction") and path.is_junction()
    )


def _absolute(path: Path) -> Path:
    return path.absolute()


def _root_and_relative(path: Path, root: Path) -> tuple[Path, tuple[str, ...]]:
    root_absolute = _absolute(root)
    path_absolute = _absolute(path)
    try:
        relative = path_absolute.relative_to(root_absolute)
    except ValueError as exc:
        raise ConfinedStateError(f"State path escapes its confinement root: {path}") from exc
    if not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
        raise ConfinedStateError(f"State path is not a safe child of {root}")
    try:
        root_stat = root_absolute.lstat()
    except OSError as exc:
        raise ConfinedStateError(f"State root is unavailable: {root}") from exc
    if _is_link_like(root_absolute, root_stat) or not stat.S_ISDIR(root_stat.st_mode):
        raise ConfinedStateError(f"State root is not a private directory: {root}")
    return root_absolute, relative.parts


def _directory_revision(file_stat: os.stat_result) -> PathRevision:
    return file_stat.st_dev, file_stat.st_ino


def _node_identity(file_stat: os.stat_result) -> _NodeIdentity:
    return file_stat.st_dev, file_stat.st_ino


def _file_identity(file_stat: os.stat_result) -> FileIdentity:
    return (
        file_stat.st_dev,
        file_stat.st_ino,
        file_stat.st_nlink,
        file_stat.st_size,
        file_stat.st_mtime_ns,
        file_stat.st_ctime_ns,
    )


def ensure_confined_parent(
    path: Path,
    root: Path,
    *,
    create: bool,
) -> tuple[Path, PathRevision] | None:
    """Validate every parent component and optionally create missing directories."""

    root_absolute, relative_parts = _root_and_relative(path, root)
    current = root_absolute
    for part in relative_parts[:-1]:
        current /= part
        try:
            current_stat = current.lstat()
        except FileNotFoundError:
            if not create:
                return None
            with contextlib.suppress(FileExistsError):
                current.mkdir()
            current_stat = current.lstat()
        except OSError as exc:
            raise ConfinedStateError(f"State directory is unavailable: {current}") from exc
        if _is_link_like(current, current_stat) or not stat.S_ISDIR(current_stat.st_mode):
            raise ConfinedStateError(f"State directory is not a private directory: {current}")
    parent = root_absolute.joinpath(*relative_parts[:-1])
    parent_stat = parent.lstat()
    return parent, _directory_revision(parent_stat)


def _require_parent_revision(path: Path, root: Path, expected: PathRevision) -> Path:
    validated = ensure_confined_parent(path, root, create=False)
    if validated is None or validated[1] != expected:
        raise ConfinedStateError(f"State directory changed during mutation: {path.parent}")
    return validated[0]


def confined_file_identity(path: Path, root: Path) -> FileIdentity | None:
    """Return a private regular file's identity, or None only when missing."""

    parent = ensure_confined_parent(path, root, create=False)
    if parent is None:
        return None
    try:
        path.lstat()
    except FileNotFoundError:
        return None
    validated = validate_confined_path(_absolute(path), _absolute(root), expect_directory=False)
    if validated is None or validated[1].st_nlink != 1:
        raise ConfinedStateError(f"State file is unsafe: {path}")
    _require_parent_revision(path, root, parent[1])
    return _file_identity(validated[1])


def read_confined_state_bytes(path: Path, root: Path, *, max_bytes: int) -> bytes | None:
    """Read one bounded private file, returning None only when it is missing."""

    if confined_file_identity(path, root) is None:
        return None
    content = read_confined_bytes(_absolute(path), _absolute(root), max_bytes=max_bytes)
    if content is None:
        raise ConfinedStateError(
            f"State file is unreadable, changed, or exceeds the {max_bytes:,}-byte limit: {path}"
        )
    return content


def read_confined_state_text(path: Path, root: Path, *, max_bytes: int) -> str | None:
    """Read one bounded private UTF-8 file, returning None only when missing."""

    content = read_confined_state_bytes(path, root, max_bytes=max_bytes)
    if content is None:
        return None
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ConfinedStateError(f"State file is not valid UTF-8: {path}") from exc


def _remove_matching(path: Path, identity: _NodeIdentity) -> None:
    with contextlib.suppress(OSError):
        current = path.lstat()
        if _node_identity(current) == identity:
            path.unlink()


def _write_all(descriptor: int, content: bytes) -> None:
    remaining = memoryview(content)
    while remaining:
        written = os.write(descriptor, remaining)
        if written <= 0 or written > len(remaining):
            raise OSError("Unable to write complete confined state")
        remaining = remaining[written:]


def _require_mutation_target(
    path: Path,
    identity: FileIdentity | None,
    *,
    exclusive: bool,
    expected: FileIdentity | None,
    stage: str,
) -> None:
    if exclusive and identity is not None:
        raise FileExistsError(path)
    if expected is not None and identity != expected:
        raise ConfinedStateError(f"State target changed {stage} mutation: {path}")


def _is_retryable_replace_error(_error: PermissionError) -> bool:
    return os.name == "nt"


def _validate_replace_attempt(
    path: Path,
    temp_path: Path,
    root: Path,
    *,
    parent_revision: PathRevision,
    initial_identity: FileIdentity | None,
    temp_revision: FileIdentity,
    exclusive: bool,
    expected: FileIdentity | None,
) -> None:
    _require_parent_revision(path, root, parent_revision)
    current_identity = confined_file_identity(path, root)
    _require_mutation_target(
        path,
        current_identity,
        exclusive=exclusive,
        expected=expected,
        stage="during",
    )
    if not exclusive and expected is None and current_identity != initial_identity:
        raise ConfinedStateError(f"State target changed during mutation: {path}")
    try:
        current_temp = temp_path.lstat()
    except OSError as exc:
        raise ConfinedStateError(
            f"Temporary state file changed during mutation: {temp_path}"
        ) from exc
    if _file_identity(current_temp) != temp_revision:
        raise ConfinedStateError(f"Temporary state file changed during mutation: {temp_path}")


def _replace_confined_with_retry(
    path: Path,
    temp_path: Path,
    root: Path,
    *,
    parent_revision: PathRevision,
    initial_identity: FileIdentity | None,
    temp_revision: FileIdentity,
    exclusive: bool,
    expected: FileIdentity | None,
) -> None:
    """Replace a confined target, revalidating state before every retry."""

    deadline = time.monotonic() + _ATOMIC_REPLACE_TIMEOUT_SECONDS
    while True:
        _validate_replace_attempt(
            path,
            temp_path,
            root,
            parent_revision=parent_revision,
            initial_identity=initial_identity,
            temp_revision=temp_revision,
            exclusive=exclusive,
            expected=expected,
        )
        try:
            temp_path.replace(_absolute(path))
            return
        except PermissionError as exc:
            if not _is_retryable_replace_error(exc) or time.monotonic() >= deadline:
                raise
            time.sleep(_ATOMIC_REPLACE_RETRY_SECONDS)


def atomic_write_confined_bytes(
    path: Path,
    content: bytes,
    root: Path,
    *,
    exclusive: bool = False,
    expected: FileIdentity | None = None,
) -> None:
    """Atomically replace one file without writing through linked child directories."""

    if exclusive and expected is not None:
        raise ValueError("exclusive and expected identity cannot be combined")
    ensure_confined_parent(path, root, create=True)
    with text_write_lock(path):
        _atomic_write_confined_bytes_unlocked(
            path,
            content,
            root,
            exclusive=exclusive,
            expected=expected,
        )


def _atomic_write_confined_bytes_unlocked(
    path: Path,
    content: bytes,
    root: Path,
    *,
    exclusive: bool,
    expected: FileIdentity | None,
) -> None:
    """Implement a confined replacement while the shared path lock is held."""

    parent, parent_revision = ensure_confined_parent(path, root, create=True) or (None, None)
    if parent is None or parent_revision is None:  # pragma: no cover - create=True
        raise ConfinedStateError(f"Could not create state directory for {path}")
    initial_identity = confined_file_identity(path, root)
    _require_mutation_target(
        path,
        initial_identity,
        exclusive=exclusive,
        expected=expected,
        stage="before",
    )

    descriptor, raw_temp = tempfile.mkstemp(dir=parent, prefix=f".{path.name}.", suffix=".tmp")
    temp_path = Path(raw_temp)
    temp_identity = _node_identity(os.fstat(descriptor))
    try:
        _require_parent_revision(path, root, parent_revision)
        validated_temp = validate_confined_path(
            temp_path,
            _absolute(root),
            expect_directory=False,
        )
        if (
            validated_temp is None
            or validated_temp[1].st_nlink != 1
            or _node_identity(validated_temp[1]) != temp_identity
        ):
            raise ConfinedStateError(f"Temporary state path escaped confinement: {temp_path}")
        _write_all(descriptor, content)
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1

        temp_revision = _file_identity(temp_path.lstat())
        if temp_revision[:2] != temp_identity:
            raise ConfinedStateError(f"Temporary state file changed during mutation: {temp_path}")
        _replace_confined_with_retry(
            path,
            temp_path,
            root,
            parent_revision=parent_revision,
            initial_identity=initial_identity,
            temp_revision=temp_revision,
            exclusive=exclusive,
            expected=expected,
        )
        final_identity = confined_file_identity(path, root)
        if final_identity is None or final_identity[:2] != temp_identity:
            raise ConfinedStateError(f"State target escaped confinement during replace: {path}")
    finally:
        if descriptor >= 0:
            with contextlib.suppress(OSError):
                os.close(descriptor)
        _remove_matching(temp_path, temp_identity)


def atomic_write_confined_text(
    path: Path,
    content: str,
    root: Path,
    *,
    exclusive: bool = False,
    expected: FileIdentity | None = None,
) -> None:
    """UTF-8 wrapper for ``atomic_write_confined_bytes``."""

    atomic_write_confined_bytes(
        path,
        content.encode("utf-8"),
        root,
        exclusive=exclusive,
        expected=expected,
    )


def unlink_confined_file(path: Path, root: Path, *, expected: FileIdentity) -> None:
    """Delete only the same private file identity that the caller previously read."""

    if ensure_confined_parent(path, root, create=False) is None:
        raise FileNotFoundError(path)
    with text_write_lock(path):
        parent = ensure_confined_parent(path, root, create=False)
        if parent is None:
            raise FileNotFoundError(path)
        identity = confined_file_identity(path, root)
        if identity != expected:
            raise ConfinedStateError(f"State target changed before deletion: {path}")
        _require_parent_revision(path, root, parent[1])
        path.unlink()

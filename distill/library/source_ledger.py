# pyright: strict
"""Strict durable completion ledgers for source-based model work."""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import cast

from distill.library.confined_state import (
    ConfinedStateError,
    atomic_write_confined_bytes,
    confined_state_lock_path,
    ensure_confined_parent,
    read_confined_state_bytes,
)
from distill.library.locking import exclusive_path_lock
from distill.parsing import strict_json_loads

MAX_SOURCE_LEDGER_BYTES = 8 * 1024 * 1024
MAX_SOURCE_LEDGER_ENTRIES = 100_000
MAX_SOURCE_ID_BYTES = 16 * 1024
_SOURCE_LEDGER_LOCK_TIMEOUT_SECONDS = 30.0


class SourceLedgerIntegrityError(ValueError):
    """An existing completion ledger cannot safely support a pending decision."""

    def __init__(self, path: Path, reason: str) -> None:
        self.path = path
        self.reason = reason
        super().__init__(f"Invalid source completion ledger at {path}: {reason}")


def validate_source_id(value: object) -> str:
    """Return one source ID after applying the canonical storage contract."""

    if not isinstance(value, str) or not value:
        raise ValueError("is not a nonempty string")
    if len(value.encode("utf-8")) > MAX_SOURCE_ID_BYTES:
        raise ValueError(f"exceeds the {MAX_SOURCE_ID_BYTES:,}-byte source-id limit")
    return value


def _validated_source_ids(
    path: Path,
    values: object,
    *,
    reject_duplicates: bool = True,
    allow_legacy_oversized: bool = False,
) -> set[str]:
    if not isinstance(values, list):
        raise SourceLedgerIntegrityError(path, "root value is not a JSON array")
    raw_values = cast("list[object]", values)
    if len(raw_values) > MAX_SOURCE_LEDGER_ENTRIES:
        raise SourceLedgerIntegrityError(
            path,
            f"ledger exceeds the {MAX_SOURCE_LEDGER_ENTRIES:,}-entry limit",
        )
    source_ids: set[str] = set()
    for index, value in enumerate(raw_values, start=1):
        try:
            if allow_legacy_oversized:
                if not isinstance(value, str) or not value:
                    raise ValueError("is not a nonempty string")
                source_id = value
            else:
                source_id = validate_source_id(value)
        except ValueError as exc:
            raise SourceLedgerIntegrityError(path, f"entry {index} {exc}") from exc
        if reject_duplicates and source_id in source_ids:
            raise SourceLedgerIntegrityError(
                path,
                f"entry {index} duplicates source ID {source_id!r}",
            )
        source_ids.add(source_id)
    return source_ids


def read_source_ledger(path: Path, *, root: Path) -> set[str]:
    """Read a complete strict ledger, returning empty only when it is missing."""

    try:
        content = read_confined_state_bytes(
            path,
            root,
            max_bytes=MAX_SOURCE_LEDGER_BYTES,
        )
    except ConfinedStateError as exc:
        raise SourceLedgerIntegrityError(path, str(exc)) from exc
    if content is None:
        return set()
    try:
        loaded = strict_json_loads(content)
    except (RecursionError, UnicodeDecodeError, ValueError) as exc:
        raise SourceLedgerIntegrityError(path, f"content is not strict JSON: {exc}") from exc
    return _validated_source_ids(path, loaded, allow_legacy_oversized=True)


def _validate_new_source_ids(path: Path, source_ids: Iterable[str]) -> set[str]:
    values = list(source_ids)
    return _validated_source_ids(path, values, reject_duplicates=False)


def _ledger_lock_path(path: Path, root: Path) -> Path:
    return confined_state_lock_path(path, root, "source-ledger")


def _encoded_merged_ledger(path: Path, current: set[str], new: set[str]) -> bytes:
    merged = current | new
    if len(merged) > MAX_SOURCE_LEDGER_ENTRIES:
        raise SourceLedgerIntegrityError(
            path,
            f"ledger exceeds the {MAX_SOURCE_LEDGER_ENTRIES:,}-entry limit",
        )
    encoded = json.dumps(
        sorted(merged),
        ensure_ascii=False,
        indent=2,
        allow_nan=False,
    ).encode("utf-8")
    if len(encoded) > MAX_SOURCE_LEDGER_BYTES:
        raise SourceLedgerIntegrityError(
            path,
            f"serialized ledger exceeds the {MAX_SOURCE_LEDGER_BYTES:,}-byte limit",
        )
    return encoded


def ensure_source_ledger_merge_capacity(
    path: Path,
    source_ids: Iterable[str],
    *,
    root: Path,
) -> None:
    """Validate a projected merge under the ledger lock without publishing it."""

    new = _validate_new_source_ids(path, source_ids)
    if not new:
        return
    try:
        lock_path = _ledger_lock_path(path, root)
        ensure_confined_parent(lock_path, root, create=False)
    except ConfinedStateError as exc:
        raise SourceLedgerIntegrityError(path, str(exc)) from exc
    with exclusive_path_lock(
        lock_path,
        timeout_seconds=_SOURCE_LEDGER_LOCK_TIMEOUT_SECONDS,
        timeout_message=f"Timed out validating source completion ledger: {path}",
    ):
        _encoded_merged_ledger(path, read_source_ledger(path, root=root), new)


def merge_source_ledger(
    path: Path,
    source_ids: Iterable[str],
    *,
    root: Path,
) -> None:
    """Merge source IDs under a cross-process lock and durable atomic replace."""

    new = _validate_new_source_ids(path, source_ids)
    if not new:
        return
    try:
        lock_path = _ledger_lock_path(path, root)
        ensure_confined_parent(lock_path, root, create=False)
    except ConfinedStateError as exc:
        raise SourceLedgerIntegrityError(path, str(exc)) from exc
    with exclusive_path_lock(
        lock_path,
        timeout_seconds=_SOURCE_LEDGER_LOCK_TIMEOUT_SECONDS,
        timeout_message=f"Timed out updating source completion ledger: {path}",
    ):
        encoded = _encoded_merged_ledger(
            path,
            read_source_ledger(path, root=root),
            new,
        )
        try:
            atomic_write_confined_bytes(path, encoded, root)
        except ConfinedStateError as exc:
            raise SourceLedgerIntegrityError(path, str(exc)) from exc

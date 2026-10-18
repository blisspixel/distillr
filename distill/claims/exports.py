"""The strict per-topic ``claims.jsonl`` append-only store."""

# pyright: strict

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any, cast

from distill.claims.generations import ClaimGeneration, active_generation_claims
from distill.claims.records import Claim
from distill.jsonl import (
    JsonlIntegrityError,
    append_jsonl_lines_locked,
    jsonl_append_lock,
    read_jsonl_objects_strict,
)
from distill.library.confined_state import read_confined_state_bytes
from distill.library.source_ledger import (
    ensure_source_ledger_merge_capacity,
    merge_source_ledger,
    read_source_ledger,
    validate_source_id,
)

__all__ = [
    "already_extracted_source_ids",
    "append_claims",
    "claims_jsonl_path",
    "ensure_claim_store_append_capacity",
    "ensure_extracted_sources_capacity",
    "latest_claims",
    "read_claims",
    "read_extracted_sources",
    "record_extracted_sources",
]

_MAX_CLAIMS_HISTORY_BYTES = 8 * 1024 * 1024
_MAX_CLAIM_ROW_BYTES = 1024 * 1024
_MAX_CLAIMS_HISTORY_ROWS = 10_000


def claims_jsonl_path(topic_dir: Path) -> Path:
    """Return the path to the per-topic ``claims.jsonl`` append-only store."""

    return topic_dir / ".claims" / "claims.jsonl"


def _extracted_sources_path(topic_dir: Path) -> Path:
    return topic_dir / ".claims" / "extracted_sources.json"


def read_extracted_sources(topic_dir: Path) -> set[str]:
    """Return every source with a durable successful-extraction receipt."""

    return read_source_ledger(_extracted_sources_path(topic_dir), root=topic_dir)


def record_extracted_sources(topic_dir: Path, source_ids: Iterable[str]) -> None:
    """Durably merge successful source IDs into the completion ledger."""

    merge_source_ledger(_extracted_sources_path(topic_dir), source_ids, root=topic_dir)


def ensure_extracted_sources_capacity(topic_dir: Path, source_ids: Iterable[str]) -> None:
    """Fail before provider work if completion receipts cannot be represented."""

    ensure_source_ledger_merge_capacity(
        _extracted_sources_path(topic_dir),
        source_ids,
        root=topic_dir,
    )


def append_claims(
    topic_dir: Path, claims: list[Claim], *, generation: ClaimGeneration | None = None
) -> Path:
    """Durably append one complete claim batch before publishing completion."""

    path = claims_jsonl_path(topic_dir)
    rows: list[dict[str, Any]] = []
    for index, claim in enumerate(claims, 1):
        try:
            row = claim.to_jsonl_row()
            Claim.from_jsonl_row(row)
            validate_source_id(row["source_id"])
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            raise JsonlIntegrityError(
                path, f"row {index} violates the Claim schema: {exc}"
            ) from exc
        rows.append(row)
    if generation is not None:
        if generation.claims != tuple(claims):
            raise JsonlIntegrityError(path, "Generation payload does not match its claim batch")
        generation_row = generation.to_row()
        ClaimGeneration.from_row(generation_row)
        rows = [generation_row]
    lines = [
        json.dumps(
            row,
            ensure_ascii=False,
            allow_nan=False,
        )
        for row in rows
    ]
    encoded_size = sum(len(line.encode("utf-8")) + 1 for line in lines)
    if any(len(line.encode("utf-8")) > _MAX_CLAIM_ROW_BYTES for line in lines):
        raise JsonlIntegrityError(
            path,
            f"claim batch contains a row above the {_MAX_CLAIM_ROW_BYTES:,}-byte limit",
        )
    with jsonl_append_lock(path, confinement_root=topic_dir):
        existing = _read_claim_history(topic_dir)
        existing_bytes = read_confined_state_bytes(
            path,
            topic_dir,
            max_bytes=_MAX_CLAIMS_HISTORY_BYTES,
        )
        if (
            len(_read_claim_rows(topic_dir)) + len(rows) > _MAX_CLAIMS_HISTORY_ROWS
            or len(existing) + len(claims) > _MAX_CLAIMS_HISTORY_ROWS
        ):
            raise JsonlIntegrityError(
                path,
                f"append would exceed the {_MAX_CLAIMS_HISTORY_ROWS:,}-row limit",
            )
        if len(existing_bytes or b"") + encoded_size > _MAX_CLAIMS_HISTORY_BYTES:
            raise JsonlIntegrityError(
                path,
                f"append would exceed the {_MAX_CLAIMS_HISTORY_BYTES:,}-byte limit",
            )
        append_jsonl_lines_locked(
            path,
            lines,
            durable=True,
            confinement_root=topic_dir,
        )
    return path


def _claim_from_row(path: Path, index: int, row: dict[str, object]) -> Claim:
    try:
        return Claim.from_jsonl_row(cast("dict[str, Any]", row))
    except (KeyError, TypeError, ValueError) as exc:
        raise JsonlIntegrityError(path, f"row {index} violates the Claim schema: {exc}") from exc


def _read_claim_rows(topic_dir: Path) -> list[dict[str, object]]:
    path = claims_jsonl_path(topic_dir)
    rows = read_jsonl_objects_strict(
        path,
        max_file_bytes=_MAX_CLAIMS_HISTORY_BYTES,
        max_row_bytes=_MAX_CLAIM_ROW_BYTES,
        max_rows=_MAX_CLAIMS_HISTORY_ROWS,
        confinement_root=topic_dir,
    )
    return rows


def _read_claim_history(topic_dir: Path) -> list[Claim]:
    return _claims_from_history_rows(topic_dir, _read_claim_rows(topic_dir))


def _claims_from_history_rows(topic_dir: Path, rows: list[dict[str, object]]) -> list[Claim]:
    path = claims_jsonl_path(topic_dir)
    claims: list[Claim] = []
    for index, row in enumerate(rows, 1):
        if "event" in row:
            try:
                if row.get("event") != "claim-generation.v1":
                    raise ValueError("Unsupported claim history event")
                claims.extend(ClaimGeneration.from_row(row).claims)
            except ValueError as exc:
                raise JsonlIntegrityError(path, f"row {index}: {exc}") from exc
        else:
            claims.append(_claim_from_row(path, index, row))
        if len(claims) > _MAX_CLAIMS_HISTORY_ROWS:
            raise JsonlIntegrityError(path, "Flattened claim history exceeds its row limit")
    return claims


def read_active_claims(topic_dir: Path) -> list[Claim]:
    rows = _read_claim_rows(topic_dir)
    _claims_from_history_rows(topic_dir, rows)
    try:
        return active_generation_claims(rows)
    except ValueError as exc:
        raise JsonlIntegrityError(claims_jsonl_path(topic_dir), str(exc)) from exc


def completed_generations(topic_dir: Path) -> dict[tuple[str, str], str]:
    result: dict[tuple[str, str], str] = {}
    rows = _read_claim_rows(topic_dir)
    _claims_from_history_rows(topic_dir, rows)
    for row in rows:
        if row.get("event") == "claim-generation.v1":
            generation = ClaimGeneration.from_row(row)
            result[(generation.source_id, generation.artifact_path)] = generation.content_sha256
    return result


def read_claims(topic_dir: Path) -> list[Claim]:
    """Read a complete bounded claim history, returning empty only if missing."""

    return _read_claim_history(topic_dir)


def latest_claims(claims: Iterable[Claim]) -> list[Claim]:
    """Return the newest row per ``claim_id``, preserving first-seen order.

    ``refresh`` re-appends extraction rows. Synthesis and its receipt must
    cite each assertion once, or a later pass can treat two copies as
    independent corroboration.
    """

    latest: dict[str, Claim] = {}
    order: list[str] = []
    for claim in claims:
        if claim.claim_id not in latest:
            order.append(claim.claim_id)
        latest[claim.claim_id] = claim
    return [latest[claim_id] for claim_id in order]


def ensure_claim_store_append_capacity(topic_dir: Path) -> None:
    """Fail before provider work when no additional claim row can be stored."""

    path = claims_jsonl_path(topic_dir)
    claims = _read_claim_history(topic_dir)
    existing = read_confined_state_bytes(
        path,
        topic_dir,
        max_bytes=_MAX_CLAIMS_HISTORY_BYTES,
    )
    if (
        len(claims) >= _MAX_CLAIMS_HISTORY_ROWS
        or len(_read_claim_rows(topic_dir)) >= _MAX_CLAIMS_HISTORY_ROWS
    ):
        raise JsonlIntegrityError(
            path, f"history reached the {_MAX_CLAIMS_HISTORY_ROWS:,}-row limit"
        )
    if len(existing or b"") >= _MAX_CLAIMS_HISTORY_BYTES:
        raise JsonlIntegrityError(
            path,
            f"history reached the {_MAX_CLAIMS_HISTORY_BYTES:,}-byte limit",
        )


def already_extracted_source_ids(topic_dir: Path) -> set[str]:
    """Return source IDs in the fully validated canonical claim history."""

    return {claim.source_id for claim in read_claims(topic_dir)} | {
        source for source, _artifact in completed_generations(topic_dir)
    }

"""The per-topic ``claims.jsonl`` append-only store.

Unlike the concept layer -- where ``mentions.jsonl`` is the raw log and
``concepts.jsonl`` is a separate merged rollup -- a claim is already the unit
the synthesis pass consumes, so ``claims.jsonl`` is both the append-only audit
trail and the canonical claim set. One row per extracted claim, never edited
or overwritten; the pipeline re-reads the whole file on synthesis.

Stored under ``<topic_dir>/.claims/claims.jsonl`` (dot-prefixed so the shared
``library.insights.discover_insights`` walk skips it).
"""

# pyright: strict

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any, cast

from distill.claims.records import Claim

__all__ = [
    "already_extracted_source_ids",
    "append_claims",
    "claims_jsonl_path",
    "read_claims",
    "read_extracted_sources",
    "record_extracted_sources",
]


def claims_jsonl_path(topic_dir: Path) -> Path:
    """Return the path to the per-topic ``claims.jsonl`` append-only store."""
    return topic_dir / ".claims" / "claims.jsonl"


def _extracted_sources_path(topic_dir: Path) -> Path:
    return topic_dir / ".claims" / "extracted_sources.json"


def read_extracted_sources(topic_dir: Path) -> set[str]:
    """Return the ledger of source_ids whose insight has been extracted.

    This ledger records *every* successfully-processed insight, including ones
    that yielded zero claims -- which ``claims.jsonl`` cannot express. Without
    it, a no-claim source has no row, so it is re-extracted (a wasted LLM call)
    on every subsequent run. Missing/unreadable ledger -> empty set.
    """
    path = _extracted_sources_path(topic_dir)
    if not path.exists():
        return set[str]()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set[str]()
    if not isinstance(data, list):
        return set[str]()
    return {str(s) for s in cast("list[object]", data)}


def record_extracted_sources(topic_dir: Path, source_ids: Iterable[str]) -> None:
    """Merge ``source_ids`` into the extracted-sources ledger (idempotent)."""
    new = {str(s) for s in source_ids}
    if not new:
        return
    merged = read_extracted_sources(topic_dir) | new
    path = _extracted_sources_path(topic_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sorted(merged), ensure_ascii=False, indent=2), encoding="utf-8")


def append_claims(topic_dir: Path, claims: list[Claim]) -> Path:
    """Append claim records to ``claims.jsonl``, creating directories as needed.

    Append-only: this file is the audit trail of what the LLM produced on which
    insights and when. Never edited or overwritten.
    """
    path = claims_jsonl_path(topic_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as f:
        for claim in claims:
            f.write(json.dumps(claim.to_jsonl_row(), ensure_ascii=False) + "\n")
    return path


def read_claims(topic_dir: Path) -> list[Claim]:
    """Read all claims from ``claims.jsonl``, or empty list if missing.

    Malformed rows are skipped (logged by the caller's context) rather than
    failing the read, so one bad line cannot block synthesis.
    """
    path = claims_jsonl_path(topic_dir)
    if not path.exists():
        return []
    claims: list[Claim] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            claims.append(Claim.from_jsonl_row(json.loads(line)))
        except (KeyError, ValueError, TypeError, json.JSONDecodeError):
            # TypeError covers a line that is valid JSON but not an object
            # (e.g. `42` or `[1,2]` from a truncated/edited append), where
            # from_jsonl_row's row["..."] would otherwise raise.
            continue
    return claims


def _read_rows(topic_dir: Path) -> list[dict[str, Any]]:
    path = claims_jsonl_path(topic_dir)
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        # Keep only object rows so the typed return holds and downstream
        # ``"source_id" in row`` / ``row[...]`` never hit a non-dict line that
        # was valid JSON but a list/scalar (a truncated or hand-edited append).
        if isinstance(obj, dict):
            rows.append(cast("dict[str, Any]", obj))
    return rows


def already_extracted_source_ids(topic_dir: Path) -> set[str]:
    """Return the set of source_ids already present in ``claims.jsonl``.

    Used by the pipeline to skip insights whose claims were already extracted,
    keeping refresh cheap (no LLM call for unchanged sources).
    """
    return {row["source_id"] for row in _read_rows(topic_dir) if "source_id" in row}

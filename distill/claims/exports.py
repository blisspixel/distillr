"""The per-topic ``claims.jsonl`` append-only store.

Unlike the concept layer -- where ``mentions.jsonl`` is the raw log and
``concepts.jsonl`` is a separate merged rollup -- a claim is already the unit
the synthesis pass consumes, so ``claims.jsonl`` is both the append-only audit
trail and the canonical claim set. One row per extracted claim, never edited
or overwritten; the pipeline re-reads the whole file on synthesis.

Stored under ``<topic_dir>/.claims/claims.jsonl`` (dot-prefixed so the shared
``library.insights.discover_insights`` walk skips it).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from distill.claims.records import Claim

__all__ = [
    "already_extracted_source_ids",
    "append_claims",
    "claims_jsonl_path",
    "read_claims",
]


def claims_jsonl_path(topic_dir: Path) -> Path:
    """Return the path to the per-topic ``claims.jsonl`` append-only store."""
    return topic_dir / ".claims" / "claims.jsonl"


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
        except (KeyError, ValueError, json.JSONDecodeError):
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
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def already_extracted_source_ids(topic_dir: Path) -> set[str]:
    """Return the set of source_ids already present in ``claims.jsonl``.

    Used by the pipeline to skip insights whose claims were already extracted,
    keeping refresh cheap (no LLM call for unchanged sources).
    """
    return {row["source_id"] for row in _read_rows(topic_dir) if "source_id" in row}

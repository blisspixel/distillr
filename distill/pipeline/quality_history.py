# pyright: strict
"""Audit adapter and persistence for the corpus-quality trend (thread #9).

Bridges the audit report to the pure ``quality_trend`` primitives: rolls an
``AuditReport`` into a ``QualitySnapshot``, and appends/loads the per-topic
append-only snapshot history under ``<topic>/.distill/quality-history.jsonl``.

Kept out of ``quality_trend`` so that stays a pure value module, and out of
``audit`` so that large module does not grow further. Deterministic and
rule-owned (invariant #6).
"""

from __future__ import annotations

import json
from pathlib import Path

from distill.jsonl import (
    JsonlIntegrityError,
    append_jsonl_lines_locked,
    jsonl_append_lock,
    read_jsonl_objects_strict,
)
from distill.pipeline.audit_records import AuditReport
from distill.pipeline.quality_trend import QualitySnapshot, parse_quality_snapshot

__all__ = [
    "append_quality_snapshot",
    "load_last_quality_snapshot",
    "quality_snapshot_from_report",
]

_MAX_QUALITY_HISTORY_BYTES = 8 * 1024 * 1024
_MAX_QUALITY_HISTORY_ROWS = 10_000
_MAX_QUALITY_ROW_BYTES = 64 * 1024


def quality_snapshot_from_report(report: AuditReport, *, generated_at: str) -> QualitySnapshot:
    """Roll one audit report's quality signals into a QualitySnapshot.

    Counts insights and synthesis artifacts together: clean = verified clean,
    flagged = checked-but-not-clean, unchecked = never checked. The "No major
    research gaps" placeholder is not counted as a gap.
    """
    verify = report.verify
    verified_clean = verify.clean + verify.synthesis_clean
    flagged = (verify.checked - verify.clean) + (verify.synthesis_checked - verify.synthesis_clean)
    unchecked = verify.never_checked + verify.synthesis_never_checked
    real_gaps = sum(1 for gap in report.gaps if "No major research gaps" not in gap)
    return QualitySnapshot(
        generated_at=generated_at,
        verified_clean=verified_clean,
        flagged=flagged,
        unchecked=unchecked,
        stale=len(report.staleness.stale),
        contested=len(report.contested),
        gaps=real_gaps,
        total_artifacts=verify.insights_total + verify.synthesis_total,
    )


def _history_path(topic_dir: Path) -> Path:
    return topic_dir / ".distill" / "quality-history.jsonl"


def load_last_quality_snapshot(topic_dir: Path) -> QualitySnapshot | None:
    """Return the most recent fully validated snapshot, or None when missing.

    Corrupt, unsafe, oversized, or schema-invalid history raises an exact-path
    ``JsonlIntegrityError`` so an operator cannot mistake damaged state for a
    fresh baseline.
    """
    return _load_last_quality_snapshot_path(_history_path(topic_dir), topic_dir)


def _load_last_quality_snapshot_path(path: Path, confinement_root: Path) -> QualitySnapshot | None:
    """Validate an entire quality history and return its final row."""

    rows = read_jsonl_objects_strict(
        path,
        max_file_bytes=_MAX_QUALITY_HISTORY_BYTES,
        max_row_bytes=_MAX_QUALITY_ROW_BYTES,
        max_rows=_MAX_QUALITY_HISTORY_ROWS,
        confinement_root=confinement_root,
    )
    snapshots: list[QualitySnapshot] = []
    for index, row in enumerate(rows, 1):
        snapshot = parse_quality_snapshot(row)
        if snapshot is None:
            raise JsonlIntegrityError(path, f"row {index} violates the QualitySnapshot schema")
        snapshots.append(snapshot)
    return snapshots[-1] if snapshots else None


def append_quality_snapshot(topic_dir: Path, snapshot: QualitySnapshot) -> None:
    """Durably append one schema-valid snapshot to the topic history."""
    path = _history_path(topic_dir)
    row = snapshot.to_dict()
    if parse_quality_snapshot(row) != snapshot:
        raise ValueError(
            "Quality snapshot must contain a valid ISO timestamp and nonnegative counts"
        )
    line = json.dumps(row, ensure_ascii=False, allow_nan=False)
    with jsonl_append_lock(path, confinement_root=topic_dir):
        # Validate existing history under the same cooperating-writer lock used
        # for append. A caller cannot extend corrupt state even when it bypasses
        # the public audit flow's preceding load.
        _load_last_quality_snapshot_path(path, topic_dir)
        append_jsonl_lines_locked(
            path,
            [line],
            durable=True,
            confinement_root=topic_dir,
        )

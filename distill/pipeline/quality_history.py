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

from distill.pipeline.audit_records import AuditReport
from distill.pipeline.quality_trend import QualitySnapshot, parse_quality_snapshot

__all__ = [
    "append_quality_snapshot",
    "load_last_quality_snapshot",
    "quality_snapshot_from_report",
]


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
    """Return the most recent usable persisted snapshot, or None.

    A missing, unreadable, or malformed history degrades to None (treated as "no
    prior snapshot") rather than crashing the audit.
    """
    try:
        raw = _history_path(topic_dir).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    for line in reversed(raw.splitlines()):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            data = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        snapshot = parse_quality_snapshot(data)
        if snapshot is not None:
            return snapshot
    return None


def append_quality_snapshot(topic_dir: Path, snapshot: QualitySnapshot) -> None:
    """Append one snapshot to the topic's append-only quality history."""
    path = _history_path(topic_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(snapshot.to_dict()) + "\n")

# pyright: strict
"""Deterministic corpus-quality trend - the compounding evidence surface.

``distill audit`` measures a topic's corpus quality at a point in time and
``distill trends`` measures growth (how many sources were added). Neither shows
whether quality *compounds* - whether the corpus gets better over refreshes,
which is distillr's central promise. This module snapshots the audit's quality
signals and renders the delta between the current run and the previous one, so a
rising verified-clean rate with falling flagged/stale/gaps counts becomes visible
evidence rather than a claim.

Rule-owned and deterministic (invariant #6): Python computes the numbers from
signals the audit already produced; no model judgment enters here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import cast

__all__ = [
    "QUALITY_SNAPSHOT_VERSION",
    "QualitySnapshot",
    "parse_quality_snapshot",
    "render_quality_trend",
]

QUALITY_SNAPSHOT_VERSION = "quality-snapshot.v1"


@dataclass(frozen=True, slots=True)
class QualitySnapshot:
    """A point-in-time rollup of a topic's corpus-quality signals."""

    generated_at: str
    verified_clean: int
    flagged: int
    unchecked: int
    stale: int
    contested: int
    gaps: int
    total_artifacts: int

    @property
    def verify_eligible(self) -> int:
        """Artifacts the verify gate can rule on (clean + flagged + unchecked)."""
        return self.verified_clean + self.flagged + self.unchecked

    @property
    def verified_rate(self) -> float:
        """Fraction of verify-eligible artifacts that are verified clean (0..1)."""
        eligible = self.verify_eligible
        return self.verified_clean / eligible if eligible else 0.0

    def to_dict(self) -> dict[str, object]:
        return {
            "version": QUALITY_SNAPSHOT_VERSION,
            "generated_at": self.generated_at,
            "verified_clean": self.verified_clean,
            "flagged": self.flagged,
            "unchecked": self.unchecked,
            "stale": self.stale,
            "contested": self.contested,
            "gaps": self.gaps,
            "total_artifacts": self.total_artifacts,
        }


_COUNT_FIELDS = (
    "verified_clean",
    "flagged",
    "unchecked",
    "stale",
    "contested",
    "gaps",
    "total_artifacts",
)


def _is_iso_timestamp(value: object) -> bool:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        return False
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        datetime.fromisoformat(candidate)
    except ValueError:
        return False
    return True


def parse_quality_snapshot(data: object) -> QualitySnapshot | None:
    """Strictly parse one versioned persisted snapshot, or return None.

    Every count must be an actual non-negative integer, not a bool or coercible
    string. This keeps corrupted trend state from being silently rendered as a
    clean zero baseline.
    """
    if not isinstance(data, dict):
        return None
    record = cast("dict[str, object]", data)
    if record.get("version") != QUALITY_SNAPSHOT_VERSION:
        return None
    generated_at = record.get("generated_at")
    if not _is_iso_timestamp(generated_at):
        return None
    counts: dict[str, int] = {}
    for field in _COUNT_FIELDS:
        value = record.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            return None
        counts[field] = value
    if not isinstance(generated_at, str):
        return None
    return QualitySnapshot(
        generated_at=generated_at,
        verified_clean=counts["verified_clean"],
        flagged=counts["flagged"],
        unchecked=counts["unchecked"],
        stale=counts["stale"],
        contested=counts["contested"],
        gaps=counts["gaps"],
        total_artifacts=counts["total_artifacts"],
    )


def _count_delta(current: int, previous: int) -> str:
    diff = current - previous
    if diff == 0:
        return "no change"
    return f"+{diff}" if diff > 0 else str(diff)


def render_quality_trend(current: QualitySnapshot, previous: QualitySnapshot | None) -> list[str]:
    """Render the "Corpus Quality Trend" section as markdown lines.

    With no prior snapshot the section records a baseline; with a prior snapshot
    it shows the deltas and states the compounding reading (a rising verified
    rate with falling flagged/stale/gaps).
    """
    rate = f"{current.verified_rate * 100:.0f}%"
    lines = ["## Corpus Quality Trend", ""]
    if previous is None:
        lines.extend(
            [
                f"- Verified-clean rate: {rate} of {current.verify_eligible} "
                "verify-eligible artifact(s).",
                f"- Flagged {current.flagged}, unchecked {current.unchecked}, "
                f"stale {current.stale}, contested {current.contested}, gaps {current.gaps}.",
                "- Baseline recorded; no prior snapshot to compare against yet.",
                "",
            ]
        )
        return lines
    rate_pp = (current.verified_rate - previous.verified_rate) * 100
    if abs(rate_pp) < 0.5:
        rate_delta = "no change"
    else:
        rate_delta = f"+{rate_pp:.0f}pp" if rate_pp > 0 else f"{rate_pp:.0f}pp"
    since = previous.generated_at[:10]
    lines.extend(
        [
            f"- Verified-clean rate: {rate} ({rate_delta} since {since}).",
            f"- Flagged {current.flagged} ({_count_delta(current.flagged, previous.flagged)}), "
            f"stale {current.stale} ({_count_delta(current.stale, previous.stale)}), "
            f"gaps {current.gaps} ({_count_delta(current.gaps, previous.gaps)}), "
            f"contested {current.contested} "
            f"({_count_delta(current.contested, previous.contested)}).",
            "- Compounding reading: a rising verified-clean rate with falling "
            "flagged, stale, and gap counts means the corpus is getting more "
            "trustworthy over refreshes, not just larger.",
            "",
        ]
    )
    return lines

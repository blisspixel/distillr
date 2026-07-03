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


def _int(value: object) -> int:
    """Coerce a persisted field to a non-negative int, else 0 (parse-don't-crash)."""
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return max(value, 0)
    return 0


def parse_quality_snapshot(data: object) -> QualitySnapshot | None:
    """Parse one persisted snapshot record into a QualitySnapshot, or None.

    Returns None for anything that is not a mapping with a usable timestamp, so a
    malformed or truncated history line degrades to "no prior snapshot" rather
    than crashing the audit.
    """
    if not isinstance(data, dict):
        return None
    record = cast("dict[str, object]", data)
    generated_at = record.get("generated_at")
    if not isinstance(generated_at, str) or not generated_at.strip():
        return None
    return QualitySnapshot(
        generated_at=generated_at,
        verified_clean=_int(record.get("verified_clean")),
        flagged=_int(record.get("flagged")),
        unchecked=_int(record.get("unchecked")),
        stale=_int(record.get("stale")),
        contested=_int(record.get("contested")),
        gaps=_int(record.get("gaps")),
        total_artifacts=_int(record.get("total_artifacts")),
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

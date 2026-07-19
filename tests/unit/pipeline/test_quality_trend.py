"""Tests for the deterministic corpus-quality trend surface."""

from __future__ import annotations

from distill.pipeline.quality_trend import (
    QUALITY_SNAPSHOT_VERSION,
    QualitySnapshot,
    parse_quality_snapshot,
    render_quality_trend,
)


def _snapshot(
    *,
    generated_at: str = "2026-07-03T00:00:00",
    verified_clean: int = 8,
    flagged: int = 1,
    unchecked: int = 1,
    stale: int = 0,
    contested: int = 0,
    gaps: int = 0,
    total_artifacts: int = 10,
) -> QualitySnapshot:
    return QualitySnapshot(
        generated_at=generated_at,
        verified_clean=verified_clean,
        flagged=flagged,
        unchecked=unchecked,
        stale=stale,
        contested=contested,
        gaps=gaps,
        total_artifacts=total_artifacts,
    )


def test_verified_rate_and_eligible():
    snap = _snapshot(verified_clean=8, flagged=1, unchecked=1)
    assert snap.verify_eligible == 10
    assert snap.verified_rate == 0.8


def test_verified_rate_zero_when_nothing_eligible():
    snap = _snapshot(verified_clean=0, flagged=0, unchecked=0, total_artifacts=0)
    assert snap.verified_rate == 0.0


def test_to_dict_round_trips_through_parse():
    snap = _snapshot()
    assert parse_quality_snapshot(snap.to_dict()) == snap


def test_to_dict_carries_version():
    assert _snapshot().to_dict()["version"] == QUALITY_SNAPSHOT_VERSION


def test_parse_rejects_non_mapping_and_blank_timestamp():
    assert parse_quality_snapshot(["not", "a", "dict"]) is None
    assert parse_quality_snapshot({"generated_at": "  "}) is None
    assert parse_quality_snapshot({"verified_clean": 3}) is None  # no timestamp


def test_parse_rejects_missing_wrong_version_and_invalid_timestamp():
    row = _snapshot().to_dict()
    for version in (None, "quality-snapshot.v0", 1):
        candidate = dict(row)
        candidate["version"] = version
        assert parse_quality_snapshot(candidate) is None

    for timestamp in ("", " 2026-07-03T00:00:00", "not-a-time"):
        candidate = dict(row)
        candidate["generated_at"] = timestamp
        assert parse_quality_snapshot(candidate) is None


def test_parse_rejects_missing_or_non_exact_nonnegative_counts():
    row = _snapshot().to_dict()
    for value in (None, True, "3", -1, 1.0):
        candidate = dict(row)
        candidate["flagged"] = value
        assert parse_quality_snapshot(candidate) is None


def test_render_baseline_when_no_previous():
    text = "\n".join(render_quality_trend(_snapshot(), None))
    assert "## Corpus Quality Trend" in text
    assert "Baseline recorded" in text
    assert "80%" in text  # verified-clean rate
    assert "pp" not in text  # no delta rendered on a baseline


def test_render_trend_shows_improvement_deltas():
    previous = _snapshot(verified_clean=5, flagged=4, unchecked=1, stale=6, gaps=3)
    current = _snapshot(verified_clean=9, flagged=1, unchecked=0, stale=0, gaps=1)
    text = "\n".join(render_quality_trend(current, previous))
    assert "90%" in text  # rate rose 50% -> 90%
    assert "+40pp" in text
    assert "Flagged 1 (-3)" in text  # improvements render as negative deltas
    assert "stale 0 (-6)" in text
    assert "gaps 1 (-2)" in text
    assert "compounding" in text.lower()


def test_render_trend_reports_no_change_for_identical_snapshots():
    snap = _snapshot()
    text = "\n".join(render_quality_trend(snap, snap))
    # Identical snapshots: the rate and every count delta read "no change".
    assert text.count("no change") >= 4

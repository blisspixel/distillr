"""Tests for per-source rigor thresholds (0.9.4 calibration)."""

from distill.pipeline.discovery import (
    PAPER_RIGOR_THRESHOLDS,
    RIGOR_LEVELS_WITH_OFF,
    RIGOR_THRESHOLDS,
    VIDEO_RIGOR_THRESHOLDS,
    source_rigor_threshold,
)


def test_per_source_tables_are_distinct_and_ordered():
    for table in (RIGOR_THRESHOLDS, PAPER_RIGOR_THRESHOLDS, VIDEO_RIGOR_THRESHOLDS):
        assert table["strict"] > table["balanced"] > table["loose"]
    # discover is the strictest gate; single-source rankers sit a notch lower.
    assert RIGOR_THRESHOLDS["balanced"] >= PAPER_RIGOR_THRESHOLDS["balanced"]
    assert PAPER_RIGOR_THRESHOLDS["balanced"] >= VIDEO_RIGOR_THRESHOLDS["balanced"]


def test_source_rigor_threshold_dispatches_by_source():
    assert source_rigor_threshold("discover", "strict") == RIGOR_THRESHOLDS["strict"]
    assert source_rigor_threshold("paper", "balanced") == PAPER_RIGOR_THRESHOLDS["balanced"]
    assert source_rigor_threshold("video", "loose") == VIDEO_RIGOR_THRESHOLDS["loose"]


def test_source_rigor_threshold_falls_back():
    # Unknown source -> discover table; unknown level -> the table's balanced.
    assert source_rigor_threshold("mystery", "strict") == RIGOR_THRESHOLDS["strict"]
    assert source_rigor_threshold("paper", "nonsense") == PAPER_RIGOR_THRESHOLDS["balanced"]


def test_rigor_levels_with_off_includes_off():
    assert "off" in RIGOR_LEVELS_WITH_OFF
    assert {"strict", "balanced", "loose"}.issubset(set(RIGOR_LEVELS_WITH_OFF))

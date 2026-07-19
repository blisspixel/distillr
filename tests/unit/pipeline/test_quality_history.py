"""Tests for the audit adapter and persistence of the corpus-quality trend."""

from __future__ import annotations

from pathlib import Path

import pytest

from distill.jsonl import JsonlIntegrityError
from distill.pipeline.audit import write_audit_artifact
from distill.pipeline.audit_records import AuditReport, VerifyRollup
from distill.pipeline.quality_history import (
    append_quality_snapshot,
    load_last_quality_snapshot,
    quality_snapshot_from_report,
)
from distill.pipeline.quality_trend import QualitySnapshot


def _raise_oserror(*args: object, **kwargs: object) -> None:
    raise OSError("simulated history write failure")


def _report(gaps: list[str] | None = None, **verify_kw: int) -> AuditReport:
    verify = VerifyRollup(
        insights_total=verify_kw.get("insights_total", 10),
        checked=verify_kw.get("checked", 9),
        clean=verify_kw.get("clean", 8),
        synthesis_total=verify_kw.get("synthesis_total", 2),
        synthesis_checked=verify_kw.get("synthesis_checked", 2),
        synthesis_clean=verify_kw.get("synthesis_clean", 2),
    )
    return AuditReport(
        topic="tkg",
        health_warnings=[],
        contested=[],
        broken_links=[],
        gaps=gaps if gaps is not None else ["No major research gaps identified."],
        next_actions=[],
        verify=verify,
    )


def test_snapshot_from_report_maps_verify_and_gaps():
    snap = quality_snapshot_from_report(_report(), generated_at="2026-07-03T00:00:00")
    # clean 8 + synth-clean 2 = 10; flagged (9-8)+(2-2)=1; unchecked (10-9)+(2-2)=1
    assert (snap.verified_clean, snap.flagged, snap.unchecked) == (10, 1, 1)
    assert snap.total_artifacts == 12
    assert snap.gaps == 0  # the "No major research gaps" placeholder is not a gap


def test_snapshot_counts_only_real_gaps():
    snap = quality_snapshot_from_report(
        _report(gaps=["Gap A", "Gap B"]), generated_at="2026-07-03T00:00:00"
    )
    assert snap.gaps == 2


def test_persistence_round_trip_returns_last(tmp_path: Path):
    older = QualitySnapshot("2026-07-01T00:00:00", 5, 2, 3, 1, 0, 2, 10)
    newer = QualitySnapshot("2026-07-03T00:00:00", 9, 0, 1, 0, 0, 0, 10)
    append_quality_snapshot(tmp_path, older)
    append_quality_snapshot(tmp_path, newer)
    assert load_last_quality_snapshot(tmp_path) == newer


def test_load_missing_history_returns_none(tmp_path: Path):
    assert load_last_quality_snapshot(tmp_path) is None


def test_load_rejects_malformed_tail_instead_of_hiding_damage(tmp_path: Path):
    valid = QualitySnapshot("2026-07-01T00:00:00", 5, 2, 3, 1, 0, 2, 10)
    append_quality_snapshot(tmp_path, valid)
    history = tmp_path / ".distill" / "quality-history.jsonl"
    history.write_text(
        history.read_text(encoding="utf-8") + "{not json\n" + '{"no":"timestamp"}\n',
        encoding="utf-8",
    )
    with pytest.raises(JsonlIntegrityError) as caught:
        load_last_quality_snapshot(tmp_path)

    assert str(history) in str(caught.value)


def test_load_rejects_schema_invalid_row(tmp_path: Path):
    history = tmp_path / ".distill" / "quality-history.jsonl"
    history.parent.mkdir(parents=True)
    history.write_text('{"version":"quality-snapshot.v1","generated_at":"bad"}\n', encoding="utf-8")

    with pytest.raises(JsonlIntegrityError, match="QualitySnapshot schema"):
        load_last_quality_snapshot(tmp_path)


def test_append_rejects_invalid_snapshot_before_touching_history(tmp_path: Path):
    invalid = QualitySnapshot("not-a-time", 1, 0, 0, 0, 0, 0, 1)

    with pytest.raises(ValueError, match="valid ISO timestamp"):
        append_quality_snapshot(tmp_path, invalid)

    assert not (tmp_path / ".distill" / "quality-history.jsonl").exists()


def test_append_rejects_existing_corruption_without_mutating_history(tmp_path: Path):
    history = tmp_path / ".distill" / "quality-history.jsonl"
    history.parent.mkdir(parents=True)
    history.write_text("not-json\n", encoding="utf-8")
    before = history.read_bytes()

    with pytest.raises(JsonlIntegrityError):
        append_quality_snapshot(
            tmp_path,
            QualitySnapshot("2026-07-03T00:00:00", 1, 0, 0, 0, 0, 0, 1),
        )

    assert history.read_bytes() == before


def test_write_audit_artifact_records_baseline_then_trend(tmp_path: Path):
    first = write_audit_artifact(tmp_path, _report(), now_iso="2026-07-03T00:00:00")
    first_text = first.read_text(encoding="utf-8")
    assert "## Corpus Quality Trend" in first_text
    assert "Baseline recorded" in first_text
    persisted = load_last_quality_snapshot(tmp_path)
    assert persisted is not None
    assert persisted.verified_clean == 10

    # A cleaner corpus on the next run: the report now shows a delta, not a baseline.
    second = write_audit_artifact(
        tmp_path, _report(checked=10, clean=10), now_iso="2026-07-04T00:00:00"
    )
    second_text = second.read_text(encoding="utf-8")
    assert "Baseline recorded" not in second_text
    assert "100%" in second_text
    assert "pp" in second_text  # a rate delta rendered


def test_write_audit_artifact_survives_history_write_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """A quality-history write failure is logged and never blocks the audit report."""
    monkeypatch.setattr("distill.pipeline.audit.append_quality_snapshot", _raise_oserror)

    path = write_audit_artifact(tmp_path, _report(), now_iso="2026-07-03T00:00:00")

    assert path.exists()  # the report is still written despite the history-write failure
    assert "## Corpus Quality Trend" in path.read_text(encoding="utf-8")


def test_write_audit_artifact_reports_corrupt_history_without_inventing_baseline(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
):
    append_quality_snapshot(
        tmp_path,
        QualitySnapshot("2026-07-01T00:00:00", 5, 2, 3, 1, 0, 2, 10),
    )
    history = tmp_path / ".distill" / "quality-history.jsonl"
    history.write_text(
        history.read_text(encoding="utf-8") + "{malformed newest row\n",
        encoding="utf-8",
    )
    before = history.read_bytes()

    with caplog.at_level("WARNING", logger="distill.pipeline.audit"):
        path = write_audit_artifact(tmp_path, _report(), now_iso="2026-07-03T00:00:00")

    text = path.read_text(encoding="utf-8")
    assert path.exists()
    assert "Trend unavailable" in text
    assert str(history) in text
    assert "No baseline or delta was inferred" in text
    assert "Baseline recorded" not in text
    assert history.read_bytes() == before
    assert str(history) in caplog.text

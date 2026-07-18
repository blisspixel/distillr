"""Tests for the estimator accountability rollup (estimate-vs-actual error)."""

from __future__ import annotations

from distill.pipeline import cost_history
from distill.pipeline.cost_history import (
    read_confined_cost_log_rows,
    read_cost_log_rows,
    scan_confined_cost_log,
    scan_cost_log,
)
from distill.pipeline.costs import estimator_accuracy, projected_next_run_cost


def _row(est, act, command="papers"):
    return {"command": command, "estimated_cost": est, "actual_cost": act}


class TestEstimatorAccuracy:
    def test_none_without_comparable_runs(self):
        assert estimator_accuracy([]) is None
        assert estimator_accuracy([{"command": "papers", "actual_cost": 0.5}]) is None
        assert estimator_accuracy([_row(None, 0.5), _row(0.5, 0)]) is None

    def test_preview_rows_excluded(self):
        rows = [_row(1.0, 0.5, command="discover_preview"), _row(0.5, 0.5)]
        result = estimator_accuracy(rows)
        assert result is not None
        assert result["runs_compared"] == 1
        assert result["median_abs_pct_error"] == 0.0

    def test_systematic_overestimate_bias_is_signed(self):
        # Estimates consistently 50% above actuals.
        rows = [_row(1.5, 1.0), _row(0.75, 0.5), _row(3.0, 2.0)]
        result = estimator_accuracy(rows)
        assert result is not None
        assert result["median_signed_pct_error"] == 50.0  # positive = overestimates
        assert result["median_abs_pct_error"] == 50.0

    def test_underestimate_bias_is_negative(self):
        rows = [_row(0.5, 1.0), _row(0.25, 0.5)]
        result = estimator_accuracy(rows)
        assert result is not None
        assert result["median_signed_pct_error"] == -50.0

    def test_median_resists_one_anomalous_run(self):
        # Nine accurate runs, one wildly wrong: median holds near zero.
        rows = [_row(1.0, 1.0)] * 9 + [_row(50.0, 1.0)]
        result = estimator_accuracy(rows)
        assert result is not None
        assert result["median_abs_pct_error"] == 0.0

    def test_recent_window_reflects_improvement(self):
        # Old runs were 100% off; the last ten are exact -- the trend shows it.
        rows = [_row(2.0, 1.0)] * 5 + [_row(1.0, 1.0)] * 10
        result = estimator_accuracy(rows)
        assert result is not None
        assert result["recent10_median_abs_pct_error"] == 0.0
        assert result["median_abs_pct_error"] == 0.0  # 10 exact of 15 -> median 0
        assert result["runs_compared"] == 15

    def test_median_single_and_odd_length(self):
        # Exercises the n % 2 branch in _median for odd counts.
        rows = [_row(1.0, 1.0)]
        result = estimator_accuracy(rows)
        assert result is not None
        assert result["median_abs_pct_error"] == 0.0

        rows3 = [_row(1.1, 1.0), _row(1.2, 1.0), _row(0.9, 1.0)]
        result3 = estimator_accuracy(rows3)
        assert result3 is not None
        # median abs around 10-20%
        assert result3["median_abs_pct_error"] > 0

    def test_non_finite_and_boolean_costs_are_not_metrics(self):
        invalid = [
            _row(float("nan"), 1.0),
            _row(1.0, float("inf")),
            _row(True, 1.0),
            _row(1.0, False),
        ]

        assert estimator_accuracy(invalid) is None
        assert (
            projected_next_run_cost(
                [_row(1.0, float("nan")), _row(1.0, float("inf")), _row(1.0, True)]
            )
            == 0.0
        )

    def test_integer_too_large_for_float_is_not_a_metric(self):
        assert estimator_accuracy([_row(10**400, 1.0)]) is None


def test_cost_log_reader_skips_oversized_nonfinite_and_boolean_rows(tmp_path):
    log = tmp_path / "cost_log.jsonl"
    log.write_text(
        "\n".join(
            [
                '{"actual_cost": ' + "9" * 5_000 + "}",
                '{"actual_cost": NaN}',
                '{"actual_cost": Infinity}',
                '{"actual_cost": 1e999}',
                '{"actual_cost": true}',
                '{"actual_cost": 1.25, "command": "papers"}',
            ]
        ),
        encoding="utf-8",
    )

    assert read_cost_log_rows(log) == [{"actual_cost": 1.25, "command": "papers"}]


def test_confined_cost_log_reader_fails_closed_on_limits_and_missing_file(tmp_path):
    root = tmp_path / "library"
    root.mkdir()
    missing = root / ".distill" / "cost_log.jsonl"

    assert read_confined_cost_log_rows(missing, root, limit=0) == []
    assert read_confined_cost_log_rows(missing, root, limit=1) == []
    assert read_cost_log_rows(missing, limit=0, root=root) == []


def test_cost_log_scan_reports_malformed_and_omitted_evidence(tmp_path):
    log = tmp_path / "cost_log.jsonl"
    log.write_bytes(
        b'{"actual_cost":1}\n{"actual_cost":true}\nnot-json\n{"actual_cost":2}\n{"actual_cost":3}\n'
    )

    scan = scan_cost_log(log, limit=2)

    assert [row["actual_cost"] for row in scan.rows] == [2, 3]
    assert scan.coverage() == {
        "complete": False,
        "valid_rows": 3,
        "retained_rows": 2,
        "malformed_rows": 2,
        "omitted_valid_rows": 1,
        "invalid_timestamp_rows": 3,
        "read_error": False,
    }


def test_cost_log_scan_recovers_after_oversized_and_invalid_utf8_rows(tmp_path, monkeypatch):
    monkeypatch.setattr(cost_history, "_MAX_COST_LOG_ROW_BYTES", 20)
    log = tmp_path / "cost_log.jsonl"
    log.write_bytes(b"x" * 24 + b"\n\xff\n" + b'{"actual_cost":4}\n')

    scan = scan_cost_log(log)

    assert scan.rows == ({"actual_cost": 4},)
    assert scan.malformed_rows == 2
    assert not scan.complete


def test_confined_cost_log_scan_marks_existing_unsafe_or_oversized_file_unreadable(
    tmp_path, monkeypatch
):
    root = tmp_path / "library"
    root.mkdir()
    log = root / "cost_log.jsonl"
    log.write_text('{"actual_cost":1}\n', encoding="utf-8")
    monkeypatch.setattr(cost_history, "_MAX_COST_LOG_BYTES", 4)

    scan = scan_confined_cost_log(log, root)

    assert scan.rows == ()
    assert scan.coverage()["read_error"] is True
    assert not scan.complete


def test_missing_cost_log_scan_is_complete_empty_evidence(tmp_path):
    log = tmp_path / "cost_log.jsonl"

    assert scan_cost_log(log).coverage() == {
        "complete": True,
        "valid_rows": 0,
        "retained_rows": 0,
        "malformed_rows": 0,
        "omitted_valid_rows": 0,
        "invalid_timestamp_rows": 0,
        "read_error": False,
    }


def test_cost_log_scan_rejects_invalid_monetary_values_and_flags_missing_timestamps(tmp_path):
    log = tmp_path / "cost_log.jsonl"
    log.write_text(
        "\n".join(
            [
                '{"actual_cost":"1.0","timestamp":"2026-07-18T10:00:00"}',
                '{"actual_cost":-1,"timestamp":"2026-07-18T10:00:00"}',
                '{"timestamp":"2026-07-18T10:00:00"}',
                '{"actual_cost":1,"timestamp":"not-a-time"}',
                '{"actual_cost":2}',
            ]
        ),
        encoding="utf-8",
    )

    scan = scan_cost_log(log)

    assert [row["actual_cost"] for row in scan.rows] == [1, 2]
    assert scan.malformed_rows == 3
    assert scan.invalid_timestamp_rows == 2
    assert "2 rows without a valid timestamp" in cost_history.cost_history_integrity_message(
        log, scan
    )


def test_run_summary_estimate_reaches_the_log(tmp_path):
    """The plumbing gap this slice closes: no caller ever passed its estimate,
    so 'logs actual vs estimated' was only half true. RunSummary.estimated_cost
    must land in the cost_log row."""
    import json

    from distill.pipeline.costs import CostTracker, TokenUsage
    from distill.pipeline.summary import RunSummary, VideoResult, display_summary

    tracker = CostTracker()
    tracker.record(
        TokenUsage(prompt_tokens=100, completion_tokens=50, model="grok-4.3", call_type="video")
    )
    summary = RunSummary(command="discover", estimated_cost=0.42)
    summary.add_result(VideoResult(video_id="v1", title="t", success=True))

    display_summary(summary, cost_tracker=tracker, log_dir=tmp_path)

    log = tmp_path / ".distill" / "cost_log.jsonl"
    row = json.loads(log.read_text(encoding="utf-8").strip().splitlines()[-1])
    assert row["estimated_cost"] == 0.42
    assert row["actual_cost"] > 0

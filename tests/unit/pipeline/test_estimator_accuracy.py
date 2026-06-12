"""Tests for the estimator accountability rollup (estimate-vs-actual error)."""

from __future__ import annotations

from distill.pipeline.costs import estimator_accuracy


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

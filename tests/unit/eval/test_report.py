"""Tests for distill.eval.report (deterministic recommendation + confidence)."""

from distill.eval.harness import EvalRow
from distill.eval.report import console_lines, render_markdown, results_log_lines, summarize
from distill.eval.scoring import QualityScore


def _rows(model: str, composites: list[float], cost_each: float, winrate: float | None) -> list:
    return [
        EvalRow(
            workload="paper",
            fixture_id=f"f{i}",
            model=model,
            quality=QualityScore(dimensions=[], composite=c),
            cost=cost_each,
            input_tokens=0,
            output_tokens=0,
            pairwise_winrate=winrate,
        )
        for i, c in enumerate(composites)
    ]


def test_recommends_cheapest_clearing_with_high_confidence():
    rows = _rows("grok-4.3", [0.95, 0.95, 0.95], 0.10, None)  # anchor (no winrate)
    rows += _rows("qwen3.5:27b", [0.90, 0.90, 0.90], 0.0, 0.55)
    summary = summarize(rows, anchor="grok-4.3", threshold=0.90)
    assert summary.recommended == "qwen3.5:27b"
    assert summary.confidence == "high"


def test_tentative_when_worst_fixture_dips_below_bar():
    # mean 0.88 clears bar 0.855, but one fixture at 0.80 is below it.
    rows = _rows("grok-4.3", [0.95, 0.95, 0.95], 0.10, None)
    rows += _rows("local", [0.92, 0.92, 0.80], 0.0, 0.55)
    summary = summarize(rows, anchor="grok-4.3", threshold=0.90)
    assert summary.recommended == "local"
    assert summary.confidence == "tentative"
    assert "worst fixture" in summary.confidence_reason


def test_tentative_when_judge_favors_anchor():
    rows = _rows("grok-4.3", [0.95, 0.95, 0.95], 0.10, None)
    rows += _rows("local", [0.90, 0.90, 0.90], 0.0, 0.30)  # clears on scores, loses to judge
    summary = summarize(rows, anchor="grok-4.3", threshold=0.90)
    assert summary.recommended == "local"
    assert summary.confidence == "tentative"
    assert "judge" in summary.confidence_reason


def test_tentative_when_judge_unavailable():
    # Both have no win-rate (judge failed). A cheaper model that "wins" on the
    # deterministic dims alone must NOT be high-confidence — those metrics are
    # gameable; without a judge it's tentative.
    rows = _rows("grok-4.3", [0.90, 0.90, 0.90], 0.10, None)
    rows += _rows("local", [0.95, 0.95, 0.95], 0.0, None)
    summary = summarize(rows, anchor="grok-4.3", threshold=0.90)
    assert summary.recommended == "local"
    assert summary.confidence == "tentative"
    assert "no signal" in summary.confidence_reason


def test_anchor_recommended_when_nothing_cheaper_clears():
    rows = _rows("grok-4.3", [0.95, 0.95, 0.95], 0.10, None)
    rows += _rows("local", [0.70, 0.70, 0.70], 0.0, 0.40)  # fails the bar
    summary = summarize(rows, anchor="grok-4.3", threshold=0.90)
    assert summary.recommended == "grok-4.3"
    assert summary.confidence == "high"


def _errored(model: str, n: int) -> list:
    return [
        EvalRow(
            workload="paper",
            fixture_id=f"f{i}",
            model=model,
            quality=QualityScore(dimensions=[], composite=0.0),
            cost=0.0,
            input_tokens=0,
            output_tokens=0,
            error="TimeoutError: read timeout",
        )
        for i in range(n)
    ]


def test_errored_model_excluded_from_recommendation_and_counted():
    rows = _rows("grok-4.3", [0.95, 0.95, 0.95], 0.10, None) + _errored("local", 3)
    summary = summarize(rows, anchor="grok-4.3", threshold=0.90)
    local = next(s for s in summary.models if s.model == "local")
    assert local.errors == 3 and local.rows == 0
    assert summary.recommended == "grok-4.3"  # errored model can't be recommended


def test_no_recommendation_when_anchor_all_errored():
    summary = summarize(_errored("grok-4.3", 3), anchor="grok-4.3", threshold=0.90)
    assert summary.recommended is None
    assert "no valid output" in summary.confidence_reason


def test_render_surfaces_anchor_confidence_and_winrate():
    rows = _rows("grok-4.3", [0.95], 0.10, None) + _rows("local", [0.92], 0.0, 0.6)
    summary = summarize(rows, anchor="grok-4.3", threshold=0.90)
    text = "\n".join(console_lines(summary))
    assert "anchor" in text and "recommended" in text.lower()
    md = render_markdown(summary, now_iso="2026-06-01T00:00:00")
    assert "Win-rate vs anchor" in md
    assert "order-randomized" in md
    log = results_log_lines(
        rows, now_iso="2026-06-01T00:00:00", anchor="grok-4.3", judge_model="grok-4.3"
    )
    assert len(log) == 2
    assert '"anchor": "grok-4.3"' in log[0]

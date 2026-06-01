"""Tests for distill.eval.report (deterministic cost x quality recommendation)."""

from distill.eval.harness import EvalRow
from distill.eval.report import console_lines, render_markdown, summarize
from distill.eval.scoring import QualityScore


def _row(model: str, composite: float, cost: float) -> EvalRow:
    return EvalRow(
        workload="paper",
        fixture_id="f",
        model=model,
        quality=QualityScore(
            dimensions=[], deterministic=composite, judge=None, composite=composite
        ),
        cost=cost,
        input_tokens=0,
        output_tokens=0,
    )


def test_recommends_cheapest_model_clearing_the_bar():
    # local is slightly worse but free and clears 0.90 x anchor (0.855).
    rows = [_row("grok-4.3", 0.95, 0.30), _row("qwen3.5:27b", 0.88, 0.0)]
    summary = summarize(rows, threshold=0.90)
    assert summary.anchor == "grok-4.3"
    assert summary.recommended == "qwen3.5:27b"


def test_falls_back_to_anchor_when_nothing_cheaper_clears():
    rows = [_row("grok-4.3", 0.95, 0.30), _row("qwen3.5:27b", 0.70, 0.0)]
    summary = summarize(rows, threshold=0.90)  # bar 0.855; local 0.70 fails
    assert summary.recommended == "grok-4.3"


def test_console_and_markdown_render_recommendation():
    rows = [_row("grok-4.3", 0.95, 0.30), _row("qwen3.5:27b", 0.90, 0.0)]
    summary = summarize(rows, threshold=0.90)
    text = "\n".join(console_lines(summary))
    assert "recommended" in text.lower()
    md = render_markdown(summary, now_iso="2026-06-01T00:00:00")
    assert "qwen3.5:27b" in md
    assert "Recommended" in md
    assert "advisory" in md.lower()


def test_empty_rows_do_not_crash():
    summary = summarize([], threshold=0.9)
    assert summary.recommended is None
    assert summary.models == []

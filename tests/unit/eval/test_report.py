"""Tests for distill.eval.report (deterministic recommendation + confidence)."""

from distill.eval.harness import EvalRow
from distill.eval.report import console_lines, render_markdown, results_log_lines, summarize
from distill.eval.scoring import QualityScore


def _rows(
    model: str,
    composites: list[float],
    cost_each: float,
    winrate: float | None,
    faithfulness: str = "",
) -> list:
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
            faithfulness=faithfulness,
        )
        for i, c in enumerate(composites)
    ]


def test_summarize_no_crash_when_threshold_clears_nothing():
    # threshold > 1.0 means even the anchor cannot clear its own bar; summarize
    # must not crash on min([]). It recommends nothing, tentatively.
    rows = _rows("grok-4.3", [0.95, 0.95, 0.95], 0.10, None)
    rows += _rows("local", [0.90, 0.90, 0.90], 0.0, 0.55)
    summary = summarize(rows, anchor="grok-4.3", threshold=1.5)
    assert summary.recommended is None
    assert summary.confidence == "tentative"
    assert "clears the bar" in summary.confidence_reason


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


def test_judge_vetoes_migration_when_it_favors_anchor():
    # The cheaper model clears the deterministic floor but the judge scores it
    # below the anchor (win-rate 0.30 < floor). Faithfulness holds the veto: the
    # migration is NOT recommended; we stay on the incumbent.
    rows = _rows("grok-4.3", [0.95, 0.95, 0.95], 0.10, None)
    rows += _rows("local", [0.90, 0.90, 0.90], 0.0, 0.30)  # clears scores, loses to judge
    summary = summarize(rows, anchor="grok-4.3", threshold=0.90)
    assert summary.recommended == "grok-4.3"
    assert "did not confirm" in summary.confidence_reason


def test_fail_closed_when_judge_unavailable():
    # A cheaper model "wins" on the gameable deterministic dims but there is NO
    # judge signal. The brittle composite must NOT license a migration on its
    # own (it's blind to faithfulness) — fail closed, recommend the incumbent.
    rows = _rows("grok-4.3", [0.90, 0.90, 0.90], 0.10, None)
    rows += _rows("local", [0.95, 0.95, 0.95], 0.0, None)
    summary = summarize(rows, anchor="grok-4.3", threshold=0.90)
    assert summary.recommended == "grok-4.3"
    assert "no judge signal" in summary.confidence_reason


def test_judge_certifies_migration_when_at_par():
    # Cheaper model clears the floor AND the judge confirms it at par -> migrate.
    rows = _rows("grok-4.3", [0.95, 0.95, 0.95], 0.10, None)
    rows += _rows("local", [0.90, 0.90, 0.90], 0.0, 0.55)
    summary = summarize(rows, anchor="grok-4.3", threshold=0.90)
    assert summary.recommended == "local"
    assert summary.confidence == "high"
    assert "judge confirms" in summary.confidence_reason


def test_faithfulness_vetoes_migration_even_when_pairwise_wins():
    # The cheaper model clears the composite floor AND wins the pairwise judge,
    # but is judged unfaithful on a fixture. Grounding veto: do NOT migrate to
    # output that invents facts, however well it ranks. Stay on the incumbent.
    rows = _rows("grok-4.3", [0.95, 0.95, 0.95], 0.10, None, faithfulness="faithful")
    rows += _rows("local", [0.95, 0.95, 0.95], 0.0, 0.70, faithfulness="unfaithful")
    summary = summarize(rows, anchor="grok-4.3", threshold=0.90)
    assert summary.recommended == "grok-4.3"
    assert "unfaithful" in summary.confidence_reason
    local = next(s for s in summary.models if s.model == "local")
    assert local.unfaithful_fixtures == 3


def test_faithful_candidate_at_par_migrates():
    # Faithful AND pairwise-confirmed at par -> migrate, high confidence.
    rows = _rows("grok-4.3", [0.95, 0.95, 0.95], 0.10, None, faithfulness="faithful")
    rows += _rows("local", [0.90, 0.90, 0.90], 0.0, 0.55, faithfulness="faithful")
    summary = summarize(rows, anchor="grok-4.3", threshold=0.90)
    assert summary.recommended == "local"
    assert summary.confidence == "high"


def test_less_faithful_than_anchor_migrates_but_tentative():
    # No outright-unfaithful fixture (clears the binary veto) and pairwise-at-par,
    # but grades less faithful than the anchor on average -> migrate, tentatively,
    # with the caveat surfaced.
    rows = _rows("grok-4.3", [0.95, 0.95, 0.95], 0.10, None, faithfulness="faithful")
    rows += _rows("local", [0.92, 0.92, 0.92], 0.0, 0.55, faithfulness="minor")
    summary = summarize(rows, anchor="grok-4.3", threshold=0.90)
    assert summary.recommended == "local"
    assert summary.confidence == "tentative"
    assert "less faithful" in summary.confidence_reason


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


def test_mixed_workloads_label_as_all():
    rows = _rows("grok-4.3", [0.9], 0.1, None)
    rows += [
        EvalRow(
            workload=w,
            fixture_id=f"{w}-1",
            model="grok-4.3",
            quality=QualityScore(dimensions=[], composite=0.9),
            cost=0.0,
            input_tokens=0,
            output_tokens=0,
        )
        for w in ("video", "site")
    ]
    summary = summarize(rows, anchor="grok-4.3", threshold=0.9)
    assert summary.workload == "all (paper+site+video)"


def test_single_workload_keeps_its_name():
    summary = summarize(_rows("grok-4.3", [0.9], 0.1, None), anchor="grok-4.3", threshold=0.9)
    assert summary.workload == "paper"


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

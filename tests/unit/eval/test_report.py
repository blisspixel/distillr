"""Tests for distill.eval.report (deterministic recommendation + confidence)."""

import json
from dataclasses import replace

from distill.eval.harness import EvalRow
from distill.eval.report import (
    console_lines,
    render_markdown,
    results_log_lines,
    review_findings,
    summarize,
)
from distill.eval.scoring import QualityScore


def _rows(
    model: str,
    composites: list[float],
    cost_each: float,
    winrate: float | None,
    faithfulness: str = "faithful",
    workload: str = "paper",
    risk_patterns: tuple[str, ...] = (),
) -> list:
    return [
        EvalRow(
            workload=workload,
            fixture_id=f"f{i}",
            model=model,
            quality=QualityScore(dimensions=[], composite=c),
            cost=cost_each,
            input_tokens=0,
            output_tokens=0,
            pairwise_winrate=winrate,
            faithfulness=faithfulness,
            risk_patterns=risk_patterns,
        )
        for i, c in enumerate(composites)
    ]


def test_threshold_is_advisory_not_a_gate():
    # The deterministic composite is no longer a gate: even an absurd composite
    # reference (threshold 1.5) must NOT suppress a judge-certified pick. The
    # model judges decide; the brittle keyword/length heuristic cannot exclude a
    # faithful, at-par candidate (the brittle-proxy fix).
    rows = _rows("grok-4.3", [0.95] * 8, 0.10, None)
    rows += _rows("local", [0.90] * 8, 0.0, 0.55)
    summary = summarize(rows, anchor="grok-4.3", threshold=1.5)
    assert summary.recommended == "local"


def test_recommends_cheapest_clearing_with_high_confidence():
    # Cheapest faithful + at-par candidate migrates. Confidence is "high" (the
    # judges agree); the fixture count rides in the reason, no min-N/bootstrap gate.
    rows = _rows("grok-4.3", [0.95, 0.95, 0.95], 0.10, None)  # anchor (no winrate)
    rows += _rows("qwen3.5:27b", [0.90, 0.90, 0.90], 0.0, 0.55)
    summary = summarize(rows, anchor="grok-4.3", threshold=0.90)
    assert summary.recommended == "qwen3.5:27b"
    assert summary.confidence == "high"
    assert "fixture" in summary.confidence_reason  # sample size stated plainly


def test_composite_does_not_exclude_a_faithful_at_par_candidate():
    # The brittle-rule fix, asserted directly: a candidate with a LOW composite
    # (terse / paraphrase-heavy -> the keyword/length heuristic scores it poorly)
    # is still recommended when it is faithful and the judge confirms it at par.
    # The composite must not veto a judge-approved switch.
    rows = _rows("grok-4.3", [0.95] * 8, 0.10, None, faithfulness="faithful")
    rows += _rows("local", [0.30] * 8, 0.0, 0.60, faithfulness="faithful")  # low composite
    summary = summarize(rows, anchor="grok-4.3", threshold=0.90)
    assert summary.recommended == "local"
    assert summary.confidence == "high"


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


def test_incomplete_faithfulness_evidence_cannot_certify_migration():
    rows = _rows("grok-4.3", [0.95] * 3, 0.10, None)
    candidate = _rows("local", [0.90] * 3, 0.0, 0.60)
    candidate[1] = replace(candidate[1], faithfulness="")
    candidate[2] = replace(candidate[2], faithfulness="unknown")

    summary = summarize(rows + candidate, anchor="grok-4.3")

    assert summary.recommended == "grok-4.3"
    local = next(model for model in summary.models if model.model == "local")
    assert local.faithfulness_fixtures == 1


def test_incomplete_pairwise_evidence_cannot_certify_migration():
    rows = _rows("grok-4.3", [0.95] * 3, 0.10, None)
    candidate = _rows("local", [0.90] * 3, 0.0, 0.60)
    candidate[1] = replace(candidate[1], pairwise_winrate=None)
    candidate[2] = replace(candidate[2], pairwise_winrate=999.0)

    summary = summarize(rows + candidate, anchor="grok-4.3")

    assert summary.recommended == "grok-4.3"
    local = next(model for model in summary.models if model.model == "local")
    assert local.pairwise_fixtures == 1


def test_judge_certifies_migration_when_at_par():
    # Cheaper model clears the floor AND the judge confirms it at par -> migrate.
    rows = _rows("grok-4.3", [0.95] * 8, 0.10, None)
    rows += _rows("local", [0.90] * 8, 0.0, 0.55)
    summary = summarize(rows, anchor="grok-4.3", threshold=0.90)
    assert summary.recommended == "local"
    assert summary.confidence == "high"
    assert "at par" in summary.confidence_reason


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


def test_anchor_not_in_results():
    rows = _rows("local", [0.90] * 3, 0.0, 0.60)
    summary = summarize(rows, anchor="grok-4.3", threshold=0.90)
    assert summary.recommended is None
    assert "anchor 'grok-4.3' not in results" in summary.confidence_reason


def test_console_lines_tags_errors_and_unfaithful():
    # hit the tag branches in console_lines
    from distill.eval.report import EvalSummary, ModelSummary, console_lines

    s = ModelSummary(
        model="local",
        rows=3,
        errors=1,
        unfaithful_fixtures=1,
        mean_composite=0.9,
        min_composite=0.8,
        max_composite=0.95,
        mean_winrate=0.5,
        total_cost=0.0,
        mean_faithfulness=0.5,
    )
    summary = EvalSummary(
        workload="paper",
        models=[s],
        anchor="grok-4.3",
        recommended="local",
        threshold=0.8,
        confidence="high",
        confidence_reason="ok",
    )
    lines = console_lines(summary)
    assert any("[1 err]" in line for line in lines)
    assert any("[1 unfaithful]" in line for line in lines)


def test_faithful_candidate_at_par_migrates():
    # Faithful AND pairwise-confirmed at par, enough fixtures -> migrate, high.
    rows = _rows("grok-4.3", [0.95] * 8, 0.10, None, faithfulness="faithful")
    rows += _rows("local", [0.90] * 8, 0.0, 0.55, faithfulness="faithful")
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


def test_migration_reason_states_the_fixture_count_not_a_bootstrap():
    # The honest replacement for the reverted bootstrap/min-N machinery: a switch
    # is recommended (faithful + at-par) and the reason states the sample size
    # plainly. No statistical theater over a tiny sample.
    rows = _rows("grok-4.3", [0.95, 0.95, 0.95], 0.10, None)
    rows += _rows("local", [0.90, 0.90, 0.90], 0.0, 0.55)
    summary = summarize(rows, anchor="grok-4.3", threshold=0.90)
    assert summary.recommended == "local"
    assert "3 fixture(s)" in summary.confidence_reason
    md = render_markdown(summary, now_iso="2026-06-14T00:00:00")
    assert "no bootstrap" in md.lower()  # the report says so explicitly


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


def test_results_log_preserves_risk_patterns_and_review_finding():
    rows = _rows(
        "local",
        [0.92],
        0.0,
        0.55,
        faithfulness="minor",
        workload="ask",
        risk_patterns=("no_evidence",),
    )

    log = results_log_lines(
        rows, now_iso="2026-06-30T00:00:00", anchor="grok-4.3", judge_model="judge"
    )
    payload = json.loads(log[0])

    assert payload["risk_patterns"] == ["no_evidence"]
    assert payload["review_finding"] == "faithfulness judge found minor support issues"


def test_review_findings_flags_missing_judge_on_risk_fixture():
    rows = _rows(
        "local",
        [0.92],
        0.0,
        None,
        faithfulness="",
        workload="ask",
        risk_patterns=("citation_request_trap",),
    )

    findings = review_findings(rows, anchor="grok-4.3")

    assert len(findings) == 1
    assert findings[0].reason == "risk fixture has no faithfulness judge signal"


def test_render_markdown_surfaces_review_findings():
    rows = _rows(
        "grok-4.3",
        [0.95],
        0.10,
        None,
        faithfulness="faithful",
        workload="ask",
        risk_patterns=("route_disagreement",),
    )
    rows += _rows(
        "local",
        [0.90],
        0.0,
        0.30,
        faithfulness="faithful",
        workload="ask",
        risk_patterns=("route_disagreement",),
    )
    summary = summarize(rows, anchor="grok-4.3", threshold=0.90)

    md = render_markdown(summary, now_iso="2026-06-30T00:00:00", rows=rows)

    assert "## Review Findings" in md
    assert "route_disagreement" in md
    assert "pairwise judge did not certify candidate on route-disagreement fixture" in md

"""Aggregate eval rows into a cost x quality summary + a recommendation.

The recommendation is pure Python aggregation over model-judge signals, in the
order the agentic-balance charter requires (model proposes, Python decides). A
*migration* away from the incumbent anchor must clear three gates; the anchor
itself needs none ("stay put" is the safe default):

1. **Composite floor** (deterministic) — clears ``threshold x anchor``. A cheap,
   key-free guardrail that is admittedly blind to faithfulness and gameable by
   verbose, keyword-stuffed output. Necessary, never sufficient.
2. **Faithfulness floor** (absolute model judge, graded against the source) — a
   candidate judged unfaithful on any fixture is vetoed however it scores. This
   is the grounding veto, independent of the anchor's framing, so a fluent-but-
   unfaithful output can't win and a faithful-but-divergent one isn't punished
   for diverging (the eval-gate #3 fix).
3. **Pairwise at-par** (relative model judge vs the anchor) — the *reliable*
   judge mode (June-2026 practice: relative ranking rho~0.95 vs absolute scoring
   kappa~0.45), so it is the primary ranking signal among the faithful: a switch
   is certified only when the win-rate confirms the candidate >= anchor. No judge
   signal => fail closed (recommend the incumbent).

This inverts the earlier (broken) design where the brittle composite decided and
the judge only tinted a "confidence" label — see
``docs/design/model-judgment-vs-brittle-fallbacks.md``. Rendering is plain strings
+ markdown (no rich dependency) so this stays trivially testable.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from distill.eval.harness import EvalRow
from distill.eval.judge import FAITHFULNESS_ORDINAL
from distill.eval.stats import bootstrap_mean_ci

__all__ = [
    "EvalSummary",
    "ModelSummary",
    "console_lines",
    "render_markdown",
    "results_log_lines",
    "summarize",
]

DEFAULT_THRESHOLD: float = 0.90
# A candidate "loses" to the anchor in the judge's eyes below this win-rate.
_WINRATE_FLOOR: float = 0.45
# Minimum fixtures backing a *migration* before it can earn "high" confidence.
# Below this, a switch is still recommended if it clears the gates, but only at
# "tentative" — three fixtures cannot certify a model swap, and a bootstrap CI
# over so few points is itself unreliable. This is the honest small-N cap; the
# 1.0 fixture scale-up (~20) is what lets a real run reach "high". The anchor
# ("stay put") needs no such certification.
_MIN_FIXTURES_FOR_HIGH: int = 8


@dataclass(frozen=True)
class ModelSummary:
    model: str
    mean_composite: float
    min_composite: float
    max_composite: float
    mean_winrate: float | None  # vs anchor; None for the anchor itself / no judge
    total_cost: float
    rows: int
    errors: int = 0  # fixtures where this model's analysis failed (excluded from scores)
    # Absolute source-anchored faithfulness (the migration veto floor). A single
    # "unfaithful" fixture blocks a migration to this model, however well it scores.
    unfaithful_fixtures: int = 0
    mean_faithfulness: float | None = None  # mean ordinal over judged rows; None if unjudged
    # Paired bootstrap CI (90%) on the per-fixture win-rate vs the anchor — the
    # honest uncertainty band on "is this candidate at par?". None for the anchor
    # / when there is no judge signal.
    winrate_ci_low: float | None = None
    winrate_ci_high: float | None = None


@dataclass(frozen=True)
class EvalSummary:
    workload: str
    models: list[ModelSummary]
    anchor: str
    recommended: str | None
    threshold: float
    confidence: str  # "high" | "tentative"
    confidence_reason: str


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _summarize_model(model: str, rows: list[EvalRow]) -> ModelSummary:
    # Errored fixtures (timeout / provider failure) are excluded from quality
    # aggregation but counted, so a flaky model can't look good by omission.
    ok = [r for r in rows if not r.error]
    composites = [r.quality.composite for r in ok]
    winrates = [r.pairwise_winrate for r in ok if r.pairwise_winrate is not None]
    faith_ordinals = [
        float(FAITHFULNESS_ORDINAL[r.faithfulness])
        for r in ok
        if r.faithfulness in FAITHFULNESS_ORDINAL
    ]
    ci_low, ci_high = bootstrap_mean_ci(winrates) if winrates else (None, None)
    return ModelSummary(
        model=model,
        mean_composite=_mean(composites),
        min_composite=min(composites) if composites else 0.0,
        max_composite=max(composites) if composites else 0.0,
        mean_winrate=_mean(winrates) if winrates else None,
        total_cost=sum(r.cost for r in rows),
        rows=len(ok),
        errors=sum(1 for r in rows if r.error),
        unfaithful_fixtures=sum(1 for r in ok if r.faithfulness == "unfaithful"),
        mean_faithfulness=_mean(faith_ordinals) if faith_ordinals else None,
        winrate_ci_low=ci_low,
        winrate_ci_high=ci_high,
    )


@dataclass(frozen=True)
class _Eligibility:
    eligible: list[ModelSummary]
    vetoed_cheaper: bool  # a cheaper candidate was blocked (faithfulness or pairwise)
    faith_vetoed_cheaper: bool  # ...specifically by the faithfulness (grounding) veto


def _eligible_for_migration(
    summaries: list[ModelSummary], anchor: str, anchor_summary: ModelSummary, bar: float
) -> _Eligibility:
    """Which models may be recommended, in charter order. A *migration* away from
    the anchor must clear three gates; the anchor itself needs none ("stay put" is
    safe):

      1. Deterministic composite floor -- a necessary guardrail, gameable on its
         own, never sufficient.
      2. Faithfulness floor (absolute, source-anchored): an "unfaithful" candidate
         is vetoed however well it scores or compares -- the grounding veto,
         independent of the anchor's framing, so a fluent-but-unfaithful output
         can't win and a faithful-but-divergent one isn't punished for diverging.
      3. Pairwise at-par (primary ranking signal among the faithful): the reliable
         relative judgment must confirm the candidate >= anchor.

    Faithfulness, not the gameable composite, holds the migration veto.
    """
    eligible: list[ModelSummary] = []
    vetoed_cheaper = False
    faith_vetoed_cheaper = False
    for s in summaries:
        if s.rows == 0 or s.mean_composite < bar:
            continue
        if s.model == anchor:
            eligible.append(s)
            continue
        cheaper = s.total_cost < anchor_summary.total_cost
        if s.unfaithful_fixtures > 0:
            # Grounding veto: never migrate to a model that invents facts on any
            # fixture, however it scores or compares.
            vetoed_cheaper = vetoed_cheaper or cheaper
            faith_vetoed_cheaper = faith_vetoed_cheaper or cheaper
            continue
        if s.mean_winrate is None or s.mean_winrate < _WINRATE_FLOOR:
            # Faithful but the pairwise judge (or its absence) can't certify it
            # at-par with the anchor. Record it so the anchor pick can explain.
            vetoed_cheaper = vetoed_cheaper or cheaper
            continue
        eligible.append(s)
    return _Eligibility(eligible, vetoed_cheaper, faith_vetoed_cheaper)


def summarize(
    rows: list[EvalRow], *, anchor: str, threshold: float = DEFAULT_THRESHOLD
) -> EvalSummary:
    """Aggregate per-model and pick the cheapest model clearing threshold x anchor."""
    # Label honestly: one workload shows its name; a mixed set (``--workload all``)
    # says "all (paper+video+site)" rather than mislabeling as the first fixture's.
    distinct = sorted({r.workload for r in rows})
    workload = (
        distinct[0] if len(distinct) == 1 else f"all ({'+'.join(distinct)})" if distinct else ""
    )
    by_model: dict[str, list[EvalRow]] = {}
    for row in rows:
        by_model.setdefault(row.model, []).append(row)

    summaries = [_summarize_model(m, rs) for m, rs in by_model.items()]
    summaries.sort(key=lambda s: s.mean_composite, reverse=True)

    anchor_summary = next((s for s in summaries if s.model == anchor), None)
    recommended: str | None = None
    confidence = "tentative"
    reason = ""
    if anchor_summary is None:
        reason = f"anchor '{anchor}' not in results"
    elif anchor_summary.rows == 0:
        reason = f"anchor '{anchor}' produced no valid output ({anchor_summary.errors} error(s))"
    else:
        bar = threshold * anchor_summary.mean_composite
        elig = _eligible_for_migration(summaries, anchor, anchor_summary, bar)
        if elig.eligible:
            rec = min(elig.eligible, key=lambda s: (s.total_cost, -s.mean_composite))
            recommended = rec.model
            confidence, reason = _confidence(
                rec, anchor_summary, bar, elig.vetoed_cheaper, elig.faith_vetoed_cheaper
            )
        else:
            # Nothing clears the bar -- possible when --threshold > 1.0, where
            # even the anchor fails its own bar. Recommend nothing rather than
            # crashing on min([]).
            reason = f"no model clears the bar ({bar:.2f}) at threshold {threshold:g}"

    return EvalSummary(
        workload=workload,
        models=summaries,
        anchor=anchor,
        recommended=recommended,
        threshold=threshold,
        confidence=confidence,
        confidence_reason=reason,
    )


def _confidence(
    rec: ModelSummary,
    anchor: ModelSummary,
    bar: float,
    vetoed_cheaper: bool,
    faith_vetoed_cheaper: bool = False,
) -> tuple[str, str]:
    """Confidence in the recommendation. The judges already gated the *pick* (a
    non-anchor rec passed the faithfulness floor AND the win-rate floor); this only
    nuances the label."""
    if rec.errors > 0:
        return (
            "tentative",
            f"{rec.model} failed on {rec.errors} fixture(s) — rerun before trusting the pick",
        )
    if rec.model == anchor.model:
        if faith_vetoed_cheaper:
            # The sharpest "don't migrate" case: a cheaper model was unfaithful on
            # the source. Cost is no argument for shipping invented facts.
            return (
                "high",
                "recommends the anchor — a cheaper model was judged unfaithful to the source "
                "(invented or unsupported claims); not migrating to ungrounded output",
            )
        if vetoed_cheaper:
            # Cheaper models cleared the cheap composite floor but the pairwise
            # judge would not certify them at par (or there was no neutral judge).
            return (
                "high",
                "recommends the anchor — cheaper models cleared the deterministic floor but the "
                "judge did not confirm them at par with the anchor (or no judge signal); "
                "not certifying a switch",
            )
        return "high", "recommends the anchor — nothing cheaper clears the bar"
    # Non-anchor rec: it already passed the composite floor, the faithfulness
    # floor, AND win-rate >= floor. "High" additionally requires statistical
    # backing -- enough fixtures, and a bootstrap CI whose lower bound clears the
    # at-par floor -- so a 3-fixture run can't crown a switch on a bare mean.
    if rec.min_composite < bar:
        return (
            "tentative",
            f"{rec.model}'s worst fixture ({rec.min_composite:.2f}) dips below the bar "
            f"({bar:.2f}) — add fixtures or inspect before switching",
        )
    if (
        rec.mean_faithfulness is not None
        and anchor.mean_faithfulness is not None
        and rec.mean_faithfulness < anchor.mean_faithfulness
    ):
        # Cleared the binary floor (no outright-unfaithful fixture) but is on
        # average less grounded than the incumbent -- a softer caveat, surfaced.
        return (
            "tentative",
            f"{rec.model} clears the bar and the judge confirms it at par, but it grades less "
            f"faithful than the anchor on average — inspect the flagged claims before switching",
        )
    if rec.rows < _MIN_FIXTURES_FOR_HIGH:
        return (
            "tentative",
            f"only {rec.rows} fixture(s) back this pick — high confidence needs "
            f">= {_MIN_FIXTURES_FOR_HIGH}; add fixtures before trusting a switch",
        )
    if rec.winrate_ci_low is None or rec.winrate_ci_low < _WINRATE_FLOOR:
        low = rec.winrate_ci_low
        band = f"{low:.2f}" if low is not None else "n/a"
        return (
            "tentative",
            f"{rec.model}'s win-rate 90% CI lower bound ({band}) dips below the at-par floor "
            f"({_WINRATE_FLOOR:.2f}) — the evidence is too noisy to certify a switch",
        )
    return (
        "high",
        f"{rec.model} clears the bar on every fixture, the judge confirms it at par, and the "
        f"win-rate CI lower bound ({rec.winrate_ci_low:.2f}) clears the floor",
    )


def _winrate_str(s: ModelSummary, anchor: str, *, with_ci: bool = False) -> str:
    if s.model == anchor:
        return "anchor"
    if s.mean_winrate is None:
        return "—"
    if with_ci and s.winrate_ci_low is not None and s.winrate_ci_high is not None:
        return f"{s.mean_winrate:.2f} [{s.winrate_ci_low:.2f}-{s.winrate_ci_high:.2f}]"
    return f"{s.mean_winrate:.2f}"


def _faithful_str(s: ModelSummary) -> str:
    """Mean faithfulness as a 0-1 string (ordinal 0/1/2 -> 0.0/0.5/1.0), '—' if unjudged.
    A trailing '!' marks any outright-unfaithful fixture (the migration veto)."""
    if s.mean_faithfulness is None:
        return "—"
    flag = "!" if s.unfaithful_fixtures else ""
    return f"{s.mean_faithfulness / 2:.2f}{flag}"


def console_lines(summary: EvalSummary) -> list[str]:
    """Plain-text lines for the terminal (no rich dependency)."""
    lines = [
        f"Model eval — {summary.workload} ({len(summary.models)} models, "
        f"anchor {summary.anchor}, threshold {summary.threshold:.0%})",
        f"  {'model':<26} {'mean':>6} {'min':>6} {'win':>6} {'cost':>9}",
    ]
    for s in summary.models:
        tag = ""
        if s.model == summary.anchor:
            tag += "  (anchor)"
        if s.model == summary.recommended:
            tag += "  <- recommended"
        if s.errors:
            tag += f"  [{s.errors} err]"
        if s.unfaithful_fixtures:
            tag += f"  [{s.unfaithful_fixtures} unfaithful]"
        lines.append(
            f"  {s.model:<26} {s.mean_composite:>6.2f} {s.min_composite:>6.2f} "
            f"{_winrate_str(s, summary.anchor):>6} {'$' + format(s.total_cost, '.4f'):>9}{tag}"
        )
    if summary.recommended:
        lines.append(
            f"  Recommendation ({summary.confidence}): {summary.recommended} "
            f"— {summary.confidence_reason}"
        )
    return lines


def results_log_lines(
    rows: list[EvalRow], *, now_iso: str, anchor: str, judge_model: str
) -> list[str]:
    """One append-only JSONL line per row, for tracking quality/cost drift over time."""
    lines: list[str] = []
    for r in rows:
        lines.append(
            json.dumps(
                {
                    "timestamp": now_iso,
                    "workload": r.workload,
                    "fixture_id": r.fixture_id,
                    "model": r.model,
                    "anchor": anchor,
                    "judge_model": judge_model,
                    "composite": round(r.quality.composite, 4),
                    "pairwise_winrate": r.pairwise_winrate,
                    "faithfulness": r.faithfulness or None,
                    "cost": round(r.cost, 6),
                    "input_tokens": r.input_tokens,
                    "output_tokens": r.output_tokens,
                    "cached": r.cached,
                }
            )
        )
    return lines


def render_markdown(summary: EvalSummary, *, now_iso: str) -> str:
    """A report artifact: the cost x quality table + the recommendation."""
    out = [
        f"# Model eval — {summary.workload}",
        "",
        f"- Generated: {now_iso}",
        f"- Anchor (incumbent/reference): `{summary.anchor}`",
        f"- Threshold: {summary.threshold:.0%} of anchor's mean composite",
        f"- **Recommended: `{summary.recommended or 'none'}` "
        f"(confidence: {summary.confidence})** — {summary.confidence_reason}",
        "",
        "| Model | Mean | Min | Max | Win-rate vs anchor | Faithful | Total cost |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for s in summary.models:
        marks = []
        if s.model == summary.anchor:
            marks.append("anchor")
        if s.model == summary.recommended:
            marks.append("**recommended**")
        if s.errors:
            marks.append(f"{s.errors} error(s)")
        suffix = f" ({', '.join(marks)})" if marks else ""
        out.append(
            f"| `{s.model}`{suffix} | {s.mean_composite:.2f} | {s.min_composite:.2f} "
            f"| {s.max_composite:.2f} | {_winrate_str(s, summary.anchor, with_ci=True)} "
            f"| {_faithful_str(s)} | ${s.total_cost:.4f} |"
        )
    out += [
        "",
        "The recommendation is gated by two model judges, not by the deterministic composite. "
        "**Faithfulness** (absolute, graded against the source) is a veto floor: a model judged "
        "unfaithful on any fixture is never a migration target, however it scores. The **pairwise "
        "win-rate** (order-randomized over both A/B orderings to cancel position bias) is the "
        "primary ranking signal among the faithful — a switch is certified only when it confirms "
        "the candidate at par with the anchor. The composite mean/min is a necessary guardrail "
        "floor, never sufficient on its own. The Faithful column is the mean of per-fixture "
        "verdicts (faithful=1.0, minor=0.5, unfaithful=0.0); '—' means no judge was available. "
        f"Win-rate shows a 90% paired bootstrap CI in brackets; **high** confidence in a switch "
        f"requires at least {_MIN_FIXTURES_FOR_HIGH} fixtures and a CI lower bound clearing the "
        f"at-par floor ({_WINRATE_FLOOR:.2f}) — a small fixture set is recommended only "
        "tentatively, never certified.",
        "",
    ]
    return "\n".join(out)

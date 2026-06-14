"""Aggregate eval rows into a cost x quality summary + a recommendation.

The recommendation is pure Python aggregation over **model-judge** signals, in the
order the agentic-balance charter requires (model proposes, Python decides). A
*migration* away from the incumbent anchor must clear two model-judged gates; the
anchor itself needs neither ("stay put" is the safe default):

1. **Faithfulness floor** (absolute model judge, graded against the source) — a
   candidate judged unfaithful on any fixture is vetoed however it scores. This
   is the grounding veto, independent of the anchor's framing, so a fluent-but-
   unfaithful output can't win and a faithful-but-divergent one isn't punished
   for diverging (the eval-gate #3 fix).
2. **Pairwise at-par** (relative model judge vs the anchor) — the *reliable*
   judge mode (June-2026 practice: relative ranking rho~0.95 vs absolute scoring
   kappa~0.45), so it is the primary ranking signal among the faithful: a switch
   is certified only when the win-rate confirms the candidate >= anchor. No judge
   signal => fail closed (recommend the incumbent).

The **deterministic composite** (``scoring.py`` keyword/length heuristics) is
deliberately NOT a gate. As a floor it would wrongly *exclude* a faithful,
judge-approved candidate that paraphrases or is terse — the brittle-proxy failure
mode the charter condemns. It survives only as the offline golden-CI regression
tripwire and an advisory diagnostic shown in the report; ``threshold`` sets that
advisory reference, nothing more. Confidence reflects the model judges' agreement
and the reason states the fixture count plainly -- there is no bootstrap CI or
min-fixture gate (statistical theater over a tiny sample; reverted 2026-06-14).

This is the end state of the inversion fix that started by gating on the judge
instead of the brittle composite — see
``docs/design/model-judgment-vs-brittle-fallbacks.md``. Rendering is plain strings
+ markdown (no rich dependency) so this stays trivially testable.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from distill.eval.harness import EvalRow
from distill.eval.judge import FAITHFULNESS_ORDINAL

__all__ = [
    "EvalSummary",
    "ModelSummary",
    "console_lines",
    "render_markdown",
    "results_log_lines",
    "summarize",
]

DEFAULT_THRESHOLD: float = 0.90
# A candidate is "at par" with the anchor in the judge's eyes at/above this
# win-rate. A plain threshold over the model's verdict (charter-allowed), not a
# statistic. There is deliberately NO bootstrap CI / min-fixture machinery: a
# bootstrap over 3 fixtures is statistical theater (reverted 2026-06-14, see
# docs/design/model-judgment-vs-brittle-fallbacks.md). Sample size is stated
# plainly in the reason instead; real statistics wait for a large fixture set.
_WINRATE_FLOOR: float = 0.45


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
    )


@dataclass(frozen=True)
class _Eligibility:
    eligible: list[ModelSummary]
    vetoed_cheaper: bool  # a cheaper candidate was blocked (faithfulness or pairwise)
    faith_vetoed_cheaper: bool  # ...specifically by the faithfulness (grounding) veto


def _eligible_for_migration(
    summaries: list[ModelSummary], anchor: str, anchor_summary: ModelSummary
) -> _Eligibility:
    """Which models may be recommended over the anchor. A *migration* must clear
    two **model-judged** gates; the anchor itself needs neither ("stay put" is
    safe):

      1. Faithfulness floor (absolute, source-anchored): an "unfaithful" candidate
         is vetoed however it compares -- the grounding veto, independent of the
         anchor's framing, so a fluent-but-unfaithful output can't win and a
         faithful-but-divergent one isn't punished for diverging.
      2. Pairwise at-par (primary ranking signal among the faithful): the reliable
         relative judgment must confirm the candidate >= anchor.

    The deterministic composite is deliberately **not** a gate here. It is a
    keyword/length heuristic (``scoring.py``) blind to faithfulness and gameable
    by paraphrase -- as a floor it would wrongly *exclude* a faithful, judge-
    approved candidate that paraphrases or is terse (the brittle-proxy failure
    mode in ``docs/design/agentic-balance.md``). It survives only as the offline
    golden-CI regression tripwire and an advisory diagnostic in the report, never
    as a decision input. Eligibility is the model judges' call; Python only
    aggregates and thresholds their verdicts (invariant #6).
    """
    eligible: list[ModelSummary] = []
    vetoed_cheaper = False
    faith_vetoed_cheaper = False
    for s in summaries:
        if s.rows == 0:
            continue
        if s.model == anchor:
            eligible.append(s)
            continue
        cheaper = s.total_cost < anchor_summary.total_cost
        if s.unfaithful_fixtures > 0:
            # Grounding veto: never migrate to a model that invents facts on any
            # fixture, however it compares.
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
    """Aggregate per-model and pick the cheapest model the model judges certify at
    par with the anchor. ``threshold`` no longer gates -- it sets only the advisory
    composite reference shown in the report (the composite is a heuristic diagnostic,
    not a decision input)."""
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
        elig = _eligible_for_migration(summaries, anchor, anchor_summary)
        if elig.eligible:
            # Cheapest, tie-broken by the model-judged win-rate (never the
            # brittle composite). The anchor is always eligible, so this list is
            # non-empty whenever the anchor produced output.
            rec = min(elig.eligible, key=lambda s: (s.total_cost, -(s.mean_winrate or 0.0)))
            recommended = rec.model
            confidence, reason = _confidence(
                rec, anchor_summary, elig.vetoed_cheaper, elig.faith_vetoed_cheaper
            )
        else:  # pragma: no cover - anchor with rows>0 is always eligible
            reason = "no model is eligible"

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
    vetoed_cheaper: bool,
    faith_vetoed_cheaper: bool = False,
) -> tuple[str, str]:
    """Confidence in the recommendation. The model judges already gated the *pick*
    (a non-anchor rec passed the faithfulness floor AND the win-rate floor); this
    only nuances the label from faithfulness, and states the fixture count -- the
    brittle composite is never consulted here, and there is no statistics gate."""
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
            # Cheaper models exist but the pairwise judge would not certify them at
            # par with the anchor (or there was no neutral judge to ask).
            return (
                "high",
                "recommends the anchor — the judge did not confirm any cheaper model at par "
                "with the anchor (or no judge signal); not certifying a switch",
            )
        return "high", "recommends the anchor — no cheaper model is certified at par"
    # Non-anchor rec: it already passed the faithfulness floor AND win-rate >=
    # floor (the model judges agree). Confidence reflects that agreement; the
    # reason states the fixture count plainly so the reader weighs the sample
    # size themselves. No bootstrap / min-N gate -- a switch is advice, never an
    # auto-action, so honest reporting beats fake statistics over a tiny sample.
    if (
        rec.mean_faithfulness is not None
        and anchor.mean_faithfulness is not None
        and rec.mean_faithfulness < anchor.mean_faithfulness
    ):
        # Cleared the binary floor (no outright-unfaithful fixture) but is on
        # average less grounded than the incumbent -- a softer caveat, surfaced.
        return (
            "tentative",
            f"{rec.model} is judged at par, but it grades less faithful than the anchor on "
            f"average — inspect the flagged claims before switching",
        )
    return (
        "high",
        f"{rec.model} is judged faithful and at par with the anchor across {rec.rows} fixture(s) "
        f"(small sample — the eval recommends, it never switches your model for you)",
    )


def _winrate_str(s: ModelSummary, anchor: str) -> str:
    if s.model == anchor:
        return "anchor"
    if s.mean_winrate is None:
        return "—"
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
        f"anchor {summary.anchor}; composite advisory only, judges gate the switch)",
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
        f"- Composite reference (advisory only, not a gate): "
        f"{summary.threshold:.0%} of anchor's mean composite",
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
            f"| {s.max_composite:.2f} | {_winrate_str(s, summary.anchor)} "
            f"| {_faithful_str(s)} | ${s.total_cost:.4f} |"
        )
    out += [
        "",
        "The recommendation is gated by two **model judges**, never the deterministic composite. "
        "**Faithfulness** (absolute, graded against the source) is a veto floor: a model judged "
        "unfaithful on any fixture is never a migration target, however it scores. The **pairwise "
        "win-rate** (order-randomized over both A/B orderings to cancel position bias) is the "
        "primary ranking signal among the faithful — a switch is certified only when it confirms "
        "the candidate at par with the anchor. The composite (Mean/Min/Max) is a keyword/length "
        "heuristic shown for diagnosis only — it is **not** a gate, because as a floor it would "
        "wrongly exclude a faithful, judge-approved candidate that paraphrases or is terse. The "
        "Faithful column is the mean of per-fixture verdicts (faithful=1.0, minor=0.5, "
        "unfaithful=0.0); '—' means no judge was available. "
        f"A candidate is 'at par' at win-rate >= {_WINRATE_FLOOR:.2f}. There is no bootstrap CI or "
        "min-fixture gate (a bootstrap over a few fixtures is statistical theater); the fixture "
        "count is stated in the recommendation instead, and the eval only ever recommends -- it "
        "never switches your configured model.",
        "",
    ]
    return "\n".join(out)

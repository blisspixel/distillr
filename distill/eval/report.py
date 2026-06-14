"""Aggregate eval rows into a cost x quality summary + a recommendation.

The recommendation is pure Python aggregation over two signals, in the order the
agentic-balance charter requires (model proposes, Python decides):

1. The **faithfulness-aware pairwise judge** gates a migration. A non-anchor
   candidate may only be recommended over the incumbent anchor if the judge
   confirms it is at least at par (win-rate >= floor). No judge signal => the
   switch is NOT certified (fail closed) — because the deterministic composite
   below is admittedly blind to faithfulness and gameable by verbose, well-
   formatted, keyword-stuffed output, so it cannot license a migration alone.
2. The **deterministic composite** is a cheap guardrail floor (clears
   ``threshold x anchor``), not the decider. It runs key-free in CI; it is
   necessary, never sufficient, for recommending a switch.

This inverts the earlier (broken) design where the brittle composite decided and
the judge only tinted a "confidence" label — see
``docs/design/model-judgment-vs-brittle-fallbacks.md``. The anchor (incumbent)
needs no judge to be recommended: "stay put" is the safe default. Rendering is
plain strings + markdown (no rich dependency) so this stays trivially testable.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from distill.eval.harness import EvalRow

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
    return ModelSummary(
        model=model,
        mean_composite=_mean(composites),
        min_composite=min(composites) if composites else 0.0,
        max_composite=max(composites) if composites else 0.0,
        mean_winrate=_mean(winrates) if winrates else None,
        total_cost=sum(r.cost for r in rows),
        rows=len(ok),
        errors=sum(1 for r in rows if r.error),
    )


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
        # Eligibility, in charter order: clear the deterministic guardrail (a
        # necessary floor), then -- for a *migration* away from the anchor -- the
        # judge must confirm at-par. The anchor itself needs no judge ("stay put"
        # is safe). A cheaper candidate that clears the floor but the judge can't
        # certify (no signal, or below floor) is vetoed: faithfulness, not the
        # gameable composite, holds the migration veto.
        eligible: list[ModelSummary] = []
        vetoed_cheaper = False
        for s in summaries:
            if s.rows == 0 or s.mean_composite < bar:
                continue
            if s.model == anchor:
                eligible.append(s)
                continue
            if s.mean_winrate is None or s.mean_winrate < _WINRATE_FLOOR:
                # Cheaper-than-anchor candidate blocked by the judge (or its
                # absence). Record it so the anchor pick can explain itself.
                if s.total_cost < anchor_summary.total_cost:
                    vetoed_cheaper = True
                continue
            eligible.append(s)
        if eligible:
            rec = min(eligible, key=lambda s: (s.total_cost, -s.mean_composite))
            recommended = rec.model
            confidence, reason = _confidence(rec, anchor_summary, bar, vetoed_cheaper)
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
    rec: ModelSummary, anchor: ModelSummary, bar: float, vetoed_cheaper: bool
) -> tuple[str, str]:
    """Confidence in the recommendation. The judge already gated the *pick* (a
    non-anchor rec has cleared the win-rate floor); this only nuances the label."""
    if rec.errors > 0:
        return (
            "tentative",
            f"{rec.model} failed on {rec.errors} fixture(s) — rerun before trusting the pick",
        )
    if rec.model == anchor.model:
        if vetoed_cheaper:
            # The honest "don't migrate" case: cheaper models cleared the cheap
            # composite floor but the judge would not certify them at par (or
            # there was no neutral judge to ask). Staying on the incumbent.
            return (
                "high",
                "recommends the anchor — cheaper models cleared the deterministic floor but the "
                "judge did not confirm them at par with the anchor (or no judge signal); "
                "not certifying a switch",
            )
        return "high", "recommends the anchor — nothing cheaper clears the bar"
    # Non-anchor rec: it already passed the composite floor AND win-rate >= floor.
    if rec.min_composite < bar:
        return (
            "tentative",
            f"{rec.model}'s worst fixture ({rec.min_composite:.2f}) dips below the bar "
            f"({bar:.2f}) — add fixtures or inspect before switching",
        )
    return "high", f"{rec.model} clears the bar on every fixture and the judge confirms it at par"


def _winrate_str(s: ModelSummary, anchor: str) -> str:
    if s.model == anchor:
        return "anchor"
    return f"{s.mean_winrate:.2f}" if s.mean_winrate is not None else "—"


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
        "| Model | Mean | Min | Max | Win-rate vs anchor | Total cost |",
        "|---|---:|---:|---:|---:|---:|",
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
            f"| {s.max_composite:.2f} | {_winrate_str(s, summary.anchor)} | ${s.total_cost:.4f} |"
        )
    out += [
        "",
        "The recommendation is deterministic: the cheapest model whose mean composite "
        "clears the threshold relative to the anchor. The pairwise judge win-rate and the "
        "per-fixture spread (min/max) feed only the confidence flag — they never change the "
        "pick. Win-rate is order-randomized (both A/B orderings) to cancel position bias.",
        "",
    ]
    return "\n".join(out)

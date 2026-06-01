"""Aggregate eval rows into a cost x quality summary + a deterministic pick.

The recommendation is pure Python over the deterministic composite: the cheapest
model whose mean composite clears ``threshold x anchor`` (the anchor is the
incumbent/reference model). The pairwise judge win-rate and the per-model spread
feed only the **confidence** flag — they never change the pick. Rendering is
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
    composites = [r.quality.composite for r in rows]
    winrates = [r.pairwise_winrate for r in rows if r.pairwise_winrate is not None]
    return ModelSummary(
        model=model,
        mean_composite=_mean(composites),
        min_composite=min(composites) if composites else 0.0,
        max_composite=max(composites) if composites else 0.0,
        mean_winrate=_mean(winrates) if winrates else None,
        total_cost=sum(r.cost for r in rows),
        rows=len(rows),
    )


def summarize(
    rows: list[EvalRow], *, anchor: str, threshold: float = DEFAULT_THRESHOLD
) -> EvalSummary:
    """Aggregate per-model and pick the cheapest model clearing threshold x anchor."""
    workload = rows[0].workload if rows else ""
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
    else:
        bar = threshold * anchor_summary.mean_composite
        clearing = [s for s in summaries if s.mean_composite >= bar]
        rec = min(clearing, key=lambda s: (s.total_cost, -s.mean_composite))
        recommended = rec.model
        confidence, reason = _confidence(rec, anchor_summary, bar)

    return EvalSummary(
        workload=workload,
        models=summaries,
        anchor=anchor,
        recommended=recommended,
        threshold=threshold,
        confidence=confidence,
        confidence_reason=reason,
    )


def _confidence(rec: ModelSummary, anchor: ModelSummary, bar: float) -> tuple[str, str]:
    """Deterministic confidence in the recommendation (advisory signals only)."""
    if rec.model == anchor.model:
        return "high", "recommends the anchor — nothing cheaper clears the bar"
    if rec.min_composite < bar:
        return (
            "tentative",
            f"{rec.model}'s worst fixture ({rec.min_composite:.2f}) dips below the bar "
            f"({bar:.2f}) — add fixtures or inspect before switching",
        )
    if rec.mean_winrate is not None and rec.mean_winrate < _WINRATE_FLOOR:
        return (
            "tentative",
            f"deterministic scores clear the bar but the judge favors the anchor "
            f"(win-rate {rec.mean_winrate:.2f} < {_WINRATE_FLOOR:.2f})",
        )
    return "high", f"{rec.model} clears the bar on every fixture and the judge agrees"


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

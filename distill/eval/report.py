"""Aggregate eval rows into a cost x quality summary + a deterministic pick.

The recommendation is pure Python: the anchor is the highest-quality model, and
the recommended model is the *cheapest* one whose mean composite clears
``threshold x anchor`` — never the judge's call. Rendering is plain strings +
markdown (no rich dependency) so this stays trivially testable.
"""

from __future__ import annotations

from dataclasses import dataclass

from distill.eval.harness import EvalRow

__all__ = ["EvalSummary", "ModelSummary", "console_lines", "render_markdown", "summarize"]

DEFAULT_THRESHOLD: float = 0.90


@dataclass(frozen=True)
class ModelSummary:
    model: str
    mean_composite: float
    mean_deterministic: float
    mean_judge: float | None
    total_cost: float
    rows: int


@dataclass(frozen=True)
class EvalSummary:
    workload: str
    models: list[ModelSummary]
    anchor: str
    recommended: str | None
    threshold: float


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def summarize(rows: list[EvalRow], *, threshold: float = DEFAULT_THRESHOLD) -> EvalSummary:
    """Aggregate per-model and pick the cheapest model clearing threshold x anchor."""
    workload = rows[0].workload if rows else ""
    by_model: dict[str, list[EvalRow]] = {}
    for row in rows:
        by_model.setdefault(row.model, []).append(row)

    summaries: list[ModelSummary] = []
    for model, model_rows in by_model.items():
        judge_vals = [r.quality.judge for r in model_rows if r.quality.judge is not None]
        summaries.append(
            ModelSummary(
                model=model,
                mean_composite=_mean([r.quality.composite for r in model_rows]),
                mean_deterministic=_mean([r.quality.deterministic for r in model_rows]),
                mean_judge=_mean(judge_vals) if judge_vals else None,
                total_cost=sum(r.cost for r in model_rows),
                rows=len(model_rows),
            )
        )

    # Sort best-quality first for display.
    summaries.sort(key=lambda s: s.mean_composite, reverse=True)
    anchor = summaries[0] if summaries else None
    recommended: str | None = None
    if anchor:
        bar = threshold * anchor.mean_composite
        clearing = [s for s in summaries if s.mean_composite >= bar]
        # Cheapest model that clears the bar; ties broken by higher quality.
        recommended = min(clearing, key=lambda s: (s.total_cost, -s.mean_composite)).model

    return EvalSummary(
        workload=workload,
        models=summaries,
        anchor=anchor.model if anchor else "",
        recommended=recommended,
        threshold=threshold,
    )


def console_lines(summary: EvalSummary) -> list[str]:
    """Plain-text lines for the terminal (no rich dependency)."""
    lines = [
        f"Model eval — {summary.workload} ({len(summary.models)} models, "
        f"threshold {summary.threshold:.0%} of anchor)",
        f"  {'model':<28} {'quality':>8} {'det':>6} {'judge':>6} {'cost':>9}",
    ]
    for s in summary.models:
        judge = f"{s.mean_judge:.2f}" if s.mean_judge is not None else "  -"
        tag = ""
        if s.model == summary.anchor:
            tag = "  (anchor)"
        if s.model == summary.recommended:
            tag += "  <- recommended"
        lines.append(
            f"  {s.model:<28} {s.mean_composite:>8.2f} {s.mean_deterministic:>6.2f} "
            f"{judge:>6} {'$' + format(s.total_cost, '.4f'):>9}{tag}"
        )
    if summary.recommended:
        rec = next(s for s in summary.models if s.model == summary.recommended)
        anchor = next(s for s in summary.models if s.model == summary.anchor)
        if rec.model == anchor.model:
            lines.append(f"  Recommendation: {rec.model} — nothing cheaper clears the bar.")
        else:
            lines.append(
                f"  Recommendation: {rec.model} at ${rec.total_cost:.4f} clears "
                f"{summary.threshold:.0%} of {anchor.model}'s quality at lower cost."
            )
    return lines


def render_markdown(summary: EvalSummary, *, now_iso: str) -> str:
    """A report artifact: the cost x quality table + the recommendation."""
    out = [
        f"# Model eval — {summary.workload}",
        "",
        f"- Generated: {now_iso}",
        f"- Anchor (highest quality): `{summary.anchor}`",
        f"- Threshold: {summary.threshold:.0%} of anchor composite",
        f"- **Recommended: `{summary.recommended or 'none'}`**",
        "",
        "| Model | Composite | Deterministic | Judge | Total cost |",
        "|---|---:|---:|---:|---:|",
    ]
    for s in summary.models:
        judge = f"{s.mean_judge:.2f}" if s.mean_judge is not None else "—"
        marks = []
        if s.model == summary.anchor:
            marks.append("anchor")
        if s.model == summary.recommended:
            marks.append("**recommended**")
        suffix = f" ({', '.join(marks)})" if marks else ""
        out.append(
            f"| `{s.model}`{suffix} | {s.mean_composite:.2f} | {s.mean_deterministic:.2f} "
            f"| {judge} | ${s.total_cost:.4f} |"
        )
    out += [
        "",
        "The recommendation is deterministic: the cheapest model whose mean composite "
        "clears the threshold relative to the anchor. The LLM judge is advisory only "
        "(capped weight in the composite); it never decides the pick.",
        "",
    ]
    return "\n".join(out)

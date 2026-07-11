"""Historical cost-log analytics used by reporting surfaces."""

# pyright: strict

from __future__ import annotations

from typing import Any

__all__ = [
    "estimator_accuracy",
    "projected_next_run_cost",
]


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    return ordered[mid] if n % 2 else (ordered[mid - 1] + ordered[mid]) / 2


def estimator_accuracy(entries: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Summarize estimate accuracy for runs that record estimate and spend."""
    signed_pct: list[float] = []
    for row in entries:
        if str(row.get("command", "")).endswith("_preview"):
            continue
        estimated = row.get("estimated_cost")
        actual = row.get("actual_cost")
        if not isinstance(estimated, int | float) or not isinstance(actual, int | float):
            continue
        if estimated <= 0 or actual <= 0:
            continue
        signed_pct.append((estimated - actual) / actual * 100.0)
    if not signed_pct:
        return None
    recent = signed_pct[-10:]
    return {
        "runs_compared": len(signed_pct),
        "median_abs_pct_error": round(_median([abs(value) for value in signed_pct]), 1),
        "median_signed_pct_error": round(_median(signed_pct), 1),
        "recent10_median_abs_pct_error": round(_median([abs(value) for value in recent]), 1),
    }


def projected_next_run_cost(entries: list[dict[str, Any]]) -> float:
    """Average up to five recent positive costs from non-preview runs."""
    costs: list[float] = []
    for row in reversed(entries):
        if str(row.get("command", "")).endswith("_preview"):
            continue
        actual = row.get("actual_cost")
        if isinstance(actual, int | float) and actual > 0:
            costs.append(float(actual))
        if len(costs) >= 5:
            break
    if not costs:
        return 0.0
    return sum(costs) / len(costs)

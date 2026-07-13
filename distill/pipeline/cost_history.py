"""Historical cost-log analytics used by reporting surfaces."""

# pyright: strict

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, cast

from distill.parsing import read_bounded_jsonl_objects

__all__ = [
    "estimator_accuracy",
    "projected_next_run_cost",
    "read_cost_log_rows",
]

_MAX_COST_LOG_BYTES = 16 * 1024 * 1024
_MAX_COST_LOG_ROWS = 10_000


def _has_boolean_monetary_value(row: dict[str, Any]) -> bool:
    return any(isinstance(row.get(field), bool) for field in ("actual_cost", "estimated_cost"))


def read_cost_log_rows(path: Path, *, limit: int = _MAX_COST_LOG_ROWS) -> list[dict[str, Any]]:
    """Read the newest bounded, strict JSON object rows from a cost ledger."""

    if limit <= 0:
        return []
    entries: list[dict[str, Any]] = []
    rows = read_bounded_jsonl_objects(
        path,
        max_bytes=_MAX_COST_LOG_BYTES,
        max_rows=_MAX_COST_LOG_ROWS,
    )
    for loaded in rows:
        row = cast(dict[str, Any], loaded)
        if _has_boolean_monetary_value(row):
            continue
        entries.append(row)
    return entries[-min(limit, _MAX_COST_LOG_ROWS) :]


def _positive_finite_cost(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    try:
        cost = float(value)
    except OverflowError:
        return None
    return cost if math.isfinite(cost) and cost > 0 else None


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
        estimated = _positive_finite_cost(row.get("estimated_cost"))
        actual = _positive_finite_cost(row.get("actual_cost"))
        if estimated is None or actual is None:
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
        actual = _positive_finite_cost(row.get("actual_cost"))
        if actual is not None:
            costs.append(actual)
        if len(costs) >= 5:
            break
    if not costs:
        return 0.0
    return sum(costs) / len(costs)

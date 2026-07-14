"""Historical cost-log analytics used by reporting surfaces."""

# pyright: strict

from __future__ import annotations

import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

from distill.library.confined import read_confined_text, validate_confined_path
from distill.parsing import read_bounded_jsonl_objects, strict_json_loads

__all__ = [
    "estimator_accuracy",
    "find_confined_cost_log",
    "project_cost_log_row",
    "projected_next_run_cost",
    "read_confined_cost_log_rows",
    "read_cost_log_rows",
]

_MAX_COST_LOG_BYTES = 16 * 1024 * 1024
_MAX_COST_LOG_ROWS = 10_000
_PUBLIC_COST_FIELDS = (
    "timestamp",
    "run_id",
    "command",
    "full_videos",
    "shorts",
    "grok_calls",
    "gemini_queries",
    "gemini_query_outcomes",
    "total_input_tokens",
    "total_output_tokens",
    "conservative_usage_calls",
    "actual_cost",
    "estimated_cost",
    "elapsed_seconds",
    "profile_receipt_id",
    "profile_receipt_cost_usd",
    "profile_receipt_tracker_id",
    "by_call_type",
    "by_model",
    "by_provider",
    "by_route_class",
    "usage_ledger",
)


def _has_boolean_monetary_value(row: dict[str, Any]) -> bool:
    return any(isinstance(row.get(field), bool) for field in ("actual_cost", "estimated_cost"))


def read_confined_cost_log_rows(
    path: Path,
    root: Path,
    *,
    limit: int = _MAX_COST_LOG_ROWS,
) -> list[dict[str, object]]:
    """Read strict object rows through the no-follow cost-log boundary."""

    if limit <= 0:
        return []
    content = read_confined_text(path, root, max_bytes=_MAX_COST_LOG_BYTES)
    if content is None:
        return []
    rows: list[dict[str, object]] = []
    for line in content.splitlines()[-_MAX_COST_LOG_ROWS:]:
        try:
            loaded = strict_json_loads(line)
        except (RecursionError, ValueError):
            continue
        if isinstance(loaded, dict):
            rows.append(cast("dict[str, object]", loaded))
    return rows[-min(limit, _MAX_COST_LOG_ROWS) :]


def find_confined_cost_log(library_dir: Path) -> Path | None:
    """Select the current or legacy cost log only when it is a confined file."""

    for path in (
        library_dir / ".distill" / "cost_log.jsonl",
        library_dir / "cost_log.jsonl",
    ):
        if validate_confined_path(path, library_dir, expect_directory=False) is not None:
            return path
    return None


def project_cost_log_row(row: Mapping[str, object]) -> dict[str, object]:
    """Project one ledger row onto the stable public cost-resource surface."""

    return {field: row[field] for field in _PUBLIC_COST_FIELDS if field in row}


def read_cost_log_rows(
    path: Path,
    *,
    limit: int = _MAX_COST_LOG_ROWS,
    root: Path | None = None,
) -> list[dict[str, Any]]:
    """Read the newest bounded, strict JSON object rows from a cost ledger."""

    if limit <= 0:
        return []
    entries: list[dict[str, Any]] = []
    rows = (
        read_confined_cost_log_rows(path, root)
        if root is not None
        else read_bounded_jsonl_objects(
            path,
            max_bytes=_MAX_COST_LOG_BYTES,
            max_rows=_MAX_COST_LOG_ROWS,
        )
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

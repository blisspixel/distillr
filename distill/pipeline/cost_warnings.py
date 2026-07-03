# pyright: strict
"""Structural cost-ledger warnings for CLI and dashboard surfaces."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, Literal, TypedDict, cast

from distill.llm.model_policy import is_xai_media_generation_model

__all__ = ["CostWarning", "cost_anomaly_warnings"]


class CostWarning(TypedDict):
    """A structural cost-ledger warning for CLI and dashboard surfaces."""

    kind: Literal[
        "daily-threshold",
        "daily-spike",
        "run-spike",
        "workflow-budget",
        "xai-media-model",
    ]
    message: str
    date: str
    cost: float


def _median_or_zero(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    midpoint = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[midpoint]
    return (ordered[midpoint - 1] + ordered[midpoint]) / 2


def _row_cost(row: dict[str, Any]) -> float:
    value = row.get("actual_cost")
    if isinstance(value, bool):
        return 0.0
    if not isinstance(value, int | float | str):
        return 0.0
    try:
        cost = float(value)
    except ValueError:
        return 0.0
    return cost if math.isfinite(cost) and cost > 0 else 0.0


def _row_date(row: dict[str, Any]) -> str:
    timestamp = row.get("timestamp")
    if not isinstance(timestamp, str) or not timestamp.strip():
        return ""
    try:
        return datetime.fromisoformat(timestamp.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return timestamp[:10] if len(timestamp) >= 10 else ""


def _row_command(row: dict[str, Any]) -> str:
    command = row.get("command")
    return command if isinstance(command, str) and command else "unknown"


def _row_topic(row: dict[str, Any]) -> str:
    metadata = row.get("metadata")
    if not isinstance(metadata, dict):
        return ""
    metadata_row = cast(dict[str, object], metadata)
    topic = metadata_row.get("topic")
    return topic if isinstance(topic, str) else ""


def _models_from_row(row: dict[str, Any]) -> list[str]:
    models: list[str] = []
    by_model = row.get("by_model")
    if isinstance(by_model, dict):
        by_model_row = cast(dict[object, object], by_model)
        models.extend(str(key) for key in by_model_row if key)
    model = row.get("model")
    if isinstance(model, str) and model:
        models.append(model)
    return sorted(dict.fromkeys(models))


def _is_preview_row(row: dict[str, Any]) -> bool:
    return _row_command(row).endswith("_preview")


def _comparable_key(row: dict[str, Any]) -> tuple[str, str]:
    return (_row_command(row), _row_topic(row))


def _media_model_cost_warnings(rows: Sequence[dict[str, Any]], *, limit: int) -> list[CostWarning]:
    warnings: list[CostWarning] = []
    seen: set[tuple[str, str, str]] = set()
    for row in reversed(rows):
        row_date = _row_date(row)
        for model in _models_from_row(row):
            if not is_xai_media_generation_model(model):
                continue
            marker = ("xai-media-model", row_date, model)
            if marker in seen:
                continue
            seen.add(marker)
            cost = _row_cost(row)
            warnings.append(
                {
                    "kind": "xai-media-model",
                    "message": (
                        "xAI media-generation model spend recorded: "
                        f"{model} in {_row_command(row)} on {row_date or 'unknown date'} "
                        f"(${cost:.2f}). Distill text routes should not emit this model id."
                    ),
                    "date": row_date,
                    "cost": round(cost, 4),
                }
            )
            if len(warnings) >= limit:
                return warnings
    return warnings


def _daily_costs(rows: Sequence[dict[str, Any]]) -> dict[str, float]:
    daily: dict[str, float] = {}
    for row in rows:
        row_date = _row_date(row)
        if not row_date:
            continue
        daily[row_date] = daily.get(row_date, 0.0) + _row_cost(row)
    return daily


def _daily_cost_warnings(
    daily: dict[str, float],
    *,
    daily_threshold_usd: float,
    spike_multiplier: float,
    limit: int,
) -> list[CostWarning]:
    warnings: list[CostWarning] = []
    for row_date, cost in sorted(daily.items(), reverse=True):
        if cost < daily_threshold_usd:
            continue
        warnings.append(
            {
                "kind": "daily-threshold",
                "message": f"Daily spend on {row_date} reached ${cost:.2f}.",
                "date": row_date,
                "cost": round(cost, 4),
            }
        )
        if len(warnings) >= limit:
            return warnings

    ordered_days = sorted(daily.items())
    if len(ordered_days) < 3:
        return warnings
    latest_date, latest_cost = ordered_days[-1]
    baseline = _median_or_zero([cost for _date, cost in ordered_days[:-1] if cost > 0])
    if baseline <= 0 or latest_cost < max(daily_threshold_usd, baseline * spike_multiplier):
        return warnings
    warnings.append(
        {
            "kind": "daily-spike",
            "message": (
                f"Daily spend spike on {latest_date}: ${latest_cost:.2f} "
                f"vs recent daily baseline ${baseline:.2f}."
            ),
            "date": latest_date,
            "cost": round(latest_cost, 4),
        }
    )
    return warnings


def _latest_and_previous_costs(
    rows: Sequence[dict[str, Any]],
) -> tuple[dict[tuple[str, str], dict[str, Any]], dict[tuple[str, str], list[float]]]:
    latest_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    previous_by_key: dict[tuple[str, str], list[float]] = {}
    for row in rows:
        key = _comparable_key(row)
        if key not in latest_by_key:
            latest_by_key[key] = row
            previous_by_key[key] = []
            continue
        previous_by_key[key].append(_row_cost(latest_by_key[key]))
        latest_by_key[key] = row
    return latest_by_key, previous_by_key


def _run_spike_warnings(
    rows: Sequence[dict[str, Any]],
    *,
    spike_multiplier: float,
    run_spike_min_usd: float,
    limit: int,
) -> list[CostWarning]:
    warnings: list[CostWarning] = []
    latest_by_key, previous_by_key = _latest_and_previous_costs(rows)
    for key, latest in sorted(
        latest_by_key.items(),
        key=lambda item: _row_date(item[1]),
        reverse=True,
    ):
        previous = previous_by_key.get(key, [])
        if len(previous) < 2:
            continue
        baseline = _median_or_zero(previous[-5:])
        latest_cost = _row_cost(latest)
        if baseline <= 0 or latest_cost < run_spike_min_usd:
            continue
        if latest_cost < baseline * spike_multiplier:
            continue
        command, topic = key
        scope = f"{command} for {topic}" if topic else command
        date = _row_date(latest)
        warnings.append(
            {
                "kind": "run-spike",
                "message": (
                    f"Run cost spike for {scope} on {date or 'unknown date'}: "
                    f"${latest_cost:.2f} vs recent baseline ${baseline:.2f}."
                ),
                "date": date,
                "cost": round(latest_cost, 4),
            }
        )
        if len(warnings) >= limit:
            return warnings
    return warnings


def _workflow_budget_warnings(
    rows: Sequence[dict[str, Any]],
    *,
    workflow_budgets_usd: Mapping[str, float],
    limit: int,
) -> list[CostWarning]:
    warnings: list[CostWarning] = []
    normalized_budgets: dict[str, float] = {}
    for command, budget in workflow_budgets_usd.items():
        normalized_command = str(command).strip().lower()
        if not normalized_command or not math.isfinite(budget) or budget <= 0:
            continue
        normalized_budgets[normalized_command] = budget
    if not normalized_budgets:
        return warnings

    seen_commands: set[str] = set()
    for row in reversed(rows):
        # Normalize the ledger command the same way budget keys are normalized
        # above (strip + lower); otherwise a stored command with surrounding
        # whitespace never matches its budget key and its overrun is not warned.
        command = _row_command(row).strip().lower()
        if command in seen_commands:
            continue
        seen_commands.add(command)
        budget = normalized_budgets.get(command)
        if budget is None:
            continue
        cost = _row_cost(row)
        if cost <= budget:
            continue
        date = _row_date(row)
        warnings.append(
            {
                "kind": "workflow-budget",
                "message": (
                    f"{command} run on {date or 'unknown date'} spent ${cost:.2f}, "
                    f"above workflow budget ${budget:.2f}."
                ),
                "date": date,
                "cost": round(cost, 4),
            }
        )
        if len(warnings) >= limit:
            return warnings
    return warnings


def cost_anomaly_warnings(
    entries: list[dict[str, Any]],
    *,
    daily_threshold_usd: float = 10.0,
    spike_multiplier: float = 2.5,
    run_spike_min_usd: float = 1.0,
    workflow_budgets_usd: Mapping[str, float] | None = None,
    limit: int = 5,
) -> list[CostWarning]:
    """Detect structural surprise-cost signals from run ledger rows."""
    warnings: list[CostWarning] = []
    normalized = [row for row in entries if not _is_preview_row(row) and _row_cost(row) > 0]
    if not normalized:
        return warnings

    for warning in _media_model_cost_warnings(normalized, limit=limit):
        warnings.append(warning)
        if len(warnings) >= limit:
            return warnings

    for warning in _workflow_budget_warnings(
        normalized,
        workflow_budgets_usd=workflow_budgets_usd or {},
        limit=limit - len(warnings),
    ):
        warnings.append(warning)
        if len(warnings) >= limit:
            return warnings

    for warning in _daily_cost_warnings(
        _daily_costs(normalized),
        daily_threshold_usd=daily_threshold_usd,
        spike_multiplier=spike_multiplier,
        limit=limit - len(warnings),
    ):
        warnings.append(warning)
        if len(warnings) >= limit:
            return warnings

    for warning in _run_spike_warnings(
        normalized,
        spike_multiplier=spike_multiplier,
        run_spike_min_usd=run_spike_min_usd,
        limit=limit - len(warnings),
    ):
        warnings.append(warning)
        if len(warnings) >= limit:
            return warnings

    return warnings

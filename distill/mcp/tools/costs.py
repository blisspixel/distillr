# pyright: strict
"""MCP tools — costs: show recent LLM cost history."""

from __future__ import annotations

import json
import math
from datetime import datetime, timedelta
from pathlib import Path

from distill.mcp.server import load_config, mcp
from distill.pipeline.cost_history import (
    CostLogScan,
    cost_history_integrity_message,
    project_cost_log_row,
    scan_confined_cost_log,
    select_cost_log_path,
)

__all__: list[str] = []


def _actual_cost(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        try:
            cost = float(value)
        except OverflowError:
            return None
        return cost if math.isfinite(cost) and cost >= 0 else None
    return None


def _finite_total(entries: list[dict[str, object]]) -> float | None:
    costs = [_actual_cost(entry.get("actual_cost")) for entry in entries]
    if any(cost is None for cost in costs):
        return None
    try:
        total = math.fsum(cost for cost in costs if cost is not None)
    except OverflowError:
        return None
    return total if math.isfinite(total) else None


def _invalid_range(name: str, minimum: int, maximum: int) -> str:
    return json.dumps(
        {
            "status": "error",
            "error": f"{name} must be an integer from {minimum} to {maximum}.",
        },
        indent=2,
    )


def _cost_result(recent: list[dict[str, object]], cost_scan: CostLogScan, log_file: Path) -> str:
    total = _finite_total(recent)
    messages: list[str] = []
    if not cost_scan.complete:
        messages.append(cost_history_integrity_message(log_file, cost_scan))
    if total is None:
        messages.append(
            "The returned cost total is unavailable because valid cost values exceed "
            "the supported aggregate range."
        )
    # A run whose external cost is unavailable (host-managed or remote-local
    # route) contributes 0 to ``actual_cost``. Reporting that sum as a complete
    # figure would state a confident total the retained evidence cannot support,
    # so name the narrower scope and warn, exactly as ``distill costs`` does.
    external_cost_unavailable = any(
        entry.get("external_cost_status") == "unavailable" for entry in recent
    )
    if external_cost_unavailable:
        messages.append(
            "The returned total covers direct Distill charges only: at least one run "
            "used a route whose external cost is unavailable."
        )
    return json.dumps(
        {
            "status": (
                "ok"
                if cost_scan.complete and total is not None and not external_cost_unavailable
                else "warning"
            ),
            "runs": recent,
            "total_cost": round(total, 4) if total is not None else None,
            "runs_shown": len(recent),
            "total_scope": (
                "distill-direct-charges" if external_cost_unavailable else "returned_valid_runs"
            ),
            "external_cost_status": "unavailable" if external_cost_unavailable else "complete",
            "cost_history": cost_scan.coverage(),
            **({"message": " ".join(messages)} if messages else {}),
        },
        indent=2,
        allow_nan=False,
    )


@mcp.tool()
def costs(days: int = 30, limit: int = 20) -> str:
    """Show recent LLM cost history and per-run spend breakdown.

    Args:
        days: Lookback window in days
        limit: Max entries to return
    """
    if type(days) is not int or not 1 <= days <= 3650:
        return _invalid_range("days", 1, 3650)
    if type(limit) is not int or not 0 <= limit <= 100:
        return _invalid_range("limit", 0, 100)

    config = load_config()
    log_file = select_cost_log_path(config.library_dir)
    if log_file is None:
        return json.dumps(
            {
                "status": "ok",
                "runs": [],
                "total_cost": 0,
                "message": "No cost history yet.",
                "cost_history": CostLogScan().coverage(),
            },
            indent=2,
        )

    entries: list[dict[str, object]] = []
    now = datetime.now().astimezone()
    cutoff = now - timedelta(days=days)
    cost_scan = scan_confined_cost_log(log_file, config.library_dir)

    for loaded in cost_scan.rows:
        entry = project_cost_log_row(loaded)
        # Filter by date if timestamp available.
        ts = entry.get("timestamp")
        if isinstance(ts, str) and ts:
            try:
                entry_dt = datetime.fromisoformat(ts)
            except ValueError:
                entry_dt = None
            if entry_dt is not None:
                if entry_dt.tzinfo is None:
                    entry_dt = entry_dt.replace(tzinfo=now.tzinfo)
                if entry_dt.astimezone() < cutoff:
                    continue
        entries.append(entry)

    recent = entries[-limit:] if limit else []
    return _cost_result(recent, cost_scan, log_file)

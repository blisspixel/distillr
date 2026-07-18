# pyright: strict
"""MCP tools — costs: show recent LLM cost history."""

from __future__ import annotations

import json
from datetime import datetime, timedelta

from distill.mcp.server import load_config, mcp
from distill.pipeline.cost_history import (
    CostLogScan,
    cost_history_integrity_message,
    project_cost_log_row,
    scan_confined_cost_log,
    select_cost_log_path,
)

__all__: list[str] = []


def _actual_cost(value: object) -> float:
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, int | float):
        return float(value)
    return 0.0


def _invalid_range(name: str, minimum: int, maximum: int) -> str:
    return json.dumps(
        {
            "status": "error",
            "error": f"{name} must be an integer from {minimum} to {maximum}.",
        },
        indent=2,
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
    total = sum(_actual_cost(entry.get("actual_cost")) for entry in recent)

    return json.dumps(
        {
            "status": "ok" if cost_scan.complete else "warning",
            "runs": recent,
            "total_cost": round(total, 4),
            "runs_shown": len(recent),
            "total_scope": "returned_valid_runs",
            "cost_history": cost_scan.coverage(),
            **(
                {"message": cost_history_integrity_message(log_file, cost_scan)}
                if not cost_scan.complete
                else {}
            ),
        },
        indent=2,
    )

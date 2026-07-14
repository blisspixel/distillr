# pyright: strict
"""MCP tools — costs: show recent LLM cost history."""

from __future__ import annotations

import json
from datetime import datetime, timedelta

from distill.mcp.server import load_config, mcp
from distill.pipeline.cost_history import (
    find_confined_cost_log,
    project_cost_log_row,
    read_confined_cost_log_rows,
)

__all__: list[str] = []


def _actual_cost(value: object) -> float:
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, int | float):
        return float(value)
    return 0.0


@mcp.tool()
def costs(days: int = 30, limit: int = 20) -> str:
    """Show recent LLM cost history and per-run spend breakdown.

    Args:
        days: Lookback window in days
        limit: Max entries to return
    """
    config = load_config()
    log_file = find_confined_cost_log(config.library_dir)
    if log_file is None:
        return json.dumps(
            {"status": "ok", "runs": [], "total_cost": 0, "message": "No cost history yet."},
            indent=2,
        )

    entries: list[dict[str, object]] = []
    cutoff = datetime.now() - timedelta(days=days)

    for loaded in read_confined_cost_log_rows(log_file, config.library_dir):
        entry = project_cost_log_row(loaded)
        # Filter by date if timestamp available.
        ts = entry.get("timestamp")
        if isinstance(ts, str) and ts:
            try:
                entry_dt = datetime.fromisoformat(ts)
            except ValueError:
                entry_dt = None
            if entry_dt is not None and entry_dt < cutoff:
                continue
        entries.append(entry)

    recent = entries[-limit:]
    total = sum(_actual_cost(entry.get("actual_cost")) for entry in recent)

    return json.dumps(
        {
            "status": "ok",
            "runs": recent,
            "total_cost": round(total, 4),
            "runs_shown": len(recent),
        },
        indent=2,
    )

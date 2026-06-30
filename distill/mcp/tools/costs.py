# pyright: strict
"""MCP tools — costs: show recent LLM cost history."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any, cast

from distill.mcp.server import load_config, mcp

__all__: list[str] = []


def _cost_entry_from_json(line: str) -> dict[str, object] | None:
    try:
        raw: Any = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(raw, dict):
        return None
    mapping = cast("dict[object, object]", raw)
    return {str(key): value for key, value in mapping.items()}


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
    # Check new location first, fall back to old
    ops_log = config.library_dir / ".distill" / "cost_log.jsonl"
    legacy_log = config.library_dir / "cost_log.jsonl"
    log_file = ops_log if ops_log.exists() else legacy_log

    if not log_file.exists():
        return json.dumps(
            {"status": "ok", "runs": [], "total_cost": 0, "message": "No cost history yet."},
            indent=2,
        )

    entries: list[dict[str, object]] = []
    cutoff = datetime.now() - timedelta(days=days)

    for line in log_file.read_text(encoding="utf-8").strip().split("\n"):
        if not line.strip():
            continue
        entry = _cost_entry_from_json(line)
        if entry is None:
            continue
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

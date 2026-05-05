"""MCP tools — costs: show recent LLM cost history."""

from __future__ import annotations

import json
from datetime import datetime, timedelta

from distill.mcp import server as _server

__all__: list[str] = []


@_server.mcp.tool()
def costs(days: int = 30, limit: int = 20) -> str:
    """Show recent LLM cost history and per-run spend breakdown.

    Args:
        days: Lookback window in days
        limit: Max entries to return
    """
    config = _server._config()
    log_file = config.library_dir / "cost_log.jsonl"

    if not log_file.exists():
        return json.dumps(
            {"status": "ok", "runs": [], "total_cost": 0, "message": "No cost history yet."},
            indent=2,
        )

    entries = []
    cutoff = datetime.now() - timedelta(days=days)

    for line in log_file.read_text(encoding="utf-8").strip().split("\n"):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
            # Filter by date if timestamp available
            ts = entry.get("timestamp", "")
            if ts:
                try:
                    entry_dt = datetime.fromisoformat(ts)
                    if entry_dt < cutoff:
                        continue
                except (ValueError, TypeError):
                    pass
            entries.append(entry)
        except json.JSONDecodeError:
            continue

    recent = entries[-limit:]
    total = sum(e.get("actual_cost", 0) for e in recent)

    return json.dumps(
        {
            "status": "ok",
            "runs": recent,
            "total_cost": round(total, 4),
            "runs_shown": len(recent),
        },
        indent=2,
    )

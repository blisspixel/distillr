# pyright: strict
"""Bounded machine and operator contracts for dashboard presentation."""

from __future__ import annotations

import math
from pathlib import Path
from typing import cast

from distill.pipeline.dashboard_records import CostRun, DashboardSnapshot

_MAX_TOPICS = 100
_MAX_RECENT_RUNS = 10
_MAX_WARNINGS_PER_KIND = 20
_MAX_TEXT_CHARS = 500


def _bounded_text(value: object) -> str:
    return str(value)[:_MAX_TEXT_CHARS]


def _finite_float(value: object) -> float:
    if not isinstance(value, (int, float, str)) or isinstance(value, bool):
        return 0.0
    try:
        result = float(value)
    except (OverflowError, ValueError):
        return 0.0
    return result if math.isfinite(result) else 0.0


def _nonnegative_int(value: object) -> int:
    if not isinstance(value, (int, float, str)) or isinstance(value, bool):
        return 0
    try:
        result = int(value)
    except (OverflowError, ValueError):
        return 0
    return max(0, result)


def _library_dir(snapshot: DashboardSnapshot) -> Path:
    return snapshot["lib"].config.library_dir


def dashboard_evidence_paths(snapshot: DashboardSnapshot) -> dict[str, str]:
    """Return exact local evidence paths for a dashboard snapshot."""

    library_dir = _library_dir(snapshot)
    ops_dir = library_dir / ".distill"
    return {
        "library": str(library_dir),
        "latest_run": str(library_dir / "latest_run.json"),
        "latest_run_errors": str(library_dir / "latest_run_errors.md"),
        "latest_changes": str(library_dir / "library_Latest_Changes.md"),
        "debug_log": str(ops_dir / "distill.log"),
        "phase_telemetry": str(ops_dir / "phase_telemetry.jsonl"),
        "cost_ledger": str(ops_dir / "cost_log.jsonl"),
        "provider_telemetry": str(ops_dir / "telemetry.jsonl"),
    }


def _recent_run_data(entry: CostRun) -> dict[str, object]:
    return {
        "timestamp": _bounded_text(entry.get("timestamp", "")),
        "command": _bounded_text(entry.get("command", "unknown")),
        "actual_cost_usd": round(_finite_float(entry.get("actual_cost")), 6),
        "elapsed_seconds": round(_finite_float(entry.get("elapsed_seconds")), 6),
    }


def _warning_texts(values: list[object]) -> list[str]:
    return [_bounded_text(value) for value in values[:_MAX_WARNINGS_PER_KIND]]


def dashboard_json_data(version: str, snapshot: DashboardSnapshot) -> dict[str, object]:
    """Build the bounded primitive-only ``dashboard.v1`` JSON data object."""

    topics = snapshot["topics"]
    watchlist = snapshot["watchlist"]
    topic_watchlist = snapshot["topic_watchlist"]
    first_run = not any(
        (
            topics,
            watchlist,
            topic_watchlist,
            snapshot["total_videos"],
            snapshot["site_count"],
            snapshot["paper_count"],
            snapshot["all_cost_entries"],
        )
    )
    cost_warning_messages = [
        _bounded_text(item.get("message", ""))
        for item in snapshot["cost_warnings"][:_MAX_WARNINGS_PER_KIND]
    ]
    latest_failed = _nonnegative_int(snapshot["latest_results"].get("failed"))
    return {
        "schema_version": "dashboard.v1",
        "version": _bounded_text(version),
        "first_run": first_run,
        "metrics": {
            "topics": len(topics),
            "channels": snapshot["total_channels"],
            "videos": snapshot["total_videos"],
            "full_videos": snapshot["full_videos"],
            "scan_videos": snapshot["scan_videos"],
            "sites": snapshot["site_count"],
            "pages": snapshot["page_count"],
            "papers": snapshot["paper_count"],
            "reports": snapshot["report_count"],
            "briefs": snapshot["brief_count"],
            "syntheses": snapshot["synthesis_count"],
            "channel_watches": len(watchlist),
            "topic_watches": len(topic_watchlist),
            "due_topic_watches": snapshot["due_topic_watches"],
        },
        "spend": {
            "recent_usd": round(_finite_float(snapshot["recent_spend"]), 6),
            "next_sweep_usd": round(_finite_float(snapshot["next_sweep_cost"]), 6),
        },
        "topics": [_bounded_text(topic) for topic in topics[:_MAX_TOPICS]],
        "truncated": {
            "topics": max(0, len(topics) - _MAX_TOPICS),
            "recent_runs": max(0, len(snapshot["recent_runs"]) - _MAX_RECENT_RUNS),
        },
        "recent_runs": [
            _recent_run_data(entry) for entry in snapshot["recent_runs"][-_MAX_RECENT_RUNS:]
        ],
        "warnings": {
            "latest_failed_items": latest_failed,
            "latest_issues": len(snapshot["latest_issues"]),
            "stale_topic_watches": _warning_texts(
                cast(list[object], snapshot["stale_topic_watches"])
            ),
            "corpus_health": _warning_texts(cast(list[object], snapshot["corpus_health_warnings"])),
            "budgets": _warning_texts(cast(list[object], snapshot["budget_messages"])),
            "costs": cost_warning_messages,
        },
        "paths": dashboard_evidence_paths(snapshot),
        "next_commands": [
            "distill --cost-mode no-metered init"
            if first_run
            else "distill audit all --next-actions",
            "distill --cost-mode no-metered doctor",
            'distill --cost-mode no-metered papers "topic" -n 5 --preview'
            if first_run
            else "distill costs",
        ],
    }


__all__ = ["dashboard_evidence_paths", "dashboard_json_data"]

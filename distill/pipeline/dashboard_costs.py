"""Finite cost projections and rollups for dashboard consumers."""

# pyright: strict

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import datetime, timedelta
from pathlib import Path

from distill.config import DistillConfig
from distill.library import TopicWatchEntry
from distill.llm.router import RouterConfig
from distill.pipeline.cost_history import (
    CostLogScan,
    cost_history_integrity_message,
)
from distill.pipeline.cost_warnings import CostWarning
from distill.pipeline.costs import (
    cost_anomaly_warnings,
    estimate_routed_video_workflow_cost,
    report_deep_research_estimate,
)
from distill.pipeline.dashboard_records import CostRollup, CostRun, json_object


def int_value(value: object, default: int = 0) -> int:
    if not isinstance(value, bool) and isinstance(value, (int, float, str)):
        try:
            return int(value)
        except (OverflowError, ValueError):
            return default
    return default


def _cost_value(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if not isinstance(value, int | float | str):
        return None
    try:
        cost = float(value)
    except (OverflowError, ValueError):
        return None
    return cost if math.isfinite(cost) and cost >= 0 else None


def _finite_cost_total(values: Sequence[float]) -> float | None:
    try:
        total = math.fsum(values)
    except OverflowError:
        return None
    return total if math.isfinite(total) else None


def sum_recent_cost(entries: Sequence[CostRun]) -> float | None:
    values: list[float] = []
    for entry in entries:
        cost = _cost_value(entry.get("actual_cost"))
        if cost is None:
            return None
        values.append(cost)
    return _finite_cost_total(values)


def format_run_timestamp(value: str) -> str:
    if not value:
        return "unknown"
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.strftime("%b %d %I:%M %p")
    except ValueError:
        return value


def parse_run_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is not None:
            dt = dt.replace(tzinfo=None)
        return dt
    except ValueError:
        return None


def estimated_topic_watch_sweep(
    topic_watchlist: Sequence[TopicWatchEntry],
    *,
    router_config: RouterConfig | None = None,
) -> float:
    rc = router_config or RouterConfig()
    total = 0.0
    for entry in topic_watchlist:
        total += estimate_routed_video_workflow_cost(
            full_videos=entry.limit,
            router_config=rc,
        )
        if entry.report:
            total += report_deep_research_estimate()
    return total


def estimate_topic_watch_cost(
    entry: TopicWatchEntry,
    *,
    router_config: RouterConfig | None = None,
) -> float:
    total = estimate_routed_video_workflow_cost(
        full_videos=entry.limit,
        router_config=router_config,
    )
    if entry.report:
        total += report_deep_research_estimate()
    return total


def topic_spend_last_days(
    entries: Sequence[CostRun],
    topic: str,
    days: int = 30,
) -> float | None:
    cutoff = datetime.now() - timedelta(days=days)
    costs: list[float] = []
    for entry in entries:
        metadata = json_object(entry.get("metadata"))
        if metadata.get("topic") != topic:
            continue
        timestamp = parse_run_datetime(str(entry.get("timestamp", "")))
        if timestamp is None or timestamp < cutoff:
            continue
        if entry.get("external_cost_status") == "unavailable":
            return None
        cost = _cost_value(entry.get("actual_cost"))
        if cost is None:
            return None
        costs.append(cost)
    return _finite_cost_total(costs)


def topic_recent_costs(
    entries: Sequence[CostRun],
    topic: str,
    limit: int = 5,
) -> list[float] | None:
    values: list[tuple[datetime, float]] = []
    for entry in entries:
        metadata = json_object(entry.get("metadata"))
        if metadata.get("topic") != topic:
            continue
        timestamp = parse_run_datetime(str(entry.get("timestamp", "")))
        if timestamp is None:
            continue
        if entry.get("external_cost_status") == "unavailable":
            return None
        cost = _cost_value(entry.get("actual_cost"))
        if cost is None:
            return None
        values.append((timestamp, cost))
    values.sort(key=lambda item: item[0], reverse=True)
    return [cost for _, cost in values[:limit]]


def _monthly_budget_message(
    entry: TopicWatchEntry,
    all_cost_entries: Sequence[CostRun],
    projected: float,
) -> str | None:
    if not entry.monthly_budget:
        return None
    monthly_spend = topic_spend_last_days(all_cost_entries, entry.topic, days=30)
    if monthly_spend is None:
        return (
            f"{entry.name} monthly budget status is unavailable because cost values "
            "cannot be aggregated safely"
        )
    projected_monthly = _finite_cost_total((monthly_spend, projected))
    if projected_monthly is None:
        return (
            f"{entry.name} monthly budget status is unavailable because cost values "
            "cannot be aggregated safely"
        )
    if projected_monthly > entry.monthly_budget:
        return (
            f"{entry.name} projected monthly spend ${projected_monthly:.2f} "
            f"exceeds monthly budget ${entry.monthly_budget:.2f}"
        )
    return None


def _spend_spike_message(
    entry: TopicWatchEntry,
    all_cost_entries: Sequence[CostRun],
) -> str | None:
    recent_costs = topic_recent_costs(all_cost_entries, entry.topic, limit=4)
    if recent_costs is None:
        return (
            f"{entry.name} spend-spike status is unavailable because cost values "
            "cannot be aggregated safely"
        )
    if len(recent_costs) < 2:
        return None
    baseline = _finite_cost_total(
        [value / max(len(recent_costs) - 1, 1) for value in recent_costs[1:]]
    )
    latest = recent_costs[0]
    if baseline is None or (baseline > 0 and not math.isfinite(baseline * 2.5)):
        return (
            f"{entry.name} spend-spike status is unavailable because cost values "
            "cannot be aggregated safely"
        )
    if baseline > 0 and latest >= baseline * 2.5:
        return f"{entry.topic} spend spike: latest ${latest:.2f} vs recent baseline ${baseline:.2f}"
    return None


def topic_watch_budget_messages(
    entry: TopicWatchEntry,
    all_cost_entries: Sequence[CostRun],
) -> list[str]:
    messages: list[str] = []
    projected = estimate_topic_watch_cost(entry)
    if entry.max_run_cost and projected > entry.max_run_cost:
        messages.append(
            f"{entry.name} projected ${projected:.2f} exceeds max-run budget "
            f"${entry.max_run_cost:.2f}"
        )
    for message in (
        _monthly_budget_message(entry, all_cost_entries, projected),
        _spend_spike_message(entry, all_cost_entries),
    ):
        if message:
            messages.append(message)
    return messages


def entry_source_type(entry: CostRun) -> str:
    metadata = json_object(entry.get("metadata"))
    source_type = metadata.get("source_type")
    if source_type:
        return str(source_type)
    command = str(entry.get("command", ""))
    if command in {"site", "site-batch"}:
        return "website"
    if command == "report":
        return "report"
    return "youtube"


def topic_cost_rollups(
    entries: Sequence[CostRun],
    days: int = 30,
    limit: int = 5,
) -> list[CostRollup]:
    cutoff = datetime.now() - timedelta(days=days)
    rollups: dict[str, tuple[float, int]] = {}
    for entry in entries:
        timestamp = parse_run_datetime(str(entry.get("timestamp", "")))
        if timestamp is None or timestamp < cutoff:
            continue
        metadata = json_object(entry.get("metadata"))
        topic = str(metadata.get("topic") or "").strip()
        if not topic:
            continue
        cost = _cost_value(entry.get("actual_cost"))
        if cost is None:
            return []
        current_cost, current_runs = rollups.get(topic, (0.0, 0))
        aggregate = _finite_cost_total((current_cost, cost))
        if aggregate is None:
            return []
        rollups[topic] = (aggregate, current_runs + 1)
    items: list[CostRollup] = [(topic, cost, runs) for topic, (cost, runs) in rollups.items()]
    items.sort(key=lambda item: item[1], reverse=True)
    return items[:limit]


def source_cost_rollups(
    entries: Sequence[CostRun],
    days: int = 30,
) -> list[CostRollup]:
    cutoff = datetime.now() - timedelta(days=days)
    rollups: dict[str, tuple[float, int]] = {}
    for entry in entries:
        timestamp = parse_run_datetime(str(entry.get("timestamp", "")))
        if timestamp is None or timestamp < cutoff:
            continue
        source_type = entry_source_type(entry)
        cost = _cost_value(entry.get("actual_cost"))
        if cost is None:
            return []
        current_cost, current_runs = rollups.get(source_type, (0.0, 0))
        aggregate = _finite_cost_total((current_cost, cost))
        if aggregate is None:
            return []
        rollups[source_type] = (aggregate, current_runs + 1)
    items: list[CostRollup] = [(source, cost, runs) for source, (cost, runs) in rollups.items()]
    items.sort(key=lambda item: item[1], reverse=True)
    return items


def dashboard_cost_surfaces(
    config: DistillConfig,
    log_path: Path,
    cost_scan: CostLogScan,
    entries: list[CostRun],
    topic_watchlist: Sequence[TopicWatchEntry],
) -> tuple[float | None, list[CostRollup], list[CostRollup], list[CostWarning], list[str]]:
    """Build dashboard cost claims only when the complete ledger supports them."""

    recent_spend = sum_recent_cost(entries[-6:]) if cost_scan.complete else None
    aggregate_available = cost_scan.complete and sum_recent_cost(entries) is not None
    if not aggregate_available:
        message = (
            "Cost totals, anomaly checks, and budget rollups are unavailable because "
            "valid cost values exceed the supported aggregate range."
            if cost_scan.complete
            else cost_history_integrity_message(log_path, cost_scan)
            + " Spending rollups and budget checks are unavailable until the ledger is repaired."
        )
        return recent_spend, [], [], [], [message]

    topic_spend = topic_cost_rollups(entries, days=30, limit=4)
    source_spend = source_cost_rollups(entries, days=30)
    warnings = cost_anomaly_warnings(
        entries,
        daily_threshold_usd=config.distill_cost_warning_daily_usd,
        spike_multiplier=config.distill_cost_warning_spike_multiplier,
        run_spike_min_usd=config.distill_cost_warning_run_spike_min_usd,
        workflow_budgets_usd=config.cost_workflow_budgets_usd,
    )
    budget_messages = [
        message
        for entry in topic_watchlist
        for message in topic_watch_budget_messages(entry, entries)
    ]
    return recent_spend, topic_spend, source_spend, warnings, budget_messages

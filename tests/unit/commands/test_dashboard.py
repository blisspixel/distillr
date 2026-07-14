from __future__ import annotations

from datetime import datetime
from io import StringIO
from types import SimpleNamespace
from typing import Any

from rich.console import Console

from distill.commands import dashboard as _dashboard


def _console_buffer(monkeypatch) -> StringIO:
    stream = StringIO()
    monkeypatch.setattr(
        _dashboard,
        "console",
        Console(file=stream, force_terminal=False, width=140, color_system=None),
    )
    return stream


def _channels(count: int) -> list[SimpleNamespace]:
    return [SimpleNamespace(name=f"Channel{i}") for i in range(count)]


def _watch(name: str, topic: str, *, days: int = 7, instructions: str = "") -> SimpleNamespace:
    return SimpleNamespace(
        name=name,
        topic=topic,
        days=days,
        instructions=instructions,
        active_instructions=instructions,
    )


def _topic_watch(
    name: str,
    topic: str,
    *,
    cadence: str = "daily",
    days: int = 7,
    limit: int = 5,
    report: bool = False,
    max_run_cost: float | None = None,
    monthly_budget: float | None = None,
    paused: bool = False,
    last_run_at: str | None = None,
    ranking_mode: str = "balanced",
) -> SimpleNamespace:
    return SimpleNamespace(
        name=name,
        topic=topic,
        cadence=cadence,
        days=days,
        limit=limit,
        report=report,
        max_run_cost=max_run_cost,
        monthly_budget=monthly_budget,
        paused=paused,
        last_run_at=last_run_at,
        ranking_mode=ranking_mode,
    )


def _snapshot(**overrides: Any) -> dict[str, Any]:
    channel_counts = {f"topic{i}": (i % 3) + 1 for i in range(8)}
    default: dict[str, Any] = {
        "lib": SimpleNamespace(
            get_channels=lambda topic: _channels(channel_counts.get(str(topic), 0))
        ),
        "topics": list(channel_counts),
        "watchlist": [
            _watch("watch0", "topic0", instructions="custom"),
            *[_watch(f"watch{i}", f"topic{i}") for i in range(1, 7)],
        ],
        "topic_watchlist": [
            _topic_watch(
                "topic-watch0",
                "topic0",
                report=True,
                max_run_cost=1.5,
                monthly_budget=3.0,
                paused=True,
                last_run_at="2026-06-01T10:00:00",
            ),
            *[_topic_watch(f"topic-watch{i}", f"topic{i}") for i in range(1, 7)],
        ],
        "total_channels": 12,
        "total_videos": 4,
        "full_videos": 3,
        "scan_videos": 1,
        "site_count": 2,
        "page_count": 5,
        "paper_count": 3,
        "report_count": 2,
        "brief_count": 1,
        "synthesis_count": 4,
        "all_cost_entries": [{"actual_cost": 1.0}],
        "recent_runs": [
            {
                "timestamp": "2026-06-01T09:00:00",
                "command": "learn",
                "actual_cost": "bad",
                "elapsed_seconds": 2.5,
            },
            {
                "timestamp": "2026-06-02T09:00:00",
                "command": "report",
                "actual_cost": 0.25,
                "elapsed_seconds": "bad",
            },
        ],
        "recent_spend": 1.25,
        "latest_results": {"failed": 2},
        "latest_issues": [{"stage": "fetch"}],
        "recent_artifacts": [(datetime(2026, 6, 2, 12, 0), "report", "topic0")],
        "topic_changes": [("topic0", "+2 videos")],
        "topic_trends": {"topic0": "trend: rising"},
        "stale_topic_watches": ["topic-watch0 is stale"],
        "corpus_health_warnings": ["topic0 synthesis is stale"],
        "next_sweep_cost": 4.5,
        "due_topic_watches": 1,
        "topic_spend_rollups": [("topic0", 1.25, 1)],
        "source_spend_rollups": [("youtube", 1.0, 2), ("report", 0.25, 1)],
        "cost_warnings": [
            {
                "kind": "daily-threshold",
                "message": "Daily spend on 2026-06-03 reached $12.00.",
                "date": "2026-06-03",
                "cost": 12.0,
            }
        ],
        "budget_messages": ["topic-watch0 projected monthly spend exceeds budget"],
    }
    default.update(overrides)
    return default


def test_cost_run_helpers_normalize_missing_invalid_and_non_numeric_values() -> None:
    assert _dashboard._cost_run_text({}, "missing", "fallback") == "fallback"
    assert _dashboard._cost_run_float({"cost": "bad"}, "cost") == 0.0
    assert _dashboard._cost_run_float({"cost": object()}, "cost") == 0.0


def test_show_dashboard_falls_back_to_first_run_when_config_fails(monkeypatch) -> None:
    stream = _console_buffer(monkeypatch)
    monkeypatch.setattr(
        _dashboard,
        "get_config",
        lambda: (_ for _ in ()).throw(RuntimeError("missing config")),
    )

    _dashboard._show_dashboard()

    output = stream.getvalue()
    assert "Distill Start" in output
    assert "distill video" in output


def test_show_dashboard_renders_overflow_attention_and_next_actions(monkeypatch) -> None:
    stream = _console_buffer(monkeypatch)
    monkeypatch.setattr(_dashboard, "get_config", lambda: SimpleNamespace())
    monkeypatch.setattr(_dashboard, "_dashboard_snapshot", lambda _config: _snapshot())

    _dashboard._show_dashboard()

    output = stream.getvalue()
    assert "Distill Home" in output
    assert "+2 more" in output
    assert "topic-watch0" in output
    assert "paused" in output
    assert "trend: rising" in output
    assert "failed video items" in output
    assert "Daily spend on 2026-06-03 reached $12.00" in output
    assert "distill run topic0 --refresh" in output


def test_show_dashboard_renders_empty_non_first_run_sections(monkeypatch) -> None:
    stream = _console_buffer(monkeypatch)
    monkeypatch.setattr(_dashboard, "get_config", lambda: SimpleNamespace())
    monkeypatch.setattr(
        _dashboard,
        "_dashboard_snapshot",
        lambda _config: _snapshot(
            topics=[],
            watchlist=[_watch("watch0", "topic0")],
            topic_watchlist=[],
            total_channels=0,
            recent_runs=[],
            latest_results={},
            latest_issues=[],
            recent_artifacts=[],
            topic_changes=[],
            topic_trends={},
            stale_topic_watches=[],
            corpus_health_warnings=[],
            topic_spend_rollups=[],
            source_spend_rollups=[],
            cost_warnings=[],
            budget_messages=[],
        ),
    )

    _dashboard._show_dashboard()

    output = stream.getvalue()
    assert "No topics yet" in output
    assert "No runs logged yet" in output
    assert "No recent synthesis/report artifacts detected" in output
    assert "No immediate issues detected" in output
    assert "distill latest" in output


def test_render_dashboard_html_renders_budget_trends_changes_and_attention() -> None:
    html = _dashboard.render_dashboard_html("1.2.3", _snapshot())

    assert "topic-watch0 - topic0 / daily / 7d / 5 picks / max $1.50/run" in html
    assert "$3.00/30d" in html
    assert "paused" in html
    assert "trend: rising" in html
    assert "topic0: +2 videos (trend: rising)" in html
    assert "Latest run failed items: 2" in html
    assert "Latest run issues: 1" in html
    assert "Daily spend on 2026-06-03 reached $12.00" in html


def test_render_dashboard_html_uses_artifact_and_empty_fallbacks() -> None:
    html = _dashboard.render_dashboard_html(
        "dev",
        _snapshot(
            topics=[],
            watchlist=[],
            topic_watchlist=[],
            total_channels=0,
            total_videos=0,
            full_videos=0,
            scan_videos=0,
            site_count=0,
            page_count=0,
            paper_count=0,
            report_count=0,
            brief_count=0,
            synthesis_count=0,
            recent_runs=[],
            recent_spend=0.0,
            latest_results={},
            latest_issues=[],
            topic_changes=[],
            topic_trends={},
            stale_topic_watches=[],
            corpus_health_warnings=[],
            next_sweep_cost=0.0,
            due_topic_watches=0,
            topic_spend_rollups=[],
            source_spend_rollups=[],
            cost_warnings=[],
            budget_messages=[],
            recent_artifacts=[(datetime(2026, 6, 1, 8, 0), "brief", "topic0")],
        ),
    )

    assert "<li>None</li>" in html
    assert "brief: topic0 Jun 01 08:00 AM" in html
    assert "No runs logged yet" in html
    assert "No immediate issues detected" in html

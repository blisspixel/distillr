# pyright: strict
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import typer

from distill.commands.monitor import monitor


def _call_monitor(
    query: str = "ai agents",
    topic: str = "",
    name: str = "",
    cadence: str = "daily",
    days: int = 1,
    limit: int = 10,
    sort: str = "date",
    per_channel_cap: int = 3,
    ranking: str = "balanced",
    report: bool = False,
    max_run_cost: float = 0.0,
    monthly_budget: float = 0.0,
    now: bool = False,
    preview: bool = False,
) -> None:
    monitor(
        query=query,
        topic=topic,
        name=name,
        cadence=cadence,
        days=days,
        limit=limit,
        sort=sort,
        per_channel_cap=per_channel_cap,
        ranking=ranking,
        report=report,
        max_run_cost=max_run_cost,
        monthly_budget=monthly_budget,
        now=now,
        preview=preview,
    )


def test_monitor_invalid_cadence():
    with pytest.raises(typer.BadParameter, match="--cadence must be 'daily' or 'weekly'"):
        _call_monitor(query="quantum computing", cadence="monthly")


def test_monitor_creates_watch_without_now():
    with (
        patch("distill.commands.monitor.get_config") as mock_get_config,
        patch("distill.commands.monitor.Library") as mock_lib_cls,
        patch("distill.commands.monitor.console") as mock_console,
    ):
        mock_config = MagicMock()
        mock_get_config.return_value = mock_config
        mock_lib = MagicMock()
        mock_lib.add_to_topic_watchlist.return_value = True
        mock_lib_cls.return_value = mock_lib

        _call_monitor(
            query="ai agents",
            topic="agents",
            name="agent-watch",
            cadence="daily",
            days=2,
            limit=5,
            now=False,
            preview=False,
        )

        mock_lib.add_to_topic_watchlist.assert_called_once_with(
            "agent-watch",
            "ai agents",
            topic="agents",
            cadence="daily",
            days=2,
            limit=5,
            sort="date",
            channel_cap=3,
            ranking_mode="balanced",
            report=False,
            max_run_cost=0.0,
            monthly_budget=0.0,
        )
        assert any(
            "distill topic-watch run agent-watch" in str(c)
            for c in mock_console.print.call_args_list
        )


def test_monitor_existing_watch():
    with (
        patch("distill.commands.monitor.get_config"),
        patch("distill.commands.monitor.Library") as mock_lib_cls,
        patch("distill.commands.monitor.console") as mock_console,
    ):
        mock_lib = MagicMock()
        mock_lib.add_to_topic_watchlist.return_value = False
        mock_lib_cls.return_value = mock_lib

        _call_monitor(
            query="ai agents",
            topic="agents",
            name="agent-watch",
            now=False,
            preview=False,
        )

        assert any("already exists" in str(c) for c in mock_console.print.call_args_list)


def test_monitor_with_preview():
    with (
        patch("distill.commands.monitor.get_config"),
        patch("distill.commands.monitor.Library") as mock_lib_cls,
        patch("distill.commands.monitor._preview_learning_selection") as mock_preview,
        patch("distill.commands.monitor.log_preview_cost") as mock_log_cost,
    ):
        mock_lib = MagicMock()
        mock_lib.add_to_topic_watchlist.return_value = True
        mock_lib_cls.return_value = mock_lib

        mock_preview_cfg = MagicMock()
        mock_preview_cfg.library_dir = "/tmp/library"
        mock_preview_tracker = MagicMock()
        mock_preview.return_value = (mock_preview_cfg, mock_preview_tracker, [])

        _call_monitor(
            query="robotics",
            topic="robotics",
            name="robot-watch",
            preview=True,
        )

        mock_preview.assert_called_once()
        mock_log_cost.assert_called_once_with(
            mock_preview_tracker,
            "/tmp/library",
            "monitor",
            metadata={"watch": "robot-watch", "topic": "robotics"},
        )


def test_monitor_with_now():
    with (
        patch("distill.commands.monitor.get_config"),
        patch("distill.commands.monitor.Library") as mock_lib_cls,
        patch("distill.commands.monitor.topic_watch_run") as mock_run,
    ):
        mock_lib = MagicMock()
        mock_lib.add_to_topic_watchlist.return_value = True
        mock_lib_cls.return_value = mock_lib

        _call_monitor(
            query="robotics",
            topic="robotics",
            name="robot-watch",
            now=True,
            preview=False,
        )

        mock_run.assert_called_once_with(
            name="robot-watch",
            preview=False,
            topic=None,
            ignore_budget=False,
        )

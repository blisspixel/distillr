"""Boundary tests for topic change summaries and watch baselines."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
import typer

from distill.commands import _topic_changes
from distill.config import DistillConfig
from distill.library import Library


def _trend_records(latest: int, previous: int) -> list[dict[str, Any]]:
    now = datetime.now().replace(microsecond=0)
    return [
        {
            "generated_at": now,
            "topic": "ai",
            "watch_name": "AI daily",
            "query": "ai",
            "cadence": "daily",
            "baseline": "",
            "summary": "latest",
            "counts": {"videos": latest, "pages": 0, "papers": 0, "outputs": 0},
        },
        {
            "generated_at": now - timedelta(days=1),
            "topic": "ai",
            "watch_name": "AI daily",
            "query": "ai",
            "cadence": "daily",
            "baseline": "",
            "summary": "previous",
            "counts": {"videos": previous, "pages": 0, "papers": 0, "outputs": 0},
        },
    ]


def test_topic_change_path_and_page_render_preserve_external_evidence(
    config: DistillConfig,
    tmp_path: Path,
) -> None:
    outside = tmp_path.parent / "outside.md"
    rendered = _topic_changes._format_page_change(
        config,
        cast(
            Any,
            {
                "site": "example.com",
                "title": "External page",
                "url": "https://example.com/page",
                "changed_at": datetime.now(),
                "path": outside,
            },
        ),
    )

    assert _topic_changes._relative_library_path(config, outside) == str(outside.resolve())
    assert "URL: https://example.com/page" in rendered
    assert str(outside.resolve()) in rendered


def test_topic_trend_helpers_cover_insufficient_cooling_and_steady_history(
    config: DistillConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    increasing = _trend_records(3, 1)
    cooling = _trend_records(1, 3)
    steady = _trend_records(2, 2)

    assert _topic_changes._topic_trend_direction(cast(Any, cooling)) == "activity is cooling"
    assert _topic_changes._topic_trend_direction(cast(Any, steady)) == "activity is steady"

    monkeypatch.setattr(_topic_changes, "_load_topic_change_history", lambda *args: increasing[:1])
    assert _topic_changes._topic_trend_label(config, "ai", min_records=1) is None
    monkeypatch.setattr(_topic_changes, "_load_topic_change_history", lambda *args: increasing)
    assert _topic_changes._topic_trend_label(config, "ai") == "trend: rising"
    monkeypatch.setattr(_topic_changes, "_load_topic_change_history", lambda *args: cooling)
    assert _topic_changes._topic_trend_label(config, "ai") == "trend: cooling"
    monkeypatch.setattr(_topic_changes, "_load_topic_change_history", lambda *args: steady)
    assert _topic_changes._topic_trend_label(config, "ai") == "trend: steady"


def test_topic_change_history_skips_invalid_timestamp(config: DistillConfig) -> None:
    path = _topic_changes._topic_change_history_path(config, "ai")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                json.dumps({"generated_at": "not-a-timestamp", "counts": {"videos": 9}}),
                json.dumps(
                    {
                        "generated_at": "2026-07-18T12:00:00",
                        "topic": "ai",
                        "summary": "+1 video",
                        "counts": {"videos": 1},
                    }
                ),
            ]
        ),
        encoding="utf-8",
    )

    records = _topic_changes._load_topic_change_history(config, "ai")

    assert len(records) == 1
    assert records[0]["counts"]["videos"] == 1


def test_topic_change_snapshot_handles_channel_without_video_directory(
    config: DistillConfig,
) -> None:
    library = Library(config)
    library.add_channel("ai", "https://www.youtube.com/@channel", "Channel")
    baseline = datetime.now().replace(microsecond=0)

    last_change, summary = _topic_changes.topic_change_snapshot(config, library, "ai", baseline)

    assert last_change is None
    assert summary.startswith("quiet since")


def test_topic_watch_baseline_rejects_missing_and_cross_topic_watch() -> None:
    missing_library = SimpleNamespace(get_topic_watch_entry=lambda _name: None)
    with pytest.raises(typer.BadParameter, match="Unknown topic watch"):
        _topic_changes.resolve_topic_diff_baseline(
            cast(Any, missing_library),
            "ai",
            watch_name="missing",
            days=7,
        )

    wrong_topic = SimpleNamespace(
        topic="ml",
        name="ML daily",
        query="ml",
        cadence="daily",
        last_run_at=None,
    )
    wrong_library = SimpleNamespace(get_topic_watch_entry=lambda _name: wrong_topic)
    with pytest.raises(typer.BadParameter, match="belongs to ml, not ai"):
        _topic_changes.resolve_topic_diff_baseline(
            cast(Any, wrong_library),
            "ai",
            watch_name="ml-daily",
            days=7,
        )

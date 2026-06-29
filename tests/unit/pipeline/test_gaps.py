"""Tests for distill.pipeline.gaps (coverage gaps + gap-driven discovery goal)."""

from __future__ import annotations

from pathlib import Path

from distill.config import DistillConfig
from distill.pipeline.gaps import (
    gap_discovery_goal,
    topic_gap_summary,
    topic_source_inventory,
    video_list,
)


def _cfg(tmp_path: Path) -> DistillConfig:
    return DistillConfig(distill_output_dir=tmp_path / "lib")


def test_video_list_degrades_on_corrupt_metadata(tmp_path: Path):
    # A corrupt metadata.json (e.g. interrupted run) must not crash video_list
    # and the MCP resources/tools built on it -- the bad entry is skipped.
    cfg = _cfg(tmp_path)
    good = cfg.video_dir("tkg", "Chan", "good")
    good.mkdir(parents=True, exist_ok=True)
    (good / "metadata.json").write_text(
        '{"title": "Good", "upload_date": "20260401"}', encoding="utf-8"
    )
    bad = cfg.video_dir("tkg", "Chan", "bad")
    bad.mkdir(parents=True, exist_ok=True)
    (bad / "metadata.json").write_text("{ not valid json", encoding="utf-8")

    result = video_list(cfg, "tkg", "Chan")

    assert [v.get("title") for v in result] == ["Good"]


def test_video_list_parses_video_resource_metadata(tmp_path: Path):
    cfg = _cfg(tmp_path)
    video_dir = cfg.video_dir("tkg", "Chan", "vid001")
    video_dir.mkdir(parents=True, exist_ok=True)
    (video_dir / "metadata.json").write_text(
        (
            '{"title": "Contract Video", "upload_date": "20260401", '
            '"duration": "900", "url": "https://youtube.com/watch?v=vid001", '
            '"analysis_mode": "scan"}'
        ),
        encoding="utf-8",
    )

    result = video_list(cfg, "tkg", "Chan")

    assert result[0]["duration"] == 900
    assert result[0]["url"] == "https://youtube.com/watch?v=vid001"
    assert result[0]["analysis_mode"] == "scan"


def test_video_list_defaults_malformed_resource_metadata(tmp_path: Path):
    cfg = _cfg(tmp_path)
    video_dir = cfg.video_dir("tkg", "Chan", "vid001")
    video_dir.mkdir(parents=True, exist_ok=True)
    (video_dir / "metadata.json").write_text(
        '{"title": "Bad Shape", "upload_date": "20260401", "duration": true, "analysis_mode": 7}',
        encoding="utf-8",
    )

    result = video_list(cfg, "tkg", "Chan")

    assert result[0]["duration"] == 0
    assert result[0]["url"] == ""
    assert result[0]["analysis_mode"] == "unknown"


def test_inventory_and_gaps_on_empty_topic(tmp_path: Path):
    cfg = _cfg(tmp_path)
    inv = topic_source_inventory(cfg, "tkg")
    assert inv["videos"] == 0 and inv["papers"] == 0 and inv["active_source_types"] == []
    summary = topic_gap_summary(cfg, "tkg")
    assert summary["topic"] == "tkg"
    assert summary["gaps"]  # at least one gap detected
    assert summary["recommended_actions"]
    assert summary["next_actions"] == summary["recommended_actions"]
    # an empty topic is single-source/no-source and missing synthesis
    assert any("single-source" in g for g in summary["gaps"])


def test_gap_discovery_goal_uses_topic_and_gaps():
    summary = {
        "topic": "tkg",
        "active_source_types": ["youtube"],
        "gaps": [
            "Coverage is effectively single-source (youtube).",
            "Only 2 processed video(s) are available for this topic.",
        ],
    }
    goal = gap_discovery_goal(summary)
    assert "tkg" in goal
    assert "single-source" in goal
    assert "cross-source validation" in goal  # single-source -> prioritize other types
    assert goal.strip()


def test_gap_discovery_goal_no_real_gaps_is_still_a_goal():
    summary = {
        "topic": "tkg",
        "active_source_types": ["youtube", "paper", "website"],
        "gaps": ["No major research gaps detected from the local corpus heuristics."],
    }
    goal = gap_discovery_goal(summary)
    assert "tkg" in goal
    assert goal.strip()  # never empty -> discover always has something to do

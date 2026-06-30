"""Tests for distill.pipeline.gaps (coverage gaps + gap-driven discovery goal)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from distill.config import DistillConfig
from distill.library import Library
from distill.library.paths import artifact_path
from distill.pipeline.gaps import (
    gap_discovery_goal,
    topic_gap_summary,
    topic_source_inventory,
    video_list,
)


def _cfg(tmp_path: Path) -> DistillConfig:
    return DistillConfig(distill_output_dir=tmp_path / "lib")


def _date_ago(days: int) -> str:
    return (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")


def _write_artifact(
    directory: Path,
    artifact_type: str,
    body: str,
    *,
    extension: str = "md",
    identity: str | None = None,
) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = artifact_path(directory, artifact_type, extension=extension, identity=identity)
    path.write_text(body, encoding="utf-8")
    return path


def _write_video(
    cfg: DistillConfig,
    topic: str,
    channel: str,
    video_id: str,
    *,
    upload_date: str | None = None,
    insights: str | None = None,
    transcript: str | None = None,
) -> Path:
    video_dir = cfg.video_dir(topic, channel, video_id)
    video_dir.mkdir(parents=True, exist_ok=True)
    video_dir.joinpath("metadata.json").write_text(
        json.dumps(
            {
                "title": video_id,
                "upload_date": upload_date or _date_ago(1),
                "duration": 900,
                "url": f"https://youtube.com/watch?v={video_id}",
            }
        ),
        encoding="utf-8",
    )
    if insights is not None:
        _write_artifact(video_dir, "insights", insights)
    if transcript is not None:
        _write_artifact(video_dir, "transcript", transcript, extension="txt")
    return video_dir


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


def test_video_list_handles_missing_unreadable_and_non_object_metadata(tmp_path: Path, monkeypatch):
    cfg = _cfg(tmp_path)
    assert video_list(cfg, "tkg", "Missing") == []

    no_meta = cfg.video_dir("tkg", "Chan", "no-meta")
    no_meta.mkdir(parents=True, exist_ok=True)
    not_dir = cfg.videos_dir("tkg", "Chan") / "not-a-dir.txt"
    not_dir.write_text("skip", encoding="utf-8")
    non_object = cfg.video_dir("tkg", "Chan", "non-object")
    non_object.mkdir(parents=True, exist_ok=True)
    non_object.joinpath("metadata.json").write_text("[]", encoding="utf-8")
    locked = cfg.video_dir("tkg", "Chan", "locked")
    locked.mkdir(parents=True, exist_ok=True)
    locked_meta = locked / "metadata.json"
    locked_meta.write_text('{"title": "Locked"}', encoding="utf-8")
    invalid_duration = cfg.video_dir("tkg", "Chan", "invalid-duration")
    invalid_duration.mkdir(parents=True, exist_ok=True)
    invalid_duration.joinpath("metadata.json").write_text(
        '{"title": "Invalid Duration", "upload_date": "bad-date", "duration": "not-int"}',
        encoding="utf-8",
    )
    original_read_text = Path.read_text

    def read_text(path: Path, *args, **kwargs):
        if path == locked_meta:
            raise OSError("locked")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read_text)

    result = video_list(cfg, "tkg", "Chan")

    assert [video["title"] for video in result] == ["Invalid Duration"]
    assert result[0]["duration"] == 0


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


def test_inventory_counts_mixed_sources_and_skips_non_directories(tmp_path: Path):
    cfg = _cfg(tmp_path)
    lib = Library(cfg)
    lib.add_channel("tkg", "https://youtube.com/@Chan", "Chan")
    _write_video(cfg, "tkg", "Chan", "v1", upload_date=_date_ago(2))
    _write_video(cfg, "tkg", "Chan", "bad-date", upload_date="not-a-date")
    no_date = cfg.video_dir("tkg", "Chan", "no-date")
    no_date.mkdir(parents=True, exist_ok=True)
    no_date.joinpath("metadata.json").write_text('{"title": "No Date"}', encoding="utf-8")

    sites_root = cfg.sites_dir("tkg")
    sites_root.mkdir(parents=True, exist_ok=True)
    sites_root.joinpath("not-a-site.txt").write_text("skip", encoding="utf-8")
    site_dir = cfg.site_dir("tkg", "example.com")
    _write_artifact(
        site_dir, "site_synthesis", "# site", extension="md", identity="tkg_example.com"
    )
    pages_dir = site_dir / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    pages_dir.joinpath("not-a-page.txt").write_text("skip", encoding="utf-8")
    page_dir = cfg.site_page_dir("tkg", "example.com", "Page")
    _write_artifact(page_dir, "content", "content")
    cfg.site_page_dir("tkg", "example.com", "Empty Page").mkdir(parents=True, exist_ok=True)
    cfg.site_dir("tkg", "empty.com").mkdir(parents=True, exist_ok=True)

    papers_root = cfg.papers_dir("tkg")
    papers_root.mkdir(parents=True, exist_ok=True)
    papers_root.joinpath("not-a-paper.txt").write_text("skip", encoding="utf-8")
    _write_artifact(cfg.paper_dir("tkg", "Paper", "2602.12670"), "insights", "# paper")
    cfg.paper_dir("tkg", "Empty Paper", "2602.99999").mkdir(parents=True, exist_ok=True)

    inv = topic_source_inventory(cfg, "tkg")

    assert inv["channels"] == 1
    assert inv["videos"] == 3
    assert inv["sites"] == 1
    assert inv["pages"] == 1
    assert inv["papers"] == 1
    assert inv["active_source_types"] == ["youtube", "website", "paper"]
    assert inv["latest_video_date"] is not None


def test_topic_gap_summary_reports_mixed_source_and_video_gaps(tmp_path: Path):
    cfg = _cfg(tmp_path)
    lib = Library(cfg)
    for channel in ("ChanA", "ChanB", "ChanC"):
        lib.add_channel("tkg", f"https://youtube.com/@{channel}", channel)

    _write_video(cfg, "tkg", "ChanA", "v1", upload_date=_date_ago(20), insights="short")
    _write_video(cfg, "tkg", "ChanA", "bad-date", upload_date="not-a-date", insights="short")
    _write_video(cfg, "tkg", "ChanB", "v2", upload_date=_date_ago(19), transcript="words")
    _write_video(
        cfg,
        "tkg",
        "ChanC",
        "v3",
        upload_date=_date_ago(18),
        insights="long enough" * 90,
        transcript="words",
    )

    _write_artifact(cfg.site_page_dir("tkg", "example.com", "Page"), "content", "content")
    _write_artifact(cfg.paper_dir("tkg", "Paper", "2602.12670"), "paper", "# paper")

    summary = topic_gap_summary(cfg, "tkg")

    assert summary["recency_status"] == "stale"
    assert "ChanB: v2" in summary["missing_insights"]
    assert "ChanA: v1" in summary["missing_transcripts"]
    assert "ChanA: v1" in summary["thin_insights"]
    assert any("Website material exists" in gap for gap in summary["gaps"])
    assert any("Paper material exists" in gap for gap in summary["gaps"])
    assert any("Mixed-source corpus synthesis is missing" in gap for gap in summary["gaps"])
    assert any("older than 7 days" in gap for gap in summary["gaps"])


def test_topic_gap_summary_reports_no_major_gaps_when_core_outputs_are_current(tmp_path: Path):
    cfg = _cfg(tmp_path)
    lib = Library(cfg)
    for channel in ("ChanA", "ChanB", "ChanC"):
        lib.add_channel("tkg", f"https://youtube.com/@{channel}", channel)
    for index in range(5):
        channel = ("ChanA", "ChanB", "ChanC")[index % 3]
        _write_video(
            cfg,
            "tkg",
            channel,
            f"v{index}",
            upload_date=_date_ago(index),
            insights="substantive " * 100,
            transcript="transcript",
        )

    _write_artifact(cfg.site_page_dir("tkg", "example.com", "Page"), "content", "content")
    topic_dir = cfg.topic_dir("tkg")
    for artifact in ("topic_synthesis", "corpus_synthesis", "topic_diff", "topic_trends", "report"):
        _write_artifact(topic_dir, artifact, "# artifact")

    summary = topic_gap_summary(cfg, "tkg")

    assert summary["recency_status"] == "fresh"
    assert summary["gaps"] == ["No major research gaps detected from the local corpus heuristics."]
    assert summary["next_actions"] == ["No immediate follow-on action required."]


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


def test_gap_discovery_goal_defaults_missing_or_filtered_fields():
    summary = {
        "gaps": ["No valid upload dates were found, so recency cannot be assessed.", 7],
        "active_source_types": "youtube",
    }

    goal = gap_discovery_goal(summary)

    assert "this topic" in goal
    assert "cannot be assessed" not in goal
    assert "cross-source validation" in goal


def test_gap_discovery_goal_no_real_gaps_is_still_a_goal():
    summary = {
        "topic": "tkg",
        "active_source_types": ["youtube", "paper", "website"],
        "gaps": ["No major research gaps detected from the local corpus heuristics."],
    }
    goal = gap_discovery_goal(summary)
    assert "tkg" in goal
    assert goal.strip()  # never empty -> discover always has something to do

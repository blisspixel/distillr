"""Unit tests for ``distill.commands.view`` corpus browsing commands."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timedelta

import typer
from typer.testing import CliRunner

from distill import cli
from distill.commands import view as view_mod
from distill.config import DistillConfig
from distill.library import Library
from distill.library.paths import artifact_path, find_artifact
from distill.library.state import ChannelState

runner = CliRunner()


def _recent(days_ago: int = 1) -> str:
    return (datetime.now() - timedelta(days=days_ago)).strftime("%Y%m%d")


def _config(tmp_path) -> DistillConfig:
    config = DistillConfig(
        xai_api_key="test-key",
        distill_output_dir=tmp_path / "library",
    )
    config.library_dir.mkdir(parents=True, exist_ok=True)
    return config


def _seed_library(config: DistillConfig, topic: str = "ai", channel: str = "TestCh") -> Library:
    lib = Library(config)
    lib.add_channel(topic, f"https://www.youtube.com/@{channel}", channel)
    return lib


def _seed_video(
    config: DistillConfig,
    *,
    topic: str = "ai",
    channel: str = "TestCh",
    video_id: str = "vid001",
    title: str = "Test Video 0",
    days_ago: int = 1,
    duration: int = 600,
    with_transcript: bool = True,
    with_insights: bool = True,
    insights_body: str | None = None,
) -> None:
    vid_dir = config.video_dir(topic, channel, video_id)
    vid_dir.mkdir(parents=True, exist_ok=True)
    meta = {
        "video_id": video_id,
        "title": title,
        "upload_date": _recent(days_ago),
        "duration": duration,
        "url": f"https://www.youtube.com/watch?v={video_id}",
    }
    (vid_dir / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")
    if with_transcript:
        find_artifact(vid_dir, "transcript", extension="txt").write_text(
            "Transcript body", encoding="utf-8"
        )
    if with_insights:
        body = insights_body or "---\ntitle: test\n---\n\n## Summary\nInsight body"
        find_artifact(vid_dir, "insights").write_text(body, encoding="utf-8")

    state = ChannelState(config.channel_dir(topic, channel) / "state.json")
    state.mark_processed(video_id, title, _recent(days_ago))


class TestLibraryCommand:
    def _patch(self, monkeypatch, config):
        monkeypatch.setattr(view_mod, "get_config", lambda: config)

    def test_empty_library_panel(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        self._patch(monkeypatch, config)

        result = runner.invoke(cli.app, ["library"])

        assert result.exit_code == 0
        assert "Library is empty" in result.output

    def test_library_json_payload(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_library(config)
        self._patch(monkeypatch, config)

        result = runner.invoke(cli.app, ["--json", "library"])

        assert result.exit_code == 0
        payload = json.loads(result.stdout)["data"]
        assert payload["count"] == 1
        assert payload["topics"][0]["topic"] == "ai"

    def test_library_lists_channel_and_topic_artifacts(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_library(config)
        ch_dir = config.channel_dir("ai", "TestCh")
        ch_dir.mkdir(parents=True, exist_ok=True)
        artifact_path(ch_dir, "synthesis", identity="ai_TestCh").write_text(
            "# Synth", encoding="utf-8"
        )
        artifact_path(ch_dir, "report", identity="ai_TestCh").write_text(
            "# Report", encoding="utf-8"
        )
        topic_dir = config.topic_dir("ai")
        topic_dir.mkdir(parents=True, exist_ok=True)
        artifact_path(topic_dir, "topic_synthesis", identity="ai").write_text(
            "# Topic", encoding="utf-8"
        )
        artifact_path(topic_dir, "report", identity="ai").write_text(
            "# Topic report", encoding="utf-8"
        )
        self._patch(monkeypatch, config)

        result = runner.invoke(cli.app, ["library"])

        assert result.exit_code == 0
        assert "TestCh" in result.output
        assert "synthesis" in result.output
        assert "Topic files" in result.output
        assert "distill videos ai" in result.output


class TestVideosCommand:
    def _patch(self, monkeypatch, config):
        monkeypatch.setattr(view_mod, "get_config", lambda: config)

    def test_no_channels_human(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        self._patch(monkeypatch, config)

        result = runner.invoke(cli.app, ["videos", "missing"])

        assert result.exit_code == 0
        assert "No channels found" in result.output

    def test_videos_json_empty_channels(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        self._patch(monkeypatch, config)

        result = runner.invoke(cli.app, ["--json", "videos", "missing"])

        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["data"]["channels"] == []

    def test_videos_json_omits_missing_video_dirs(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        lib = _seed_library(config)
        lib.add_channel("ai", "https://www.youtube.com/@NoVideos", "NoVideos")
        shutil.rmtree(config.videos_dir("ai", "NoVideos"))
        self._patch(monkeypatch, config)

        result = runner.invoke(cli.app, ["--json", "videos", "ai"])

        assert result.exit_code == 0
        names = {ch["channel"] for ch in json.loads(result.stdout)["data"]["channels"]}
        assert names == {"TestCh"}

    def test_videos_json_skips_invalid_entries(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_library(config)
        videos_dir = config.videos_dir("ai", "TestCh")
        (videos_dir / "file.txt").write_text("x", encoding="utf-8")
        bad = videos_dir / "broken"
        bad.mkdir()
        (bad / "metadata.json").write_text("{bad", encoding="utf-8")
        self._patch(monkeypatch, config)

        result = runner.invoke(cli.app, ["--json", "videos", "ai"])

        assert result.exit_code == 0
        payload = json.loads(result.stdout)["data"]
        assert payload["channels"][0]["total"] == 0

    def test_videos_json_payload(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_library(config)
        _seed_video(config, video_id="v1", title="First", days_ago=2)
        _seed_video(config, video_id="v2", title="Second", days_ago=1)
        self._patch(monkeypatch, config)

        result = runner.invoke(cli.app, ["--json", "videos", "ai", "--limit", "1"])

        assert result.exit_code == 0
        payload = json.loads(result.stdout)["data"]
        assert payload["topic"] == "ai"
        assert payload["channels"][0]["total"] == 2
        assert len(payload["channels"][0]["videos"]) == 1
        assert payload["channels"][0]["videos"][0]["has_insights"] is True

    def test_videos_human_statuses_and_overflow(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_library(config)
        _seed_video(config, video_id="full", with_transcript=True, with_insights=True)
        _seed_video(
            config,
            video_id="transcript-only",
            title="Transcript Only",
            days_ago=2,
            with_insights=False,
        )
        _seed_video(
            config,
            video_id="missing",
            title="Missing Files",
            days_ago=3,
            with_transcript=False,
            with_insights=False,
        )
        for i in range(4, 8):
            _seed_video(config, video_id=f"extra{i}", title=f"Extra {i}", days_ago=i)
        self._patch(monkeypatch, config)

        result = runner.invoke(cli.app, ["videos", "ai", "--limit", "3"])

        assert result.exit_code == 0
        assert "complete" in result.output
        assert "transcript only" in result.output
        assert "missing" in result.output
        assert "Showing 3/" in result.output

    def test_videos_channel_filter_and_skips_bad_entries(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_library(config)
        _seed_video(config)
        videos_dir = config.videos_dir("ai", "TestCh")
        (videos_dir / "skip.txt").write_text("not a dir", encoding="utf-8")
        bad_dir = videos_dir / "bad-meta"
        bad_dir.mkdir()
        self._patch(monkeypatch, config)

        result = runner.invoke(cli.app, ["videos", "ai", "--channel", "TestCh"])

        assert result.exit_code == 0
        assert "Test Video 0" in result.output


class TestShowCommand:
    def _patch(self, monkeypatch, config):
        monkeypatch.setattr(view_mod, "get_config", lambda: config)

    def test_show_insights_first_video_navigation(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_library(config)
        _seed_video(config, video_id="v1", title="Newest", days_ago=1)
        _seed_video(config, video_id="v2", title="Older", days_ago=3)
        self._patch(monkeypatch, config)

        result = runner.invoke(cli.app, ["show", "ai", "1"])

        assert result.exit_code == 0
        assert "distill show TestCh 2 >>" in result.output
        assert "distill show TestCh 0" not in result.output

    def test_show_insights_with_navigation(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_library(config)
        _seed_video(config, video_id="v1", title="Newest", days_ago=1)
        _seed_video(config, video_id="v2", title="Older", days_ago=3)
        self._patch(monkeypatch, config)

        result = runner.invoke(cli.app, ["show", "ai", "2"])

        assert result.exit_code == 0
        assert "Older" in result.output
        assert "distill show TestCh 1" in result.output
        assert "distill show TestCh 3" not in result.output

    def test_show_short_transcript(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_library(config)
        _seed_video(config, with_insights=False)
        self._patch(monkeypatch, config)

        result = runner.invoke(cli.app, ["show", "ai", "1", "--what", "transcript"])

        assert result.exit_code == 0
        assert "Transcript body" in result.output
        assert "showing first 3000" not in result.output

    def test_show_transcript_truncation(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_library(config)
        _seed_video(config, with_insights=False)
        transcript = find_artifact(
            config.video_dir("ai", "TestCh", "vid001"), "transcript", extension="txt"
        )
        transcript.write_text("x" * 4000, encoding="utf-8")
        self._patch(monkeypatch, config)

        result = runner.invoke(cli.app, ["show", "ai", "1", "--what", "transcript"])

        assert result.exit_code == 0
        assert "showing first 3000" in result.output

    def test_show_missing_insights(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_library(config)
        _seed_video(config, with_insights=False)
        self._patch(monkeypatch, config)

        result = runner.invoke(cli.app, ["show", "ai", "1", "--what", "insights"])

        assert result.exit_code == 0
        assert "No insights found" in result.output

    def test_show_no_channels(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        self._patch(monkeypatch, config)

        result = runner.invoke(cli.app, ["show", "missing", "1"])

        assert result.exit_code == 0
        assert "No channels found" in result.output

    def test_show_skips_non_directory_entries(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_library(config)
        _seed_video(config, video_id="good", title="Good Video")
        videos_dir = config.videos_dir("ai", "TestCh")
        (videos_dir / "stray.txt").write_text("x", encoding="utf-8")
        self._patch(monkeypatch, config)

        result = runner.invoke(cli.app, ["show", "ai", "1"])

        assert result.exit_code == 0
        assert "Good Video" in result.output or "Insight body" in result.output

    def test_show_channel_name_arg(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_library(config)
        _seed_video(config)
        self._patch(monkeypatch, config)

        result = runner.invoke(cli.app, ["show", "TestCh", "1"])

        assert result.exit_code == 0
        assert "Test Video 0" in result.output or "Insight body" in result.output

    def test_show_json_payloads(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_library(config)
        _seed_video(config)
        self._patch(monkeypatch, config)

        insights = runner.invoke(cli.app, ["--json", "show", "ai", "1", "--what", "insights"])
        transcript = runner.invoke(cli.app, ["--json", "show", "ai", "1", "--what", "transcript"])
        metadata = runner.invoke(cli.app, ["--json", "show", "ai", "1", "--what", "metadata"])

        assert json.loads(insights.stdout)["data"]["found"] is True
        assert "Insight body" in json.loads(insights.stdout)["data"]["content"]
        assert json.loads(transcript.stdout)["data"]["found"] is True
        assert json.loads(metadata.stdout)["data"]["what"] == "metadata"

    def test_show_metadata_human(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_library(config)
        _seed_video(config)
        self._patch(monkeypatch, config)

        result = runner.invoke(cli.app, ["show", "ai", "1", "--what", "metadata"])

        assert result.exit_code == 0
        assert "vid001" in result.output

    def test_show_no_videos_directory(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_library(config)
        videos_dir = config.videos_dir("ai", "TestCh")
        if videos_dir.exists():
            shutil.rmtree(videos_dir)
        self._patch(monkeypatch, config)

        result = runner.invoke(cli.app, ["show", "ai", "1"])

        assert result.exit_code == 0
        assert "No videos found for TestCh" in result.output

    def test_show_out_of_range(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_library(config)
        _seed_video(config)
        self._patch(monkeypatch, config)

        result = runner.invoke(cli.app, ["show", "ai", "99"])

        assert result.exit_code == 0
        assert "Video #99 not found" in result.output

    def test_show_missing_transcript(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_library(config)
        _seed_video(config, with_transcript=False, with_insights=True)
        self._patch(monkeypatch, config)

        result = runner.invoke(cli.app, ["show", "ai", "1", "--what", "transcript"])

        assert result.exit_code == 0
        assert "No transcript found" in result.output

    def test_show_invalid_what(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_library(config)
        _seed_video(config)
        self._patch(monkeypatch, config)

        result = runner.invoke(cli.app, ["show", "ai", "1", "--what", "unknown"])

        assert result.exit_code == 0
        assert "Invalid --what" in result.output


class TestPackageLatest:
    def _patch(self, monkeypatch, config):
        monkeypatch.setattr(view_mod, "get_config", lambda: config)

    def test_packages_videos_with_optional_transcript(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_library(config)
        _seed_video(config, video_id="pack1", title="Packaged Video")
        self._patch(monkeypatch, config)

        result = runner.invoke(cli.app, ["package-latest", "ai", "--transcript", "--limit", "2"])

        assert result.exit_code == 0
        assert "Packaged 1 videos" in result.output
        out_path = config.library_dir.parent / "output" / "latest-ai.md"
        assert out_path.exists()
        text = out_path.read_text(encoding="utf-8")
        assert "Packaged Video" in text
        assert "### Insights" in text
        assert "### Transcript" in text

    def test_package_latest_no_matching_channels(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_library(config)
        self._patch(monkeypatch, config)

        result = runner.invoke(cli.app, ["package-latest", "ai", "--channel", "Missing"])

        assert result.exit_code == 0
        assert "No channels found" in result.output

    def test_package_latest_without_insights(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_library(config)
        _seed_video(config, with_insights=False, with_transcript=False)
        self._patch(monkeypatch, config)

        result = runner.invoke(cli.app, ["package-latest", "ai"])

        assert result.exit_code == 0
        text = (config.library_dir.parent / "output" / "latest-ai.md").read_text(encoding="utf-8")
        assert "### Insights" not in text

    def test_package_latest_channel_scope(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        lib = _seed_library(config)
        lib.add_channel("ai", "https://www.youtube.com/@Other", "OtherCh")
        _seed_video(config, video_id="main", title="Main Video")
        _seed_video(config, channel="OtherCh", video_id="other", title="Other Video")
        self._patch(monkeypatch, config)

        result = runner.invoke(cli.app, ["package-latest", "ai", "--channel", "TestCh"])

        assert result.exit_code == 0
        text = (config.library_dir.parent / "output" / "latest-TestCh.md").read_text(
            encoding="utf-8"
        )
        assert "Main Video" in text
        assert "Other Video" not in text

    def test_package_latest_no_videos(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_library(config)
        self._patch(monkeypatch, config)

        result = runner.invoke(cli.app, ["package-latest", "ai"])

        assert result.exit_code == 0
        assert "No videos found" in result.output


class TestSynthesisAndFindings:
    def _patch(self, monkeypatch, config):
        monkeypatch.setattr(view_mod, "get_config", lambda: config)

    def test_synthesis_falls_back_to_channel_file(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_library(config)
        ch_dir = config.channel_dir("ai", "TestCh")
        ch_dir.mkdir(parents=True, exist_ok=True)
        artifact_path(ch_dir, "synthesis", identity="ai_TestCh").write_text(
            "# Channel fallback", encoding="utf-8"
        )
        self._patch(monkeypatch, config)

        result = runner.invoke(cli.app, ["synthesis", "ai"])

        assert result.exit_code == 0
        assert "Channel fallback" in result.output

    def test_synthesis_generates_topic_when_processed_videos_exist(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_library(config)
        _seed_video(config)
        self._patch(monkeypatch, config)

        def fake_topic(topic, cfg, tracker=None):
            topic_dir = config.topic_dir(topic)
            topic_dir.mkdir(parents=True, exist_ok=True)
            artifact_path(topic_dir, "topic_synthesis", identity=topic).write_text(
                "# Generated topic synth", encoding="utf-8"
            )

        monkeypatch.setattr(view_mod, "synthesize_topic", fake_topic)

        result = runner.invoke(cli.app, ["synthesis", "ai"])

        assert result.exit_code == 0
        assert "Topic synthesis generated" in result.output
        assert "Generated topic synth" in result.output

    def test_synthesis_no_processed_videos(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_library(config)
        self._patch(monkeypatch, config)

        result = runner.invoke(cli.app, ["synthesis", "ai"])

        assert result.exit_code == 0
        assert "no videos have been processed" in result.output
        assert "distill catch-up TestCh" in result.output

    def test_synthesis_missing_output_after_generation(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_library(config)
        _seed_video(config)
        self._patch(monkeypatch, config)
        monkeypatch.setattr(view_mod, "synthesize_topic", lambda *args, **kwargs: None)

        result = runner.invoke(cli.app, ["synthesis", "ai"])

        assert result.exit_code == 0
        assert "Topic synthesis generated" in result.output

    def test_synthesis_generation_failure(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_library(config)
        _seed_video(config)
        self._patch(monkeypatch, config)

        def boom(*args, **kwargs):
            raise RuntimeError("synth fail")

        monkeypatch.setattr(view_mod, "synthesize_channel", boom)

        result = runner.invoke(cli.app, ["synthesis", "ai", "--channel", "TestCh"])

        assert result.exit_code == 0
        assert "Synthesis failed: synth fail" in result.output

    def test_synthesis_generates_channel(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_library(config)
        _seed_video(config)
        self._patch(monkeypatch, config)

        def fake_channel(topic, channel, cfg, tracker=None):
            ch_dir = config.channel_dir(topic, channel)
            ch_dir.mkdir(parents=True, exist_ok=True)
            artifact_path(ch_dir, "synthesis", identity=f"{topic}_{channel}").write_text(
                "# Channel synth", encoding="utf-8"
            )

        monkeypatch.setattr(view_mod, "synthesize_channel", fake_channel)

        result = runner.invoke(cli.app, ["synthesis", "ai", "--channel", "TestCh"])

        assert result.exit_code == 0
        assert "Synthesis generated for TestCh" in result.output

    def test_findings_missing_report_human(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_library(config)
        self._patch(monkeypatch, config)

        result = runner.invoke(cli.app, ["findings", "ai"])

        assert result.exit_code == 0
        assert "No report yet" in result.output

    def test_findings_reads_report(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_library(config)
        topic_dir = config.topic_dir("ai")
        topic_dir.mkdir(parents=True, exist_ok=True)
        artifact_path(topic_dir, "report", identity="ai").write_text(
            "# Report body", encoding="utf-8"
        )
        self._patch(monkeypatch, config)

        result = runner.invoke(cli.app, ["findings", "ai"])

        assert result.exit_code == 0
        assert "Report body" in result.output

    def test_findings_json_and_missing(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_library(config)
        self._patch(monkeypatch, config)

        missing = runner.invoke(cli.app, ["--json", "findings", "ai"])
        assert json.loads(missing.stdout)["data"]["found"] is False

        topic_dir = config.topic_dir("ai")
        topic_dir.mkdir(parents=True, exist_ok=True)
        artifact_path(topic_dir, "report", identity="ai").write_text("# Report", encoding="utf-8")
        found = runner.invoke(cli.app, ["--json", "findings", "ai"])
        assert json.loads(found.stdout)["data"]["found"] is True

    def test_findings_channel_scope(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_library(config)
        ch_dir = config.channel_dir("ai", "TestCh")
        ch_dir.mkdir(parents=True, exist_ok=True)
        artifact_path(ch_dir, "report", identity="ai_TestCh").write_text(
            "# Channel report", encoding="utf-8"
        )
        self._patch(monkeypatch, config)

        result = runner.invoke(cli.app, ["findings", "ai", "--channel", "TestCh"])

        assert result.exit_code == 0
        assert "Channel report" in result.output


class TestAddAndRemove:
    def _patch(self, monkeypatch, config):
        monkeypatch.setattr(view_mod, "get_config", lambda: config)

    def test_add_channel(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        self._patch(monkeypatch, config)
        monkeypatch.setattr(view_mod, "resolve_channel_name", lambda _url: "AddedCh")

        result = runner.invoke(cli.app, ["add", "ai", "https://www.youtube.com/@AddedCh"])

        assert result.exit_code == 0
        assert "Added AddedCh" in result.output

    def test_add_duplicate_channel(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_library(config)
        self._patch(monkeypatch, config)
        monkeypatch.setattr(view_mod, "resolve_channel_name", lambda _url: "TestCh")

        result = runner.invoke(cli.app, ["add", "ai", "https://www.youtube.com/@TestCh"])

        assert result.exit_code == 0
        assert "already exists" in result.output

    def test_remove_not_found(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_library(config)
        self._patch(monkeypatch, config)

        result = runner.invoke(
            cli.app, ["remove", "ai", "https://www.youtube.com/@Missing", "--yes"]
        )

        assert result.exit_code == 0
        assert "Not found in ai" in result.output

    def test_remove_success(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_library(config)
        self._patch(monkeypatch, config)

        result = runner.invoke(
            cli.app, ["remove", "ai", "https://www.youtube.com/@TestCh", "--yes"]
        )

        assert result.exit_code == 0
        assert "Removed from ai" in result.output

    def test_remove_aborts_without_yes(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_library(config)
        self._patch(monkeypatch, config)
        monkeypatch.setattr(view_mod, "_tty_confirm", lambda _msg: False)

        result = runner.invoke(cli.app, ["remove", "ai", "https://www.youtube.com/@TestCh"])

        assert result.exit_code != 0


class TestDiffAndTrends:
    def _patch(self, monkeypatch, config):
        monkeypatch.setattr(view_mod, "get_config", lambda: config)

    def test_diff_topic_not_found(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        self._patch(monkeypatch, config)

        result = runner.invoke(cli.app, ["diff", "missing-topic"])

        assert result.exit_code == 1
        assert "Topic not found" in result.output

    def test_diff_writes_artifact(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_library(config)
        _seed_video(config)
        self._patch(monkeypatch, config)

        result = runner.invoke(cli.app, ["diff", "ai", "--no-write"])

        assert result.exit_code == 0
        assert "Topic Diff: ai" in result.output

        written = runner.invoke(cli.app, ["diff", "ai"])
        assert written.exit_code == 0
        diff_path = artifact_path(config.topic_dir("ai"), "topic_diff", identity="ai")
        assert diff_path.exists()

    def test_trends_topic_not_found(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        self._patch(monkeypatch, config)

        result = runner.invoke(cli.app, ["trends", "missing-topic"])

        assert result.exit_code == 1
        assert "Topic not found" in result.output

    def test_trends_no_write(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_library(config)
        self._patch(monkeypatch, config)
        runner.invoke(cli.app, ["diff", "ai", "--no-write"])

        result = runner.invoke(cli.app, ["trends", "ai", "--no-write"])

        assert result.exit_code == 0
        assert "Topic Trends: ai" in result.output
        trends_path = artifact_path(config.topic_dir("ai"), "topic_trends", identity="ai")
        assert not trends_path.exists()

    def test_trends_writes_artifact(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_library(config)
        self._patch(monkeypatch, config)
        runner.invoke(cli.app, ["diff", "ai"])

        result = runner.invoke(cli.app, ["trends", "ai"])

        assert result.exit_code == 0
        assert "Topic Trends: ai" in result.output
        trends_path = artifact_path(config.topic_dir("ai"), "topic_trends", identity="ai")
        assert trends_path.exists()


class TestHelpersAndRegister:
    def test_library_payload_includes_artifacts(self, tmp_path):
        config = _config(tmp_path)
        lib = _seed_library(config)
        ch_dir = config.channel_dir("ai", "TestCh")
        ch_dir.mkdir(parents=True, exist_ok=True)
        artifact_path(ch_dir, "synthesis", identity="ai_TestCh").write_text("# S", encoding="utf-8")

        payload = view_mod._library_payload(config, lib, ["ai"])

        assert payload["count"] == 1
        assert payload["topics"][0]["channels"][0]["artifacts"] == ["synthesis"]

    def test_show_payload_metadata(self, tmp_path):
        config = _config(tmp_path)
        _seed_library(config)
        _seed_video(config)
        vid_dir = config.video_dir("ai", "TestCh", "vid001")
        video = json.loads((vid_dir / "metadata.json").read_text(encoding="utf-8"))
        video["_dir"] = vid_dir

        payload = view_mod._show_payload(vid_dir, video, "metadata")

        assert payload["found"] is True
        assert payload["content"] is None

    def test_register_attaches_view_commands(self):
        app = typer.Typer()
        view_mod.register(app)
        names = {cmd.name for cmd in app.registered_commands}
        callbacks = {cmd.callback for cmd in app.registered_commands}
        assert "library" in names
        assert "package-latest" in names
        assert view_mod.show in callbacks
        assert view_mod.videos in callbacks
        assert view_mod.diff in callbacks
        assert view_mod.trends in callbacks

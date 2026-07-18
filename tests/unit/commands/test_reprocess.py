"""Unit tests for ``distill.commands.reprocess`` resynthesize and reanalyze commands."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import typer
from typer.testing import CliRunner

from distill import cli
from distill.commands import _helpers as helpers_mod
from distill.commands import reprocess as reprocess_mod
from distill.commands._json import ExitCode
from distill.config import DistillConfig
from distill.library import Library
from distill.library.paths import find_artifact
from distill.pipeline.costs import ProjectedBudgetExceededError

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
    video_id: str = "v1",
    title: str = "Video 1",
    duration: int = 600,
    analysis_mode: str = "full",
    transcript: str = "Transcript body for analysis.",
) -> None:
    vid_dir = config.video_dir(topic, channel, video_id)
    vid_dir.mkdir(parents=True, exist_ok=True)
    meta = {
        "video_id": video_id,
        "title": title,
        "upload_date": _recent(2),
        "duration": duration,
        "url": f"https://youtube.com/watch?v={video_id}",
        "analysis_mode": analysis_mode,
    }
    (vid_dir / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")
    transcript_file = find_artifact(vid_dir, "transcript", extension="txt")
    transcript_file.write_text(transcript, encoding="utf-8")


def _write_synthesis(
    config: DistillConfig, topic: str, channel: str, body: str = "# Synth"
) -> None:
    ch_dir = config.channel_dir(topic, channel)
    ch_dir.mkdir(parents=True, exist_ok=True)
    (ch_dir / "synthesis.md").write_text(body, encoding="utf-8")


def _write_topic_synthesis(config: DistillConfig, topic: str, body: str = "# Topic") -> None:
    topic_dir = config.topic_dir(topic)
    topic_dir.mkdir(parents=True, exist_ok=True)
    (topic_dir / "topic_synthesis.md").write_text(body, encoding="utf-8")


class TestResynthesize:
    def _patch_common(self, monkeypatch, config):
        monkeypatch.setattr(reprocess_mod, "get_config", lambda: config)
        monkeypatch.setattr(reprocess_mod, "display_estimate", lambda *args, **kwargs: None)
        monkeypatch.setattr(reprocess_mod, "display_summary", lambda *args, **kwargs: None)

    def test_no_channels_exits(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        self._patch_common(monkeypatch, config)

        result = runner.invoke(cli.app, ["resynthesize", "missing"])

        assert result.exit_code == int(ExitCode.NOT_FOUND)
        assert "No channels found" in result.output

    def test_two_pass_resynthesizes_channelless_recursive_insights(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        insight = (
            config.topic_dir("agent-loops")
            / "x"
            / "researcher"
            / "posts"
            / "123"
            / "researcher_123_Insights.md"
        )
        insight.parent.mkdir(parents=True, exist_ok=True)
        insight.write_text(
            "---\nsource_id: x-123\ntitle: Queue design\n---\n\nUse durable work queues.\n",
            encoding="utf-8",
        )
        self._patch_common(monkeypatch, config)
        channel_synthesis = MagicMock()
        topic_synthesis = MagicMock()
        corpus_calls: list[tuple[str, bool]] = []
        monkeypatch.setattr(reprocess_mod, "synthesize_channel", channel_synthesis)
        monkeypatch.setattr(reprocess_mod, "synthesize_topic", topic_synthesis)

        def fake_corpus(topic, cfg, tracker=None, style="", two_pass=False):
            del cfg, tracker, style
            corpus_calls.append((topic, two_pass))
            output = config.topic_dir(topic) / "corpus_synthesis.md"
            output.write_text("# Corpus", encoding="utf-8")

        monkeypatch.setattr(reprocess_mod, "synthesize_corpus", fake_corpus)

        result = runner.invoke(cli.app, ["resynthesize", "agent-loops", "--two-pass"])

        assert result.exit_code == 0
        assert corpus_calls == [("agent-loops", True)]
        channel_synthesis.assert_not_called()
        topic_synthesis.assert_not_called()
        assert "Two-pass corpus synthesis" in result.output
        assert "done" in result.output

    def test_two_pass_estimate_counts_pending_claim_extractions(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        for source_id in ("x-123", "x-456"):
            insight = config.topic_dir("agent-loops") / "x" / source_id / f"{source_id}_Insights.md"
            insight.parent.mkdir(parents=True, exist_ok=True)
            insight.write_text(
                f"---\nsource_id: {source_id}\ntitle: Queue design\n---\n\nUse durable queues.\n",
                encoding="utf-8",
            )
        self._patch_common(monkeypatch, config)
        projected: list[dict[str, int]] = []
        displayed: list[dict[str, int]] = []

        def fake_estimate(**kwargs):
            projected.append(kwargs)
            return 0.0

        monkeypatch.setattr(reprocess_mod, "estimate_routed_video_workflow_cost", fake_estimate)
        monkeypatch.setattr(
            reprocess_mod,
            "display_estimate",
            lambda **kwargs: displayed.append(kwargs),
        )

        def fake_corpus(topic, cfg, tracker=None, style="", two_pass=False):
            del cfg, tracker, style, two_pass
            output = config.topic_dir(topic) / "corpus_synthesis.md"
            output.write_text("# Corpus", encoding="utf-8")

        monkeypatch.setattr(reprocess_mod, "synthesize_corpus", fake_corpus)

        result = runner.invoke(cli.app, ["resynthesize", "agent-loops", "--two-pass"])

        assert result.exit_code == 0
        assert projected == [{"synthesis_calls": 1, "claim_extraction_calls": 2}]
        assert displayed[0]["synthesis_calls"] == 1
        assert displayed[0]["claim_extraction_calls"] == 2

    def test_two_pass_refuses_empty_channelless_corpus(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        config.topic_dir("empty").mkdir(parents=True, exist_ok=True)
        self._patch_common(monkeypatch, config)
        corpus_synthesis = MagicMock()
        monkeypatch.setattr(reprocess_mod, "synthesize_corpus", corpus_synthesis)

        result = runner.invoke(cli.app, ["resynthesize", "empty", "--two-pass"])

        assert result.exit_code == int(ExitCode.NOT_FOUND)
        assert "No insight artifacts or extracted claims found" in result.output
        corpus_synthesis.assert_not_called()

    def test_channel_not_found_exits(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_library(config)
        self._patch_common(monkeypatch, config)

        result = runner.invoke(cli.app, ["resynthesize", "ai", "--channel", "Missing"])

        assert result.exit_code == int(ExitCode.NOT_FOUND)
        assert "not found" in result.output

    def test_refuses_projected_resynthesize_budget_before_synthesis(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DISTILL_PROVIDER", "xai")
        monkeypatch.setenv("XAI_API_KEY", "test-key")
        config = _config(tmp_path)
        config.distill_cost_workflow_budgets = "resynthesize=0.0001"
        _seed_library(config)
        self._patch_common(monkeypatch, config)
        synthesize_channel = MagicMock()
        synthesize_topic = MagicMock()
        monkeypatch.setattr(reprocess_mod, "synthesize_channel", synthesize_channel)
        monkeypatch.setattr(reprocess_mod, "synthesize_topic", synthesize_topic)

        result = runner.invoke(cli.app, ["resynthesize", "ai"])

        assert result.exit_code == 1
        assert isinstance(result.exception, ProjectedBudgetExceededError)
        synthesize_channel.assert_not_called()
        synthesize_topic.assert_not_called()

    def test_resynthesizes_channel_and_topic(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_library(config)
        self._patch_common(monkeypatch, config)
        calls: list[str] = []

        def fake_channel(topic, channel, cfg, tracker=None):
            calls.append(f"ch:{channel}")
            _write_synthesis(config, topic, channel)

        def fake_topic(topic, cfg, tracker=None, style=""):
            calls.append(f"topic:{topic}:{style}")
            _write_topic_synthesis(config, topic)

        monkeypatch.setattr(reprocess_mod, "synthesize_channel", fake_channel)
        monkeypatch.setattr(reprocess_mod, "synthesize_topic", fake_topic)

        result = runner.invoke(cli.app, ["resynthesize", "ai", "--style", "exec"])

        assert result.exit_code == 0
        assert calls == ["ch:TestCh", "topic:ai:exec"]
        assert "done" in result.output

    def test_local_resynthesize_records_zero_route_estimate(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DISTILL_PROVIDER", "ollama")
        monkeypatch.setenv("DISTILL_FAST_MODEL", "qwen2.5:14b")
        config = _config(tmp_path)
        _seed_library(config)
        self._patch_common(monkeypatch, config)
        summaries = []
        monkeypatch.setattr(
            reprocess_mod,
            "synthesize_channel",
            lambda *args, **kwargs: _write_synthesis(config, "ai", "TestCh"),
        )
        monkeypatch.setattr(
            reprocess_mod,
            "synthesize_topic",
            lambda *args, **kwargs: _write_topic_synthesis(config, "ai"),
        )
        monkeypatch.setattr(
            reprocess_mod,
            "display_summary",
            lambda summary, **kwargs: summaries.append(summary),
        )

        result = runner.invoke(cli.app, ["resynthesize", "ai"])

        assert result.exit_code == 0
        assert len(summaries) == 1
        assert summaries[0].estimated_cost == 0.0

    def test_channel_synthesis_failure(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_library(config)
        self._patch_common(monkeypatch, config)

        def boom(*args, **kwargs):
            raise RuntimeError("channel synth fail")

        monkeypatch.setattr(reprocess_mod, "synthesize_channel", boom)
        monkeypatch.setattr(reprocess_mod, "synthesize_topic", lambda *args, **kwargs: None)

        result = runner.invoke(cli.app, ["resynthesize", "ai"])

        assert result.exit_code == 0
        assert "Failed: channel synth fail" in result.output

    def test_topic_synthesis_failure(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_library(config)
        self._patch_common(monkeypatch, config)
        monkeypatch.setattr(
            reprocess_mod,
            "synthesize_channel",
            lambda *args, **kwargs: _write_synthesis(config, "ai", "TestCh"),
        )

        def boom(*args, **kwargs):
            raise RuntimeError("topic synth fail")

        monkeypatch.setattr(reprocess_mod, "synthesize_topic", boom)

        result = runner.invoke(cli.app, ["resynthesize", "ai"])

        assert result.exit_code == 0
        assert "Topic synthesis failed" in result.output

    def test_missing_channel_output_reported(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_library(config)
        self._patch_common(monkeypatch, config)
        monkeypatch.setattr(reprocess_mod, "synthesize_channel", lambda *args, **kwargs: None)
        monkeypatch.setattr(reprocess_mod, "synthesize_topic", lambda *args, **kwargs: None)

        result = runner.invoke(cli.app, ["resynthesize", "ai"])

        assert result.exit_code == 0
        assert "no synthesis output" in result.output

    def test_two_pass_corpus_synthesis(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_library(config)
        self._patch_common(monkeypatch, config)
        monkeypatch.setattr(
            reprocess_mod,
            "synthesize_channel",
            lambda *args, **kwargs: _write_synthesis(config, "ai", "TestCh"),
        )
        monkeypatch.setattr(
            reprocess_mod,
            "synthesize_topic",
            lambda *args, **kwargs: _write_topic_synthesis(config, "ai"),
        )

        def fake_corpus(topic, cfg, tracker=None, style="", two_pass=False):
            topic_dir = config.topic_dir(topic)
            topic_dir.mkdir(parents=True, exist_ok=True)
            (topic_dir / "corpus_synthesis.md").write_text("# Corpus", encoding="utf-8")

        monkeypatch.setattr(reprocess_mod, "synthesize_corpus", fake_corpus)

        result = runner.invoke(cli.app, ["resynthesize", "ai", "--two-pass"])

        assert result.exit_code == 0
        assert "Two-pass corpus synthesis" in result.output
        assert "done" in result.output

    def test_resynthesize_single_channel_filter(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        lib = Library(config)
        lib.add_channel("ai", "https://www.youtube.com/@A", "Alpha")
        lib.add_channel("ai", "https://www.youtube.com/@B", "Beta")
        self._patch_common(monkeypatch, config)
        seen: list[str] = []

        monkeypatch.setattr(
            reprocess_mod,
            "synthesize_channel",
            lambda topic, channel, cfg, tracker=None: seen.append(channel),
        )
        monkeypatch.setattr(reprocess_mod, "synthesize_topic", lambda *args, **kwargs: None)

        result = runner.invoke(cli.app, ["resynthesize", "ai", "--channel", "Alpha"])

        assert result.exit_code == 0
        assert seen == ["Alpha"]

    def test_missing_topic_synthesis_output(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_library(config)
        self._patch_common(monkeypatch, config)
        monkeypatch.setattr(
            reprocess_mod,
            "synthesize_channel",
            lambda *args, **kwargs: _write_synthesis(config, "ai", "TestCh"),
        )
        monkeypatch.setattr(reprocess_mod, "synthesize_topic", lambda *args, **kwargs: None)

        result = runner.invoke(cli.app, ["resynthesize", "ai"])

        assert result.exit_code == 0
        assert "no topic synthesis output" in result.output

    def test_two_pass_failure(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_library(config)
        self._patch_common(monkeypatch, config)
        monkeypatch.setattr(reprocess_mod, "synthesize_channel", lambda *args, **kwargs: None)
        monkeypatch.setattr(reprocess_mod, "synthesize_topic", lambda *args, **kwargs: None)

        def boom(*args, **kwargs):
            raise RuntimeError("corpus fail")

        monkeypatch.setattr(reprocess_mod, "synthesize_corpus", boom)

        result = runner.invoke(cli.app, ["resynthesize", "ai", "--two-pass"])

        assert result.exit_code == 0
        assert "Two-pass corpus synthesis failed" in result.output


class TestReanalyze:
    def _patch_common(self, monkeypatch, config):
        monkeypatch.setattr(reprocess_mod, "get_config", lambda: config)
        monkeypatch.setattr(reprocess_mod, "display_estimate", lambda *args, **kwargs: None)
        monkeypatch.setattr(reprocess_mod, "display_summary", lambda *args, **kwargs: None)

    def test_no_channels_exits(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        self._patch_common(monkeypatch, config)

        result = runner.invoke(cli.app, ["reanalyze", "missing"])

        assert result.exit_code == int(ExitCode.NOT_FOUND)
        assert "No channels found" in result.output

    def test_channel_not_found_exits(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_library(config)
        self._patch_common(monkeypatch, config)

        result = runner.invoke(cli.app, ["reanalyze", "ai", "--channel", "Missing"])

        assert result.exit_code == int(ExitCode.NOT_FOUND)
        assert "not found" in result.output

    def test_no_transcripts_returns_early(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_library(config)
        config.videos_dir("ai", "TestCh").mkdir(parents=True, exist_ok=True)
        self._patch_common(monkeypatch, config)

        result = runner.invoke(cli.app, ["reanalyze", "ai"])

        assert result.exit_code == 0
        assert "No videos with transcripts found" in result.output

    def test_refuses_projected_reanalyze_budget_before_analysis(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DISTILL_PROVIDER", "xai")
        monkeypatch.setenv("XAI_API_KEY", "test-key")
        config = _config(tmp_path)
        config.distill_cost_workflow_budgets = "reanalyze=0.0001"
        _seed_library(config)
        _seed_video(config)
        self._patch_common(monkeypatch, config)
        process_video = MagicMock()
        monkeypatch.setattr(reprocess_mod, "_process_video", process_video)

        result = runner.invoke(cli.app, ["reanalyze", "ai"])

        assert result.exit_code == 1
        assert isinstance(result.exception, ProjectedBudgetExceededError)
        process_video.assert_not_called()

    def test_dry_run_lists_videos(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_library(config)
        _seed_video(config, video_id="v1", title="Full Video", duration=600)
        _seed_video(config, video_id="v2", title="Short Clip", duration=30)
        self._patch_common(monkeypatch, config)

        result = runner.invoke(cli.app, ["reanalyze", "ai", "--dry-run"])

        assert result.exit_code == 0
        assert "Full Video" in result.output
        assert "Short Clip" in result.output
        assert "(Short)" in result.output

    def test_deep_filters_scan_videos(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_library(config)
        _seed_video(
            config,
            video_id="scan1",
            title="Scan Target",
            analysis_mode="scan",
            duration=600,
        )
        _seed_video(
            config,
            video_id="full1",
            title="Already Full",
            analysis_mode="full",
            duration=600,
        )
        self._patch_common(monkeypatch, config)

        result = runner.invoke(cli.app, ["reanalyze", "ai", "--deep", "--dry-run"])

        assert result.exit_code == 0
        assert "Scan Target" in result.output
        assert "Already Full" not in result.output

    def test_deep_no_matches(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_library(config)
        _seed_video(config, analysis_mode="full")
        self._patch_common(monkeypatch, config)

        result = runner.invoke(cli.app, ["reanalyze", "ai", "--deep"])

        assert result.exit_code == 0
        assert "No scan-analyzed videos to upgrade" in result.output

    def test_reanalyzes_full_and_short_videos(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_library(config)
        _seed_video(config, video_id="full1", duration=600)
        _seed_video(config, video_id="short1", title="Short Clip", duration=30)
        self._patch_common(monkeypatch, config)
        seen: list[str] = []

        monkeypatch.setattr(
            helpers_mod,
            "analyze_video",
            lambda *args, **kwargs: seen.append("full") or "## Full insight",
        )
        monkeypatch.setattr(
            helpers_mod,
            "analyze_short",
            lambda *args, **kwargs: seen.append("short") or "## Short insight",
        )
        monkeypatch.setattr(reprocess_mod, "synthesize_channel", lambda *args, **kwargs: None)
        monkeypatch.setattr(reprocess_mod, "synthesize_topic", lambda *args, **kwargs: None)
        monkeypatch.setattr(helpers_mod, "load_intent", lambda *args, **kwargs: None)

        result = runner.invoke(cli.app, ["reanalyze", "ai"])

        assert result.exit_code == 0
        assert seen == ["full", "short"]
        full_dir = config.video_dir("ai", "TestCh", "full1")
        assert find_artifact(full_dir, "insights").exists()

    def test_reanalyze_delegates_writes_and_verification_to_shared_processor(
        self, tmp_path, monkeypatch
    ):
        config = _config(tmp_path)
        _seed_library(config)
        _seed_video(config, video_id="scan1", analysis_mode="scan")
        self._patch_common(monkeypatch, config)
        processor = MagicMock(return_value=False)
        monkeypatch.setattr(reprocess_mod, "_process_video", processor, raising=False)
        monkeypatch.setattr(reprocess_mod, "synthesize_channel", lambda *args, **kwargs: None)
        monkeypatch.setattr(reprocess_mod, "synthesize_topic", lambda *args, **kwargs: None)

        result = runner.invoke(cli.app, ["reanalyze", "ai", "--deep"])

        assert result.exit_code == 0, result.output
        processor.assert_called_once()
        args, kwargs = processor.call_args
        video = args[2]
        assert (video.video_id, video.title, video.channel_name) == (
            "scan1",
            "Video 1",
            "TestCh",
        )
        assert kwargs["analysis_mode"] == "full"
        assert kwargs["video_dir"] == config.video_dir("ai", "TestCh", "scan1")

    def test_analysis_failure_reported(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_library(config)
        _seed_video(config)
        self._patch_common(monkeypatch, config)

        def boom(*args, **kwargs):
            raise RuntimeError("llm fail")

        monkeypatch.setattr(helpers_mod, "analyze_video", boom)
        monkeypatch.setattr(reprocess_mod, "synthesize_channel", lambda *args, **kwargs: None)
        monkeypatch.setattr(reprocess_mod, "synthesize_topic", lambda *args, **kwargs: None)
        monkeypatch.setattr(helpers_mod, "load_intent", lambda *args, **kwargs: None)

        result = runner.invoke(cli.app, ["reanalyze", "ai"])

        assert result.exit_code == 0
        assert "failed: llm fail" in result.output

    def test_resynthesizes_after_analysis(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_library(config)
        _seed_video(config)
        self._patch_common(monkeypatch, config)
        synth_calls: list[str] = []

        monkeypatch.setattr(helpers_mod, "analyze_video", lambda *args, **kwargs: "## Reanalyzed")
        monkeypatch.setattr(
            reprocess_mod,
            "synthesize_channel",
            lambda topic, channel, cfg, tracker=None: synth_calls.append(channel),
        )
        monkeypatch.setattr(
            reprocess_mod,
            "synthesize_topic",
            lambda topic, cfg, tracker=None: synth_calls.append(f"topic:{topic}"),
        )
        monkeypatch.setattr(helpers_mod, "load_intent", lambda *args, **kwargs: None)

        result = runner.invoke(cli.app, ["reanalyze", "ai"])

        assert result.exit_code == 0
        assert synth_calls == ["TestCh", "topic:ai"]

    def test_channel_synthesis_failure_after_reanalyze(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_library(config)
        _seed_video(config)
        self._patch_common(monkeypatch, config)
        monkeypatch.setattr(helpers_mod, "analyze_video", lambda *args, **kwargs: "## Reanalyzed")
        monkeypatch.setattr(helpers_mod, "load_intent", lambda *args, **kwargs: None)

        def boom(*args, **kwargs):
            raise RuntimeError("synth fail")

        monkeypatch.setattr(reprocess_mod, "synthesize_channel", boom)
        monkeypatch.setattr(reprocess_mod, "synthesize_topic", lambda *args, **kwargs: None)

        result = runner.invoke(cli.app, ["reanalyze", "ai"])

        assert result.exit_code == 0
        assert "Synthesis failed" in result.output

    def test_topic_synthesis_failure_after_reanalyze(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_library(config)
        _seed_video(config)
        self._patch_common(monkeypatch, config)
        monkeypatch.setattr(helpers_mod, "analyze_video", lambda *args, **kwargs: "## Reanalyzed")
        monkeypatch.setattr(reprocess_mod, "synthesize_channel", lambda *args, **kwargs: None)
        monkeypatch.setattr(helpers_mod, "load_intent", lambda *args, **kwargs: None)

        def boom(*args, **kwargs):
            raise RuntimeError("topic fail")

        monkeypatch.setattr(reprocess_mod, "synthesize_topic", boom)

        result = runner.invoke(cli.app, ["reanalyze", "ai"])

        assert result.exit_code == 0
        assert "Topic synthesis failed" in result.output

    def test_skips_zero_byte_transcript(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_library(config)
        vid_dir = config.video_dir("ai", "TestCh", "empty")
        vid_dir.mkdir(parents=True, exist_ok=True)
        (vid_dir / "metadata.json").write_text(
            json.dumps({"title": "Empty Transcript", "duration": 600}),
            encoding="utf-8",
        )
        find_artifact(vid_dir, "transcript", extension="txt").write_text("", encoding="utf-8")
        _seed_video(config, video_id="good", title="Has Transcript")
        self._patch_common(monkeypatch, config)
        monkeypatch.setattr(helpers_mod, "analyze_video", lambda *args, **kwargs: "## Reanalyzed")
        monkeypatch.setattr(reprocess_mod, "synthesize_channel", lambda *args, **kwargs: None)
        monkeypatch.setattr(reprocess_mod, "synthesize_topic", lambda *args, **kwargs: None)
        monkeypatch.setattr(helpers_mod, "load_intent", lambda *args, **kwargs: None)

        result = runner.invoke(cli.app, ["reanalyze", "ai"])

        assert result.exit_code == 0
        assert "Has Transcript" in result.output
        assert "Empty Transcript" not in result.output

    def test_reanalyze_without_metadata(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_library(config)
        vid_dir = config.video_dir("ai", "TestCh", "nometa")
        vid_dir.mkdir(parents=True, exist_ok=True)
        find_artifact(vid_dir, "transcript", extension="txt").write_text(
            "Transcript without metadata.", encoding="utf-8"
        )
        self._patch_common(monkeypatch, config)
        seen: list[str] = []
        monkeypatch.setattr(
            helpers_mod,
            "analyze_video",
            lambda *args, **kwargs: seen.append("full") or "## No meta insight",
        )
        monkeypatch.setattr(
            helpers_mod,
            "analyze_short",
            lambda *args, **kwargs: seen.append("short") or "## Short no meta",
        )
        monkeypatch.setattr(reprocess_mod, "synthesize_channel", lambda *args, **kwargs: None)
        monkeypatch.setattr(reprocess_mod, "synthesize_topic", lambda *args, **kwargs: None)
        monkeypatch.setattr(helpers_mod, "load_intent", lambda *args, **kwargs: None)

        result = runner.invoke(cli.app, ["reanalyze", "ai"])

        assert result.exit_code == 0
        assert seen == ["short"]
        assert find_artifact(vid_dir, "insights").exists()

    def test_skips_channel_without_videos_dir(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        lib = Library(config)
        lib.add_channel("ai", "https://www.youtube.com/@A", "Alpha")
        lib.add_channel("ai", "https://www.youtube.com/@B", "Beta")
        _seed_video(config, channel="Alpha", video_id="v1", title="Alpha Video")
        self._patch_common(monkeypatch, config)
        monkeypatch.setattr(helpers_mod, "analyze_video", lambda *args, **kwargs: "## Reanalyzed")
        monkeypatch.setattr(reprocess_mod, "synthesize_channel", lambda *args, **kwargs: None)
        monkeypatch.setattr(reprocess_mod, "synthesize_topic", lambda *args, **kwargs: None)
        monkeypatch.setattr(helpers_mod, "load_intent", lambda *args, **kwargs: None)

        result = runner.invoke(cli.app, ["reanalyze", "ai", "--dry-run"])

        assert result.exit_code == 0
        assert "Alpha Video" in result.output

    def test_skips_non_video_entries(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_library(config)
        vdir = config.videos_dir("ai", "TestCh")
        vdir.mkdir(parents=True, exist_ok=True)
        (vdir / "notes.txt").write_text("not a directory", encoding="utf-8")
        _seed_video(config, video_id="good", title="Real Video")
        self._patch_common(monkeypatch, config)
        monkeypatch.setattr(helpers_mod, "analyze_video", lambda *args, **kwargs: "## Reanalyzed")
        monkeypatch.setattr(reprocess_mod, "synthesize_channel", lambda *args, **kwargs: None)
        monkeypatch.setattr(reprocess_mod, "synthesize_topic", lambda *args, **kwargs: None)
        monkeypatch.setattr(helpers_mod, "load_intent", lambda *args, **kwargs: None)

        result = runner.invoke(cli.app, ["reanalyze", "ai", "--dry-run"])

        assert result.exit_code == 0
        assert "Real Video" in result.output

    def test_skips_missing_transcript_file(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_library(config)
        vid_dir = config.video_dir("ai", "TestCh", "empty")
        vid_dir.mkdir(parents=True, exist_ok=True)
        (vid_dir / "metadata.json").write_text(
            json.dumps({"title": "No Transcript", "duration": 600}), encoding="utf-8"
        )
        self._patch_common(monkeypatch, config)

        result = runner.invoke(cli.app, ["reanalyze", "ai"])

        assert result.exit_code == 0
        assert "No videos with transcripts found" in result.output


class TestRegister:
    def test_register_adds_reprocess_commands(self):
        app = typer.Typer()
        reprocess_mod.register(app)
        callbacks = {cmd.callback for cmd in app.registered_commands}
        assert reprocess_mod.resynthesize in callbacks
        assert reprocess_mod.reanalyze in callbacks

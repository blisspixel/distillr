"""Unit tests for ``distill.commands.process`` video, channel, and run commands."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

from typer.testing import CliRunner

from distill import cli
from distill.commands import _helpers as helpers_mod
from distill.commands import process as process_mod
from distill.config import DistillConfig
from distill.ingestors.youtube.discovery import VideoInfo
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


def _video(**kwargs) -> VideoInfo:
    defaults = {
        "video_id": "v1",
        "title": "Video 1",
        "upload_date": _recent(2),
        "duration": 600,
        "url": "https://youtube.com/watch?v=v1",
        "channel_name": "TestCh",
        "channel_url": "https://www.youtube.com/@TestCh",
    }
    defaults.update(kwargs)
    return VideoInfo(**defaults)


def _seed_library(config: DistillConfig, topic: str = "ai", channel: str = "TestCh") -> Library:
    lib = Library(config)
    lib.add_channel(topic, f"https://www.youtube.com/@{channel}", channel)
    return lib


class TestVideoCommand:
    @staticmethod
    def _seed_completed_video(config: DistillConfig, info: VideoInfo) -> tuple[Path, Path]:
        video_dir = config.video_dir_slug("ai", info.channel_name, info.title, info.video_id)
        video_dir.mkdir(parents=True, exist_ok=True)
        (video_dir / "metadata.json").write_text(
            json.dumps(
                {
                    "video_id": info.video_id,
                    "title": info.title,
                    "upload_date": info.upload_date,
                    "duration": info.duration,
                    "url": info.url,
                    "channel": info.channel_name,
                    "analysis_mode": "full",
                }
            ),
            encoding="utf-8",
        )
        transcript = video_dir / "transcript.txt"
        insights = video_dir / "insights.md"
        transcript.write_text("Existing transcript", encoding="utf-8")
        insights.write_text("---\nvideo_id: v1\n---\n\nExisting insight", encoding="utf-8")
        return transcript, insights

    def test_exact_completed_video_replay_is_a_write_free_noop(self, tmp_path, monkeypatch):
        info = _video()
        config = _config(tmp_path)
        transcript, insights = self._seed_completed_video(config, info)
        before = {
            path: (path.read_bytes(), path.stat().st_mtime_ns) for path in (transcript, insights)
        }
        process_video = MagicMock(return_value=True)
        require_model = MagicMock()
        enforce_budget = MagicMock()
        monkeypatch.setattr(process_mod, "get_config", lambda: config)
        monkeypatch.setattr(process_mod, "get_video_info", lambda _url: info)
        monkeypatch.setattr(process_mod, "_process_video", process_video)
        monkeypatch.setattr(process_mod, "_require_model", require_model)
        monkeypatch.setattr(process_mod, "enforce_projected_workflow_budget", enforce_budget)

        result = runner.invoke(cli.app, ["video", info.url, "--topic", "ai"])

        assert result.exit_code == 0, result.output
        assert "Already complete for this video ID" in result.output
        assert "--force" in result.output
        process_video.assert_not_called()
        require_model.assert_not_called()
        enforce_budget.assert_not_called()
        assert {
            path: (path.read_bytes(), path.stat().st_mtime_ns) for path in (transcript, insights)
        } == before
        assert not (config.library_dir / ".distill" / "cost_log.jsonl").exists()

    def test_force_reanalyzes_an_exact_completed_video(self, tmp_path, monkeypatch):
        info = _video()
        config = _config(tmp_path)
        self._seed_completed_video(config, info)
        process_video = MagicMock(return_value=True)
        require_model = MagicMock()
        monkeypatch.setattr(process_mod, "get_config", lambda: config)
        monkeypatch.setattr(process_mod, "get_video_info", lambda _url: info)
        monkeypatch.setattr(process_mod, "_process_video", process_video)
        monkeypatch.setattr(process_mod, "_require_model", require_model)
        monkeypatch.setattr(process_mod, "display_summary", lambda *args, **kwargs: None)

        result = runner.invoke(cli.app, ["video", info.url, "--topic", "ai", "--force"])

        assert result.exit_code == 0, result.output
        process_video.assert_called_once()
        require_model.assert_called_once()

    def test_video_info_failure_exits(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        monkeypatch.setattr(process_mod, "get_config", lambda: config)
        monkeypatch.setattr(process_mod, "get_video_info", lambda _url: None)
        monkeypatch.setattr(process_mod, "display_summary", lambda *args, **kwargs: None)

        result = runner.invoke(cli.app, ["video", "https://youtube.com/watch?v=bad"])

        assert result.exit_code == 1
        assert "Could not get video info" in result.output

    def test_invalid_video_is_refused_before_config_fetch_or_run_evidence(self, monkeypatch):
        get_config = MagicMock()
        get_video_info = MagicMock()
        display_summary = MagicMock()
        raw = "https://evil.example/watch?v=abc&token=VIDEO-CANARY"
        monkeypatch.setattr(process_mod, "get_config", get_config)
        monkeypatch.setattr(process_mod, "get_video_info", get_video_info)
        monkeypatch.setattr(process_mod, "display_summary", display_summary)

        result = runner.invoke(cli.app, ["video", raw])

        assert result.exit_code == 2
        assert "Refusing invalid YouTube video URL" in result.output
        assert "VIDEO-CANARY" not in result.output
        get_config.assert_not_called()
        get_video_info.assert_not_called()
        display_summary.assert_not_called()

    def test_process_video_failure_exits(self, tmp_path, monkeypatch):
        info = _video()
        config = _config(tmp_path)
        monkeypatch.setattr(process_mod, "get_config", lambda: config)
        monkeypatch.setattr(process_mod, "get_video_info", lambda _url: info)
        monkeypatch.setattr(process_mod, "_process_video", lambda *args, **kwargs: False)
        monkeypatch.setattr(process_mod, "display_summary", lambda *args, **kwargs: None)

        result = runner.invoke(cli.app, ["video", info.url])

        assert result.exit_code == 1

    def test_refuses_projected_video_budget_before_processing(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DISTILL_PROVIDER", "xai")
        monkeypatch.setenv("XAI_API_KEY", "test-key")
        info = _video()
        config = _config(tmp_path)
        config.distill_cost_workflow_budgets = "video=0.0001"
        monkeypatch.setattr(process_mod, "get_config", lambda: config)
        monkeypatch.setattr(process_mod, "get_video_info", lambda _url: info)
        process_video = MagicMock(return_value=True)
        monkeypatch.setattr(process_mod, "_process_video", process_video)

        result = runner.invoke(cli.app, ["video", info.url])

        assert result.exit_code == 1
        assert isinstance(result.exception, ProjectedBudgetExceededError)
        process_video.assert_not_called()

    def test_video_show_prints_insights_inline(self, tmp_path, monkeypatch):
        info = _video()
        config = _config(tmp_path)
        monkeypatch.setattr(process_mod, "get_config", lambda: config)
        monkeypatch.setattr(process_mod, "get_video_info", lambda _url: info)
        monkeypatch.setattr(process_mod, "display_summary", lambda *args, **kwargs: None)

        def fake_process(topic, channel_name, video, cfg, tracker, summary):
            vid_dir = cfg.video_dir_slug(topic, channel_name, video.title, video.video_id)
            vid_dir.mkdir(parents=True, exist_ok=True)
            (vid_dir / "transcript.txt").write_text("Transcript", encoding="utf-8")
            (vid_dir / "insights.md").write_text(
                "---\n---\n\n## Summary\nInline insight", encoding="utf-8"
            )
            return True

        monkeypatch.setattr(process_mod, "_process_video", fake_process)

        result = runner.invoke(cli.app, ["video", info.url, "--show"])

        assert result.exit_code == 0
        assert "Inline insight" in result.output
        assert "Use --show to print the analysis inline" not in result.output

    def test_panel_render_failure_falls_back_to_plain_text(self, tmp_path, monkeypatch):
        info = _video()
        config = _config(tmp_path)
        monkeypatch.setattr(process_mod, "get_config", lambda: config)
        monkeypatch.setattr(process_mod, "get_video_info", lambda _url: info)
        monkeypatch.setattr(process_mod, "display_summary", lambda *args, **kwargs: None)

        def fake_process(topic, channel_name, video, cfg, tracker, summary):
            vid_dir = cfg.video_dir_slug(topic, channel_name, video.title, video.video_id)
            vid_dir.mkdir(parents=True, exist_ok=True)
            (vid_dir / "transcript.txt").write_text("Transcript", encoding="utf-8")
            (vid_dir / "insights.md").write_text("---\n---\n\nBody", encoding="utf-8")
            return True

        monkeypatch.setattr(process_mod, "_process_video", fake_process)
        monkeypatch.setattr(process_mod, "Panel", MagicMock(side_effect=RuntimeError("panel fail")))

        result = runner.invoke(cli.app, ["video", info.url])

        assert result.exit_code == 0
        assert info.title in result.output


class TestChannelCommand:
    def _patch_common(self, monkeypatch, config, videos: list[VideoInfo]):
        monkeypatch.setattr(process_mod, "get_config", lambda: config)
        monkeypatch.setattr(process_mod, "_preflight", lambda: None)
        monkeypatch.setattr(process_mod, "resolve_channel_name", lambda _url: "TestCh")
        monkeypatch.setattr(
            process_mod,
            "discover_videos",
            lambda _url, _months, include_shorts=True, **_kwargs: videos,
        )
        monkeypatch.setattr(process_mod, "display_estimate", lambda *args, **kwargs: None)
        monkeypatch.setattr(process_mod, "display_summary", lambda *args, **kwargs: None)
        monkeypatch.setattr(process_mod, "_ensure_channel_context", lambda *args, **kwargs: None)

    def test_channel_adds_and_processes_videos(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        videos = [_video(), _video(video_id="v2", title="Video 2")]
        self._patch_common(monkeypatch, config, videos)
        processed: list[str] = []

        def fake_process(topic, channel, video, cfg, tracker, summary, **kwargs):
            processed.append(video.video_id)
            return True

        monkeypatch.setattr(process_mod, "_process_video", fake_process)
        monkeypatch.setattr(process_mod, "synthesize_channel", lambda *args, **kwargs: "# Synth")

        result = runner.invoke(cli.app, ["channel", "https://www.youtube.com/@TestCh"])

        assert result.exit_code == 0
        assert "Added TestCh" in result.output
        assert processed == ["v1", "v2"]
        assert "What's next" in result.output

    def test_invalid_channel_is_refused_before_preflight_config_or_library_mutation(
        self, monkeypatch
    ):
        preflight = MagicMock()
        get_config = MagicMock()
        resolve_name = MagicMock()
        discover = MagicMock()
        raw = "https://www.youtube.com/@TestCh?token=CHANNEL-CANARY"
        monkeypatch.setattr(process_mod, "_preflight", preflight)
        monkeypatch.setattr(process_mod, "get_config", get_config)
        monkeypatch.setattr(process_mod, "resolve_channel_name", resolve_name)
        monkeypatch.setattr(process_mod, "discover_videos", discover)

        result = runner.invoke(cli.app, ["channel", raw])

        assert result.exit_code == 2
        assert "Refusing invalid YouTube channel URL" in result.output
        assert "CHANNEL-CANARY" not in result.output
        preflight.assert_not_called()
        get_config.assert_not_called()
        resolve_name.assert_not_called()
        discover.assert_not_called()

    def test_channel_already_registered_and_skips_processed(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_library(config)
        state_file = config.channel_dir("ai", "TestCh") / "state.json"
        from distill.library.state import ChannelState

        state = ChannelState(state_file)
        state.mark_processed("v1", "Video 1", _recent(2))

        self._patch_common(monkeypatch, config, [_video()])
        monkeypatch.setattr(process_mod, "_process_video", lambda *args, **kwargs: True)
        monkeypatch.setattr(process_mod, "synthesize_channel", lambda *args, **kwargs: None)

        result = runner.invoke(cli.app, ["channel", "https://www.youtube.com/@TestCh"])

        assert result.exit_code == 0
        assert "already in ai" in result.output
        assert "Already done" in result.output

    def test_channel_no_videos_in_range(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        self._patch_common(monkeypatch, config, [])

        result = runner.invoke(cli.app, ["channel", "https://www.youtube.com/@TestCh"])

        assert result.exit_code == 0
        assert "No videos found in date range" in result.output

    def test_refuses_projected_channel_budget_before_processing(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DISTILL_PROVIDER", "xai")
        monkeypatch.setenv("XAI_API_KEY", "test-key")
        config = _config(tmp_path)
        config.distill_cost_workflow_budgets = "channel=0.0001"
        self._patch_common(monkeypatch, config, [_video()])
        process_video = MagicMock(return_value=True)
        synthesize_channel = MagicMock()
        monkeypatch.setattr(process_mod, "_process_video", process_video)
        monkeypatch.setattr(process_mod, "synthesize_channel", synthesize_channel)

        result = runner.invoke(cli.app, ["channel", "https://www.youtube.com/@TestCh"])

        assert result.exit_code == 1
        assert isinstance(result.exception, ProjectedBudgetExceededError)
        process_video.assert_not_called()
        synthesize_channel.assert_not_called()

    def test_channel_synthesis_failure_is_reported(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        self._patch_common(monkeypatch, config, [_video()])

        def boom(*args, **kwargs):
            raise RuntimeError("synth fail")

        monkeypatch.setattr(process_mod, "_process_video", lambda *args, **kwargs: True)
        monkeypatch.setattr(process_mod, "synthesize_channel", boom)

        result = runner.invoke(cli.app, ["channel", "https://www.youtube.com/@TestCh"])

        assert result.exit_code == 0
        assert "Synthesis failed" in result.output

    def test_channel_honors_limit(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        videos = [_video(), _video(video_id="v2", title="Video 2")]
        self._patch_common(monkeypatch, config, videos)
        monkeypatch.setattr(process_mod, "_process_video", lambda *args, **kwargs: True)
        monkeypatch.setattr(process_mod, "synthesize_channel", lambda *args, **kwargs: None)

        result = runner.invoke(
            cli.app, ["channel", "https://www.youtube.com/@TestCh", "--limit", "1"]
        )

        assert result.exit_code == 0
        assert "Limited to 1 videos" in result.output

    def test_channel_limit_applies_to_unprocessed_videos(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        videos = [
            _video(video_id="old1", title="Already Done"),
            _video(video_id="new1", title="Should Process"),
        ]
        self._patch_common(monkeypatch, config, videos)
        processed: list[str] = []

        def fake_process(_topic, _channel, video, *_args, **_kwargs):
            processed.append(video.video_id)
            return True

        monkeypatch.setattr(process_mod, "_process_video", fake_process)
        monkeypatch.setattr(process_mod, "synthesize_channel", lambda *args, **kwargs: None)
        from distill.library.state import ChannelState

        Library(config).add_channel("ai", "https://www.youtube.com/@TestCh", "TestCh")
        state = ChannelState(config.channel_dir("ai", "TestCh") / "state.json")
        state.mark_processed("old1", "Already Done", _recent(2))

        result = runner.invoke(
            cli.app, ["channel", "https://www.youtube.com/@TestCh", "--limit", "1"]
        )

        assert result.exit_code == 0, result.output
        assert processed == ["new1"]

    def test_channel_with_report_flag(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        self._patch_common(monkeypatch, config, [_video()])
        monkeypatch.setattr(process_mod, "_process_video", lambda *args, **kwargs: True)
        monkeypatch.setattr(process_mod, "synthesize_channel", lambda *args, **kwargs: None)
        called: list[str] = []
        monkeypatch.setattr(
            process_mod,
            "_run_scope_report",
            lambda topic, cfg, tracker, **kwargs: called.append(kwargs.get("scope", "")),
        )

        result = runner.invoke(cli.app, ["channel", "https://www.youtube.com/@TestCh", "--report"])

        assert result.exit_code == 0
        assert called == ["channel"]

    def test_channel_discovery_failure_exits(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        self._patch_common(monkeypatch, config, [_video()])

        def boom(*_args, **_kwargs):
            raise RuntimeError("extractor down")

        monkeypatch.setattr(process_mod, "discover_videos", boom)

        result = runner.invoke(cli.app, ["channel", "https://www.youtube.com/@TestCh"])

        assert result.exit_code == 1
        assert "Discovery failed: extractor down" in result.output


class TestRunCommand:
    def _patch_discover(self, monkeypatch, videos: list[VideoInfo]):
        monkeypatch.setattr(
            process_mod,
            "discover_videos",
            lambda _url, _months, include_shorts=False, **_kwargs: videos,
        )

    def _patch_run_processing(self, monkeypatch):
        monkeypatch.setattr(
            process_mod,
            "generate_channel_context",
            lambda *args, **kwargs: "# Channel context\n",
        )

    def test_run_continues_when_one_channel_discovery_fails(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        lib = Library(config)
        lib.add_channel("ai", "https://www.youtube.com/@ChanA", "Alpha")
        lib.add_channel("ai", "https://www.youtube.com/@ChanB", "Beta")
        seen: list[str] = []

        def discover(url, months=1, include_shorts=False, **_kwargs):
            seen.append(url)
            if "ChanA" in url:
                raise RuntimeError("extractor down")
            return [_video(video_id="b1", title="Beta Video")]

        monkeypatch.setattr(process_mod, "discover_videos", discover)
        monkeypatch.setattr(process_mod, "get_config", lambda: config)
        monkeypatch.setattr(process_mod, "display_summary", lambda *args, **kwargs: None)
        self._patch_run_processing(monkeypatch)
        processed: list[str] = []
        monkeypatch.setattr(
            process_mod,
            "_process_video",
            lambda *_args, **_kwargs: processed.append("ok") or True,
        )
        monkeypatch.setattr(process_mod, "synthesize_channel", lambda *args, **kwargs: None)
        monkeypatch.setattr(process_mod, "synthesize_topic", lambda *args, **kwargs: None)

        result = runner.invoke(cli.app, ["run", "ai"])

        assert result.exit_code == 0, result.output
        assert "Discovery failed: extractor down" in result.output
        assert seen == ["https://www.youtube.com/@ChanA", "https://www.youtube.com/@ChanB"]
        assert processed == ["ok"]

    def test_run_requires_topic_or_all(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        monkeypatch.setattr(process_mod, "get_config", lambda: config)

        result = runner.invoke(cli.app, ["run"])

        assert result.exit_code == 1
        assert "Specify a topic or use --all" in result.output

    def test_run_no_channels_for_topic(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        monkeypatch.setattr(process_mod, "get_config", lambda: config)

        result = runner.invoke(cli.app, ["run", "missing"])

        assert result.exit_code == 0
        assert "No channels found" in result.output

    def test_run_all_empty_library_no_crash(self, tmp_path, monkeypatch):
        """Regression: `run --all` against an empty library has no topics, so the
        'What's next' hints must not index into an empty list (was IndexError).
        """
        config = _config(tmp_path)
        monkeypatch.setattr(process_mod, "get_config", lambda: config)
        monkeypatch.setattr(process_mod, "display_summary", lambda *args, **kwargs: None)

        result = runner.invoke(cli.app, ["run", "--all"])

        assert result.exit_code == 0, result.output

    def test_run_dry_run_marks_skip_and_new(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_library(config)
        self._patch_discover(
            monkeypatch, [_video(), _video(video_id="v2", title="Short", duration=30)]
        )
        monkeypatch.setattr(process_mod, "get_config", lambda: config)

        from distill.library.state import ChannelState

        state = ChannelState(config.channel_dir("ai", "TestCh") / "state.json")
        state.mark_processed("v1", "Video 1", _recent(2))
        synthesize_topic = MagicMock()
        monkeypatch.setattr(process_mod, "synthesize_topic", synthesize_topic)

        result = runner.invoke(cli.app, ["run", "ai", "--dry-run", "--shorts"])

        assert result.exit_code == 0
        assert "[SKIP]" in result.output
        assert "[NEW]" in result.output
        assert "Dry run: 1 videos would be processed" in result.output
        synthesize_topic.assert_not_called()

    def test_refuses_projected_run_budget_before_processing(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DISTILL_PROVIDER", "xai")
        monkeypatch.setenv("XAI_API_KEY", "test-key")
        config = _config(tmp_path)
        config.distill_cost_workflow_budgets = "run=0.0001"
        _seed_library(config)
        self._patch_discover(monkeypatch, [_video()])
        monkeypatch.setattr(process_mod, "get_config", lambda: config)
        generate_context = MagicMock(return_value="# Context\n")
        monkeypatch.setattr(process_mod, "generate_channel_context", generate_context)

        result = runner.invoke(cli.app, ["run", "ai"])

        assert result.exit_code == 1
        assert isinstance(result.exception, ProjectedBudgetExceededError)
        generate_context.assert_not_called()

    def test_run_refresh_and_limit(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_library(config)
        self._patch_discover(
            monkeypatch,
            [
                _video(),
                _video(video_id="v2", title="Video 2"),
                _video(video_id="v3", title="Video 3"),
            ],
        )
        monkeypatch.setattr(process_mod, "get_config", lambda: config)
        monkeypatch.setattr(process_mod, "display_summary", lambda *args, **kwargs: None)
        self._patch_run_processing(monkeypatch)
        monkeypatch.setattr(helpers_mod, "get_transcript", lambda *args, **kwargs: False)
        monkeypatch.setattr(process_mod, "synthesize_channel", lambda *args, **kwargs: None)
        monkeypatch.setattr(process_mod, "synthesize_topic", lambda *args, **kwargs: None)

        from distill.library.state import ChannelState

        state = ChannelState(config.channel_dir("ai", "TestCh") / "state.json")
        state.mark_processed("v1", "Video 1", _recent(2))

        result = runner.invoke(cli.app, ["run", "ai", "--refresh", "--limit", "1"])

        assert result.exit_code == 0
        assert "new since last refresh" in result.output
        assert "Limited to 1 videos" in result.output

    def test_run_limit_without_refresh_processes_unprocessed(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_library(config)
        self._patch_discover(
            monkeypatch,
            [
                _video(video_id="old1", title="Already Done"),
                _video(video_id="new1", title="Should Process"),
                _video(video_id="new2", title="Later New"),
            ],
        )
        monkeypatch.setattr(process_mod, "get_config", lambda: config)
        monkeypatch.setattr(process_mod, "display_summary", lambda *args, **kwargs: None)
        self._patch_run_processing(monkeypatch)
        processed: list[str] = []

        def fake_process(_topic, _channel, video, *_args, **_kwargs):
            processed.append(video.video_id)
            return True

        monkeypatch.setattr(process_mod, "_process_video", fake_process)
        monkeypatch.setattr(process_mod, "synthesize_channel", lambda *args, **kwargs: None)
        monkeypatch.setattr(process_mod, "synthesize_topic", lambda *args, **kwargs: None)
        from distill.library.state import ChannelState

        state = ChannelState(config.channel_dir("ai", "TestCh") / "state.json")
        state.mark_processed("old1", "Already Done", _recent(2))

        result = runner.invoke(cli.app, ["run", "ai", "--limit", "1"])

        assert result.exit_code == 0, result.output
        assert processed == ["new1"]

    def test_run_delegates_writes_and_verification_to_shared_processor(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_library(config)
        video = _video()
        self._patch_discover(monkeypatch, [video])
        self._patch_run_processing(monkeypatch)
        processor = MagicMock(return_value=True)
        monkeypatch.setattr(process_mod, "get_config", lambda: config)
        monkeypatch.setattr(process_mod, "display_estimate", lambda *args, **kwargs: None)
        monkeypatch.setattr(process_mod, "display_summary", lambda *args, **kwargs: None)
        monkeypatch.setattr(process_mod, "_process_video", processor)
        monkeypatch.setattr(process_mod, "synthesize_channel", lambda *args, **kwargs: None)
        monkeypatch.setattr(process_mod, "synthesize_topic", lambda *args, **kwargs: None)

        result = runner.invoke(cli.app, ["run", "ai"])

        assert result.exit_code == 0, result.output
        processor.assert_called_once()
        args, kwargs = processor.call_args
        assert args[:3] == ("ai", "TestCh", video)
        assert kwargs["state"].state_file == config.channel_dir("ai", "TestCh") / "state.json"
        assert not kwargs["state"].is_processed(video.video_id)
        assert kwargs["eta"] is not None

    def test_run_processes_full_video_path(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_library(config)
        video = _video()
        self._patch_discover(monkeypatch, [video])
        monkeypatch.setattr(process_mod, "get_config", lambda: config)
        monkeypatch.setattr(process_mod, "display_estimate", lambda *args, **kwargs: None)
        monkeypatch.setattr(process_mod, "display_summary", lambda *args, **kwargs: None)
        self._patch_run_processing(monkeypatch)

        def write_transcript(_url, _video_id, transcript_file, _cfg, tracker=None):
            transcript_file.parent.mkdir(parents=True, exist_ok=True)
            transcript_file.write_text("Long enough transcript body.", encoding="utf-8")
            return True

        monkeypatch.setattr(helpers_mod, "get_transcript", write_transcript)
        monkeypatch.setattr(
            helpers_mod, "analyze_video", lambda *args, **kwargs: "## Summary\nInsight"
        )
        monkeypatch.setattr(process_mod, "synthesize_channel", lambda *args, **kwargs: "# Channel")
        monkeypatch.setattr(process_mod, "synthesize_topic", lambda *args, **kwargs: "# Topic")
        monkeypatch.setattr(helpers_mod, "load_intent", lambda *args, **kwargs: None)

        result = runner.invoke(cli.app, ["run", "ai"])

        assert result.exit_code == 0
        assert "done" in result.output
        assert "What's next" in result.output
        vid_dir = config.video_dir_slug("ai", "TestCh", video.title, video.video_id)
        assert (vid_dir / "metadata.json").exists()
        assert find_artifact(vid_dir, "insights").exists()

    def test_run_short_video_uses_analyze_short(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_library(config)
        self._patch_discover(monkeypatch, [_video(duration=30, title="Short Clip")])
        monkeypatch.setattr(process_mod, "get_config", lambda: config)
        monkeypatch.setattr(process_mod, "display_estimate", lambda *args, **kwargs: None)
        monkeypatch.setattr(process_mod, "display_summary", lambda *args, **kwargs: None)
        self._patch_run_processing(monkeypatch)

        def write_transcript(_url, _video_id, transcript_file, _cfg, tracker=None):
            transcript_file.parent.mkdir(parents=True, exist_ok=True)
            transcript_file.write_text("Short transcript body.", encoding="utf-8")
            return True

        monkeypatch.setattr(helpers_mod, "get_transcript", write_transcript)
        seen: list[str] = []

        def capture_short(*args, **kwargs):
            seen.append("short")
            return "## Short insight"

        monkeypatch.setattr(helpers_mod, "analyze_short", capture_short)
        monkeypatch.setattr(
            helpers_mod, "analyze_video", lambda *args, **kwargs: seen.append("full")
        )
        monkeypatch.setattr(process_mod, "synthesize_channel", lambda *args, **kwargs: None)
        monkeypatch.setattr(process_mod, "synthesize_topic", lambda *args, **kwargs: None)
        monkeypatch.setattr(helpers_mod, "load_intent", lambda *args, **kwargs: None)

        result = runner.invoke(cli.app, ["run", "ai", "--shorts"])

        assert result.exit_code == 0
        assert seen == ["short"]

    def test_run_skips_when_transcript_missing(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_library(config)
        self._patch_discover(monkeypatch, [_video()])
        monkeypatch.setattr(process_mod, "get_config", lambda: config)
        monkeypatch.setattr(process_mod, "display_estimate", lambda *args, **kwargs: None)
        monkeypatch.setattr(process_mod, "display_summary", lambda *args, **kwargs: None)
        self._patch_run_processing(monkeypatch)
        monkeypatch.setattr(helpers_mod, "get_transcript", lambda *args, **kwargs: False)
        monkeypatch.setattr(process_mod, "synthesize_channel", lambda *args, **kwargs: None)
        monkeypatch.setattr(process_mod, "synthesize_topic", lambda *args, **kwargs: None)

        result = runner.invoke(cli.app, ["run", "ai"])

        assert result.exit_code == 0
        assert "no transcript" in result.output.lower()

    def test_run_skips_empty_transcript(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_library(config)
        video = _video()
        self._patch_discover(monkeypatch, [video])
        monkeypatch.setattr(process_mod, "get_config", lambda: config)
        monkeypatch.setattr(process_mod, "display_estimate", lambda *args, **kwargs: None)
        monkeypatch.setattr(process_mod, "display_summary", lambda *args, **kwargs: None)
        self._patch_run_processing(monkeypatch)

        def write_empty_transcript(url, video_id, transcript_file, cfg, tracker=None):
            transcript_file.parent.mkdir(parents=True, exist_ok=True)
            transcript_file.write_text("   ", encoding="utf-8")
            return True

        monkeypatch.setattr(helpers_mod, "get_transcript", write_empty_transcript)
        monkeypatch.setattr(process_mod, "synthesize_channel", lambda *args, **kwargs: None)
        monkeypatch.setattr(process_mod, "synthesize_topic", lambda *args, **kwargs: None)

        result = runner.invoke(cli.app, ["run", "ai"])

        assert result.exit_code == 0
        assert "empty transcript" in result.output.lower()

    def test_run_analysis_failure_keeps_transcript(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_library(config)
        self._patch_discover(monkeypatch, [_video()])
        monkeypatch.setattr(process_mod, "get_config", lambda: config)
        monkeypatch.setattr(process_mod, "display_estimate", lambda *args, **kwargs: None)
        monkeypatch.setattr(process_mod, "display_summary", lambda *args, **kwargs: None)
        self._patch_run_processing(monkeypatch)

        def write_transcript(_url, _video_id, transcript_file, _cfg, tracker=None):
            transcript_file.parent.mkdir(parents=True, exist_ok=True)
            transcript_file.write_text("Transcript for retry.", encoding="utf-8")
            return True

        monkeypatch.setattr(helpers_mod, "get_transcript", write_transcript)
        monkeypatch.setattr(
            helpers_mod, "analyze_video", MagicMock(side_effect=RuntimeError("llm fail"))
        )
        monkeypatch.setattr(process_mod, "synthesize_channel", lambda *args, **kwargs: None)
        monkeypatch.setattr(process_mod, "synthesize_topic", lambda *args, **kwargs: None)
        monkeypatch.setattr(helpers_mod, "load_intent", lambda *args, **kwargs: None)

        result = runner.invoke(cli.app, ["run", "ai"])

        assert result.exit_code == 0
        assert "failed: llm fail" in result.output.lower()
        transcript = find_artifact(
            config.video_dir_slug("ai", "TestCh", "Video 1", "v1"),
            "transcript",
            extension="txt",
        )
        assert transcript.read_text(encoding="utf-8") == "Transcript for retry."

    def test_run_filters_to_single_channel(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        lib = Library(config)
        lib.add_channel("ai", "https://www.youtube.com/@ChanA", "Alpha")
        lib.add_channel("ai", "https://www.youtube.com/@ChanB", "Beta")
        seen: list[str] = []
        monkeypatch.setattr(
            process_mod,
            "discover_videos",
            lambda url, months, include_shorts=False, **_kwargs: seen.append(url) or [],
        )
        monkeypatch.setattr(process_mod, "get_config", lambda: config)

        result = runner.invoke(cli.app, ["run", "ai", "--channel", "Alpha", "--dry-run"])

        assert result.exit_code == 0
        assert seen == ["https://www.youtube.com/@ChanA"]

    def test_run_skips_already_processed_videos(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_library(config)
        self._patch_discover(monkeypatch, [_video()])
        monkeypatch.setattr(process_mod, "get_config", lambda: config)
        monkeypatch.setattr(process_mod, "display_summary", lambda *args, **kwargs: None)
        self._patch_run_processing(monkeypatch)

        from distill.library.state import ChannelState

        state = ChannelState(config.channel_dir("ai", "TestCh") / "state.json")
        state.mark_processed("v1", "Video 1", _recent(2))
        monkeypatch.setattr(process_mod, "synthesize_channel", lambda *args, **kwargs: None)
        monkeypatch.setattr(process_mod, "synthesize_topic", lambda *args, **kwargs: None)

        result = runner.invoke(cli.app, ["run", "ai"])

        assert result.exit_code == 0
        assert "Already processed" in result.output

    def test_run_reuses_existing_transcript(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_library(config)
        video = _video()
        self._patch_discover(monkeypatch, [video])
        monkeypatch.setattr(process_mod, "get_config", lambda: config)
        monkeypatch.setattr(process_mod, "display_estimate", lambda *args, **kwargs: None)
        monkeypatch.setattr(process_mod, "display_summary", lambda *args, **kwargs: None)
        self._patch_run_processing(monkeypatch)

        vid_dir = config.video_dir_slug("ai", "TestCh", video.title, video.video_id)
        vid_dir.mkdir(parents=True, exist_ok=True)
        transcript_file = find_artifact(vid_dir, "transcript", extension="txt")
        transcript_file.write_text("Existing transcript body.", encoding="utf-8")

        get_transcript = MagicMock(return_value=True)
        monkeypatch.setattr(helpers_mod, "get_transcript", get_transcript)
        monkeypatch.setattr(
            helpers_mod, "analyze_video", lambda *args, **kwargs: "## Summary\nDone"
        )
        monkeypatch.setattr(process_mod, "synthesize_channel", lambda *args, **kwargs: None)
        monkeypatch.setattr(process_mod, "synthesize_topic", lambda *args, **kwargs: None)
        monkeypatch.setattr(helpers_mod, "load_intent", lambda *args, **kwargs: None)

        result = runner.invoke(cli.app, ["run", "ai"])

        get_transcript.assert_not_called()
        assert result.exit_code == 0
        assert find_artifact(vid_dir, "insights").exists()

    def test_run_channel_synthesis_failure(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_library(config)
        video = _video()
        self._patch_discover(monkeypatch, [video])
        self._patch_run_processing(monkeypatch)
        monkeypatch.setattr(process_mod, "get_config", lambda: config)
        monkeypatch.setattr(process_mod, "display_summary", lambda *args, **kwargs: None)

        ctx_file = config.channel_dir("ai", "TestCh") / "channel_context.md"
        ctx_file.parent.mkdir(parents=True, exist_ok=True)
        ctx_file.write_text("# Channel context\n", encoding="utf-8")

        from distill.library.state import ChannelState

        state = ChannelState(config.channel_dir("ai", "TestCh") / "state.json")
        state.mark_processed(video.video_id, video.title, video.upload_date)

        def boom(*args, **kwargs):
            raise RuntimeError("channel synth fail")

        monkeypatch.setattr(process_mod, "synthesize_channel", boom)
        monkeypatch.setattr(process_mod, "synthesize_topic", lambda *args, **kwargs: None)

        result = runner.invoke(cli.app, ["run", "ai"])

        assert result.exit_code == 0
        assert "Channel synthesis failed" in result.output

    def test_run_topic_synthesis_failure(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_library(config)
        self._patch_discover(monkeypatch, [])
        monkeypatch.setattr(process_mod, "get_config", lambda: config)
        monkeypatch.setattr(process_mod, "display_summary", lambda *args, **kwargs: None)
        monkeypatch.setattr(process_mod, "synthesize_channel", lambda *args, **kwargs: None)

        def boom(*args, **kwargs):
            raise RuntimeError("topic synth fail")

        monkeypatch.setattr(process_mod, "synthesize_topic", boom)

        result = runner.invoke(cli.app, ["run", "ai"])

        assert result.exit_code == 0
        assert "Topic synthesis failed" in result.output

    def test_register_adds_process_commands(self):
        import typer

        app = typer.Typer()
        process_mod.register(app)
        callbacks = {cmd.callback for cmd in app.registered_commands}
        assert process_mod.video in callbacks
        assert process_mod.channel_cmd in callbacks
        assert process_mod.run in callbacks

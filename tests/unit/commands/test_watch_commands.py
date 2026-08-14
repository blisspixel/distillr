"""Unit tests for ``distill.commands.watch`` watchlist and catch-up commands."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import typer
from typer.testing import CliRunner

from distill import cli
from distill.commands import watch as watch_mod
from distill.config import DistillConfig
from distill.ingestors.youtube.discovery import VideoInfo
from distill.library import Library
from distill.library.paths import artifact_path, find_artifact
from distill.library.state import ChannelState
from distill.pipeline.costs import ProjectedBudgetExceededError, TokenUsage

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


def _video(
    video_id: str = "v1",
    title: str = "New Video",
    *,
    days_ago: int = 2,
    duration: int = 600,
) -> VideoInfo:
    return VideoInfo(
        video_id,
        title,
        _recent(days_ago),
        duration,
        f"https://youtube.com/watch?v={video_id}",
    )


def _seed_watch(
    config: DistillConfig,
    *,
    name: str = "WatchMe",
    topic: str = "deals",
    days: int = 7,
    instructions: str = "",
    url: str | None = None,
) -> Library:
    lib = Library(config)
    lib.add_to_watchlist(
        url or f"https://youtube.com/@{name}",
        name,
        topic=topic,
        days=days,
        instructions=instructions,
    )
    return lib


def _seed_insight_video(
    config: DistillConfig,
    *,
    topic: str,
    channel: str,
    video_id: str,
    title: str,
    upload_date: str,
    insights_body: str,
) -> None:
    vid_dir = config.video_dir(topic, channel, video_id)
    vid_dir.mkdir(parents=True, exist_ok=True)
    meta = {
        "video_id": video_id,
        "title": title,
        "upload_date": upload_date,
        "duration": 600,
        "url": f"https://youtube.com/watch?v={video_id}",
    }
    (vid_dir / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")
    find_artifact(vid_dir, "insights").write_text(insights_body, encoding="utf-8")


class TestWatchDefault:
    def _patch(self, monkeypatch, config):
        monkeypatch.setattr(watch_mod, "get_config", lambda: config)

    def test_empty_watchlist(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        self._patch(monkeypatch, config)

        result = runner.invoke(cli.app, ["watch"])

        assert result.exit_code == 0
        assert "No channels on your watch list" in result.output

    def test_populated_watchlist_without_instructions(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_watch(config)
        self._patch(monkeypatch, config)

        result = runner.invoke(cli.app, ["watch"])

        assert result.exit_code == 0
        assert "WatchMe" in result.output
        assert "deals / 7d" in result.output

    def test_populated_watchlist_truncates_instructions(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        long_instructions = "Extract every deal with price, link, and rationale " * 3
        _seed_watch(config, instructions=long_instructions)
        self._patch(monkeypatch, config)

        result = runner.invoke(cli.app, ["watch"])

        assert result.exit_code == 0
        assert "WatchMe" in result.output
        assert "..." in result.output
        assert "1 watched" in result.output


class TestWatchAdd:
    def _patch(self, monkeypatch, config):
        monkeypatch.setattr(watch_mod, "get_config", lambda: config)
        monkeypatch.setattr(watch_mod, "resolve_channel_name", lambda _url: "NewWatch")

    def test_add_with_explicit_instructions(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        self._patch(monkeypatch, config)
        monkeypatch.setattr(watch_mod, "model_available", lambda: False)

        result = runner.invoke(
            cli.app,
            [
                "watch",
                "add",
                "https://youtube.com/@NewWatch",
                "--instructions",
                "Track enterprise pricing changes",
            ],
        )

        assert result.exit_code == 0
        assert "Watching" in result.output
        assert "Focus: Track enterprise pricing changes" in result.output
        entry = Library(config).get_watchlist()[0]
        assert entry.instructions_approved is True
        assert entry.active_instructions == "Track enterprise pricing changes"

    def test_add_auto_suggestion_requires_explicit_approval(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        self._patch(monkeypatch, config)
        monkeypatch.setattr(watch_mod, "model_available", lambda: True)
        monkeypatch.setattr(
            watch_mod,
            "discover_videos",
            lambda url, months=1, quiet=True: [_video(title="Deal Roundup")],
        )

        def generate(name, titles, cfg, tracker=None):
            assert tracker is not None
            tracker.record(
                TokenUsage(
                    call_type="watch_instructions",
                    prompt_tokens=100,
                    completion_tokens=25,
                    model="grok-4.3",
                )
            )
            return "Focus on weekly deal roundups"

        monkeypatch.setattr(
            "distill.pipeline.analysis.video.generate_watch_instructions",
            generate,
        )

        result = runner.invoke(cli.app, ["watch", "add", "https://youtube.com/@NewWatch"])

        assert result.exit_code == 0
        assert "Suggested focus (not active): Focus on weekly deal roundups" in result.output
        entry = Library(config).get_watchlist()[0]
        assert entry.instructions == ""
        assert entry.instructions_approved is False
        assert entry.active_instructions == ""
        rows = [
            json.loads(line)
            for line in (config.library_dir / ".distill" / "cost_log.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        assert len(rows) == 1
        assert rows[0]["command"] == "watch-add"
        assert rows[0]["grok_calls"] == 1

    def test_add_auto_instructions_empty_result(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        self._patch(monkeypatch, config)
        monkeypatch.setattr(watch_mod, "model_available", lambda: True)
        monkeypatch.setattr(
            watch_mod,
            "discover_videos",
            lambda url, months=1, quiet=True: [_video(title="Deal Roundup")],
        )
        monkeypatch.setattr(
            "distill.pipeline.analysis.video.generate_watch_instructions",
            lambda name, titles, cfg: "   ",
        )

        result = runner.invoke(cli.app, ["watch", "add", "https://youtube.com/@NewWatch"])

        assert result.exit_code == 0
        assert "Watching" in result.output
        assert Library(config).get_watchlist()[0].instructions == ""

    def test_add_auto_instructions_discovery_failure(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        self._patch(monkeypatch, config)
        monkeypatch.setattr(watch_mod, "model_available", lambda: True)

        def boom(*args, **kwargs):
            raise RuntimeError("discover fail")

        monkeypatch.setattr(watch_mod, "discover_videos", boom)

        result = runner.invoke(cli.app, ["watch", "add", "https://youtube.com/@NewWatch"])

        assert result.exit_code == 0
        assert "Watching" in result.output
        assert "auto-instructions skipped: discover fail" in result.output
        assert Library(config).get_watchlist()[0].instructions == ""

    def test_add_auto_instructions_generation_failure(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        self._patch(monkeypatch, config)
        monkeypatch.setattr(watch_mod, "model_available", lambda: True)
        monkeypatch.setattr(
            watch_mod,
            "discover_videos",
            lambda url, months=1, quiet=True: [_video(title="Deal Roundup")],
        )

        def boom(*args, **kwargs):
            raise RuntimeError("generation fail")

        monkeypatch.setattr("distill.pipeline.analysis.video.generate_watch_instructions", boom)

        result = runner.invoke(cli.app, ["watch", "add", "https://youtube.com/@NewWatch"])

        assert result.exit_code == 0
        assert "Watching" in result.output
        assert "auto-instructions skipped: generation fail" in result.output
        assert Library(config).get_watchlist()[0].instructions == ""

    def test_add_duplicate(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_watch(config, name="WatchMe")
        monkeypatch.setattr(watch_mod, "get_config", lambda: config)
        monkeypatch.setattr(watch_mod, "resolve_channel_name", lambda _url: "WatchMe")
        monkeypatch.setattr(watch_mod, "model_available", lambda: True)
        discover = MagicMock(return_value=[_video(title="Duplicate")])
        monkeypatch.setattr(watch_mod, "discover_videos", discover)
        generate = MagicMock(return_value="must not run")
        monkeypatch.setattr(
            "distill.pipeline.analysis.video.generate_watch_instructions",
            generate,
        )

        result = runner.invoke(cli.app, ["watch", "add", "https://youtube.com/@WatchMe"])

        assert result.exit_code == 0
        assert "already on watch list" in result.output
        discover.assert_not_called()
        generate.assert_not_called()

    def test_add_rejects_invalid_url_before_state_or_discovery(self, monkeypatch):
        get_config = MagicMock()
        resolve_name = MagicMock()
        discover = MagicMock()
        monkeypatch.setattr(watch_mod, "get_config", get_config)
        monkeypatch.setattr(watch_mod, "resolve_channel_name", resolve_name)
        monkeypatch.setattr(watch_mod, "discover_videos", discover)

        result = runner.invoke(
            cli.app,
            [
                "watch",
                "add",
                "https://user-urlpass-canary:secret@youtube.com/@WatchMe?token=query-canary",
            ],
        )

        assert result.exit_code == 2
        assert "Refusing invalid YouTube channel URL" in result.output
        assert "user-urlpass-canary" not in result.output
        assert "query-canary" not in result.output
        get_config.assert_not_called()
        resolve_name.assert_not_called()
        discover.assert_not_called()


class TestWatchMutations:
    def _patch(self, monkeypatch, config):
        monkeypatch.setattr(watch_mod, "get_config", lambda: config)

    def test_instructions_update(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_watch(config)
        self._patch(monkeypatch, config)

        result = runner.invoke(
            cli.app,
            ["watch", "instructions", "WatchMe", "Track GPU deals under $500"],
        )

        assert result.exit_code == 0
        assert "Updated instructions" in result.output
        assert Library(config).get_watchlist()[0].instructions == "Track GPU deals under $500"

    def test_instructions_missing_channel(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        self._patch(monkeypatch, config)

        result = runner.invoke(cli.app, ["watch", "instructions", "Missing", "Focus"])

        assert result.exit_code == 0
        assert "not found on watch list" in result.output

    def test_days_update_and_missing(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_watch(config, days=14)
        self._patch(monkeypatch, config)

        ok = runner.invoke(cli.app, ["watch", "days", "WatchMe", "3"])
        missing = runner.invoke(cli.app, ["watch", "days", "Missing", "3"])

        assert ok.exit_code == 0
        assert "3d lookback" in ok.output
        assert missing.exit_code == 0
        assert "not found on watch list" in missing.output

    def test_remove_success_and_missing(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_watch(config)
        self._patch(monkeypatch, config)

        ok = runner.invoke(cli.app, ["watch", "remove", "WatchMe"])
        missing = runner.invoke(cli.app, ["watch", "remove", "Missing"])

        assert ok.exit_code == 0
        assert "Removed WatchMe" in ok.output
        assert missing.exit_code == 0
        assert "not found on watch list" in missing.output


class TestShowLatestInsights:
    def test_skips_non_directory_entries_and_missing_artifacts(self, tmp_path):
        config = _config(tmp_path)
        videos_dir = config.videos_dir("deals", "WatchMe")
        videos_dir.mkdir(parents=True, exist_ok=True)
        (videos_dir / "not-a-dir.txt").write_text("file", encoding="utf-8")
        incomplete = videos_dir / "incomplete"
        incomplete.mkdir()
        (incomplete / "metadata.json").write_text("{}", encoding="utf-8")

        from io import StringIO

        buffer = StringIO()

        class _PrintConsole:
            def print(self, *args, **kwargs):
                buffer.write("".join(str(a) for a in args) + "\n")

        original = watch_mod.console
        watch_mod.console = _PrintConsole()
        try:
            watch_mod._show_latest_insights(config, "deals", "WatchMe", limit=3)
        finally:
            watch_mod.console = original

        assert buffer.getvalue() == ""

    def test_empty_summary_section_uses_fallback_line(self, tmp_path):
        config = _config(tmp_path)
        _seed_insight_video(
            config,
            topic="deals",
            channel="WatchMe",
            video_id="empty-summary",
            title="Empty Summary",
            upload_date=_recent(1),
            insights_body="# Empty Summary\n\n## Summary\n\n## Details\nDetail body only.",
        )

        from io import StringIO

        buffer = StringIO()

        class _PrintConsole:
            def print(self, *args, **kwargs):
                buffer.write("".join(str(a) for a in args) + "\n")

        original = watch_mod.console
        watch_mod.console = _PrintConsole()
        try:
            watch_mod._show_latest_insights(config, "deals", "WatchMe", limit=1)
        finally:
            watch_mod.console = original

        assert "Detail body only." in buffer.getvalue()

    def test_fallback_first_non_header_line(self, tmp_path):
        config = _config(tmp_path)
        _seed_insight_video(
            config,
            topic="deals",
            channel="WatchMe",
            video_id="fallback",
            title="Fallback Only",
            upload_date=_recent(1),
            insights_body="# Title\n\nOpening sentence without summary headings.",
        )

        from io import StringIO

        buffer = StringIO()

        class _PrintConsole:
            def print(self, *args, **kwargs):
                buffer.write("".join(str(a) for a in args) + "\n")

        original = watch_mod.console
        watch_mod.console = _PrintConsole()
        try:
            watch_mod._show_latest_insights(config, "deals", "WatchMe", limit=1)
        finally:
            watch_mod.console = original

        assert "Opening sentence without summary headings." in buffer.getvalue()

    def test_skips_missing_directory(self, tmp_path, capsys):
        config = _config(tmp_path)
        watch_mod._show_latest_insights(config, "deals", "Missing")
        assert capsys.readouterr().out == ""

    def test_skips_unreadable_insight_and_shows_readable(self, tmp_path):
        config = _config(tmp_path)
        _seed_insight_video(
            config,
            topic="deals",
            channel="WatchMe",
            video_id="good",
            title="Readable Insight",
            upload_date=_recent(1),
            insights_body="# Title\n\nReadable summary line.",
        )
        bad = config.video_dir("deals", "WatchMe", "bad")
        bad.mkdir(parents=True, exist_ok=True)
        (bad / "metadata.json").write_text("{not-json", encoding="utf-8")
        find_artifact(bad, "insights").write_bytes(b"\xff\xfe")

        from io import StringIO

        buffer = StringIO()

        class _PrintConsole:
            def print(self, *args, **kwargs):
                buffer.write("".join(str(a) for a in args) + "\n")

        original = watch_mod.console
        watch_mod.console = _PrintConsole()
        try:
            watch_mod._show_latest_insights(config, "deals", "WatchMe", limit=3)
        finally:
            watch_mod.console = original

        output = buffer.getvalue()
        assert "Readable Insight" in output
        assert "Readable summary line." in output

    def test_renders_summary_quick_take_and_fallback(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_insight_video(
            config,
            topic="deals",
            channel="WatchMe",
            video_id="v1",
            title="Summary Video",
            upload_date=_recent(1),
            insights_body="---\n---\n\n## Summary\nFirst summary line.\n\n## Details\nMore",
        )
        _seed_insight_video(
            config,
            topic="deals",
            channel="WatchMe",
            video_id="v2",
            title="Quick Take Video",
            upload_date=_recent(2),
            insights_body="# Quick Take Video\n\n## Quick Take\nFast insight here.",
        )
        _seed_insight_video(
            config,
            topic="deals",
            channel="WatchMe",
            video_id="v3",
            title="Fallback Video",
            upload_date=_recent(3),
            insights_body="# Title Only\n\nPlain opening sentence without a summary header.",
        )
        bad_dir = config.video_dir("deals", "WatchMe", "bad-meta")
        bad_dir.mkdir(parents=True, exist_ok=True)
        (bad_dir / "metadata.json").write_text("{not json", encoding="utf-8")
        find_artifact(bad_dir, "insights").write_text("body", encoding="utf-8")

        from io import StringIO

        buffer = StringIO()

        class _PrintConsole:
            def print(self, *args, **kwargs):
                buffer.write("".join(str(a) for a in args) + "\n")

        original = watch_mod.console
        watch_mod.console = _PrintConsole()
        try:
            watch_mod._show_latest_insights(config, "deals", "WatchMe", limit=3)
        finally:
            watch_mod.console = original
        output = buffer.getvalue()

        assert "Latest from WatchMe" in output
        assert "First summary line." in output
        assert "Fast insight here." in output
        assert "Plain opening sentence" in output
        assert "distill show WatchMe" in output

    def test_truncates_long_summary(self, tmp_path):
        config = _config(tmp_path)
        long_body = "x" * 350
        _seed_insight_video(
            config,
            topic="deals",
            channel="WatchMe",
            video_id="vlong",
            title="Long Summary",
            upload_date=_recent(1),
            insights_body=f"# Long\n\n## Summary\n{long_body}",
        )

        from io import StringIO

        buffer = StringIO()

        class _PrintConsole:
            def print(self, *args, **kwargs):
                buffer.write("".join(str(a) for a in args) + "\n")

        original = watch_mod.console
        watch_mod.console = _PrintConsole()
        try:
            watch_mod._show_latest_insights(config, "deals", "WatchMe", limit=1)
        finally:
            watch_mod.console = original

        rendered = buffer.getvalue()
        assert "..." in rendered
        assert "x" * 350 not in rendered


class TestCatchUp:
    def test_empty_watchlist(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        monkeypatch.setattr(watch_mod, "get_config", lambda: config)
        monkeypatch.setattr(watch_mod, "_preflight", lambda: None)

        result = runner.invoke(cli.app, ["catch-up"])

        assert result.exit_code == 0
        assert "Watch list is empty" in result.output

    def test_channel_not_on_watchlist(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_watch(config)
        monkeypatch.setattr(watch_mod, "get_config", lambda: config)
        monkeypatch.setattr(watch_mod, "_preflight", lambda: None)

        result = runner.invoke(cli.app, ["catch-up", "Nobody"])

        assert result.exit_code == 0
        assert "Nobody not on watch list" in result.output

    def test_topic_filter_no_match(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_watch(config)
        monkeypatch.setattr(watch_mod, "get_config", lambda: config)
        monkeypatch.setattr(watch_mod, "_preflight", lambda: None)

        result = runner.invoke(cli.app, ["catch-up", "--topic", "missing-topic"])

        assert result.exit_code == 0
        assert "No watched channels in topic 'missing-topic'" in result.output

    def _patch_common(self, monkeypatch, config):
        monkeypatch.setattr(watch_mod, "get_config", lambda: config)
        monkeypatch.setattr(watch_mod, "_preflight", lambda: None)
        monkeypatch.setattr(watch_mod, "_require_model", lambda: None)
        monkeypatch.setattr(watch_mod, "display_summary", lambda *args, **kwargs: None)

    def test_discovery_failure(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_watch(config)
        self._patch_common(monkeypatch, config)

        def boom(*args, **kwargs):
            raise RuntimeError("yt-dlp down")

        monkeypatch.setattr(watch_mod, "discover_videos", boom)

        result = runner.invoke(cli.app, ["catch-up"])

        assert result.exit_code == 0
        assert "discovery failed: yt-dlp down" in result.output

    def test_up_to_date_single_channel_shows_insights(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_watch(config)
        state = ChannelState(config.channel_dir("deals", "WatchMe") / "state.json")
        state.mark_processed("v1", "Existing", _recent(1))
        _seed_insight_video(
            config,
            topic="deals",
            channel="WatchMe",
            video_id="v1",
            title="Existing",
            upload_date=_recent(1),
            insights_body="# Existing\n\n## Summary\nAlready processed insight.",
        )
        self._patch_common(monkeypatch, config)
        monkeypatch.setattr(
            watch_mod,
            "discover_videos",
            lambda url, days=7, include_shorts=True, quiet=True: [_video(video_id="v1")],
        )

        result = runner.invoke(cli.app, ["catch-up", "WatchMe"])

        assert result.exit_code == 0
        assert "up to date" in result.output
        assert "Latest from WatchMe" in result.output
        assert "Already processed insight." in result.output

    def test_dry_run_lists_overflow_and_estimate(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_watch(config)
        self._patch_common(monkeypatch, config)
        videos = [
            _video(video_id=f"v{i}", title=f"Deal Video {i}", duration=600 if i % 2 else 60)
            for i in range(1, 8)
        ]
        monkeypatch.setattr(
            watch_mod,
            "discover_videos",
            lambda url, days=7, include_shorts=True, quiet=True: videos,
        )
        estimates: list[tuple[int, int]] = []

        def capture_estimate(**kwargs):
            estimates.append((kwargs["scan_videos"], kwargs["shorts"]))

        monkeypatch.setattr(watch_mod, "display_estimate", capture_estimate)

        result = runner.invoke(cli.app, ["catch-up", "--dry-run", "--limit", "7"])

        assert result.exit_code == 0
        assert "7 new" in result.output
        assert "...and 2 more" in result.output
        assert estimates == [(4, 3)]

    def test_refuses_projected_catch_up_budget_before_processing(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DISTILL_PROVIDER", "xai")
        monkeypatch.setenv("XAI_API_KEY", "test-key")
        config = _config(tmp_path)
        config.distill_cost_workflow_budgets = "catch-up=0.0001"
        _seed_watch(config)
        self._patch_common(monkeypatch, config)
        monkeypatch.setattr(
            watch_mod,
            "discover_videos",
            lambda url, days=7, include_shorts=True, quiet=True: [_video(video_id="n1")],
        )
        process_video = MagicMock()
        synthesize_channel = MagicMock()
        monkeypatch.setattr(watch_mod, "_process_video", process_video)
        monkeypatch.setattr(watch_mod, "synthesize_channel", synthesize_channel)

        result = runner.invoke(cli.app, ["catch-up"])

        assert result.exit_code == 1
        assert isinstance(result.exception, ProjectedBudgetExceededError)
        process_video.assert_not_called()
        synthesize_channel.assert_not_called()

    def test_processes_new_videos_and_synthesizes(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_watch(config, instructions="Track deals")
        self._patch_common(monkeypatch, config)
        videos = [_video(video_id="n1"), _video(video_id="n2", title="Second Video")]
        monkeypatch.setattr(
            watch_mod,
            "discover_videos",
            lambda url, days=7, include_shorts=True, quiet=True: videos,
        )
        processed: list[str] = []
        monkeypatch.setattr(watch_mod, "_ensure_channel_context", lambda *args, **kwargs: None)
        monkeypatch.setattr(
            watch_mod,
            "_process_video",
            lambda topic, channel, video, cfg, tracker, summary, **kwargs: processed.append(
                video.video_id
            ),
        )

        def fake_channel(topic, channel, cfg, tracker=None):
            ch_dir = config.channel_dir(topic, channel)
            ch_dir.mkdir(parents=True, exist_ok=True)
            artifact_path(ch_dir, "synthesis", identity=f"{topic}_{channel}").write_text(
                "# Channel synth", encoding="utf-8"
            )

        def fake_topic(topic, cfg, tracker=None):
            topic_dir = config.topic_dir(topic)
            topic_dir.mkdir(parents=True, exist_ok=True)
            artifact_path(topic_dir, "topic_synthesis", identity=topic).write_text(
                "# Topic synth", encoding="utf-8"
            )

        monkeypatch.setattr(watch_mod, "synthesize_channel", fake_channel)
        monkeypatch.setattr(watch_mod, "synthesize_topic", fake_topic)

        result = runner.invoke(cli.app, ["catch-up", "--days", "3"])

        assert result.exit_code == 0
        assert processed == ["n1", "n2"]
        assert "2 new" in result.output
        assert "What's next" in result.output

    def test_single_channel_post_run_insights(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_watch(config)
        self._patch_common(monkeypatch, config)
        monkeypatch.setattr(
            watch_mod,
            "discover_videos",
            lambda url, days=7, include_shorts=True, quiet=True: [_video(video_id="fresh")],
        )
        monkeypatch.setattr(watch_mod, "_ensure_channel_context", lambda *args, **kwargs: None)
        monkeypatch.setattr(watch_mod, "_process_video", lambda *args, **kwargs: None)
        monkeypatch.setattr(watch_mod, "synthesize_channel", lambda *args, **kwargs: None)
        monkeypatch.setattr(watch_mod, "synthesize_topic", lambda *args, **kwargs: None)
        _seed_insight_video(
            config,
            topic="deals",
            channel="WatchMe",
            video_id="fresh",
            title="Fresh Insight",
            upload_date=_recent(1),
            insights_body="# Fresh\n\n## Summary\nJust processed insight.",
        )

        result = runner.invoke(cli.app, ["catch-up", "WatchMe"])

        assert result.exit_code == 0
        assert "Just processed insight." in result.output

    def test_channel_synthesis_failure(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_watch(config)
        self._patch_common(monkeypatch, config)
        monkeypatch.setattr(
            watch_mod,
            "discover_videos",
            lambda url, days=7, include_shorts=True, quiet=True: [_video()],
        )
        monkeypatch.setattr(watch_mod, "_ensure_channel_context", lambda *args, **kwargs: None)
        monkeypatch.setattr(watch_mod, "_process_video", lambda *args, **kwargs: None)

        def boom(*args, **kwargs):
            raise RuntimeError("channel synth fail")

        monkeypatch.setattr(watch_mod, "synthesize_channel", boom)
        monkeypatch.setattr(watch_mod, "synthesize_topic", lambda *args, **kwargs: None)

        result = runner.invoke(cli.app, ["catch-up"])

        assert result.exit_code == 0
        assert "synthesis failed: channel synth fail" in result.output

    def test_topic_synthesis_failure(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_watch(config)
        self._patch_common(monkeypatch, config)
        monkeypatch.setattr(
            watch_mod,
            "discover_videos",
            lambda url, days=7, include_shorts=True, quiet=True: [_video()],
        )
        monkeypatch.setattr(watch_mod, "_ensure_channel_context", lambda *args, **kwargs: None)
        monkeypatch.setattr(watch_mod, "_process_video", lambda *args, **kwargs: None)
        monkeypatch.setattr(watch_mod, "synthesize_channel", lambda *args, **kwargs: None)

        def boom(*args, **kwargs):
            raise RuntimeError("topic synth fail")

        monkeypatch.setattr(watch_mod, "synthesize_topic", boom)

        result = runner.invoke(cli.app, ["catch-up"])

        assert result.exit_code == 0
        assert "topic synthesis failed: topic synth fail" in result.output

    def test_single_channel_skips_insights_when_watchlist_changes(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_watch(config)
        self._patch_common(monkeypatch, config)
        monkeypatch.setattr(
            watch_mod,
            "discover_videos",
            lambda url, days=7, include_shorts=True, quiet=True: [_video(video_id="fresh2")],
        )
        monkeypatch.setattr(watch_mod, "_ensure_channel_context", lambda *args, **kwargs: None)
        monkeypatch.setattr(watch_mod, "_process_video", lambda *args, **kwargs: None)
        monkeypatch.setattr(watch_mod, "synthesize_channel", lambda *args, **kwargs: None)
        monkeypatch.setattr(watch_mod, "synthesize_topic", lambda *args, **kwargs: None)

        original_get = Library.get_watchlist
        calls = {"n": 0}

        def patched_get(self):
            calls["n"] += 1
            if calls["n"] >= 2:
                return []
            return original_get(self)

        monkeypatch.setattr(Library, "get_watchlist", patched_get)

        result = runner.invoke(cli.app, ["catch-up", "WatchMe"])

        assert result.exit_code == 0
        assert "1 new" in result.output
        assert "Latest from WatchMe" not in result.output

    def test_surfaces_goal_refreshes(self, tmp_path, monkeypatch):
        from distill.pipeline.goals import save_topic_goal

        config = _config(tmp_path)
        _seed_watch(config, topic="music")
        save_topic_goal(config.library_dir, "music", "goal text", goal_file="g.md")
        self._patch_common(monkeypatch, config)
        monkeypatch.setattr(
            watch_mod,
            "discover_videos",
            lambda url, days=7, include_shorts=True, quiet=True: [],
        )

        result = runner.invoke(cli.app, ["catch-up", "--topic", "music"])

        assert result.exit_code == 0
        assert "Goal-driven topics" in result.output
        assert "distill discover --goal-file g.md --topic music --preview" in result.output

    def test_topic_filter_match(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_watch(config, name="Alpha", topic="ai")
        _seed_watch(config, name="Beta", topic="deals", url="https://youtube.com/@Beta")
        self._patch_common(monkeypatch, config)
        seen: list[str] = []

        def discover(url, days=7, include_shorts=True, quiet=True):
            seen.append(url)
            return []

        monkeypatch.setattr(watch_mod, "discover_videos", discover)

        result = runner.invoke(cli.app, ["catch-up", "--topic", "ai"])

        assert result.exit_code == 0
        assert seen == ["https://www.youtube.com/@Alpha"]


class TestRegister:
    def test_register_attaches_watch_subapp_and_catch_up(self):
        app = typer.Typer()
        watch_mod.register(app)
        assert any(group.name == "watch" for group in app.registered_groups)
        callbacks = {cmd.name for cmd in app.registered_commands}
        assert "catch-up" in callbacks

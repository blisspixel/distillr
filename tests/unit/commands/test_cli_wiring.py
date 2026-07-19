"""Tests for distill CLI commands."""

import json
import os
import re
import zipfile
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from distill import _cli_impl, cli
from distill.commands import _discover_flow, _helpers, _site_ingest, _site_page_storage
from distill.commands import _learning as _learning_support
from distill.commands import dashboard as _dashboard
from distill.commands import discover as _discover
from distill.commands import doctor as _doctor
from distill.commands import learn as _learn
from distill.commands import maintain as _maintain
from distill.commands import papers as _papers
from distill.commands import process as _process
from distill.commands import profile as _profile
from distill.commands import reports as _reports
from distill.commands import reprocess as _reprocess
from distill.commands import root as _root
from distill.commands import topic as _topic
from distill.commands import topic_watch as _topic_watch
from distill.commands import view as _view
from distill.commands import watch as _watch
from distill.commands._helpers import _truncate_channel_list, duration_str, format_date
from distill.commands._json import ExitCode
from distill.config import DistillConfig
from distill.ingestors.sites.scraper import SitePage
from distill.library import Library
from distill.library.paths import artifact_path, find_artifact
from distill.pipeline.costs import (
    ProjectedBudgetExceededError,
    estimate_paper_workflow_cost,
    estimate_site_batch_workflow_cost,
    estimate_synthesis_workflow_cost,
)


def _recent(days_ago: int = 1) -> str:
    """Return a YYYYMMDD date string for `days_ago` days before today."""
    return (datetime.now() - timedelta(days=days_ago)).strftime("%Y%m%d")


runner = CliRunner()
ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


class _RootCallbackContext:
    def __init__(self, *, invoked_subcommand=None, obj=None):
        self.invoked_subcommand = invoked_subcommand
        self.obj = obj

    def ensure_object(self, _type):
        if self.obj is None:
            self.obj = {}
        return self.obj


@pytest.fixture
def mock_config(tmp_path, monkeypatch):
    """Patch get_config to return a test config."""
    config = DistillConfig(
        xai_api_key="test-key",
        gemini_api_key="test-gemini",
        distill_output_dir=tmp_path / "library",
    )
    original = cli.get_config
    original_impl = _cli_impl.get_config
    original_view = _view.get_config  # `library` moved to commands/view.py
    original_maintain = _maintain.get_config  # `costs`/`cleanup` moved to commands/maintain.py
    original_doctor = _doctor.get_config  # `doctor`/`health` moved to commands/doctor.py
    original_reprocess = _reprocess.get_config  # resynthesize/reanalyze moved here
    original_reports = _reports.get_config  # report/export moved to commands/reports.py
    original_papers = _papers.get_config  # paper/papers moved to commands/papers.py
    original_profile = _profile.get_config  # profile sub-app moved to commands/profile.py
    original_process = _process.get_config  # video/channel/run moved to commands/process.py
    original_discover = _discover.get_config  # discover-panel cmds moved to commands/discover.py
    original_learn = (
        _learn.get_config
    )  # search/explore/learn/brief/latest moved to commands/learn.py
    original_watch = _watch.get_config  # watch sub-app + catch-up moved to commands/watch.py
    original_topic = _topic.get_config  # topic sub-app moved to commands/topic.py
    original_topic_watch = _topic_watch.get_config  # topic-watch moved to commands/topic_watch.py
    original_root = _root.get_config  # top-level callback moved to commands/root.py
    original_dashboard = _dashboard.get_config  # home screen moved to commands/dashboard.py
    original_expand = getattr(cli, "_llm_expand_learning_queries", None)
    original_expand_impl = getattr(_cli_impl, "_llm_expand_learning_queries", None)
    cli.get_config = lambda: config
    _cli_impl.get_config = lambda: config
    _view.get_config = lambda: config
    _maintain.get_config = lambda: config
    _doctor.get_config = lambda: config
    _reprocess.get_config = lambda: config
    _reports.get_config = lambda: config
    _papers.get_config = lambda: config
    _profile.get_config = lambda: config
    _process.get_config = lambda: config
    _discover.get_config = lambda: config
    _learn.get_config = lambda: config
    monkeypatch.setattr(_learning_support, "get_config", lambda: config)
    _watch.get_config = lambda: config
    _topic.get_config = lambda: config
    _topic_watch.get_config = lambda: config
    _root.get_config = lambda: config
    _dashboard.get_config = lambda: config
    if original_expand is not None:
        cli._llm_expand_learning_queries = lambda *args, **kwargs: []
    if original_expand_impl is not None:
        _cli_impl._llm_expand_learning_queries = lambda *args, **kwargs: []
    monkeypatch.setattr(_learning_support, "model_available", lambda *args, **kwargs: False)
    yield config
    cli.get_config = original
    _cli_impl.get_config = original_impl
    _view.get_config = original_view
    _maintain.get_config = original_maintain
    _doctor.get_config = original_doctor
    _reprocess.get_config = original_reprocess
    _reports.get_config = original_reports
    _papers.get_config = original_papers
    _profile.get_config = original_profile
    _process.get_config = original_process
    _discover.get_config = original_discover
    _learn.get_config = original_learn
    _watch.get_config = original_watch
    _topic.get_config = original_topic
    _topic_watch.get_config = original_topic_watch
    _root.get_config = original_root
    _dashboard.get_config = original_dashboard
    if original_expand is not None:
        cli._llm_expand_learning_queries = original_expand
    if original_expand_impl is not None:
        _cli_impl._llm_expand_learning_queries = original_expand_impl


@pytest.fixture
def mock_config_with_library(mock_config):
    """Config with a pre-populated library."""
    from distill.library import Library

    lib = Library(mock_config)
    lib.add_channel("ai", "https://www.youtube.com/@TestCh", "TestCh")
    return mock_config


def _populate_videos(config, topic, channel, count=3):
    """Helper to create fake video data."""
    from distill.library.state import ChannelState

    for i in range(count):
        vid_id = f"vid{i:03d}"
        vid_dir = config.video_dir(topic, channel, vid_id)
        vid_dir.mkdir(parents=True, exist_ok=True)
        meta = {
            "video_id": vid_id,
            "title": f"Test Video {i}",
            "upload_date": _recent(i + 1),
            "duration": 600 + i * 100,
            "url": f"https://www.youtube.com/watch?v={vid_id}",
        }
        (vid_dir / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")
        (vid_dir / "transcript.txt").write_text(f"Transcript {i}", encoding="utf-8")
        (vid_dir / "insights.md").write_text(
            f'---\nvideo_title: "Test {i}"\n---\n\n## Summary\nInsight {i}',
            encoding="utf-8",
        )

    state_file = config.channel_dir(topic, channel) / "state.json"
    state = ChannelState(state_file)
    for i in range(count):
        state.mark_processed(f"vid{i:03d}", f"Test Video {i}", _recent(i + 1))


class TestTopLevelExperience:
    def test_help_shows_intent_led_examples(self):
        result = runner.invoke(cli.app, ["--help"])
        assert result.exit_code == 0
        output = ANSI_RE.sub("", result.output)
        assert "First-time setup" in output
        assert "distill --cost-mode no-metered init" in output
        assert "distill --cost-mode no-metered doctor" in output
        assert 'distill --cost-mode no-metered papers "topic" -n 5 --preview' in output
        assert "distill --cost-mode paid-ok init" in output
        assert "--preview" in output
        assert "Have one YouTube URL?" in output
        assert "Build a topic corpus?" in output
        assert "Want recurring updates?" in output
        assert "distill monitor" in output
        assert "Microsoft AI news" in output

    def test_help_shows_recurring_workflow_examples(self):
        checks = [
            (["profile", "preview", "--help"], "distill profile preview ai-developer-news"),
            (["profile", "run", "--help"], "distill profile run ai-developer-news --yes"),
            (["discover", "--help"], 'distill discover "agentic coding loops"'),
            (["ingest", "--help"], "distill ingest https://github.com/example/project"),
            (["audit", "--help"], "distill --json audit all --next-actions"),
            (["export", "--help"], "distill export ai --what bundle --format okf"),
            (["okf", "validate", "--help"], "distill okf validate output/okf-ai"),
        ]

        for argv, expected in checks:
            result = runner.invoke(cli.app, argv)

            assert result.exit_code == 0, result.output
            assert expected in ANSI_RE.sub("", result.output)

    @pytest.mark.parametrize("command", ["init", "doctor"])
    def test_live_validation_help_names_cost_guard(self, command):
        result = runner.invoke(cli.app, [command, "--help"])

        assert result.exit_code == 0
        output = ANSI_RE.sub("", result.output)
        assert "may be billed" in output
        assert "--cost-mode no-metered" in output

    def test_ask_help_renders_wiki_link_description(self):
        result = runner.invoke(cli.app, ["ask", "--help"])

        assert result.exit_code == 0, result.output
        rendered = ANSI_RE.sub("", result.output)
        assert "wiki-link citations" in rendered
        assert "with [] to every cited" not in rendered

    def test_no_args_empty_library_shows_launcher(self, mock_config, monkeypatch):
        monkeypatch.setattr(_root, "show_banner", lambda console: None)
        monkeypatch.setattr(cli.console, "clear", lambda: None)

        result = runner.invoke(cli.app, [])

        assert result.exit_code == 0
        assert "Distill Start" in result.output
        # Panel title may not render in narrow test console; check for content instead
        assert "distill video" in result.output
        assert "Recent Spend" not in result.output

    def test_no_args_with_library_shows_operational_dashboard(
        self, mock_config_with_library, monkeypatch
    ):
        monkeypatch.setattr(_root, "show_banner", lambda console: None)
        monkeypatch.setattr(cli.console, "clear", lambda: None)

        result = runner.invoke(cli.app, [])

        assert result.exit_code == 0
        assert "Distill Home" in result.output
        assert "Quick commands:" in result.output
        assert "Topics" in result.output

    def test_no_args_json_emits_one_dashboard_envelope(self, mock_config, capsys):
        result = runner.invoke(cli.app, ["--json"])

        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)
        assert payload["status"] == "ok"
        assert payload["data"]["schema_version"] == "dashboard.v2"
        assert payload["data"]["first_run"] is True
        assert payload["data"]["paths"]["library"] == str(mock_config.library_dir)
        assert payload["data"]["next_commands"][:2] == [
            "distill --cost-mode no-metered init",
            "distill --cost-mode no-metered doctor",
        ]
        assert payload["data"]["next_commands"][2] == (
            'distill --cost-mode no-metered papers "topic" -n 5 --preview'
        )
        assert result.stderr == ""

    def test_dashboard_command_json_matches_root_contract(self, mock_config):
        root = runner.invoke(cli.app, ["--json"])
        command = runner.invoke(cli.app, ["--json", "dashboard"])

        assert root.exit_code == 0, root.output
        assert command.exit_code == 0, command.output
        assert json.loads(command.stdout) == json.loads(root.stdout)
        assert command.stderr == ""

    def test_quiet_suppresses_home_output_and_resets(self, mock_config, monkeypatch):
        monkeypatch.setattr(_root, "show_banner", lambda console: None)
        monkeypatch.setattr(cli.console, "clear", lambda: None)

        quiet = runner.invoke(cli.app, ["--quiet"])
        normal = runner.invoke(cli.app, [])

        assert quiet.exit_code == 0
        assert quiet.output == ""
        assert normal.exit_code == 0
        assert "Distill Start" in normal.output

    def test_quiet_conflicts_with_verbose(self):
        result = runner.invoke(cli.app, ["--quiet", "--verbose", "alerts"])

        assert result.exit_code == 2
        assert "--quiet cannot be combined with --verbose" in result.output

    def test_verbose_enables_debug_logging(self, mock_config, monkeypatch):
        captured: dict[str, object] = {}

        def configure_logging(*, debug, ops_dir):
            captured["debug"] = debug
            captured["ops_dir"] = ops_dir

        monkeypatch.setattr("distill._logging.configure_logging", configure_logging)
        monkeypatch.setattr(_root, "show_banner", lambda console: None)
        monkeypatch.setattr(cli.console, "clear", lambda: None)

        result = runner.invoke(cli.app, ["--verbose"])

        assert result.exit_code == 0
        assert captured["debug"] is True

    def test_root_callback_logs_without_config(self, monkeypatch):
        captured: dict[str, object] = {}

        def configure_logging(*, debug, ops_dir):
            captured["debug"] = debug
            captured["ops_dir"] = ops_dir

        monkeypatch.setattr("distill._logging.configure_logging", configure_logging)
        monkeypatch.setattr(
            _root, "get_config", lambda: (_ for _ in ()).throw(RuntimeError("no config"))
        )

        _root.default_callback(
            _RootCallbackContext(invoked_subcommand="status"),
            debug=False,
            quiet=False,
            verbose=False,
            json_output=False,
            model="",
            cost_mode="",
            version=False,
        )

        assert captured == {"debug": False, "ops_dir": None}

    def test_root_callback_clears_interactive_terminal(self, mock_config, monkeypatch):
        calls: list[str] = []

        monkeypatch.setattr("distill._logging.configure_logging", lambda **_kwargs: None)
        monkeypatch.setattr(_root.sys.stdout, "isatty", lambda: True)
        monkeypatch.setattr(_root.console, "clear", lambda: calls.append("clear"))
        monkeypatch.setattr(_root, "show_banner", lambda _console: calls.append("banner"))
        monkeypatch.setattr(_dashboard, "show_dashboard", lambda: calls.append("dashboard"))

        _root.default_callback(
            _RootCallbackContext(),
            debug=False,
            quiet=False,
            verbose=False,
            json_output=False,
            model="",
            cost_mode="",
            version=False,
        )

        assert calls == ["clear", "banner", "dashboard"]

    def test_root_model_override_reads_context_object(self):
        assert (
            _root.get_model_override(_RootCallbackContext(obj={"model": "grok-4.3"})) == "grok-4.3"
        )
        assert _root.get_model_override(_RootCallbackContext(obj={})) == ""
        assert _root.get_model_override(None) == ""


class TestVideoCommand:
    def test_video_defaults_to_artifact_links(self, mock_config, monkeypatch):
        from distill.ingestors.youtube.discovery import VideoInfo

        info = VideoInfo(
            "vid123",
            "Test Video",
            _recent(1),
            600,
            "https://youtube.com/watch?v=vid123",
            "Test Channel",
            "https://www.youtube.com/@TestChannel",
        )

        monkeypatch.setattr(_process, "get_video_info", lambda url: info)
        monkeypatch.setattr(_process, "display_summary", lambda *args, **kwargs: None)

        def fake_process(topic, channel_name, video, config, tracker, summary):
            vid_dir = config.video_dir_slug(topic, channel_name, video.title, video.video_id)
            vid_dir.mkdir(parents=True, exist_ok=True)
            (vid_dir / "transcript.txt").write_text("Transcript body", encoding="utf-8")
            (vid_dir / "insights.md").write_text(
                "---\nvideo_title: Test Video\n---\n\n## Summary\nInsight body",
                encoding="utf-8",
            )
            return True

        monkeypatch.setattr(_process, "_process_video", fake_process)

        result = runner.invoke(cli.app, ["video", info.url])

        assert result.exit_code == 0
        assert "transcript.txt" in result.output
        assert "insights.md" in result.output
        assert "Use --show to print the analysis inline" in result.output
        assert "Insight body" not in result.output

    def test_video_show_prints_analysis_inline(self, mock_config, monkeypatch):
        from distill.ingestors.youtube.discovery import VideoInfo

        info = VideoInfo(
            "vid123",
            "Test Video",
            _recent(1),
            600,
            "https://youtube.com/watch?v=vid123",
            "Test Channel",
            "https://www.youtube.com/@TestChannel",
        )

        monkeypatch.setattr(_process, "get_video_info", lambda url: info)
        monkeypatch.setattr(_process, "display_summary", lambda *args, **kwargs: None)

        def fake_process(topic, channel_name, video, config, tracker, summary):
            vid_dir = config.video_dir_slug(topic, channel_name, video.title, video.video_id)
            vid_dir.mkdir(parents=True, exist_ok=True)
            (vid_dir / "transcript.txt").write_text("Transcript body", encoding="utf-8")
            (vid_dir / "insights.md").write_text(
                "---\nvideo_title: Test Video\n---\n\n## Summary\nInsight body",
                encoding="utf-8",
            )
            return True

        monkeypatch.setattr(_process, "_process_video", fake_process)

        result = runner.invoke(cli.app, ["video", info.url, "--show"])

        assert result.exit_code == 0
        assert "Insight body" in result.output
        assert "Use --show to print the analysis inline" not in result.output


class TestLibraryCommand:
    def test_empty_library(self, mock_config):
        result = runner.invoke(cli.app, ["library"])
        assert result.exit_code == 0
        assert "empty" in result.output.lower() or "Library" in result.output

    def test_library_with_channels(self, mock_config_with_library):
        result = runner.invoke(cli.app, ["library"])
        assert result.exit_code == 0
        assert "TestCh" in result.output


class TestAddCommand:
    def test_add_channel(self, mock_config, monkeypatch):
        monkeypatch.setattr(_cli_impl, "resolve_channel_name", lambda url: "NewChannel")
        result = runner.invoke(cli.app, ["add", "ai", "https://www.youtube.com/@NewChannel"])
        assert result.exit_code == 0
        assert "Added" in result.output or "NewChannel" in result.output

    def test_add_duplicate(self, mock_config_with_library, monkeypatch):
        monkeypatch.setattr(_cli_impl, "resolve_channel_name", lambda url: "TestCh")
        result = runner.invoke(cli.app, ["add", "ai", "https://www.youtube.com/@TestCh"])
        assert result.exit_code == 0
        assert "already exists" in result.output


class TestRemoveCommand:
    def test_remove_existing(self, mock_config_with_library):
        result = runner.invoke(
            cli.app, ["remove", "ai", "https://www.youtube.com/@TestCh", "--yes"]
        )
        assert result.exit_code == 0
        assert "Removed" in result.output

    def test_remove_nonexistent(self, mock_config_with_library):
        result = runner.invoke(
            cli.app, ["remove", "ai", "https://www.youtube.com/@Missing", "--yes"]
        )
        assert result.exit_code == 0
        assert "Not found" in result.output


class TestVideosCommand:
    def test_no_channels(self, mock_config):
        result = runner.invoke(cli.app, ["videos", "nonexistent"])
        assert result.exit_code == 0
        assert "No channels" in result.output

    def test_videos_with_data(self, mock_config_with_library):
        _populate_videos(mock_config_with_library, "ai", "TestCh")
        result = runner.invoke(cli.app, ["videos", "ai"])
        assert result.exit_code == 0
        assert "Test Video" in result.output

    def test_videos_no_videos_dir(self, mock_config_with_library):
        """Should handle channel with no videos dir."""
        result = runner.invoke(cli.app, ["videos", "ai"])
        assert result.exit_code == 0


class TestShowCommand:
    def test_show_insights(self, mock_config_with_library):
        _populate_videos(mock_config_with_library, "ai", "TestCh")
        result = runner.invoke(cli.app, ["show", "ai", "1"])
        assert result.exit_code == 0

    def test_show_no_videos_dir(self, mock_config_with_library):
        """Should handle empty videos directory gracefully."""
        result = runner.invoke(cli.app, ["show", "ai", "1"])
        assert result.exit_code == 0
        assert "not found" in result.output.lower()

    def test_show_out_of_range(self, mock_config_with_library):
        _populate_videos(mock_config_with_library, "ai", "TestCh")
        result = runner.invoke(cli.app, ["show", "ai", "99"])
        assert result.exit_code == 0
        assert "not found" in result.output.lower()

    def test_show_metadata(self, mock_config_with_library):
        _populate_videos(mock_config_with_library, "ai", "TestCh")
        result = runner.invoke(cli.app, ["show", "ai", "1", "--what", "metadata"])
        assert result.exit_code == 0


class TestRunCommand:
    def test_run_no_topic(self, mock_config):
        result = runner.invoke(cli.app, ["run"])
        assert result.exit_code == 1

    def test_dry_run(self, mock_config_with_library, monkeypatch):
        from distill.ingestors.youtube.discovery import VideoInfo

        monkeypatch.setattr(
            _process,
            "discover_videos",
            lambda url, months, include_shorts=False: [
                VideoInfo("v1", "Video 1", _recent(2), 600, "https://youtube.com/watch?v=v1"),
            ],
        )
        result = runner.invoke(cli.app, ["run", "ai", "--dry-run"])
        assert result.exit_code == 0
        assert "Dry run" in result.output or "would be processed" in result.output


class TestSynthesisCommand:
    def test_no_synthesis(self, mock_config_with_library):
        result = runner.invoke(cli.app, ["synthesis", "ai"])
        assert result.exit_code == 0
        assert "No synthesis" in result.output or "run" in result.output.lower()

    def test_channel_synthesis(self, mock_config_with_library):
        ch_dir = mock_config_with_library.channel_dir("ai", "TestCh")
        ch_dir.mkdir(parents=True, exist_ok=True)
        (ch_dir / "synthesis.md").write_text("# Test Synthesis", encoding="utf-8")
        result = runner.invoke(cli.app, ["synthesis", "ai", "--channel", "TestCh"])
        assert result.exit_code == 0


class TestResearchCommand:
    def test_research_no_topic(self, mock_config):
        result = runner.invoke(cli.app, ["report"])
        assert result.exit_code == int(ExitCode.USAGE_ERROR)

    def test_research_no_gemini_key(self, tmp_path):
        config = DistillConfig(
            gemini_api_key="",
            distill_output_dir=tmp_path / "library",
        )
        original = cli.get_config
        original_impl = _cli_impl.get_config
        original_reports = _reports.get_config  # `report` resolves get_config here
        cli.get_config = lambda: config
        _cli_impl.get_config = lambda: config
        _reports.get_config = lambda: config
        try:
            result = runner.invoke(cli.app, ["report", "ai"])
            assert result.exit_code == int(ExitCode.CONFIG_ERROR)
        finally:
            cli.get_config = original
            _cli_impl.get_config = original_impl
            _reports.get_config = original_reports


class TestStatusCommand:
    def test_empty_status(self, mock_config):
        result = runner.invoke(cli.app, ["status"])
        assert result.exit_code == 0
        assert "distill --cost-mode no-metered init" in result.output
        assert "distill --cost-mode no-metered doctor" in result.output

    def test_status_with_data(self, mock_config_with_library):
        _populate_videos(mock_config_with_library, "ai", "TestCh")
        result = runner.invoke(cli.app, ["status"])
        assert result.exit_code == 0
        assert "TestCh" in result.output


class TestFormatHelpers:
    """Test the CLI helper functions directly."""

    def test_format_date_yyyymmdd(self):
        result = format_date("20250115")
        assert "Jan" in result
        assert "2025" in result

    def test_format_date_iso(self):
        result = format_date("2025-01-15T10:30:00")
        assert "Jan" in result
        assert "2025" in result

    def test_format_date_empty(self):
        assert format_date("") == "Unknown"

    def test_format_date_none(self):
        assert format_date(None) == "Unknown"

    def test_format_date_invalid(self):
        result = format_date("not-a-date")
        assert result == "not-a-date"

    def test_duration_seconds(self):
        assert duration_str(30) == "30s"

    def test_duration_minutes(self):
        assert duration_str(120) == "2m"

    def test_duration_hours(self):
        assert duration_str(3720) == "1h 2m"

    def test_duration_none(self):
        assert duration_str(None) == "?"

    def test_duration_negative(self):
        assert duration_str(-5) == "?"

    def test_duration_string_input(self):
        assert duration_str("not a number") == "?"

    def test_duration_zero(self):
        assert duration_str(0) == "0s"

    def test_duration_float(self):
        result = duration_str(90.5)
        assert result == "1m"


class TestLearnCommand:
    def _ranked(self, videos):
        from types import SimpleNamespace

        return [
            SimpleNamespace(video=v, final_score=0.9 - (idx * 0.1), rationale="best fit")
            for idx, v in enumerate(videos)
        ]

    def test_learn_searches_processes_and_saves_channels(self, mock_config, monkeypatch):
        from distill.ingestors.youtube.discovery import VideoInfo
        from distill.library import Library

        def fake_transcript(url, video_id, output_path, config):
            output_path.write_text(f"Transcript for {video_id}", encoding="utf-8")
            return True

        def fake_synthesize_channel(topic, channel_name, config, tracker=None):
            path = config.channel_dir(topic, channel_name) / "synthesis.md"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"# {channel_name} synthesis", encoding="utf-8")

        def fake_synthesize_topic(topic, config, tracker=None):
            path = config.topic_dir(topic) / "topic_synthesis.md"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"# {topic} synthesis", encoding="utf-8")

        videos = [
            VideoInfo(
                "v1",
                "Fabric Best Practices 1",
                _recent(3),
                900,
                "https://youtube.com/watch?v=v1",
                "CreatorOne",
                "https://www.youtube.com/@CreatorOne",
                view_count=5000,
            ),
            VideoInfo(
                "v2",
                "Fabric Best Practices 2",
                _recent(4),
                840,
                "https://youtube.com/watch?v=v2",
                "CreatorTwo",
                "https://www.youtube.com/@CreatorTwo",
                view_count=4000,
            ),
        ]
        monkeypatch.setattr(
            _learning_support,
            "search_youtube_results",
            lambda query, days=None, limit=None, hours=None: videos,
        )
        monkeypatch.setattr(_learning_support, "enrich_videos", lambda vids, max_videos=None: vids)
        monkeypatch.setattr(
            _learning_support,
            "rerank_videos",
            lambda query, vids, config, tracker=None, top_n=10, use_llm=True, skeptical=False: (
                self._ranked(vids)
            ),
        )
        monkeypatch.setattr(_helpers, "get_transcript", fake_transcript)
        monkeypatch.setattr(
            _helpers,
            "analyze_video",
            lambda title, upload_date, channel_name, transcript, config, tracker=None, intent=None: (
                f"# {title}\n\nInsight"
            ),
        )
        monkeypatch.setattr(
            _helpers,
            "analyze_short",
            lambda title, upload_date, channel_name, transcript, config, tracker=None, intent=None: (
                f"# {title}\n\nShort"
            ),
        )
        monkeypatch.setattr(
            _helpers,
            "generate_channel_context",
            lambda channel_name, titles, config, tracker=None: f"# {channel_name}\n\nContext",
        )
        monkeypatch.setattr(_learning_support, "synthesize_channel", fake_synthesize_channel)
        monkeypatch.setattr(_learning_support, "synthesize_topic", fake_synthesize_topic)
        monkeypatch.setattr(
            _learning_support,
            "synthesize_corpus",
            lambda topic, config, tracker=None: None,
        )
        result = runner.invoke(cli.app, ["learn", "Microsoft Fabric best practices"])

        assert result.exit_code == 0
        assert "Processing 2 best-pick videos across 2 channels" in result.output

        lib = Library(mock_config)
        channels = lib.get_channels("microsoft-fabric-best-practices")
        assert sorted(ch.name for ch in channels) == ["CreatorOne", "CreatorTwo"]
        assert (
            mock_config.topic_dir("microsoft-fabric-best-practices") / "topic_synthesis.md"
        ).exists()

    def test_search_previews_best_picks(self, mock_config, monkeypatch):
        from distill.ingestors.youtube.discovery import VideoInfo

        videos = [
            VideoInfo(
                "v1",
                "Fabric Best Practices 1",
                _recent(3),
                900,
                "https://youtube.com/watch?v=v1",
                "CreatorOne",
                "https://www.youtube.com/@CreatorOne",
                view_count=5000,
            ),
            VideoInfo(
                "v2",
                "Fabric Best Practices 2",
                _recent(4),
                840,
                "https://youtube.com/watch?v=v2",
                "CreatorTwo",
                "https://www.youtube.com/@CreatorTwo",
                view_count=4000,
            ),
        ]
        monkeypatch.setattr(
            _learning_support,
            "search_youtube_results",
            lambda query, days=None, limit=None, hours=None: videos,
        )
        monkeypatch.setattr(_learning_support, "enrich_videos", lambda vids, max_videos=None: vids)
        monkeypatch.setattr(
            _learning_support,
            "rerank_videos",
            lambda query, vids, config, tracker=None, top_n=10, use_llm=True, skeptical=False: (
                self._ranked(vids)
            ),
        )

        result = runner.invoke(cli.app, ["search", "Microsoft Fabric best practices"])

        assert result.exit_code == 0
        assert "Best Videos to Learn From" in result.output
        assert "CreatorOne" in result.output

    def test_learn_ephemeral_does_not_register_channels(self, mock_config, monkeypatch):
        from distill.ingestors.youtube.discovery import VideoInfo
        from distill.library import Library

        def fake_transcript(url, video_id, output_path, config):
            output_path.write_text("Transcript", encoding="utf-8")
            return True

        videos = [
            VideoInfo(
                "v1",
                "Fabric Update",
                _recent(3),
                900,
                "https://youtube.com/watch?v=v1",
                "CreatorOne",
                "https://www.youtube.com/@CreatorOne",
            ),
        ]
        monkeypatch.setattr(
            _learning_support,
            "search_youtube_results",
            lambda query, days=None, limit=None, hours=None: videos,
        )
        monkeypatch.setattr(_learning_support, "enrich_videos", lambda vids, max_videos=None: vids)
        monkeypatch.setattr(
            _learning_support,
            "rerank_videos",
            lambda query, vids, config, tracker=None, top_n=10, use_llm=True, skeptical=False: (
                self._ranked(vids)
            ),
        )
        monkeypatch.setattr(_helpers, "get_transcript", fake_transcript)
        monkeypatch.setattr(
            _helpers,
            "analyze_video",
            lambda title, upload_date, channel_name, transcript, config, tracker=None, intent=None: (
                "# Insight"
            ),
        )
        monkeypatch.setattr(
            _helpers,
            "generate_channel_context",
            lambda channel_name, titles, config, tracker=None: "# Context",
        )
        monkeypatch.setattr(
            _learning_support,
            "synthesize_channel",
            lambda topic, channel_name, config, tracker=None: (
                config.channel_dir(topic, channel_name) / "synthesis.md"
            ).write_text("# Synth", encoding="utf-8"),
        )
        monkeypatch.setattr(
            _learning_support,
            "synthesize_topic",
            lambda topic, config, tracker=None: None,
        )
        monkeypatch.setattr(
            _learning_support,
            "synthesize_corpus",
            lambda topic, config, tracker=None: None,
        )
        result = runner.invoke(cli.app, ["learn", "Microsoft Fabric", "--ephemeral"])

        assert result.exit_code == 0
        lib = Library(mock_config)
        assert lib.get_channels("microsoft-fabric") == []

    def test_learn_rejects_invalid_sort(self, mock_config):
        result = runner.invoke(cli.app, ["learn", "Microsoft Fabric", "--sort", "popular"])
        assert result.exit_code == int(ExitCode.USAGE_ERROR)
        assert "relevance" in result.output

    def test_latest_preview_shows_ranked_set(self, mock_config, monkeypatch):
        from distill.ingestors.youtube.discovery import VideoInfo

        videos = [
            VideoInfo(
                "v1",
                "Fabric Best Practices 1",
                _recent(3),
                900,
                "https://youtube.com/watch?v=v1",
                "CreatorOne",
                "https://www.youtube.com/@CreatorOne",
                view_count=5000,
            ),
            VideoInfo(
                "v2",
                "Fabric Best Practices 2",
                _recent(4),
                840,
                "https://youtube.com/watch?v=v2",
                "CreatorTwo",
                "https://www.youtube.com/@CreatorTwo",
                view_count=4000,
            ),
        ]
        monkeypatch.setattr(
            _learning_support,
            "search_youtube_results",
            lambda query, days=None, limit=None, hours=None: videos,
        )
        monkeypatch.setattr(_learning_support, "enrich_videos", lambda vids, max_videos=None: vids)
        monkeypatch.setattr(
            _learning_support,
            "rerank_videos",
            lambda query, vids, config, tracker=None, top_n=10, use_llm=True, skeptical=False: (
                self._ranked(vids)
            ),
        )

        result = runner.invoke(
            cli.app, ["latest", "Microsoft Fabric best practices", "--preview", "--days", "10"]
        )

        assert result.exit_code == 0
        assert "Latest Best-Pick Learning Set" in result.output
        assert "CreatorOne" in result.output

    def test_explore_uses_broader_defaults(self, mock_config, monkeypatch):
        from types import SimpleNamespace

        from distill.ingestors.youtube.discovery import VideoInfo

        captured = {}

        def fake_select(
            query, config, tracker, days, limit, sort, per_channel_cap, shorts, rerank, **kwargs
        ):
            captured.update(
                days=days,
                limit=limit,
                sort=sort,
                per_channel_cap=per_channel_cap,
                shorts=shorts,
                rerank=rerank,
            )
            video = VideoInfo(
                "v1",
                "Kubernetes Architecture",
                _recent(3),
                900,
                "https://youtube.com/watch?v=v1",
                "CreatorOne",
                "https://www.youtube.com/@CreatorOne",
                view_count=5000,
            )
            return [], [SimpleNamespace(video=video, final_score=0.91, rationale="best fit")]

        monkeypatch.setattr(_learning_support, "_select_learning_videos", fake_select)

        result = runner.invoke(cli.app, ["explore", "Kubernetes"])

        assert result.exit_code == 0
        assert captured == {
            "days": 90,
            "limit": 10,
            "sort": "relevance",
            "per_channel_cap": 3,
            "shorts": False,
            "rerank": True,
        }

    def test_brief_generates_markdown_brief(self, mock_config, monkeypatch):
        from distill.ingestors.youtube.discovery import VideoInfo

        def fake_transcript(url, video_id, output_path, config):
            output_path.write_text(f"Transcript for {video_id}", encoding="utf-8")
            return True

        def fake_synthesize_channel(topic, channel_name, config, tracker=None):
            path = config.channel_dir(topic, channel_name) / "synthesis.md"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"# {channel_name} synthesis", encoding="utf-8")

        def fake_synthesize_topic(topic, config, tracker=None):
            path = config.topic_dir(topic) / "topic_synthesis.md"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"# {topic} synthesis", encoding="utf-8")

        def fake_generate_topic_brief(topic, config, tracker=None):
            path = config.topic_dir(topic) / "brief.md"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"# Topic Brief: {topic}", encoding="utf-8")
            return path

        videos = [
            VideoInfo(
                "v1",
                "Fabric Best Practices 1",
                _recent(3),
                900,
                "https://youtube.com/watch?v=v1",
                "CreatorOne",
                "https://www.youtube.com/@CreatorOne",
                view_count=5000,
            ),
        ]
        monkeypatch.setattr(
            _learning_support,
            "search_youtube_results",
            lambda query, days=None, limit=None, hours=None: videos,
        )
        monkeypatch.setattr(_learning_support, "enrich_videos", lambda vids, max_videos=None: vids)
        monkeypatch.setattr(
            _learning_support,
            "rerank_videos",
            lambda query, vids, config, tracker=None, top_n=10, use_llm=True, skeptical=False: (
                self._ranked(vids)
            ),
        )
        monkeypatch.setattr(_helpers, "get_transcript", fake_transcript)
        monkeypatch.setattr(
            _helpers,
            "analyze_video",
            lambda title, upload_date, channel_name, transcript, config, tracker=None, intent=None: (
                f"# {title}\n\nInsight"
            ),
        )
        monkeypatch.setattr(
            _helpers,
            "analyze_short",
            lambda title, upload_date, channel_name, transcript, config, tracker=None, intent=None: (
                f"# {title}\n\nShort"
            ),
        )
        monkeypatch.setattr(
            _helpers,
            "generate_channel_context",
            lambda channel_name, titles, config, tracker=None: f"# {channel_name}\n\nContext",
        )
        monkeypatch.setattr(_learning_support, "synthesize_channel", fake_synthesize_channel)
        monkeypatch.setattr(_learning_support, "synthesize_topic", fake_synthesize_topic)
        monkeypatch.setattr(_learning_support, "generate_topic_brief", fake_generate_topic_brief)
        monkeypatch.setattr(
            _learning_support,
            "synthesize_corpus",
            lambda topic, config, tracker=None: None,
        )
        result = runner.invoke(cli.app, ["brief", "Microsoft Fabric best practices"])

        assert result.exit_code == 0
        topic_dir = mock_config.topic_dir("microsoft-fabric-best-practices")
        assert (topic_dir / "brief.md").exists()
        assert (
            mock_config.library_dir.parent / "output" / "brief-microsoft-fabric-best-practices.md"
        ).exists()


class TestLearnHelpers:
    def test_expand_learning_queries_is_topic_agnostic(self):
        queries = cli._expand_learning_queries("Snowflake best practices")
        assert queries[0] == "Snowflake best practices"
        assert any("architecture" in q.lower() for q in queries[1:])
        assert any("implementation" in q.lower() or "walkthrough" in q.lower() for q in queries[1:])

    def test_select_learning_videos_filters_old_enriched_candidates(self, mock_config, monkeypatch):
        from distill.ingestors.youtube.discovery import VideoInfo

        monkeypatch.setattr(
            _learning_support,
            "search_youtube_results",
            lambda query, days=None, limit=None, hours=None: [
                VideoInfo("v1", "New", "", 900, "https://youtube.com/watch?v=v1", "CreatorOne"),
                VideoInfo("v2", "Old", "", 900, "https://youtube.com/watch?v=v2", "CreatorTwo"),
            ],
        )
        monkeypatch.setattr(_learning_support, "search_videos", lambda *args, **kwargs: [])
        monkeypatch.setattr(
            _learning_support,
            "enrich_videos",
            lambda vids, max_videos=None: [
                VideoInfo(
                    "v1",
                    "New",
                    _recent(5),
                    900,
                    "https://youtube.com/watch?v=v1",
                    "CreatorOne",
                    view_count=1000,
                ),
                VideoInfo(
                    "v2",
                    "Old",
                    (datetime.now() - timedelta(days=800)).strftime("%Y%m%d"),
                    900,
                    "https://youtube.com/watch?v=v2",
                    "CreatorTwo",
                    view_count=1000,
                ),
            ],
        )
        from types import SimpleNamespace

        monkeypatch.setattr(
            _learning_support,
            "rerank_videos",
            lambda query, vids, config, tracker=None, top_n=10, use_llm=True, skeptical=False: [
                SimpleNamespace(video=v, final_score=0.9, rationale="best fit") for v in vids
            ],
        )

        _, selected = cli._select_learning_videos(
            "Microsoft Fabric best practices",
            mock_config,
            cli.CostTracker(),
            days=60,
            limit=5,
            sort="relevance",
            per_channel_cap=2,
            shorts=False,
            rerank=False,
        )

        assert [item.video.video_id for item in selected] == ["v1"]


class TestTopicCommands:
    def test_topic_create_mixed_dispatches_to_discover_and_saves_profile(
        self, mock_config, monkeypatch
    ):
        captured = {}

        def fake_discover(**kwargs):
            captured.update(kwargs)

        monkeypatch.setattr(_discover, "discover", fake_discover)

        result = runner.invoke(
            cli.app,
            [
                "topic",
                "create",
                "Microsoft Fabric best practices",
                "--topic",
                "fabric",
                "--videos",
                "10",
                "--papers",
                "10",
            ],
        )

        assert result.exit_code == 0
        assert captured["goal"] == "Microsoft Fabric best practices"
        assert captured["topic"] == "fabric"
        assert captured["video_limit"] == 10
        assert captured["paper_limit"] == 10
        profile = json.loads(
            (mock_config.topic_dir("fabric") / "topic_profile.json").read_text(encoding="utf-8")
        )
        assert profile["goal"] == "Microsoft Fabric best practices"
        assert profile["videos"] == 10
        assert profile["papers"] == 10

    def test_invoke_command_resolves_typer_option_defaults(self):
        # Regression: calling a typer command as a plain function leaks its
        # typer.Option/Argument sentinels (which are truthy) into any parameter the
        # caller omits, so guards like `if channel:` or `sort not in {...}` misfire.
        # This is what broke every mixed-source `topic create` (the discover
        # from_preview/from_gaps guard) and `distill ingest <paper-query>` (the
        # papers sort/rigor guard). _invoke_command must resolve omitted params to
        # their real defaults instead.
        import typer

        captured = {}

        def fake_command(
            goal: str = typer.Argument(""),
            topic: str = typer.Option("", "--topic"),
            rigor: str = typer.Option("balanced", "--rigor"),
            from_gaps: bool = typer.Option(False, "--from-gaps"),
            from_preview: str = typer.Option("", "--from-preview"),
        ):
            captured.update(
                goal=goal,
                topic=topic,
                rigor=rigor,
                from_gaps=from_gaps,
                from_preview=from_preview,
            )

        _cli_impl._invoke_command(fake_command, goal="g", topic="t")

        # Caller-supplied values pass through unchanged.
        assert captured["goal"] == "g"
        assert captured["topic"] == "t"
        # Omitted params resolve to real defaults, not truthy OptionInfo sentinels.
        assert captured["rigor"] == "balanced"
        assert captured["from_gaps"] is False
        assert captured["from_preview"] == ""
        assert not any(isinstance(v, typer.models.OptionInfo) for v in captured.values())
        assert not any(isinstance(v, typer.models.ArgumentInfo) for v in captured.values())

    def test_topic_create_videos_only_uses_learning_pipeline(self, mock_config, monkeypatch):
        captured = {}

        def fake_run_learning_command(query, **kwargs):
            captured["query"] = query
            captured["kwargs"] = kwargs

        monkeypatch.setattr(_topic, "_run_learning_command", fake_run_learning_command)

        result = runner.invoke(
            cli.app,
            [
                "topic",
                "create",
                "Agent memory systems",
                "--topic",
                "memory",
                "--videos",
                "8",
                "--papers",
                "0",
            ],
        )

        assert result.exit_code == 0
        assert captured["query"] == "Agent memory systems"
        assert captured["kwargs"]["topic"] == "memory"
        assert captured["kwargs"]["limit"] == 8
        assert captured["kwargs"]["header"] == "Topic Create"

    def test_topic_preview_does_not_save_profile(self, mock_config, monkeypatch):
        monkeypatch.setattr(_discover, "discover", lambda **kwargs: None)

        result = runner.invoke(
            cli.app,
            ["topic", "preview", "AI coding agents", "--topic", "agents", "--videos", "5"],
        )

        assert result.exit_code == 0
        assert not (mock_config.topic_dir("agents") / "topic_profile.json").exists()

    def test_topic_update_reuses_saved_profile_and_allows_overrides(self, mock_config, monkeypatch):
        (mock_config.topic_dir("fabric")).mkdir(parents=True, exist_ok=True)
        (mock_config.topic_dir("fabric") / "topic_profile.json").write_text(
            json.dumps(
                {
                    "goal": "Microsoft Fabric best practices",
                    "videos": 10,
                    "papers": 10,
                    "days": 30,
                    "shorts": False,
                }
            ),
            encoding="utf-8",
        )
        captured = {}
        monkeypatch.setattr(_discover, "discover", lambda **kwargs: captured.update(kwargs))

        result = runner.invoke(
            cli.app,
            ["topic", "update", "fabric", "--videos", "6", "--preview"],
        )

        assert result.exit_code == 0
        assert captured["goal"] == "Microsoft Fabric best practices"
        assert captured["video_limit"] == 6
        assert captured["paper_limit"] == 10
        assert captured["preview"] is True

    def test_topic_show_summary_reads_profile(self, mock_config):
        topic_dir = mock_config.topic_dir("fabric")
        topic_dir.mkdir(parents=True, exist_ok=True)
        (topic_dir / "topic_profile.json").write_text(
            json.dumps(
                {
                    "goal": "Microsoft Fabric best practices",
                    "videos": 10,
                    "papers": 10,
                    "days": 30,
                    "shorts": False,
                }
            ),
            encoding="utf-8",
        )

        result = runner.invoke(cli.app, ["topic", "show", "fabric"])

        assert result.exit_code == 0
        assert "Topic Summary" in result.output
        assert "Microsoft Fabric best practices" in result.output
        assert "videos=10 papers=10 days=30" in result.output

    def test_topic_watch_uses_saved_profile(self, mock_config, monkeypatch):
        topic_dir = mock_config.topic_dir("fabric")
        topic_dir.mkdir(parents=True, exist_ok=True)
        (topic_dir / "topic_profile.json").write_text(
            json.dumps(
                {
                    "goal": "Microsoft Fabric best practices",
                    "videos": 9,
                    "papers": 4,
                    "days": 21,
                    "shorts": False,
                }
            ),
            encoding="utf-8",
        )
        captured = {}

        def fake_monitor(**kwargs):
            captured.update(kwargs)

        monkeypatch.setattr(_discover, "monitor", fake_monitor)

        result = runner.invoke(cli.app, ["topic", "watch", "fabric", "--preview"])

        assert result.exit_code == 0
        assert captured["query"] == "Microsoft Fabric best practices"
        assert captured["topic"] == "fabric"
        assert captured["days"] == 21
        assert captured["limit"] == 9
        assert captured["preview"] is True

    def test_topic_create_requires_at_least_one_source(self, mock_config):
        result = runner.invoke(
            cli.app,
            [
                "topic",
                "create",
                "Microsoft Fabric best practices",
                "--videos",
                "0",
                "--papers",
                "0",
            ],
        )

        assert result.exit_code == int(ExitCode.USAGE_ERROR)
        assert "Specify at least one source" in result.output


class TestReadCommands:
    def test_synthesis_falls_back_to_first_channel(self, mock_config_with_library):
        ch_dir = mock_config_with_library.channel_dir("ai", "TestCh")
        ch_dir.mkdir(parents=True, exist_ok=True)
        (ch_dir / "synthesis.md").write_text("# Channel Synth", encoding="utf-8")

        result = runner.invoke(cli.app, ["synthesis", "ai"])

        assert result.exit_code == 0
        assert "Channel Synthesis: TestCh" in result.output

    def test_findings_reports_missing_report(self, mock_config):
        result = runner.invoke(cli.app, ["findings", "ai"])

        assert result.exit_code == 0
        assert "No report yet" in result.output

    def test_show_rejects_invalid_what(self, mock_config_with_library):
        _populate_videos(mock_config_with_library, "ai", "TestCh")

        result = runner.invoke(cli.app, ["show", "ai", "1", "--what", "unknown"])

        assert result.exit_code == 0
        assert "Invalid --what" in result.output


class TestExportOpenCostsAndStatus:
    def test_export_rejects_unknown_type(self, mock_config):
        result = runner.invoke(cli.app, ["export", "ai", "--what", "unknown"])

        assert result.exit_code == int(ExitCode.USAGE_ERROR)
        assert "Unknown export type" in result.output

    def test_export_converts_report_to_docx(self, mock_config, monkeypatch):
        report = mock_config.topic_dir("ai") / "report.md"
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text("# Report", encoding="utf-8")
        captured = {}

        def fake_markdown_to_docx(md_path, docx_path, title):
            captured["md_path"] = md_path
            captured["docx_path"] = docx_path
            captured["title"] = title
            docx_path.write_text("docx", encoding="utf-8")

        monkeypatch.setattr(_reports, "markdown_to_docx", fake_markdown_to_docx)

        result = runner.invoke(cli.app, ["export", "ai"])

        assert result.exit_code == 0
        assert captured["md_path"] == report
        assert captured["docx_path"].exists()

    def test_export_bundle_writes_manifest_and_corpus_files(self, mock_config):
        topic_dir = mock_config.topic_dir("ai")
        channel_dir = mock_config.channel_dir("ai", "TestCh")
        video_dir = channel_dir / "videos" / "video-1"
        video_dir.mkdir(parents=True, exist_ok=True)
        (topic_dir / "topic_synthesis.md").parent.mkdir(parents=True, exist_ok=True)
        (topic_dir / "topic_synthesis.md").write_text("# Topic", encoding="utf-8")
        (topic_dir / "report.md").write_text("# Report", encoding="utf-8")
        (video_dir / "insights.md").write_text("# Insight", encoding="utf-8")
        (video_dir / "metadata.json").write_text('{"title":"Test"}', encoding="utf-8")

        result = runner.invoke(cli.app, ["export", "ai", "--what", "bundle", "--format", "deepr"])

        assert result.exit_code == 0
        output_dir = mock_config.library_dir.parent / "output"
        bundle = output_dir / "corpus-ai-deepr.zip"
        assert bundle.exists()
        with zipfile.ZipFile(bundle) as zf:
            names = set(zf.namelist())
            assert "manifest.json" in names
            assert "ai/topic_synthesis.md" in names
            assert "ai/report.md" in names
            assert "ai/channels/TestCh/videos/video-1/insights.md" in names
            manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        assert manifest["topic"] == "ai"
        assert manifest["format"] == "deepr"

    def test_export_okf_writes_valid_directory_bundle(self, mock_config):
        topic_dir = mock_config.topic_dir("ai")
        video_dir = topic_dir / "channels" / "TestCh" / "videos" / "video-1"
        video_dir.mkdir(parents=True, exist_ok=True)
        (video_dir / "video_Insights.md").write_text(
            "---\nvideo_title: Test Video\nurl: https://youtube.com/watch?v=1\n---\n\n# Insight\n",
            encoding="utf-8",
        )

        result = runner.invoke(cli.app, ["export", "ai", "--format", "okf"])

        assert result.exit_code == 0
        output_dir = mock_config.library_dir.parent / "output" / "okf-ai"
        assert (output_dir / "index.md").exists()
        assert (output_dir / "log.md").exists()
        exported = output_dir / "channels" / "TestCh" / "videos" / "video-1" / "video_Insights.md"
        assert exported.exists()
        text = exported.read_text(encoding="utf-8")
        assert 'type: "Source Insight"' in text
        assert 'resource: "https://youtube.com/watch?v=1"' in text

    def test_export_citations_writes_bibtex(self, mock_config):
        paper_dir = mock_config.paper_dir("ai", "Agent Memory Systems", "2602.12670v1")
        paper_dir.mkdir(parents=True, exist_ok=True)
        artifact_path(paper_dir, "paper").write_text(
            "\n".join(
                [
                    "---",
                    'title: "Agent Memory Systems"',
                    'type: "paper"',
                    'topic: "ai"',
                    'source: "arxiv"',
                    'source_id: "2602.12670v1"',
                    'paper_id: "2602.12670v1"',
                    'url: "https://arxiv.org/abs/2602.12670v1"',
                    'date: "2026-02-17T00:00:00Z"',
                    'authors: ["Alice Example", "Bob Researcher"]',
                    'categories: ["cs.AI"]',
                    'doi: "10.5555/agent-memory"',
                    "---",
                    "",
                    "# Agent Memory Systems",
                ]
            ),
            encoding="utf-8",
        )

        result = runner.invoke(cli.app, ["export", "ai", "--what", "citations"])

        assert result.exit_code == 0
        output_path = mock_config.library_dir.parent / "output" / "citations-ai.bib"
        assert output_path.exists()
        text = output_path.read_text(encoding="utf-8")
        assert "@misc{" in text
        assert "doi = {10.5555/agent-memory}" in text

    def test_export_citations_writes_ris(self, mock_config):
        paper_dir = mock_config.paper_dir("ai", "Agent Memory Systems", "2602.12670v1")
        paper_dir.mkdir(parents=True, exist_ok=True)
        artifact_path(paper_dir, "paper").write_text(
            "\n".join(
                [
                    "---",
                    'title: "Agent Memory Systems"',
                    'type: "paper"',
                    'topic: "ai"',
                    'source: "arxiv"',
                    'source_id: "2602.12670v1"',
                    'paper_id: "2602.12670v1"',
                    'url: "https://arxiv.org/abs/2602.12670v1"',
                    'date: "2026-02-17T00:00:00Z"',
                    'authors: ["Alice Example"]',
                    'doi: "10.5555/agent-memory"',
                    "---",
                    "",
                    "# Agent Memory Systems",
                ]
            ),
            encoding="utf-8",
        )

        result = runner.invoke(cli.app, ["export", "ai", "--what", "citations", "--format", "ris"])

        assert result.exit_code == 0
        output_path = mock_config.library_dir.parent / "output" / "citations-ai.ris"
        assert output_path.exists()
        text = output_path.read_text(encoding="utf-8")
        assert "TY  - JOUR" in text
        assert "DO  - 10.5555/agent-memory" in text

    def _write_valid_okf_bundle(self, bundle):
        (bundle / "concepts").mkdir(parents=True)
        (bundle / "index.md").write_text(
            "---\ntitle: Test\n---\n\n# Index\n\n- [Item](concepts/item.md)\n",
            encoding="utf-8",
        )
        (bundle / "log.md").write_text("# Log\n", encoding="utf-8")
        (bundle / "concepts" / "item.md").write_text(
            "---\ntype: Concept\n---\n\n# Item\n",
            encoding="utf-8",
        )

    def test_okf_validate_reports_valid_bundle(self, tmp_path):
        bundle = tmp_path / "bundle"
        self._write_valid_okf_bundle(bundle)

        result = runner.invoke(cli.app, ["okf", "validate", str(bundle)])

        assert result.exit_code == 0
        assert "OKF valid" in result.output
        assert "Markdown files checked: 3" in result.output
        assert "Errors" not in result.output
        assert "Warnings" not in result.output

    def test_okf_validate_json_reports_valid_bundle(self, tmp_path):
        bundle = tmp_path / "bundle"
        self._write_valid_okf_bundle(bundle)

        result = runner.invoke(cli.app, ["--json", "okf", "validate", str(bundle)])

        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["status"] == "ok"
        assert payload["data"]["ok"] is True
        assert payload["data"]["files_checked"] == 3

    def test_okf_validate_reports_invalid_bundle(self, tmp_path):
        bundle = tmp_path / "bundle"
        bundle.mkdir()
        (bundle / "concept.md").write_text("---\ntitle: Missing type\n---\n\n# Concept\n")

        result = runner.invoke(cli.app, ["okf", "validate", str(bundle)])

        assert result.exit_code == 1
        assert "OKF invalid" in result.output
        assert "type" in result.output

    def test_okf_validate_json_reports_invalid_bundle(self, tmp_path):
        bundle = tmp_path / "bundle"
        bundle.mkdir()
        (bundle / "concept.md").write_text(
            "---\ntitle: Missing type\n---\n\n# Concept\n", encoding="utf-8"
        )

        result = runner.invoke(cli.app, ["--json", "okf", "validate", str(bundle)])

        assert result.exit_code == 1
        payload = json.loads(result.output)
        assert payload["status"] == "error"
        assert payload["error"] == "OKF validation failed"
        assert payload["data"]["ok"] is False

    def test_export_bundle_sanitizes_archive_topic_prefix(self, mock_config):
        raw_topic = "../escape"
        topic_dir = mock_config.topic_dir(raw_topic)
        topic_dir.mkdir(parents=True, exist_ok=True)
        (topic_dir / "topic_synthesis.md").write_text("# Topic", encoding="utf-8")

        result = runner.invoke(
            cli.app, ["export", raw_topic, "--what", "bundle", "--format", "deepr"]
        )

        assert result.exit_code == 0
        output_dir = mock_config.library_dir.parent / "output"
        bundle = output_dir / "corpus-escape-deepr.zip"
        assert bundle.exists()
        assert not (mock_config.library_dir.parent / "corpus-..").exists()
        with zipfile.ZipFile(bundle) as zf:
            names = zf.namelist()
        assert "escape/topic_synthesis.md" in names
        assert all(not name.startswith(("../", "/")) for name in names)

    def test_dashboard_web_writes_html(self, mock_config):
        topic_dir = mock_config.topic_dir("ai")
        topic_dir.mkdir(parents=True, exist_ok=True)
        (topic_dir / "topic_synthesis.md").write_text("# Topic", encoding="utf-8")

        result = runner.invoke(cli.app, ["dashboard", "--web", "--no-open"])

        assert result.exit_code == 0
        output_dir = mock_config.library_dir.parent / "output"
        html_path = output_dir / "dashboard.html"
        assert html_path.exists()
        html = html_path.read_text(encoding="utf-8")
        assert "Distill Dashboard" in html
        assert "Stay Current" in html

    def test_open_uses_startfile_for_existing_target(self, mock_config, monkeypatch):
        opened = []
        output_dir = mock_config.library_dir.parent / "output"
        output_dir.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(
            _cli_impl.os,
            "startfile",
            lambda target: opened.append(str(target)),
            raising=False,
        )

        result = runner.invoke(cli.app, ["open"])

        assert result.exit_code == 0
        assert opened

    def test_open_rejects_missing_target(self, mock_config):
        result = runner.invoke(cli.app, ["open", "ai", "--what", "report"])

        assert result.exit_code == int(ExitCode.NOT_FOUND)
        assert "Not found" in result.output

    @pytest.mark.parametrize(
        "args, message",
        [
            (["open", "--what", "unknown"], "Unknown --what"),
            (["open", "--what", "report"], "requires a topic or channel argument"),
            (["open", "--what", "synthesis"], "requires a topic or channel argument"),
        ],
    )
    def test_open_rejects_invalid_target_intent(self, mock_config, args, message):
        result = runner.invoke(cli.app, args)

        assert result.exit_code == int(ExitCode.USAGE_ERROR)
        assert message in result.output

    def test_open_rejects_unknown_target_before_topic_resolution(self, mock_config, monkeypatch):
        def unexpected_topic_resolution(*_args, **_kwargs):
            pytest.fail("topic resolution ran for an invalid open target")

        monkeypatch.setattr(_maintain, "Library", unexpected_topic_resolution)

        result = runner.invoke(cli.app, ["open", "ai", "--what", "unknown"])

        assert result.exit_code == int(ExitCode.USAGE_ERROR)
        assert "Unknown --what" in result.output

    def test_costs_reads_log_and_shows_breakdown(self, mock_config):
        log_file = mock_config.library_dir / "cost_log.jsonl"
        log_file.parent.mkdir(parents=True, exist_ok=True)
        log_file.write_text(
            '{"timestamp":"2026-03-12T12:00:00","command":"learn","full_videos":2,"shorts":1,"actual_cost":0.1234,"total_input_tokens":1000,"total_output_tokens":500,"elapsed_seconds":65,"by_call_type":{"pass1":{"calls":2,"input_tokens":500,"output_tokens":200}}}\n',
            encoding="utf-8",
        )
        telemetry_file = mock_config.library_dir / ".distill" / "telemetry.jsonl"
        telemetry_file.parent.mkdir(parents=True, exist_ok=True)
        telemetry_file.write_text(
            json.dumps(
                {
                    "timestamp": "2026-03-12T12:01:00",
                    "workload_tag": "report",
                    "call_type": "qa",
                    "model": "grok-4.3",
                    "provider_name": "xai",
                    "provider_type": "cloud",
                    "input_tokens": 2400,
                    "output_tokens": 600,
                    "elapsed_seconds": 12.5,
                    "outcome": "success",
                }
            )
            + "\n",
            encoding="utf-8",
        )

        result = runner.invoke(cli.app, ["costs"])

        assert result.exit_code == 0
        assert "Cost History" in result.output
        assert "Latest run breakdown" in result.output
        assert "Biggest Prompts" in result.output
        assert "report" in result.output
        assert "3,000" in result.output

    def test_costs_shows_only_latest_run_breakdown(self, mock_config):
        log_file = mock_config.library_dir / "cost_log.jsonl"
        log_file.parent.mkdir(parents=True, exist_ok=True)
        log_file.write_text(
            "\n".join(
                [
                    '{"timestamp":"2026-03-12T12:00:00","command":"learn","actual_cost":0.10,"total_input_tokens":1000,"total_output_tokens":500,"elapsed_seconds":65,"by_call_type":{"old_pass":{"calls":2,"input_tokens":500,"output_tokens":200}}}',
                    '{"timestamp":"2026-03-13T12:00:00","command":"ask","actual_cost":0.00,"total_input_tokens":2000,"total_output_tokens":300,"elapsed_seconds":20,"metadata":{"topic":"ai"},"by_call_type":{"ask":{"calls":1,"input_tokens":2000,"output_tokens":300}}}',
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        result = runner.invoke(cli.app, ["costs"])

        assert result.exit_code == 0, result.output
        assert result.output.count("Latest run breakdown") == 1
        assert "Breakdown: ask" in result.output
        assert "old_pass" not in result.output

    def test_costs_reports_malformed_monetary_fields_without_partial_claims(self, mock_config):
        log_file = mock_config.library_dir / "cost_log.jsonl"
        log_file.parent.mkdir(parents=True, exist_ok=True)
        log_file.write_text(
            json.dumps(
                {
                    "timestamp": "2026-03-13T12:00:00",
                    "command": "ask",
                    "actual_cost": "not-a-number",
                    "total_input_tokens": None,
                    "total_output_tokens": "bad",
                    "elapsed_seconds": "nan",
                    "metadata": "bad",
                    "by_call_type": {
                        "ask": {
                            "calls": "1",
                            "input_tokens": "bad",
                            "output_tokens": None,
                        }
                    },
                }
            )
            + "\n",
            encoding="utf-8",
        )

        result = runner.invoke(cli.app, ["costs"])

        assert result.exit_code == 0, result.output
        assert "Cost history integrity warning" in result.output
        assert "1 malformed row" in result.output
        assert "Cost History" not in result.output
        assert "Latest run breakdown" not in result.output
        assert "not-a-number" not in result.output

    def test_costs_tolerates_malformed_biggest_prompt_fields(self, mock_config, monkeypatch):
        log_file = mock_config.library_dir / "cost_log.jsonl"
        log_file.parent.mkdir(parents=True, exist_ok=True)
        log_file.write_text(
            '{"timestamp":"2026-03-13T12:00:00","command":"ask","actual_cost":0.01}\n',
            encoding="utf-8",
        )
        monkeypatch.setattr(
            _maintain,
            "_biggest_prompt_rows",
            lambda config: [
                {
                    "timestamp": "2026-03-13T12:01:00",
                    "workload_tag": "ask",
                    "call_type": "answer",
                    "model": "local",
                    "provider_type": "local",
                    "input_tokens": "bad",
                    "output_tokens": None,
                    "elapsed_seconds": "nan",
                    "outcome": "success",
                }
            ],
        )

        result = runner.invoke(cli.app, ["costs"])

        assert result.exit_code == 0, result.output
        assert "Biggest Prompts" in result.output
        assert "ask" in result.output
        assert "0.0s" in result.output

    def test_status_shows_artifacts(self, mock_config_with_library):
        _populate_videos(mock_config_with_library, "ai", "TestCh")
        ch_dir = mock_config_with_library.channel_dir("ai", "TestCh")
        (ch_dir / "channel_context.md").write_text("# Context", encoding="utf-8")
        (ch_dir / "synthesis.md").write_text("# Synth", encoding="utf-8")
        (mock_config_with_library.topic_dir("ai") / "topic_synthesis.md").write_text(
            "# Topic", encoding="utf-8"
        )

        result = runner.invoke(cli.app, ["status"])

        assert result.exit_code == 0
        assert "context, synthesis" in result.output or "synthesis, context" in result.output
        assert "synthesis" in result.output

    def test_status_online_uses_channel_info(self, mock_config_with_library, monkeypatch):
        from distill.ingestors.youtube.discovery import VideoInfo

        _populate_videos(mock_config_with_library, "ai", "TestCh")
        seen_urls: list[str] = []

        def discover(
            url,
            months=1,
            include_shorts=False,
            quiet=True,
        ):
            seen_urls.append(url)
            return [
                VideoInfo(
                    "fresh",
                    "Fresh Video",
                    _recent(1),
                    600,
                    "https://youtube.com/watch?v=fresh",
                )
            ]

        monkeypatch.setattr(_maintain, "discover_videos", discover)

        result = runner.invoke(cli.app, ["status", "--online"])

        assert result.exit_code == 0, result.output
        assert seen_urls == ["https://www.youtube.com/@TestCh"]
        assert "TestCh" in result.output
        assert "1 new" in result.output


class TestDoctorCleanupAndMigrate:
    def test_doctor_reports_missing_keys(self, tmp_path):
        config = DistillConfig(
            xai_api_key="",
            gemini_api_key="",
            openai_api_key="",
            distill_output_dir=tmp_path / "library",
        )
        original = cli.get_config
        original_impl = _cli_impl.get_config
        original_doctor = _doctor.get_config  # `doctor` resolves get_config here now
        cli.get_config = lambda: config
        _cli_impl.get_config = lambda: config
        _doctor.get_config = lambda: config
        try:
            result = runner.invoke(cli.app, ["doctor"])
        finally:
            cli.get_config = original
            _cli_impl.get_config = original_impl
            _doctor.get_config = original_doctor

        assert result.exit_code == 0
        assert "NOT SET" in result.output

    def test_health_flags_stale_and_thin_artifacts(self, tmp_path):
        config = DistillConfig(
            xai_api_key="",
            gemini_api_key="",
            openai_api_key="",
            distill_output_dir=tmp_path / "library",
        )
        lib = Library(config)
        lib.add_channel("ai", "https://www.youtube.com/@TestCh", "TestCh")

        topic_synth = config.topic_dir("ai") / "topic_synthesis.md"
        topic_synth.parent.mkdir(parents=True, exist_ok=True)
        topic_synth.write_text("# Old synthesis", encoding="utf-8")
        stale_ts = (datetime.now() - timedelta(days=120)).timestamp()
        os.utime(topic_synth, (stale_ts, stale_ts))

        video_dir = config.channel_dir("ai", "TestCh") / "videos" / "video-1"
        video_dir.mkdir(parents=True, exist_ok=True)
        (video_dir / "metadata.json").write_text(
            json.dumps({"title": "Long Video", "duration": 3600}),
            encoding="utf-8",
        )
        (video_dir / "transcript.txt").write_text("too short", encoding="utf-8")
        (video_dir / "insights.md").write_text("brief", encoding="utf-8")
        site_dir = config.site_dir("ai", "example.com")
        site_dir.mkdir(parents=True, exist_ok=True)
        (site_dir / "site.json").write_text(
            json.dumps(
                {
                    "sections": [
                        {
                            "section": "topic/agents",
                            "page_count": 2,
                            "urls": ["https://example.com/topic/agents/a"],
                            "last_crawled_at": "2026-01-01T00:00:00",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )

        original = cli.get_config
        original_impl = _cli_impl.get_config
        original_doctor = _doctor.get_config  # `health` resolves get_config here now
        cli.get_config = lambda: config
        _cli_impl.get_config = lambda: config
        _doctor.get_config = lambda: config
        try:
            result = runner.invoke(cli.app, ["health", "ai"])
        finally:
            cli.get_config = original
            _cli_impl.get_config = original_impl
            _doctor.get_config = original_doctor

        assert result.exit_code == 0
        assert "topic synthesis is stale" in result.output
        assert "section topic/agents is stale" in result.output
        assert "transcript looks thin" in result.output
        assert "insights look thin" in result.output

    def test_cleanup_requires_gemini_key(self, tmp_path):
        config = DistillConfig(gemini_api_key="", distill_output_dir=tmp_path / "library")
        original = cli.get_config
        original_impl = _cli_impl.get_config
        original_maintain = _maintain.get_config  # `cleanup` resolves get_config here
        cli.get_config = lambda: config
        _cli_impl.get_config = lambda: config
        _maintain.get_config = lambda: config
        try:
            result = runner.invoke(cli.app, ["cleanup"])
        finally:
            cli.get_config = original
            _cli_impl.get_config = original_impl
            _maintain.get_config = original_maintain

        assert result.exit_code == int(ExitCode.CONFIG_ERROR)
        assert "GEMINI_API_KEY required" in result.output

    def test_migrate_renames_video_dirs(self, mock_config_with_library):
        vid_dir = mock_config_with_library.video_dir("ai", "TestCh", "abc123xyz")
        vid_dir.mkdir(parents=True, exist_ok=True)
        (vid_dir / "metadata.json").write_text(
            json.dumps({"video_id": "abc123xyz", "title": "Great Video"}),
            encoding="utf-8",
        )

        result = runner.invoke(cli.app, ["migrate", "--yes"])

        assert result.exit_code == 0
        renamed = mock_config_with_library.videos_dir("ai", "TestCh") / "great-video_abc123xy"
        assert renamed.exists()


class TestWatchCommands:
    def test_watch_list_empty(self, mock_config):
        result = runner.invoke(cli.app, ["watch"])
        assert result.exit_code == 0
        assert "No channels" in result.output or "watch list" in result.output.lower()

    def test_watch_list_populated(self, mock_config):
        from distill.library import Library

        lib = Library(mock_config)
        lib.add_to_watchlist("https://youtube.com/@WatchMe", "WatchMe", topic="deals", days=7)
        result = runner.invoke(cli.app, ["watch"])
        assert result.exit_code == 0
        assert "WatchMe" in result.output

    def test_watch_add(self, mock_config, monkeypatch):
        monkeypatch.setattr(_watch, "resolve_channel_name", lambda url: "NewWatch")
        monkeypatch.setattr(_watch, "discover_videos", lambda url, months=1, quiet=True: [])
        result = runner.invoke(cli.app, ["watch", "add", "https://youtube.com/@NewWatch"])
        assert result.exit_code == 0
        assert "Watching" in result.output or "NewWatch" in result.output

    def test_watch_add_duplicate(self, mock_config, monkeypatch):
        from distill.library import Library

        lib = Library(mock_config)
        lib.add_to_watchlist("https://youtube.com/@WatchMe", "WatchMe")
        monkeypatch.setattr(_watch, "resolve_channel_name", lambda url: "WatchMe")
        result = runner.invoke(cli.app, ["watch", "add", "https://youtube.com/@WatchMe"])
        assert result.exit_code == 0
        assert "already" in result.output

    def test_watch_remove(self, mock_config):
        from distill.library import Library

        lib = Library(mock_config)
        lib.add_to_watchlist("https://youtube.com/@WatchMe", "WatchMe")
        result = runner.invoke(cli.app, ["watch", "remove", "WatchMe"])
        assert result.exit_code == 0
        assert "Removed" in result.output

    def test_watch_remove_missing(self, mock_config):
        result = runner.invoke(cli.app, ["watch", "remove", "NotHere"])
        assert result.exit_code == 0
        assert "not found" in result.output

    def test_watch_days(self, mock_config):
        from distill.library import Library

        lib = Library(mock_config)
        lib.add_to_watchlist("https://youtube.com/@WatchMe", "WatchMe", days=14)
        result = runner.invoke(cli.app, ["watch", "days", "WatchMe", "3"])
        assert result.exit_code == 0
        assert "3d" in result.output

    def test_watch_days_missing(self, mock_config):
        result = runner.invoke(cli.app, ["watch", "days", "NotHere", "3"])
        assert result.exit_code == 0
        assert "not found" in result.output

    def test_monitor_creates_topic_watch(self, mock_config):
        result = runner.invoke(
            cli.app,
            [
                "monitor",
                "Microsoft AI news",
                "--topic",
                "microsoft-news",
                "--cadence",
                "daily",
                "--days",
                "1",
                "--limit",
                "10",
                "--max-run-cost",
                "0.75",
            ],
        )
        assert result.exit_code == 0
        assert "Monitoring" in result.output

        from distill.library import Library

        entry = Library(mock_config).get_topic_watch_entry("microsoft-news")
        assert entry is not None
        assert entry.topic == "microsoft-news"
        assert entry.max_run_cost == 0.75

    def test_ramp_up_dispatches_to_site_batch(self, mock_config, monkeypatch):
        captured = {}

        def fake_site_batch_cmd(
            path, topic, scrape_only, seed_only, same_section_only, ingest_attachments, report, test
        ):
            captured["path"] = path
            captured["topic"] = topic
            captured["seed_only"] = seed_only
            captured["report"] = report

        monkeypatch.setattr(_discover, "site_batch_cmd", fake_site_batch_cmd)

        result = runner.invoke(
            cli.app,
            ["ramp-up", "configs/example_seeds.json", "--topic", "example", "--report"],
        )
        assert result.exit_code == 0
        assert captured["path"].name == "example_seeds.json"
        assert captured["topic"] == "example"
        assert captured["seed_only"] is True
        assert captured["report"] is True

    def test_ramp_up_dispatches_to_youtube_learning(self, mock_config, monkeypatch):
        captured = {}

        def fake_run_learning_command(query, **kwargs):
            captured["query"] = query
            captured["kwargs"] = kwargs

        monkeypatch.setattr(_discover, "_run_learning_command", fake_run_learning_command)

        result = runner.invoke(
            cli.app,
            ["ramp-up", "Microsoft Fabric best practices", "--topic", "fabric"],
        )
        assert result.exit_code == 0
        assert captured["query"] == "Microsoft Fabric best practices"
        assert captured["kwargs"]["topic"] == "fabric"

    def test_ramp_up_dispatches_to_paper_query(self, mock_config, monkeypatch):
        captured = {}

        def fake_papers(query, topic, limit):
            captured["query"] = query
            captured["topic"] = topic
            captured["limit"] = limit

        monkeypatch.setattr(_papers, "papers", fake_papers)

        result = runner.invoke(
            cli.app, ["ramp-up", "agent memory systems", "--source", "paper", "--topic", "papers"]
        )
        assert result.exit_code == 0
        assert captured["query"] == "agent memory systems"
        assert captured["topic"] == "papers"

    def test_paper_command_writes_artifacts(self, mock_config, monkeypatch):
        from distill.ingestors.papers.arxiv import PaperRecord

        monkeypatch.setattr(
            _papers,
            "fetch_arxiv_paper",
            lambda target: PaperRecord(
                paper_id="2602.12670v1",
                title="Agent Memory Systems",
                abstract="A paper about memory systems.",
                authors=["Alice"],
                abs_url="https://arxiv.org/abs/2602.12670v1",
            ),
        )
        monkeypatch.setattr(
            _papers,
            "analyze_paper",
            lambda paper, config, tracker=None, intent=None: ("# Insight", "# Paper doc"),
        )
        monkeypatch.setattr(
            _papers, "synthesize_papers", lambda topic, config, tracker=None: "paper synthesis"
        )

        result = runner.invoke(cli.app, ["paper", "2602.12670", "--topic", "papers"])

        assert result.exit_code == 0
        papers_dir = mock_config.papers_dir("papers")
        written = list(papers_dir.glob("*/*_Paper.md"))
        assert written

    def test_paper_projected_budget_refuses_after_metadata_before_model(
        self, mock_config, monkeypatch
    ):
        from distill.ingestors.papers.arxiv import PaperRecord

        monkeypatch.setenv("DISTILL_PROVIDER", "xai")
        monkeypatch.setenv("XAI_API_KEY", "test-key")
        projected = estimate_paper_workflow_cost(1, synthesis_calls=1)
        mock_config.distill_cost_workflow_budgets = f"paper={projected / 2:.8f}"
        calls: list[str] = []

        monkeypatch.setattr(_papers, "_require_model", lambda *a, **k: calls.append("model"))
        monkeypatch.setattr(
            _papers,
            "fetch_arxiv_paper",
            lambda *a, **k: (
                calls.append("fetch")
                or PaperRecord(
                    paper_id="2602.12670v1",
                    title="Agent Memory Systems",
                    abstract="A paper about memory systems.",
                    authors=["Alice"],
                    abs_url="https://arxiv.org/abs/2602.12670v1",
                )
            ),
        )

        result = runner.invoke(cli.app, ["paper", "2602.12670", "--topic", "papers"])

        assert isinstance(result.exception, ProjectedBudgetExceededError)
        assert calls == ["fetch"]

    def test_papers_command_searches_and_writes_synthesis(self, mock_config, monkeypatch):
        from distill.ingestors.papers.arxiv import PaperRecord

        monkeypatch.setattr(
            _papers,
            "search_arxiv_papers",
            lambda query, limit=10, **kwargs: [
                PaperRecord(
                    paper_id="2602.12670v1",
                    title="Agent Memory Systems",
                    abstract="A paper about memory systems.",
                    authors=["Alice"],
                    abs_url="https://arxiv.org/abs/2602.12670v1",
                )
            ],
        )
        monkeypatch.setattr(
            _papers,
            "analyze_paper",
            lambda paper, config, tracker=None, intent=None: ("# Insight", "# Paper doc"),
        )
        monkeypatch.setattr(
            _papers,
            "synthesize_papers",
            lambda topic, config, tracker=None: (
                (mock_config.topic_dir(topic) / "paper_synthesis.md").write_text(
                    "paper synthesis", encoding="utf-8"
                )
                or "paper synthesis"
            ),
        )
        monkeypatch.setattr(
            _papers,
            "synthesize_corpus",
            lambda topic, config, tracker=None: (
                (mock_config.topic_dir(topic) / "corpus_synthesis.md").write_text(
                    "corpus synthesis", encoding="utf-8"
                )
                or "corpus synthesis"
            ),
        )

        result = runner.invoke(
            cli.app,
            [
                "papers",
                "agent memory systems",
                "--topic",
                "papers",
                "--limit",
                "1",
                "--no-expand",
                "--no-rerank",
            ],
        )

        assert result.exit_code == 0
        assert "paper 1/1" in result.output
        assert "phase analyze" in result.output
        assert "completed 1/1" in result.output
        assert "spent $" in result.output
        assert (mock_config.topic_dir("papers") / "paper_synthesis.md").exists()
        assert (mock_config.topic_dir("papers") / "corpus_synthesis.md").exists()

    def test_papers_projected_budget_refuses_before_analysis(self, mock_config, monkeypatch):
        from distill.ingestors.papers.arxiv import PaperRecord

        monkeypatch.setenv("DISTILL_PROVIDER", "xai")
        monkeypatch.setenv("XAI_API_KEY", "test-key")
        projected = estimate_paper_workflow_cost(1, synthesis_calls=1)
        mock_config.distill_cost_workflow_budgets = f"papers={projected / 2:.8f}"
        calls: list[str] = []

        monkeypatch.setattr(_papers, "_require_model", lambda *a, **k: calls.append("model"))
        monkeypatch.setattr(
            _papers,
            "search_arxiv_papers",
            lambda *a, **k: (
                calls.append("search")
                or [
                    PaperRecord(
                        paper_id="2602.12670v1",
                        title="Agent Memory Systems",
                        abstract="A paper about memory systems.",
                        authors=["Alice"],
                        abs_url="https://arxiv.org/abs/2602.12670v1",
                    )
                ]
            ),
        )
        monkeypatch.setattr(
            _papers,
            "analyze_paper",
            lambda *a, **k: calls.append("analyze") or ("# Insight", "# Paper doc"),
        )
        monkeypatch.setattr(
            _papers,
            "synthesize_papers",
            lambda *a, **k: calls.append("paper synthesis"),
        )
        monkeypatch.setattr(
            _papers,
            "synthesize_corpus",
            lambda *a, **k: calls.append("corpus synthesis"),
        )

        result = runner.invoke(
            cli.app,
            [
                "papers",
                "agent memory systems",
                "--topic",
                "papers",
                "--limit",
                "1",
                "--no-expand",
                "--no-rerank",
            ],
        )

        assert isinstance(result.exception, ProjectedBudgetExceededError)
        assert calls == []

    def test_site_batch_progress_continues_after_seed_failure(
        self, mock_config, monkeypatch, tmp_path
    ):
        seeds = tmp_path / "seeds.txt"
        seeds.write_text(
            "https://bad.example.com\nhttps://good.example.com\n",
            encoding="utf-8",
        )
        calls: list[str] = []

        def fake_process_site_seed(
            seed, config, tracker, summary, scrape_only=False, ingest_attachments=False
        ):
            calls.append(seed.url)
            if "bad" in seed.url:
                raise RuntimeError("crawl exploded")

        monkeypatch.setattr(_discover, "_process_site_seed", fake_process_site_seed)
        monkeypatch.setattr(_discover, "synthesize_site_topic", lambda *a, **k: None)
        monkeypatch.setattr(_discover, "synthesize_corpus", lambda *a, **k: None)

        result = runner.invoke(
            cli.app,
            ["site-batch", str(seeds), "--topic", "web", "--seed-only"],
        )

        assert result.exit_code == 0
        assert calls == ["https://bad.example.com", "https://good.example.com"]
        assert "site 1/2" in result.output
        assert "site 2/2" in result.output
        assert "phase crawl" in result.output
        assert "completed 1/2" in result.output
        assert "failed 1" in result.output
        assert "site-ingest" in result.output

    def test_site_batch_projected_budget_refuses_before_processing(
        self, mock_config, monkeypatch, tmp_path
    ):
        monkeypatch.setenv("DISTILL_PROVIDER", "xai")
        monkeypatch.setenv("XAI_API_KEY", "test-key")
        seeds = tmp_path / "seeds.txt"
        seeds.write_text("https://good.example.com\n", encoding="utf-8")
        projected = estimate_site_batch_workflow_cost(1, synthesis_calls=3)
        mock_config.distill_cost_workflow_budgets = f"site-batch={projected / 2:.8f}"
        calls: list[str] = []

        monkeypatch.setattr(_discover, "_require_model", lambda *a, **k: calls.append("model"))
        monkeypatch.setattr(
            _discover, "_process_site_seed", lambda *a, **k: calls.append("process")
        )

        result = runner.invoke(
            cli.app,
            ["site-batch", str(seeds), "--topic", "web", "--seed-only"],
        )

        assert isinstance(result.exception, ProjectedBudgetExceededError)
        assert calls == []

    def test_site_batch_preview_shows_mixed_crawl_plan_without_writes(
        self, mock_config, monkeypatch, tmp_path
    ):
        mock_config.distill_cost_workflow_budgets = "site-batch=0.000001"
        seeds = tmp_path / "sites.json"
        seeds.write_text(
            json.dumps(
                {
                    "topic": "web",
                    "crawl": {
                        "max_depth": 1,
                        "max_pages_per_seed": 4,
                        "same_section_only": True,
                    },
                    "collections": [
                        {
                            "name": "overview",
                            "label": "Overview",
                            "mode": "exact-page",
                            "seeds": ["https://example.com/overview"],
                        },
                        {
                            "name": "docs",
                            "label": "Docs",
                            "mode": "shallow-crawl",
                            "crawl_prefix": "/docs",
                            "seeds": ["https://example.com/docs/start"],
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )
        calls: list[str] = []

        monkeypatch.setattr(
            _discover, "_require_model", lambda *args, **kwargs: calls.append("model")
        )
        monkeypatch.setattr(
            _discover,
            "_process_site_seed",
            lambda *args, **kwargs: calls.append("process"),
        )

        result = runner.invoke(cli.app, ["site-batch", str(seeds), "--preview"])

        assert result.exit_code == 0
        assert calls == []
        output = re.sub(r"\s+", " ", ANSI_RE.sub("", result.output))
        assert "Site batch preview" in output
        assert "writes: none" in output
        assert "exact-page | pages=1 depth=0 | topic=web | boundary=seed URL only" in output
        assert (
            "shallow-crawl | pages=4 depth=1 | topic=web | boundary=prefix /docs, same-section"
            in output
        )
        assert "label=Docs" in output

    def test_papers_preview_shows_ranked_set(self, mock_config, monkeypatch):
        """--preview should display ranked papers and skip ingestion entirely."""
        from distill.ingestors.papers.arxiv import PaperRecord

        analyze_calls: list = []

        def fake_search(query, limit=10, **kwargs):
            return [
                PaperRecord(
                    paper_id="2601.11111v1",
                    title="Attention Is All You Need for Papers",
                    abstract="We present a transformer for paper analysis.",
                    authors=["Alice", "Bob"],
                    categories=["cs.CL"],
                    published_at="2026-01-15T00:00:00Z",
                    abs_url="https://arxiv.org/abs/2601.11111v1",
                ),
                PaperRecord(
                    paper_id="2601.22222v1",
                    title="Unrelated Image Harmonization",
                    abstract="Image compositing pipeline.",
                    authors=["Carol"],
                    categories=["cs.CV"],
                    published_at="2026-01-10T00:00:00Z",
                    abs_url="https://arxiv.org/abs/2601.22222v1",
                ),
            ]

        monkeypatch.setattr(_papers, "search_arxiv_papers", fake_search)
        monkeypatch.setattr(
            _papers, "analyze_paper", lambda *a, **k: analyze_calls.append(a) or ("", "")
        )

        result = runner.invoke(
            cli.app,
            [
                "papers",
                "transformer",
                "--topic",
                "preview_topic",
                "--limit",
                "2",
                "--preview",
                "--no-expand",
                "--no-rerank",
            ],
        )

        assert result.exit_code == 0
        assert "Paper Best-Pick Learning Set" in result.stdout
        assert "Alice" in result.stdout  # author rendered
        assert "cs.CL" in result.stdout  # category rendered
        assert analyze_calls == []  # preview must not invoke paper analysis

    def test_papers_expand_runs_multiple_searches(self, mock_config, monkeypatch):
        """--expand should fan out to multiple arXiv searches via search_arxiv_multi."""
        from distill.ingestors.papers.arxiv import PaperRecord

        multi_calls: list = []

        def fake_multi(queries, limit_per_query=10, sort="relevance"):
            multi_calls.append(list(queries))
            return [
                PaperRecord(
                    paper_id="2601.33333v1",
                    title="Expanded Result",
                    abstract="A substantive paper.",
                    authors=["Dave", "Eve"],
                    categories=["cs.LG"],
                    published_at="2026-02-01T00:00:00Z",
                )
            ]

        monkeypatch.setattr(_papers, "search_arxiv_multi", fake_multi)
        monkeypatch.setattr(_learning_support, "model_available", lambda workload: True)
        monkeypatch.setattr(
            _learning_support,
            "_llm_expand_paper_queries",
            lambda query, config, tracker=None: ["q1 variant", "q2 variant"],
        )
        monkeypatch.setattr(_papers, "analyze_paper", lambda *a, **k: ("", ""))

        result = runner.invoke(
            cli.app,
            [
                "papers",
                "music transformer",
                "--topic",
                "expand_topic",
                "--limit",
                "1",
                "--preview",
                "--no-rerank",
            ],
        )

        assert result.exit_code == 0
        assert len(multi_calls) == 1
        # Should include original query plus the two LLM variants
        queries_sent = multi_calls[0]
        assert "music transformer" in queries_sent
        assert "q1 variant" in queries_sent
        assert "q2 variant" in queries_sent

    def test_discover_preview_shows_goal_ranked_plan(self, mock_config, monkeypatch):
        """discover --preview should generate queries, fetch candidates, rerank, display, stop."""
        from distill.ingestors.papers.arxiv import PaperRecord
        from distill.ingestors.youtube.discovery import VideoInfo

        papers_fixture = [
            PaperRecord(
                paper_id="2604.11111v1",
                title="AI Composer Transformer",
                abstract="A transformer for AI music composition.",
                authors=["Alice"],
                categories=["cs.SD"],
                published_at="2026-04-01T00:00:00Z",
            )
        ]
        videos_fixture = [
            VideoInfo(
                "v1",
                "Building an AI Composer",
                "20260315",
                1200,
                "https://youtube.com/watch?v=v1",
                "AI Composer Creator",
                "https://www.youtube.com/@AIComposerCreator",
                description="How to build an AI music composer end-to-end.",
                view_count=10000,
            )
        ]

        monkeypatch.setattr(
            _discover,
            "_discover_generate_queries",
            lambda goal, config, tracker, *, paper_count, video_count: (
                ["transformer music"],
                ["ai composer tutorial"],
            ),
        )
        monkeypatch.setattr(
            _discover,
            "search_arxiv_multi",
            lambda queries, limit_per_query=10, sort="relevance": papers_fixture,
        )
        monkeypatch.setattr(
            _discover,
            "_discover_fetch_videos",
            lambda queries, effective_days, candidate_cap, shorts: videos_fixture,
        )

        rerank_calls: list = []

        def fake_rerank(goal, papers, videos, sites, config, tracker):
            rerank_calls.append((goal, len(papers), len(videos), len(sites)))
            return [
                cli._RankedDiscoverItem(
                    kind="paper",
                    identifier="2604.11111v1",
                    title="AI Composer Transformer",
                    subtitle="Alice",
                    date="2026-04-01",
                    final_score=0.95,
                    goal_fit=0.9,
                    depth_score=0.9,
                    complementarity_score=0.85,
                    rationale="directly enables AI composition on computer",
                    paper=papers_fixture[0],
                ),
                cli._RankedDiscoverItem(
                    kind="video",
                    identifier="v1",
                    title="Building an AI Composer",
                    subtitle="AI Composer Creator",
                    date="Mar 15, 2026",
                    final_score=0.92,
                    goal_fit=0.88,
                    depth_score=0.85,
                    complementarity_score=0.9,
                    rationale="practical build walkthrough",
                    video=videos_fixture[0],
                ),
            ]

        monkeypatch.setattr(_discover, "_discover_rerank", fake_rerank)

        # Must not execute ingestion under --preview
        analyze_calls: list = []
        monkeypatch.setattr(
            _discover_flow, "analyze_paper", lambda *a, **k: analyze_calls.append(a) or ("", "")
        )
        process_calls: list = []
        monkeypatch.setattr(
            _discover_flow,
            "_process_learning_selection",
            lambda *a, **k: process_calls.append(a),
        )

        result = runner.invoke(
            cli.app,
            [
                "discover",
                "help an AI compose music on a computer",
                "--topic",
                "discover_test",
                "--paper-limit",
                "1",
                "--video-limit",
                "1",
                "--preview",
            ],
        )

        assert result.exit_code == 0
        assert len(rerank_calls) == 1
        assert rerank_calls[0][0] == "help an AI compose music on a computer"
        assert rerank_calls[0][3] == 0
        assert "Goal-Ranked Corpus Plan" in result.stdout
        assert "Found 1 video, ~20m of content across 1 search(es)" in result.stdout
        assert "paper" in result.stdout  # type column
        assert "video" in result.stdout
        assert "0.95" in result.stdout  # paper score
        assert "0.92" in result.stdout  # video score
        assert analyze_calls == []  # preview: no ingestion
        assert process_calls == []

    def test_discover_loads_goal_from_file(self, mock_config, monkeypatch, tmp_path):
        """--goal-file should load the goal from disk and pass it to query generation."""
        from distill.ingestors.papers.arxiv import PaperRecord

        goal_file = tmp_path / "music.md"
        goal_file.write_text(
            "Help an AI become a great composer -- computer only, no instruments.",
            encoding="utf-8",
        )

        generate_calls: list = []

        def fake_generate(goal, config, tracker, *, paper_count, video_count):
            generate_calls.append(goal)
            return (["transformer music"], [])

        monkeypatch.setattr(_discover, "_discover_generate_queries", fake_generate)
        monkeypatch.setattr(
            _discover,
            "search_arxiv_multi",
            lambda queries, limit_per_query=10, sort="relevance": [
                PaperRecord(paper_id="2604.99999v1", title="X", abstract="y")
            ],
        )
        monkeypatch.setattr(
            _discover,
            "_discover_rerank",
            lambda goal, papers, videos, sites, config, tracker: [
                cli._RankedDiscoverItem(
                    kind="paper",
                    identifier="2604.99999v1",
                    title="X",
                    subtitle="-",
                    date="2026-04-01",
                    final_score=0.9,
                    goal_fit=0.9,
                    depth_score=0.9,
                    complementarity_score=0.9,
                    rationale="goal fit",
                    paper=papers[0],
                )
            ],
        )

        result = runner.invoke(
            cli.app,
            [
                "discover",
                "--goal-file",
                str(goal_file),
                "--topic",
                "goal_file_test",
                "--paper-limit",
                "1",
                "--video-limit",
                "0",
                "--preview",
            ],
        )

        assert result.exit_code == 0
        assert len(generate_calls) == 1
        assert generate_calls[0].startswith("Help an AI become a great composer")
        assert "Goal loaded from" in result.stdout

    def test_discover_preview_can_rank_curated_site_seeds(self, mock_config, monkeypatch, tmp_path):
        seeds_path = tmp_path / "agent365_sites.json"
        seeds_path.write_text(
            json.dumps(
                {
                    "collections": [
                        {
                            "label": "Official Agent365 docs",
                            "seeds": [
                                "https://learn.microsoft.com/en-us/microsoft-365/agents/overview"
                            ],
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )

        rerank_calls: list = []

        def fake_rerank(goal, papers, videos, sites, config, tracker):
            rerank_calls.append((len(papers), len(videos), len(sites)))
            return [
                cli._RankedDiscoverItem(
                    kind="site",
                    identifier=sites[0].url,
                    title="Official Agent365 docs",
                    subtitle="learn.microsoft.com",
                    date="-",
                    final_score=0.91,
                    goal_fit=0.95,
                    depth_score=0.82,
                    complementarity_score=0.78,
                    rationale="official implementation guidance",
                    site_seed=sites[0],
                )
            ]

        monkeypatch.setattr(_discover, "_discover_rerank", fake_rerank)

        result = runner.invoke(
            cli.app,
            [
                "discover",
                "learn Microsoft Agent365 architecture and best practices",
                "--topic",
                "agent365",
                "--paper-limit",
                "0",
                "--video-limit",
                "0",
                "--site-seeds",
                str(seeds_path),
                "--site-limit",
                "1",
                "--preview",
            ],
        )

        assert result.exit_code == 0
        assert rerank_calls == [(0, 0, 1)]
        assert "Goal-Ranked Corpus Plan" in result.stdout
        assert "site" in result.stdout
        assert "0.91" in result.stdout

    def test_discover_preview_can_expand_trusted_site_candidates(self, mock_config, monkeypatch):
        from distill.ingestors.sites.discovery import TrustedSiteDiscoveryResult
        from distill.ingestors.sites.scraper import SiteSeed

        trusted_seed = SiteSeed(
            url="https://learn.example.com/docs/agents/overview",
            topic="agent365",
            site_name="learn.example.com",
            label="Agents overview",
            max_depth=0,
            max_pages=1,
            same_section_only=True,
        )
        trusted_calls: list[tuple[list[str], str, int]] = []

        def fake_trusted(sources, *, topic, max_candidates):
            trusted_calls.append((list(sources), topic, max_candidates))
            return TrustedSiteDiscoveryResult(
                seeds=[trusted_seed],
                source_count=len(sources),
                fetched_sitemaps=1,
                fetched_landing_pages=1,
            )

        rerank_calls: list[tuple[int, int, int]] = []

        def fake_rerank(goal, papers, videos, sites, config, tracker):
            rerank_calls.append((len(papers), len(videos), len(sites)))
            return [
                cli._RankedDiscoverItem(
                    kind="site",
                    identifier=sites[0].url,
                    title="Agents overview",
                    subtitle="learn.example.com",
                    date="-",
                    final_score=0.88,
                    goal_fit=0.9,
                    depth_score=0.8,
                    complementarity_score=0.7,
                    rationale="official docs page",
                    site_seed=sites[0],
                )
            ]

        monkeypatch.setattr(_discover, "_discover_trusted_site_seeds", fake_trusted)
        monkeypatch.setattr(_discover, "_discover_rerank", fake_rerank)

        result = runner.invoke(
            cli.app,
            [
                "discover",
                "learn Microsoft Agent365 architecture and best practices",
                "--topic",
                "agent365",
                "--paper-limit",
                "0",
                "--video-limit",
                "0",
                "--trusted-site",
                "https://learn.example.com/docs/agents",
                "--site-limit",
                "1",
                "--preview",
            ],
        )

        assert result.exit_code == 0
        assert trusted_calls == [(["https://learn.example.com/docs/agents"], "agent365", 20)]
        assert rerank_calls == [(0, 0, 1)]
        assert "Trusted-site candidates: 1 from 1 source(s)" in result.stdout
        assert "Website candidates: 1" in result.stdout
        assert "0.88" in result.stdout

    def test_discover_ingests_selected_site_seeds_safely(self, mock_config, monkeypatch, tmp_path):
        seeds_path = tmp_path / "agent365_sites.json"
        seeds_path.write_text(
            json.dumps(
                {
                    "collections": [
                        {
                            "label": "Official Agent365 docs",
                            "seeds": [
                                "https://learn.microsoft.com/en-us/microsoft-365/agents/overview"
                            ],
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )

        def fake_rerank(goal, papers, videos, sites, config, tracker):
            return [
                cli._RankedDiscoverItem(
                    kind="site",
                    identifier=sites[0].url,
                    title="Official Agent365 docs",
                    subtitle="learn.microsoft.com",
                    date="-",
                    final_score=0.91,
                    goal_fit=0.95,
                    depth_score=0.82,
                    complementarity_score=0.78,
                    rationale="official implementation guidance",
                    site_seed=sites[0],
                )
            ]

        process_calls: list[dict[str, object]] = []

        def fake_process_site_seed(
            seed, config, tracker, summary, scrape_only=False, ingest_attachments=False
        ):
            process_calls.append(
                {
                    "topic": seed.topic,
                    "url": seed.url,
                    "max_depth": seed.max_depth,
                    "max_pages": seed.max_pages,
                    "ingest_attachments": ingest_attachments,
                }
            )
            page_dir = config.site_page_dir(
                seed.topic, "learn.microsoft.com", "Official Agent365 docs"
            )
            page_dir.mkdir(parents=True, exist_ok=True)
            content_path = page_dir / "content.md"
            content_path.write_text("# Site content", encoding="utf-8")
            summary.add_output(content_path)
            return "learn.microsoft.com", 1

        synth_calls: list[str] = []

        def fake_synthesize_site_topic(topic, config, tracker=None):
            synth_calls.append(topic)
            path = config.topic_dir(topic) / "topic_synthesis.md"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("# Topic synthesis", encoding="utf-8")
            return "topic synthesis"

        monkeypatch.setattr(_discover, "_discover_rerank", fake_rerank)
        monkeypatch.setattr(_discover_flow, "_process_site_seed", fake_process_site_seed)
        monkeypatch.setattr(_discover_flow, "synthesize_site_topic", fake_synthesize_site_topic)
        monkeypatch.setattr(
            _discover_flow, "synthesize_corpus", lambda topic, config, tracker=None: None
        )

        result = runner.invoke(
            cli.app,
            [
                "discover",
                "learn Microsoft Agent365 architecture and best practices",
                "--topic",
                "agent365",
                "--paper-limit",
                "0",
                "--video-limit",
                "0",
                "--site-seeds",
                str(seeds_path),
                "--site-limit",
                "1",
                "--ingest-attachments",
                "--yes",
            ],
        )

        assert result.exit_code == 0
        assert process_calls == [
            {
                "topic": "agent365",
                "url": "https://learn.microsoft.com/en-us/microsoft-365/agents/overview",
                "max_depth": 0,
                "max_pages": 1,
                "ingest_attachments": True,
            }
        ]
        assert synth_calls == ["agent365"]

    def test_discover_site_crawl_flags_are_applied_to_selected_seeds(
        self, mock_config, monkeypatch, tmp_path
    ):
        seeds_path = tmp_path / "agent365_sites.json"
        seeds_path.write_text(
            json.dumps(
                {
                    "urls": [
                        {
                            "url": "https://learn.microsoft.com/en-us/microsoft-365/agents/overview",
                            "same_section_only": True,
                            "crawl_prefix": "/en-us/microsoft-365/agents",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )

        def fake_rerank(goal, papers, videos, sites, config, tracker):
            return [
                cli._RankedDiscoverItem(
                    kind="site",
                    identifier=sites[0].url,
                    title="Official Agent365 docs",
                    subtitle="learn.microsoft.com",
                    date="-",
                    final_score=0.91,
                    goal_fit=0.95,
                    depth_score=0.82,
                    complementarity_score=0.78,
                    rationale="official implementation guidance",
                    site_seed=sites[0],
                )
            ]

        process_calls: list[dict[str, object]] = []

        def fake_process_site_seed(
            seed, config, tracker, summary, scrape_only=False, ingest_attachments=False
        ):
            process_calls.append(
                {
                    "max_depth": seed.max_depth,
                    "max_pages": seed.max_pages,
                    "same_section_only": seed.same_section_only,
                    "crawl_prefix": seed.crawl_prefix,
                }
            )

        monkeypatch.setattr(_discover, "_discover_rerank", fake_rerank)
        monkeypatch.setattr(_discover_flow, "_process_site_seed", fake_process_site_seed)
        monkeypatch.setattr(_discover_flow, "synthesize_site_topic", lambda *args, **kwargs: None)
        monkeypatch.setattr(_discover_flow, "synthesize_corpus", lambda *args, **kwargs: None)

        result = runner.invoke(
            cli.app,
            [
                "discover",
                "learn Microsoft Agent365 architecture and best practices",
                "--topic",
                "agent365",
                "--paper-limit",
                "0",
                "--video-limit",
                "0",
                "--site-seeds",
                str(seeds_path),
                "--site-limit",
                "1",
                "--site-crawl-depth",
                "1",
                "--site-crawl-pages",
                "3",
                "--yes",
            ],
        )

        assert result.exit_code == 0
        assert process_calls == [
            {
                "max_depth": 1,
                "max_pages": 3,
                "same_section_only": True,
                "crawl_prefix": "/en-us/microsoft-365/agents",
            }
        ]
        assert "Website crawl: depth 1, max 3 page(s) per selected seed" in result.stdout

    def test_corpus_command_writes_output(self, mock_config, monkeypatch):
        topic_dir = mock_config.topic_dir("mixed")
        topic_dir.mkdir(parents=True, exist_ok=True)
        (topic_dir / "topic_synthesis.md").write_text("# Topic", encoding="utf-8")

        monkeypatch.setattr(
            _maintain,
            "synthesize_corpus",
            lambda topic, config, tracker=None: (
                (mock_config.topic_dir(topic) / "corpus_synthesis.md").write_text(
                    "corpus synthesis", encoding="utf-8"
                )
                or "corpus synthesis"
            ),
        )

        result = runner.invoke(cli.app, ["corpus", "mixed"])

        assert result.exit_code == 0
        assert (mock_config.topic_dir("mixed") / "corpus_synthesis.md").exists()

    def test_corpus_projected_budget_refuses_before_model_or_synthesis(
        self, mock_config, monkeypatch
    ):
        monkeypatch.setenv("DISTILL_PROVIDER", "xai")
        monkeypatch.setenv("XAI_API_KEY", "test-key")
        channel_dir = mock_config.channel_dir("mixed", "CreatorOne")
        channel_dir.mkdir(parents=True, exist_ok=True)
        (channel_dir / "synthesis.md").write_text("# Channel", encoding="utf-8")
        projected = estimate_synthesis_workflow_cost()
        mock_config.distill_cost_workflow_budgets = f"corpus={projected / 2:.8f}"
        calls: list[str] = []

        monkeypatch.setattr(_maintain, "_require_model", lambda: calls.append("model"))
        monkeypatch.setattr(
            _maintain,
            "synthesize_corpus",
            lambda *a, **k: calls.append("synthesis") or "corpus synthesis",
        )

        result = runner.invoke(cli.app, ["corpus", "mixed"])

        assert isinstance(result.exception, ProjectedBudgetExceededError)
        assert calls == []


class TestCatchUpCommand:
    def test_empty_watchlist(self, mock_config):
        result = runner.invoke(cli.app, ["catch-up"])
        assert result.exit_code == 0
        assert "empty" in result.output.lower() or "watch" in result.output.lower()

    def test_dry_run(self, mock_config, monkeypatch):
        from distill.ingestors.youtube.discovery import VideoInfo
        from distill.library import Library

        lib = Library(mock_config)
        lib.add_to_watchlist("https://youtube.com/@WatchMe", "WatchMe", topic="deals", days=7)

        monkeypatch.setattr(
            _watch,
            "discover_videos",
            lambda url, days=7, include_shorts=True, quiet=True: [
                VideoInfo(
                    "v1",
                    "New Deal Video",
                    _recent(3),
                    600,
                    "https://youtube.com/watch?v=v1",
                ),
            ],
        )

        result = runner.invoke(cli.app, ["catch-up", "--dry-run"])
        assert result.exit_code == 0
        assert "New Deal Video" in result.output


class TestResynthesize:
    def test_missing_topic(self, mock_config):
        result = runner.invoke(cli.app, ["resynthesize", "nonexistent"])
        assert result.exit_code == int(ExitCode.NOT_FOUND)
        assert "No channels" in result.output


class TestDashboard:
    def test_truncate_channel_list_empty(self):
        assert _truncate_channel_list([], 80) == ""

    def test_truncate_channel_list_single(self):
        result = _truncate_channel_list(["Alpha"], 80)
        assert result == "Alpha"

    def test_truncate_channel_list_fits(self):
        result = _truncate_channel_list(["Alpha", "Beta", "Gamma"], 80)
        assert result == "Alpha, Beta, Gamma"

    def test_truncate_channel_list_overflows(self):
        result = _truncate_channel_list(
            ["LongChannelName1", "LongChannelName2", "LongChannelName3"], 30
        )
        assert "+1 more" in result or "+2 more" in result

    def test_truncate_channel_list_extra_count(self):
        result = _truncate_channel_list(["A", "B"], 80, extra_count=3)
        assert "+3 more" in result

    def test_show_dashboard_with_library(self, mock_config_with_library):
        _populate_videos(mock_config_with_library, "ai", "TestCh")
        result = runner.invoke(cli.app, [])
        assert result.exit_code == 0
        # Should show topic and channel info
        assert "ai" in result.output


class TestShowChannelNameArg:
    """Tests for the smart show command that accepts channel names."""

    def test_show_with_channel_name(self, mock_config_with_library):
        _populate_videos(mock_config_with_library, "ai", "TestCh")
        result = runner.invoke(cli.app, ["show", "ai", "TestCh"])
        assert result.exit_code == 0
        assert "Summary" in result.output or "Insight" in result.output

    def test_show_with_channel_flag(self, mock_config_with_library):
        _populate_videos(mock_config_with_library, "ai", "TestCh")
        result = runner.invoke(cli.app, ["show", "ai", "-c", "TestCh"])
        assert result.exit_code == 0

    def test_show_transcript(self, mock_config_with_library):
        _populate_videos(mock_config_with_library, "ai", "TestCh")
        result = runner.invoke(cli.app, ["show", "ai", "1", "-w", "transcript"])
        assert result.exit_code == 0
        assert "Transcript" in result.output

    def test_show_invalid_what(self, mock_config_with_library):
        _populate_videos(mock_config_with_library, "ai", "TestCh")
        result = runner.invoke(cli.app, ["show", "ai", "1", "-w", "garbage"])
        assert result.exit_code == 0
        assert "Invalid" in result.output

    def test_show_no_insights(self, mock_config_with_library):
        """Show command when insights.md doesn't exist."""
        vid_dir = mock_config_with_library.video_dir("ai", "TestCh", "noinsights")
        vid_dir.mkdir(parents=True, exist_ok=True)
        meta = {
            "video_id": "noinsights",
            "title": "No Insights Video",
            "upload_date": _recent(1),
            "duration": 600,
            "url": "https://youtube.com/watch?v=noinsights",
        }
        (vid_dir / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")
        result = runner.invoke(cli.app, ["show", "ai", "1", "-c", "TestCh"])
        assert result.exit_code == 0
        assert "No insights" in result.output

    def test_show_no_transcript(self, mock_config_with_library):
        """Show transcript when file doesn't exist."""
        vid_dir = mock_config_with_library.video_dir("ai", "TestCh", "notrans")
        vid_dir.mkdir(parents=True, exist_ok=True)
        meta = {
            "video_id": "notrans",
            "title": "No Transcript",
            "upload_date": _recent(1),
            "duration": 600,
            "url": "https://youtube.com/watch?v=notrans",
        }
        (vid_dir / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")
        result = runner.invoke(cli.app, ["show", "ai", "1", "-c", "TestCh", "-w", "transcript"])
        assert result.exit_code == 0
        assert "No transcript" in result.output

    def test_show_no_channels(self, mock_config):
        result = runner.invoke(cli.app, ["show", "nonexistent"])
        assert result.exit_code == 0
        assert "No channels" in result.output


class TestSynthesisAutoGenerate:
    """Tests for synthesis auto-generation when videos exist."""

    def test_synthesis_topic_fallback_to_channel(self, mock_config_with_library):
        ch_dir = mock_config_with_library.channel_dir("ai", "TestCh")
        ch_dir.mkdir(parents=True, exist_ok=True)
        (ch_dir / "synthesis.md").write_text("# Channel Synth", encoding="utf-8")
        result = runner.invoke(cli.app, ["synthesis", "ai"])
        assert result.exit_code == 0
        assert "Channel Synth" in result.output

    def test_synthesis_no_videos_no_synthesis(self, mock_config_with_library):
        result = runner.invoke(cli.app, ["synthesis", "ai"])
        assert result.exit_code == 0
        assert "No synthesis" in result.output or "no videos" in result.output.lower()


class TestFindingsCommand:
    def test_findings_missing(self, mock_config_with_library):
        result = runner.invoke(cli.app, ["findings", "ai"])
        assert result.exit_code == 0
        assert "No report" in result.output

    def test_findings_exists(self, mock_config_with_library):
        report = mock_config_with_library.topic_dir("ai") / "report.md"
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text("# Test Report\nSome findings.", encoding="utf-8")
        result = runner.invoke(cli.app, ["findings", "ai"])
        assert result.exit_code == 0
        assert "Report" in result.output

    def test_findings_channel(self, mock_config_with_library):
        report = mock_config_with_library.channel_dir("ai", "TestCh") / "report.md"
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text("# Channel Report", encoding="utf-8")
        result = runner.invoke(cli.app, ["findings", "ai", "-c", "TestCh"])
        assert result.exit_code == 0


class TestVideosHints:
    def test_videos_shows_next_steps(self, mock_config_with_library):
        _populate_videos(mock_config_with_library, "ai", "TestCh")
        result = runner.invoke(cli.app, ["videos", "ai"])
        assert result.exit_code == 0
        assert "distill show" in result.output
        assert "distill synthesis" in result.output

    def test_videos_channel_filter(self, mock_config_with_library):
        _populate_videos(mock_config_with_library, "ai", "TestCh")
        result = runner.invoke(cli.app, ["videos", "ai", "-c", "TestCh"])
        assert result.exit_code == 0
        assert "Test Video" in result.output


class TestFileLink:
    def test_file_link_returns_link(self):
        from pathlib import Path

        link = cli._file_link(Path("test.md"))
        assert "test.md" in link
        assert "link=" in link or "file:" in link


class TestWatchDisplay:
    def test_watch_empty(self, mock_config):
        from distill.library import Library

        Library(mock_config)
        result = runner.invoke(cli.app, ["watch"])
        assert result.exit_code == 0
        assert "No channels" in result.output or "empty" in result.output.lower()

    def test_watch_with_entries(self, mock_config):
        from distill.library import Library

        lib = Library(mock_config)
        lib.add_to_watchlist(
            "https://youtube.com/@Test",
            "Test",
            topic="ai",
            instructions="Extract deals",
            days=7,
        )
        result = runner.invoke(cli.app, ["watch"])
        assert result.exit_code == 0
        assert "Test" in result.output

    def test_watch_instructions_update(self, mock_config):
        from distill.library import Library

        lib = Library(mock_config)
        lib.add_to_watchlist("https://youtube.com/@Test", "Test")
        result = runner.invoke(cli.app, ["watch", "instructions", "Test", "New instructions"])
        assert result.exit_code == 0
        assert "Updated" in result.output

    def test_watch_instructions_missing(self, mock_config):
        result = runner.invoke(cli.app, ["watch", "instructions", "Nobody", "Instructions"])
        assert result.exit_code == 0
        assert "not found" in result.output


class TestLibraryHints:
    def test_library_shows_hints(self, mock_config_with_library):
        _populate_videos(mock_config_with_library, "ai", "TestCh")
        result = runner.invoke(cli.app, ["library"])
        assert result.exit_code == 0
        assert "distill videos ai" in result.output
        assert "distill synthesis ai" in result.output

    def test_library_empty_shows_examples(self, mock_config):
        result = runner.invoke(cli.app, ["library"])
        assert result.exit_code == 0
        assert "empty" in result.output.lower()
        assert "distill --cost-mode no-metered init" in result.output


class TestCatchUpHints:
    def test_catchup_empty_watchlist(self, mock_config):
        result = runner.invoke(cli.app, ["catch-up"])
        assert result.exit_code == 0
        assert "empty" in result.output.lower() or "watch" in result.output.lower()

    def test_catchup_channel_not_found(self, mock_config):
        from distill.library import Library

        lib = Library(mock_config)
        lib.add_to_watchlist("https://youtube.com/@Ch", "Ch", topic="ai")
        result = runner.invoke(cli.app, ["catch-up", "NobodyHere"])
        assert result.exit_code == 0
        assert "not on watch list" in result.output

    def test_catchup_topic_filter_no_match(self, mock_config):
        from distill.library import Library

        lib = Library(mock_config)
        lib.add_to_watchlist("https://youtube.com/@Ch", "Ch", topic="ai")
        result = runner.invoke(cli.app, ["catch-up", "--topic", "nonexistent"])
        assert result.exit_code == 0
        assert "No watched channels" in result.output


class TestAddCommandHints:
    def test_add_shows_next_step(self, mock_config, monkeypatch):
        monkeypatch.setattr(_cli_impl, "resolve_channel_name", lambda url: "NewCh")
        result = runner.invoke(cli.app, ["add", "ai", "https://youtube.com/@NewCh"])
        assert result.exit_code == 0
        assert "distill run ai" in result.output


class TestSiteCommands:
    def test_site_scrape_only_does_not_require_xai(self, tmp_path, monkeypatch):
        config = DistillConfig(
            xai_api_key="",
            gemini_api_key="test-gemini",
            distill_output_dir=tmp_path / "library",
        )
        original = cli.get_config
        original_impl = _cli_impl.get_config
        original_discover_gc = _discover.get_config
        cli.get_config = lambda: config
        _cli_impl.get_config = lambda: config
        _discover.get_config = lambda: config

        try:
            monkeypatch.setattr(
                _site_ingest,
                "crawl_site",
                lambda seed: [
                    SitePage(
                        url=seed.url,
                        title="Example Page",
                        site_name=seed.resolved_site_name(),
                        page_type="page",
                        text="Body text",
                        pdf_links=["https://example.com/guide.pdf"],
                        source_url=seed.url,
                    )
                ],
            )
            called = []
            monkeypatch.setattr(
                _site_ingest,
                "analyze_site_page",
                lambda *args, **kwargs: called.append("analyze") or "should not run",
            )

            result = runner.invoke(
                cli.app,
                [
                    "site",
                    "https://example.com",
                    "--topic",
                    "web",
                    "--scrape-only",
                    "--seed-only",
                    "--crawl-prefix",
                    "/docs/agents",
                ],
            )

            assert result.exit_code == 0
            assert called == []
            assert (config.site_dir("web", "example.com") / "site.json").exists()
            site_manifest = json.loads(
                (config.site_dir("web", "example.com") / "site.json").read_text(encoding="utf-8")
            )
            page_dir = next(
                path
                for path in config.site_pages_dir("web", "example.com").iterdir()
                if path.is_dir()
            )
            assert find_artifact(page_dir, "content").exists()
            assert (page_dir / "metadata.json").exists()
            assert (page_dir / "attachments.json").exists()
            assert site_manifest["sections"][0]["section"] == "root"
            assert site_manifest["crawl_prefix"] == "/docs/agents"
            assert not find_artifact(page_dir, "insights").exists()
        finally:
            cli.get_config = original
            _cli_impl.get_config = original_impl
            _discover.get_config = original_discover_gc

    def test_site_writes_section_update_when_manifest_changes(self, tmp_path, monkeypatch):
        config = DistillConfig(
            xai_api_key="",
            gemini_api_key="test-gemini",
            distill_output_dir=tmp_path / "library",
        )
        original = cli.get_config
        original_impl = _cli_impl.get_config
        original_discover_gc = _discover.get_config
        cli.get_config = lambda: config
        _cli_impl.get_config = lambda: config
        _discover.get_config = lambda: config

        try:
            site_dir = config.site_dir("web", "example.com")
            site_dir.mkdir(parents=True, exist_ok=True)
            (site_dir / "site.json").write_text(
                json.dumps(
                    {
                        "sections": [
                            {
                                "section": "topic/agents",
                                "page_count": 1,
                                "urls": ["https://example.com/topic/agents/old"],
                                "last_crawled_at": "2026-01-01T00:00:00",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            monkeypatch.setattr(
                _site_ingest,
                "crawl_site",
                lambda seed: [
                    SitePage(
                        url="https://example.com/topic/agents/new",
                        title="New Page",
                        site_name=seed.resolved_site_name(),
                        page_type="topic",
                        text="Body text",
                        source_url=seed.url,
                        final_url="https://example.com/topic/agents/new",
                    )
                ],
            )

            result = runner.invoke(
                cli.app,
                [
                    "site",
                    "https://example.com/topic/agents/overview",
                    "--topic",
                    "web",
                    "--scrape-only",
                    "--seed-only",
                ],
            )

            assert result.exit_code == 0
            update_path = artifact_path(site_dir, "site_update", identity="web_example.com")
            assert update_path.exists()
            assert "topic/agents changed" in update_path.read_text(encoding="utf-8")
        finally:
            cli.get_config = original
            _cli_impl.get_config = original_impl
            _discover.get_config = original_discover_gc

    def test_site_ingest_attachments_writes_attachment_artifacts(self, tmp_path, monkeypatch):
        config = DistillConfig(
            xai_api_key="test-key",
            gemini_api_key="test-gemini",
            distill_output_dir=tmp_path / "library",
        )
        original = cli.get_config
        original_impl = _cli_impl.get_config
        original_discover_gc = _discover.get_config
        cli.get_config = lambda: config
        _cli_impl.get_config = lambda: config
        _discover.get_config = lambda: config

        try:
            monkeypatch.setattr(
                _site_ingest,
                "crawl_site",
                lambda seed: [
                    SitePage(
                        url=seed.url,
                        title="Example Page",
                        site_name=seed.resolved_site_name(),
                        page_type="page",
                        text="Body text",
                        pdf_links=["https://example.com/guide.pdf"],
                        source_url=seed.url,
                    )
                ],
            )
            monkeypatch.setattr(
                _site_ingest,
                "ingest_page_attachments",
                lambda page, page_dir, config, **_kwargs: (
                    [
                        __import__(
                            "distill.ingestors.sites.attachments", fromlist=["AttachmentRecord"]
                        ).AttachmentRecord(
                            url="https://example.com/guide.pdf",
                            kind="pdf",
                            provider="pdf",
                            source="pdf_link",
                            status="ingested",
                            text_path="guide.txt",
                            content_chars=42,
                        )
                    ],
                    "### PDF Attachment: https://example.com/guide.pdf\nPDF body",
                ),
            )
            monkeypatch.setattr(
                _site_ingest, "analyze_site_page", lambda *args, **kwargs: "# Insight"
            )
            monkeypatch.setattr(
                _site_ingest,
                "synthesize_site",
                lambda topic, site_name, config, tracker=None: "# Synthesis",
            )
            monkeypatch.setattr(
                _discover,
                "synthesize_site_topic",
                lambda topic, config, tracker=None: "# Topic synthesis",
            )

            result = runner.invoke(
                cli.app,
                [
                    "site",
                    "https://example.com",
                    "--topic",
                    "web",
                    "--seed-only",
                    "--ingest-attachments",
                ],
            )

            assert result.exit_code == 0
            page_dir = next(
                path
                for path in config.site_pages_dir("web", "example.com").iterdir()
                if path.is_dir()
            )
            assert (page_dir / "attachments.json").exists()
            assert "Attachment Extracts" in find_artifact(page_dir, "content").read_text(
                encoding="utf-8"
            )
        finally:
            cli.get_config = original
            _cli_impl.get_config = original_impl
            _discover.get_config = original_discover_gc

    def test_site_reuses_existing_insights_when_page_is_unchanged(self, tmp_path, monkeypatch):
        config = DistillConfig(
            xai_api_key="test-key",
            gemini_api_key="test-gemini",
            distill_output_dir=tmp_path / "library",
        )
        original = cli.get_config
        original_impl = _cli_impl.get_config
        original_discover_gc = _discover.get_config
        cli.get_config = lambda: config
        _cli_impl.get_config = lambda: config
        _discover.get_config = lambda: config

        try:
            page = SitePage(
                url="https://example.com/agent",
                title="Agent Page",
                site_name="example.com",
                page_type="page",
                text="Body text",
                source_url="https://example.com/agent",
            )
            page_dir = _site_page_storage.reserve_site_page_directory(
                config,
                "web",
                "example.com",
                page,
            ).path
            prior_doc = _site_ingest.build_page_document(page)
            (page_dir / "metadata.json").write_text(
                json.dumps({"content_hash": _site_ingest.content_hash(prior_doc)}),
                encoding="utf-8",
            )
            (page_dir / "insights.md").write_text("# Existing insight", encoding="utf-8")

            monkeypatch.setattr(_site_ingest, "crawl_site", lambda seed: [page])
            called = []
            monkeypatch.setattr(
                _site_ingest,
                "analyze_site_page",
                lambda *args, **kwargs: called.append("analyze") or "# New insight",
            )
            monkeypatch.setattr(
                _site_ingest,
                "synthesize_site",
                lambda topic, site_name, config, tracker=None: "# Synthesis",
            )
            monkeypatch.setattr(
                _discover,
                "synthesize_site_topic",
                lambda topic, config, tracker=None: "# Topic synthesis",
            )

            result = runner.invoke(
                cli.app,
                ["site", "https://example.com/agent", "--topic", "web", "--seed-only"],
            )

            assert result.exit_code == 0
            assert called == []
            assert "unchanged page" in result.output
            manifest = json.loads(
                (config.site_dir("web", "example.com") / "site.json").read_text(encoding="utf-8")
            )
            assert manifest["skipped_pages"] == 1
            assert manifest["analyzed_pages"] == 0
        finally:
            cli.get_config = original
            _cli_impl.get_config = original_impl
            _discover.get_config = original_discover_gc

    def test_site_projected_budget_refuses_before_model_or_processing(
        self, mock_config, monkeypatch
    ):
        monkeypatch.setenv("DISTILL_PROVIDER", "xai")
        monkeypatch.setenv("XAI_API_KEY", "test-key")
        projected = estimate_site_batch_workflow_cost(1, synthesis_calls=3)
        mock_config.distill_cost_workflow_budgets = f"site={projected / 2:.8f}"
        calls: list[str] = []

        monkeypatch.setattr(_discover, "_require_model", lambda *a, **k: calls.append("model"))
        monkeypatch.setattr(
            _discover, "_process_site_seed", lambda *a, **k: calls.append("process")
        )

        result = runner.invoke(
            cli.app,
            ["site", "https://example.com/agent", "--topic", "web", "--seed-only"],
        )

        assert isinstance(result.exception, ProjectedBudgetExceededError)
        assert calls == []

    def test_site_scrape_only_rejects_report(self, tmp_path):
        config = DistillConfig(
            xai_api_key="",
            gemini_api_key="test-gemini",
            distill_output_dir=tmp_path / "library",
        )
        original = cli.get_config
        original_impl = _cli_impl.get_config
        cli.get_config = lambda: config
        _cli_impl.get_config = lambda: config

        try:
            result = runner.invoke(
                cli.app,
                ["site", "https://example.com", "--scrape-only", "--report"],
            )
            assert result.exit_code != 0
            assert "--report cannot be used with --scrape-only" in result.output
        finally:
            cli.get_config = original
            _cli_impl.get_config = original_impl

    def test_latest_preview_uses_stay_current_defaults(self, mock_config, monkeypatch):
        captured = {}

        def fake_preview(query, **kwargs):
            captured.update(query=query, **kwargs)
            return mock_config, cli.CostTracker(), []

        monkeypatch.setattr(_learn, "_preview_learning_selection", fake_preview)

        result = runner.invoke(cli.app, ["latest", "Claude Code leak", "--preview"])

        assert result.exit_code == 0
        assert captured["days"] == 3
        assert captured["hours"] is None
        assert captured["limit"] == 10
        assert captured["sort"] == "date"
        assert captured["per_channel_cap"] == 3
        assert captured["shorts"] is True

    def test_search_passes_hours_to_preview(self, mock_config, monkeypatch):
        captured = {}

        def fake_preview(query, **kwargs):
            captured.update(query=query, **kwargs)
            return mock_config, cli.CostTracker(), []

        monkeypatch.setattr(_learn, "_preview_learning_selection", fake_preview)

        result = runner.invoke(cli.app, ["search", "Claude Code leak", "--hours", "20"])

        assert result.exit_code == 0
        assert captured["hours"] == 20


def test_auto_skeptical_mode_ignores_rumor_keywords():
    # P3: a keyword list no longer flips skeptical mode on. Whether "leak" /
    # "analysis" in a query signals a rumor is the model's read, not a trip-wire's
    # (April 1 stays the one structural trigger -- see test_learning.py).
    assert cli._auto_skeptical_mode("Claude Code leak analysis", hours=20, days=1) is False


def test_filter_recent_candidates_prefers_exact_published_at_hours():
    from distill.ingestors.youtube.discovery import VideoInfo

    recent = VideoInfo(
        "v1",
        "Recent",
        _recent(1),
        600,
        "https://youtube.com/watch?v=v1",
        published_at=(datetime.now() - timedelta(hours=6)).isoformat(),
    )
    stale = VideoInfo(
        "v2",
        "Stale",
        _recent(1),
        600,
        "https://youtube.com/watch?v=v2",
        published_at=(datetime.now() - timedelta(hours=30)).isoformat(),
    )

    filtered = cli._filter_recent_candidates([recent, stale], days=2, hours=20)

    assert [video.video_id for video in filtered] == ["v1"]


def test_cli_query_helpers_cover_noise_and_focus_defaults():
    assert cli._replace_case_insensitive("Hello Leak", "leak", "news") == "Hello news"
    assert cli._strip_intent_terms("best practices for implementation guide") == ""
    assert cli._strip_noise_terms("latest rumor analysis leak") == ""
    assert cli._effective_days(2, 49) == 3
    assert cli._window_label(3, None) == "3 days"
    assert cli._window_label(3, 12) == "12 hours"
    assert cli._default_report_focus("Claude Code leak", skeptical=False) is None
    assert "rumor-sensitive" in cli._default_report_focus("Claude Code leak", skeptical=True)
    assert cli._format_metric(1500) == "1.5K"
    assert cli._format_metric(2_500_000) == "2.5M"


def test_cli_dedupe_and_ranked_channel_cap():
    from types import SimpleNamespace

    v1 = SimpleNamespace(video_id="one")
    v2 = SimpleNamespace(video_id="one")
    v3 = SimpleNamespace(video_id="two")
    deduped = cli._dedupe_candidates([v1, v2, v3])

    ranked = [
        SimpleNamespace(video=SimpleNamespace(channel_name="ChanA")),
        SimpleNamespace(video=SimpleNamespace(channel_name="ChanA")),
        SimpleNamespace(video=SimpleNamespace(channel_name="ChanB")),
    ]
    selected = cli._apply_ranked_channel_cap(ranked, limit=3, per_channel_cap=1)

    assert deduped == [v1, v3]
    assert [item.video.channel_name for item in selected] == ["ChanA", "ChanB"]


def test_select_learning_videos_falls_back_and_filters_shorts(mock_config, monkeypatch):
    from distill.ingestors.youtube.discovery import VideoInfo

    short = VideoInfo(
        "short1",
        "Short",
        _recent(1),
        60,
        "https://youtube.com/watch?v=short1",
        "CreatorOne",
        view_count=1000,
    )
    full = VideoInfo(
        "full1",
        "Full",
        _recent(1),
        900,
        "https://youtube.com/watch?v=full1",
        "CreatorTwo",
        view_count=2000,
    )

    monkeypatch.setattr(
        _learning_support, "_expand_learning_queries", lambda *args, **kwargs: ["query"]
    )
    monkeypatch.setattr(_learning_support, "search_youtube_results", lambda *args, **kwargs: [])
    monkeypatch.setattr(_learning_support, "search_videos", lambda *args, **kwargs: [short, full])
    monkeypatch.setattr(_learning_support, "enrich_videos", lambda vids, max_videos=None: vids)
    monkeypatch.setattr(
        _learning_support,
        "rerank_videos",
        lambda query, vids, config, tracker=None, top_n=10, use_llm=True, skeptical=False: [
            SimpleNamespace(video=v, final_score=0.9, rationale="fit") for v in vids
        ],
    )

    enriched, selected = cli._select_learning_videos(
        "query",
        mock_config,
        cli.CostTracker(),
        days=7,
        limit=2,
        sort="relevance",
        per_channel_cap=2,
        shorts=False,
        rerank=False,
    )

    assert [video.video_id for video in enriched] == ["full1"]
    assert [item.video.video_id for item in selected] == ["full1"]


def test_cli_topic_change_helpers_cover_rendering_and_history(mock_config_with_library):
    _populate_videos(mock_config_with_library, "ai", "TestCh", count=1)

    page_dir = mock_config_with_library.site_page_dir("ai", "example.com", "Page One")
    page_dir.mkdir(parents=True, exist_ok=True)
    (page_dir / "content.md").write_text("content", encoding="utf-8")
    (page_dir / "metadata.json").write_text(
        json.dumps({"title": "Page One", "url": "https://example.com/page"}),
        encoding="utf-8",
    )
    (mock_config_with_library.site_dir("ai", "example.com") / "synthesis.md").write_text(
        "# Site synthesis", encoding="utf-8"
    )

    paper_dir = mock_config_with_library.paper_dir("ai", "Paper One", "2602.12670")
    paper_dir.mkdir(parents=True, exist_ok=True)
    (paper_dir / "insights.md").write_text("insight", encoding="utf-8")
    (paper_dir / "metadata.json").write_text(
        json.dumps({"title": "Paper One", "paper_id": "2602.12670"}),
        encoding="utf-8",
    )

    topic_dir = mock_config_with_library.topic_dir("ai")
    topic_dir.mkdir(parents=True, exist_ok=True)
    (topic_dir / "topic_synthesis.md").write_text("# Topic synth", encoding="utf-8")
    (topic_dir / "brief.md").write_text("# Brief", encoding="utf-8")

    lib = Library(mock_config_with_library)
    details = cli._collect_topic_change_details(mock_config_with_library, lib, "ai", None)
    markdown = cli._render_topic_diff_markdown(
        mock_config_with_library,
        title="# Topic Diff: ai",
        topic="ai",
        summary=str(details["summary"]),
        baseline=None,
        effective_baseline=details["effective_baseline"],
        generated_at=details["generated_at"],
        new_videos=details["new_videos"],
        new_pages=details["new_pages"],
        new_papers=details["new_papers"],
        refreshed_outputs=details["refreshed_outputs"],
        watch_name="AI Daily",
        query="AI daily",
        cadence="daily",
        limit=2,
    )
    history_path = cli._append_topic_change_history(
        mock_config_with_library,
        topic="ai",
        summary=str(details["summary"]),
        baseline=None,
        generated_at=details["generated_at"],
        watch_name="AI Daily",
        query="AI daily",
        cadence="daily",
        new_videos=details["new_videos"],
        new_pages=details["new_pages"],
        new_papers=details["new_papers"],
        refreshed_outputs=details["refreshed_outputs"],
    )
    history = cli._load_topic_change_history(mock_config_with_library, "ai")
    briefing_path = cli._write_topic_change_briefing(
        mock_config_with_library,
        watch_name="AI Daily",
        topic="ai",
        query="AI daily",
        cadence="daily",
        baseline=None,
        summary=str(details["summary"]),
        change_details=details,
    )

    assert "New Video Insights" in markdown
    assert "New Website Pages" in markdown
    assert "New Paper Insights" in markdown
    assert history_path.exists()
    assert history[0]["topic"] == "ai"
    assert briefing_path.exists()
    assert cli._topic_diff_output_path(mock_config_with_library, "ai").exists()


def test_cli_topic_change_history_normalizes_malformed_counts(mock_config):
    history_path = mock_config.topic_dir("ai") / "change_history.jsonl"
    history_path.parent.mkdir(parents=True, exist_ok=True)
    history_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-04-01T08:00:00",
                "topic": "ai",
                "watch_name": "AI Daily",
                "summary": "malformed counts",
                "counts": {
                    "videos": "bad",
                    "pages": "2",
                    "papers": None,
                    "outputs": [],
                },
            }
        ),
        encoding="utf-8",
    )

    records = cli._load_topic_change_history(mock_config, "ai")

    assert records[0]["counts"] == {
        "videos": 0,
        "pages": 2,
        "papers": 0,
        "outputs": 0,
    }


def test_cli_topic_change_history_skips_nonfinite_and_oversized_rows(mock_config):
    history_path = mock_config.topic_dir("ai") / "change_history.jsonl"
    history_path.parent.mkdir(parents=True, exist_ok=True)
    valid = json.dumps(
        {
            "generated_at": "2026-04-01T08:00:00",
            "topic": "ai",
            "counts": {"videos": 1},
        }
    )
    history_path.write_text(
        "\n".join(
            [
                '{"generated_at":"2026-04-04T08:00:00","counts":{"videos":NaN}}',
                '{"generated_at":"2026-04-03T08:00:00","counts":{"videos":1e999}}',
                '{"generated_at":"2026-04-02T08:00:00","counts":{"videos":' + "9" * 5000 + "}}",
                valid,
            ]
        ),
        encoding="utf-8",
    )

    records = cli._load_topic_change_history(mock_config, "ai")

    assert len(records) == 1
    assert records[0]["counts"]["videos"] == 1


def test_cli_trend_and_alert_helpers(mock_config):
    generated_at = datetime.now().replace(microsecond=0)
    records = [
        {
            "generated_at": generated_at,
            "watch_name": "AI Daily",
            "summary": "+2 videos",
            "counts": {"videos": 2, "pages": 0, "papers": 0, "outputs": 1},
        },
        {
            "generated_at": generated_at - timedelta(days=1),
            "watch_name": "AI Daily",
            "summary": "+1 video",
            "counts": {"videos": 1, "pages": 0, "papers": 0, "outputs": 0},
        },
    ]

    trends = cli._render_topic_trends_markdown(
        mock_config,
        topic="ai",
        records=records,
        generated_at=generated_at,
        limit=5,
    )
    alerts = cli._topic_watch_alert_lines(
        watch_name="AI Daily",
        topic="ai",
        ranking_label="balanced",
        summary="+2 videos",
        change_details={
            "new_videos": [1],
            "new_pages": [],
            "new_papers": [],
            "refreshed_outputs": [],
        },
        trend_label="trend: rising",
    )
    digest = cli._write_watch_alert_digest(
        mock_config,
        generated_at=generated_at,
        alert_lines=alerts,
    )

    assert cli._topic_trend_direction(records) == "activity is increasing"
    assert "Topic Trends: ai" in trends
    assert "activity is increasing" in trends
    assert alerts and "trend: rising" in alerts[0]
    assert digest.exists()


def test_cli_misc_helpers_and_baseline_resolution(mock_config):
    lib = Library(mock_config)
    lib.add_to_topic_watchlist(
        "ai-daily",
        "AI daily",
        topic="ai",
        cadence="daily",
        limit=5,
    )
    lib.mark_topic_watch_run(
        "ai-daily",
        (datetime.now() - timedelta(days=2)).replace(microsecond=0).isoformat(),
    )

    current_sections = [
        {"section": "topic/ai", "page_count": 2, "urls": ["a", "b"]},
        {"section": "topic/ml", "page_count": 1, "urls": ["c"]},
    ]
    previous = {
        "sections": [
            {"section": "topic/ai", "page_count": 1, "urls": ["a"]},
            {"section": "topic/old", "page_count": 3, "urls": ["x", "y", "z"]},
        ]
    }
    json_path = mock_config.library_dir / "data.json"
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text('{"ok": true}', encoding="utf-8")

    baseline, watch_name, query, cadence = cli._resolve_topic_diff_baseline(
        lib, "ai", watch_name="ai-daily", days=7
    )

    assert cli._truncate_channel_list(["Alpha", "Beta", "Gamma"], max_width=10) == "Alpha +2 more"
    messages = cli._site_section_change_summary(previous, current_sections)
    assert any("topic/ml added" in message for message in messages)
    assert any("topic/old missing" in message for message in messages)
    assert cli._read_json_file(json_path) == {"ok": True}
    assert cli._content_hash("abc") == cli._content_hash("abc")
    assert watch_name == "ai-daily"
    assert query == "AI daily"
    assert cadence == "daily"
    assert baseline is not None

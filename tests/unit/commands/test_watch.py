import os
from datetime import datetime, timedelta

from click import unstyle
from typer.testing import CliRunner

from distill import _cli_impl, cli
from distill.commands import dashboard as _dashboard
from distill.commands import root as _root
from distill.commands import topic_watch as _topic_watch_cmd
from distill.commands import view as _view
from distill.config import DistillConfig
from distill.library import Library, TopicWatchEntry
from distill.library.paths import artifact_path

runner = CliRunner()


def _plain_cli_output(output: str) -> str:
    return unstyle(output)


class _DashboardSnapshotLib:
    def get_channels(self, _topic):
        return []


def _patch_topic_watch_config(monkeypatch, config):
    monkeypatch.setattr(cli, "get_config", lambda: config)
    monkeypatch.setattr(_cli_impl, "get_config", lambda: config)
    monkeypatch.setattr(_topic_watch_cmd, "get_config", lambda: config)


def _patch_topic_watch_run_dependencies(monkeypatch):
    monkeypatch.setattr(_topic_watch_cmd, "_preflight", lambda: None)
    monkeypatch.setattr(_topic_watch_cmd, "_require_model", lambda: None)


def test_topic_watch_library_round_trip(config):
    lib = Library(config)
    result = lib.add_to_topic_watchlist(
        "microsoft-news",
        "Microsoft AI news",
        topic="microsoft-news",
        cadence="daily",
        days=1,
        limit=10,
        sort="date",
        channel_cap=3,
        report=True,
    )
    assert result is True

    entries = lib.get_topic_watchlist()
    assert len(entries) == 1
    assert isinstance(entries[0], TopicWatchEntry)
    assert entries[0].name == "microsoft-news"
    assert entries[0].cadence == "daily"
    assert entries[0].report is True
    assert entries[0].ranking_mode == "balanced"

    lib2 = Library(config)
    again = lib2.get_topic_watch_entry("microsoft-news")
    assert again is not None
    assert again.days == 1
    assert again.limit == 10


def test_topic_watch_sanitizes_topic_before_storage(config):
    lib = Library(config)

    result = lib.add_to_topic_watchlist(
        "outside-watch",
        "Outside query",
        topic="../outside",
    )

    assert result is True
    entry = lib.get_topic_watch_entry("outside-watch")
    assert entry is not None
    assert entry.topic == "outside"
    assert not (config.library_dir.parent / "outside").exists()


def test_topic_watch_update_and_remove(config):
    lib = Library(config)
    lib.add_to_topic_watchlist("msft", "Microsoft AI news")

    assert lib.update_topic_watch_days("msft", 3) is True
    assert lib.update_topic_watch_cadence("msft", "daily") is True
    assert lib.update_topic_watch_ranking_mode("msft", "popularity") is True
    assert lib.get_topic_watch_entry("msft").days == 3
    assert lib.get_topic_watch_entry("msft").cadence == "daily"
    assert lib.get_topic_watch_entry("msft").ranking_mode == "popularity"

    assert lib.remove_from_topic_watchlist("msft") is True
    assert lib.get_topic_watchlist() == []


def test_topic_watch_budget_and_pause_round_trip(config):
    lib = Library(config)
    lib.add_to_topic_watchlist("msft", "Microsoft AI news")

    assert lib.update_topic_watch_budget("msft", max_run_cost=0.25, monthly_budget=3.0) is True
    assert lib.set_topic_watch_paused("msft", True) is True

    entry = lib.get_topic_watch_entry("msft")
    assert entry is not None
    assert entry.max_run_cost == 0.25
    assert entry.monthly_budget == 3.0
    assert entry.paused is True


def test_topic_watch_cli_add_and_list(tmp_path):
    config = DistillConfig(
        xai_api_key="test-key",
        gemini_api_key="test-gemini",
        distill_output_dir=tmp_path / "library",
    )
    original = cli.get_config
    cli.get_config = lambda: config
    _cli_impl.get_config = lambda: config
    _topic_watch_cmd.get_config = lambda: config
    try:
        result = runner.invoke(
            cli.app,
            [
                "topic-watch",
                "add",
                "Microsoft AI news",
                "--topic",
                "microsoft-news",
                "--cadence",
                "daily",
                "--days",
                "1",
                "--limit",
                "10",
            ],
        )
        assert result.exit_code == 0
        assert "Watching topic" in result.output

        listed = runner.invoke(cli.app, ["topic-watch"])
        assert listed.exit_code == 0
        assert "microsoft-news" in listed.output
        assert "Microsoft AI news" in listed.output
        assert "balanced mix" in listed.output
    finally:
        cli.get_config = original
        _cli_impl.get_config = original
        _topic_watch_cmd.get_config = original
        _dashboard.get_config = original


def test_topic_watch_empty_list_shows_add_command(tmp_path, monkeypatch):
    config = DistillConfig(
        xai_api_key="test-key",
        gemini_api_key="test-gemini",
        distill_output_dir=tmp_path / "library",
    )
    _patch_topic_watch_config(monkeypatch, config)

    result = runner.invoke(cli.app, ["topic-watch"])

    assert result.exit_code == 0
    assert "No recurring topics configured" in result.output
    assert "topic-watch add" in result.output


def test_topic_watch_add_rejects_invalid_cadence():
    result = runner.invoke(
        cli.app,
        [
            "topic-watch",
            "add",
            "Microsoft AI news",
            "--topic",
            "microsoft-news",
            "--cadence",
            "monthly",
        ],
    )

    assert result.exit_code == 2
    assert "--cadence must be" in _plain_cli_output(result.output)


def test_topic_watch_add_prints_budgets_and_duplicate(tmp_path, monkeypatch):
    config = DistillConfig(
        xai_api_key="test-key",
        gemini_api_key="test-gemini",
        distill_output_dir=tmp_path / "library",
    )
    _patch_topic_watch_config(monkeypatch, config)
    argv = [
        "topic-watch",
        "add",
        "Microsoft AI news",
        "--name",
        "microsoft-news",
        "--topic",
        "microsoft-news",
        "--max-run-cost",
        "0.25",
        "--monthly-budget",
        "3.00",
    ]

    first = runner.invoke(cli.app, argv)
    second = runner.invoke(cli.app, argv)

    assert first.exit_code == 0
    assert "max $0.25/run" in first.output
    assert "$3.00/30d" in first.output
    assert second.exit_code == 0
    assert "already exists" in second.output


def test_topic_watch_management_not_found_and_invalid_branches(tmp_path, monkeypatch):
    config = DistillConfig(
        xai_api_key="test-key",
        gemini_api_key="test-gemini",
        distill_output_dir=tmp_path / "library",
    )
    _patch_topic_watch_config(monkeypatch, config)
    lib = Library(config)
    lib.add_to_topic_watchlist("microsoft-news", "Microsoft AI news")

    checks = [
        (["topic-watch", "remove", "ghost"], "not found on topic-watch list", 0),
        (["topic-watch", "days", "ghost", "2"], "not found on topic-watch list", 0),
        (["topic-watch", "cadence", "ghost", "monthly"], "weekly", 2),
        (["topic-watch", "cadence", "ghost", "daily"], "not found on topic-watch list", 0),
        (["topic-watch", "ranking", "ghost", "balanced"], "not found on topic-watch list", 0),
        (
            ["topic-watch", "budget", "ghost", "--max-run-cost", "1.00"],
            "not found on topic-watch list",
            0,
        ),
        (["topic-watch", "budget", "ghost"], "Provide --max-run-cost", 2),
        (["topic-watch", "pause", "ghost"], "not found on topic-watch list", 0),
        (["topic-watch", "resume", "ghost"], "not found on topic-watch list", 0),
    ]

    for argv, expected, exit_code in checks:
        result = runner.invoke(cli.app, argv)
        assert result.exit_code == exit_code
        assert expected in _plain_cli_output(result.output)

    budget = runner.invoke(
        cli.app, ["topic-watch", "budget", "microsoft-news", "--monthly-budget", "2.50"]
    )

    assert budget.exit_code == 0
    assert "monthly $2.50" in budget.output


def test_topic_watch_run_empty_missing_topic_and_paused_branches(tmp_path, monkeypatch):
    config = DistillConfig(
        xai_api_key="test-key",
        gemini_api_key="test-gemini",
        distill_output_dir=tmp_path / "library",
    )
    _patch_topic_watch_config(monkeypatch, config)
    _patch_topic_watch_run_dependencies(monkeypatch)

    empty = runner.invoke(cli.app, ["topic-watch", "run"])
    assert empty.exit_code == 0
    assert "Topic-watch list is empty" in empty.output

    lib = Library(config)
    lib.add_to_topic_watchlist("ai-daily", "AI daily", topic="ai")
    lib.set_topic_watch_paused("ai-daily", True)

    missing_name = runner.invoke(cli.app, ["topic-watch", "run", "ghost"])
    missing_topic = runner.invoke(cli.app, ["topic-watch", "run", "--topic", "ghost"])
    paused = runner.invoke(cli.app, ["topic-watch", "run", "ai-daily"])

    assert missing_name.exit_code == 0
    assert "ghost not on topic-watch list" in missing_name.output
    assert missing_topic.exit_code == 0
    assert "No watched topics in topic 'ghost'" in missing_topic.output
    assert paused.exit_code == 0
    assert "Paused" in paused.output


def test_topic_watch_run_invokes_learning(tmp_path, monkeypatch):
    config = DistillConfig(
        xai_api_key="test-key",
        gemini_api_key="test-gemini",
        distill_output_dir=tmp_path / "library",
    )
    lib = Library(config)
    lib.add_to_topic_watchlist(
        "microsoft-news",
        "Microsoft AI news",
        topic="microsoft-news",
        cadence="daily",
        days=1,
        limit=10,
        sort="date",
        channel_cap=3,
        report=False,
    )

    original = cli.get_config
    cli.get_config = lambda: config
    _cli_impl.get_config = lambda: config
    _topic_watch_cmd.get_config = lambda: config
    calls = []

    def fake_run_learning_command(query, **kwargs):
        calls.append((query, kwargs))

    monkeypatch.setattr(_topic_watch_cmd, "_run_learning_command", fake_run_learning_command)

    try:
        result = runner.invoke(cli.app, ["topic-watch", "run", "microsoft-news"])
        assert result.exit_code == 0
        assert calls
        query, kwargs = calls[0]
        assert query == "Microsoft AI news"
        assert kwargs["topic"] == "microsoft-news"
        assert kwargs["days"] == 1
        assert kwargs["limit"] == 10
        assert kwargs["sort"] == "date"
        assert kwargs["rerank"] is True
    finally:
        cli.get_config = original
        _cli_impl.get_config = original
        _topic_watch_cmd.get_config = original
        _dashboard.get_config = original


def test_topic_watch_run_writes_change_briefing(tmp_path, monkeypatch):
    config = DistillConfig(
        xai_api_key="test-key",
        gemini_api_key="test-gemini",
        distill_output_dir=tmp_path / "library",
    )
    lib = Library(config)
    lib.add_channel("ai", "https://www.youtube.com/@TestCh", "TestCh")
    lib.add_to_topic_watchlist(
        "microsoft-news",
        "Microsoft AI news",
        topic="ai",
        cadence="daily",
        days=1,
        limit=10,
        sort="date",
        channel_cap=3,
        report=False,
    )
    baseline = datetime.now() - timedelta(days=1)
    assert lib.mark_topic_watch_run("microsoft-news", baseline.isoformat()) is True

    def fake_run_learning_command(query, **kwargs):
        video_dir = config.channel_dir("ai", "TestCh") / "videos" / "video-1"
        video_dir.mkdir(parents=True, exist_ok=True)
        (video_dir / "insights.md").write_text("# Insight", encoding="utf-8")
        topic_synth = config.topic_dir("ai") / "topic_synthesis.md"
        topic_synth.parent.mkdir(parents=True, exist_ok=True)
        topic_synth.write_text("# Synthesis", encoding="utf-8")

    original = cli.get_config
    cli.get_config = lambda: config
    _cli_impl.get_config = lambda: config
    _topic_watch_cmd.get_config = lambda: config
    monkeypatch.setattr(_topic_watch_cmd, "_run_learning_command", fake_run_learning_command)

    try:
        result = runner.invoke(cli.app, ["topic-watch", "run", "microsoft-news"])
        assert result.exit_code == 0
        assert "Update" in result.output
        assert "+1 video" in result.output
        topic_update = artifact_path(config.topic_dir("ai"), "watch_update", identity="ai")
        assert topic_update.exists()
        text = topic_update.read_text(encoding="utf-8")
        assert "Topic Watch Update: microsoft-news" in text
        assert "Microsoft AI news" in text
        assert "+1 video" in text
        latest_changes = artifact_path(config.library_dir, "latest_changes", identity="library")
        assert latest_changes.exists()
        latest_text = latest_changes.read_text(encoding="utf-8")
        assert "microsoft-news" in latest_text
        assert "ai_Topic_Diff.md" in latest_text

        topic_diff = cli._topic_diff_output_path(config, "ai")
        assert topic_diff.exists()
        diff_text = topic_diff.read_text(encoding="utf-8")
        assert "# Topic Diff: ai" in diff_text
        assert "## New Video Insights" in diff_text

        history_path = config.topic_dir("ai") / "change_history.jsonl"
        assert history_path.exists()
        history_lines = [
            line for line in history_path.read_text(encoding="utf-8").splitlines() if line.strip()
        ]
        assert history_lines
        assert '"videos": 1' in history_lines[-1]

        alerts_path = cli._watch_alerts_output_path(config)
        assert alerts_path.exists()
        alerts_text = alerts_path.read_text(encoding="utf-8")
        assert "Topic Watch Alerts" in alerts_text
        assert "microsoft-news" in alerts_text
        assert "+1 video" in alerts_text
    finally:
        cli.get_config = original
        _cli_impl.get_config = original
        _topic_watch_cmd.get_config = original
        _dashboard.get_config = original


def test_topic_watch_run_skips_when_budget_exceeded(tmp_path, monkeypatch):
    config = DistillConfig(
        xai_api_key="test-key",
        gemini_api_key="test-gemini",
        distill_output_dir=tmp_path / "library",
    )
    lib = Library(config)
    lib.add_to_topic_watchlist(
        "microsoft-news",
        "Microsoft AI news",
        topic="microsoft-news",
        cadence="daily",
        days=1,
        limit=20,
        sort="date",
        channel_cap=3,
        report=True,
        max_run_cost=1.00,
    )

    original = cli.get_config
    cli.get_config = lambda: config
    _cli_impl.get_config = lambda: config
    _topic_watch_cmd.get_config = lambda: config
    calls = []

    def fake_run_learning_command(query, **kwargs):
        calls.append((query, kwargs))

    monkeypatch.setattr(_topic_watch_cmd, "_run_learning_command", fake_run_learning_command)

    try:
        result = runner.invoke(cli.app, ["topic-watch", "run", "microsoft-news"])
        assert result.exit_code == 0
        assert "Budget guardrail" in result.output
        assert "--ignore-budget" in result.output
        assert not calls
    finally:
        cli.get_config = original
        _cli_impl.get_config = original
        _topic_watch_cmd.get_config = original
        _dashboard.get_config = original


def test_dashboard_shows_topic_watch_recent_runs_and_attention(tmp_path, monkeypatch):
    config = DistillConfig(
        xai_api_key="test-key",
        gemini_api_key="test-gemini",
        distill_output_dir=tmp_path / "library",
    )
    lib = Library(config)
    lib.add_channel("ai", "https://www.youtube.com/@TestCh", "TestCh")
    lib.add_to_topic_watchlist("microsoft-news", "Microsoft AI news", topic="microsoft-news")

    (config.library_dir / "cost_log.jsonl").write_text(
        '{"timestamp":"2026-03-21T10:00:00","command":"topic-watch","actual_cost":0.12,"elapsed_seconds":8.5}\n',
        encoding="utf-8",
    )
    (config.library_dir / "latest_run.json").write_text(
        '{"results":{"failed":1},"issues":[{"stage":"demo","message":"problem"}]}',
        encoding="utf-8",
    )

    original = cli.get_config
    original_root = _root.get_config
    original_dashboard = _dashboard.get_config
    cli.get_config = lambda: config
    _cli_impl.get_config = lambda: config
    _root.get_config = lambda: config
    _dashboard.get_config = lambda: config
    monkeypatch.setattr(_root, "show_banner", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(_root.console, "clear", lambda: None)

    try:
        result = runner.invoke(cli.app, [])
        assert result.exit_code == 0
        assert "Stay Current" in result.output
        assert "Learn Fast" in result.output
        assert "Build Corpus" in result.output
        assert "Recent Activity" in result.output
        assert "What Changed" in result.output
        assert "Needs Attention" in result.output
        assert "Recommended Next Actions" in result.output
    finally:
        cli.get_config = original
        _cli_impl.get_config = original
        _root.get_config = original_root
        _dashboard.get_config = original_dashboard


def test_dashboard_cli_home_uses_shared_snapshot(tmp_path, monkeypatch):
    config = DistillConfig(
        xai_api_key="test-key",
        gemini_api_key="test-gemini",
        distill_output_dir=tmp_path / "library",
    )
    calls = []

    def fake_dashboard_snapshot(received_config):
        calls.append(received_config)
        return {
            "lib": _DashboardSnapshotLib(),
            "topics": ["snapshot-topic"],
            "watchlist": [],
            "topic_watchlist": [],
            "total_channels": 0,
            "total_videos": 0,
            "full_videos": 0,
            "scan_videos": 0,
            "site_count": 0,
            "page_count": 0,
            "paper_count": 0,
            "report_count": 0,
            "brief_count": 0,
            "synthesis_count": 0,
            "all_cost_entries": [],
            "recent_runs": [],
            "recent_spend": 0.0,
            "latest_results": {},
            "latest_issues": [],
            "recent_artifacts": [],
            "topic_changes": [("snapshot-topic", "from shared snapshot")],
            "topic_trends": {"snapshot-topic": "trend: steady"},
            "stale_topic_watches": [],
            "corpus_health_warnings": [],
            "next_sweep_cost": 0.0,
            "due_topic_watches": 0,
            "topic_spend_rollups": [],
            "source_spend_rollups": [],
            "budget_messages": [],
        }

    monkeypatch.setattr(cli, "get_config", lambda: config)
    monkeypatch.setattr(_cli_impl, "get_config", lambda: config)
    monkeypatch.setattr(_root, "get_config", lambda: config)
    monkeypatch.setattr(_dashboard, "get_config", lambda: config)
    monkeypatch.setattr(_dashboard, "_dashboard_snapshot", fake_dashboard_snapshot)
    monkeypatch.setattr(_root, "show_banner", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(_root.console, "clear", lambda: None)

    result = runner.invoke(cli.app, [])

    assert result.exit_code == 0
    assert calls and calls[0] is config
    assert "snapshot-topic" in result.output
    assert "from shared snapshot" in result.output
    assert "trend: steady" in result.output


def test_dashboard_what_changed_is_topic_aware(tmp_path, monkeypatch):
    config = DistillConfig(
        xai_api_key="test-key",
        gemini_api_key="test-gemini",
        distill_output_dir=tmp_path / "library",
    )
    lib = Library(config)
    lib.add_channel("ai", "https://www.youtube.com/@TestCh", "TestCh")
    lib.add_to_topic_watchlist("ai-daily", "AI daily", topic="ai", cadence="daily")

    last_run = datetime.now() - timedelta(days=1)
    assert lib.mark_topic_watch_run("ai-daily", last_run.isoformat()) is True

    video_dir = config.channel_dir("ai", "TestCh") / "videos" / "video-1"
    video_dir.mkdir(parents=True, exist_ok=True)
    insight_path = video_dir / "insights.md"
    insight_path.write_text("# Insight", encoding="utf-8")
    now_ts = datetime.now().timestamp()
    os.utime(insight_path, (now_ts, now_ts))

    topic_synth = config.topic_dir("ai") / "topic_synthesis.md"
    topic_synth.parent.mkdir(parents=True, exist_ok=True)
    topic_synth.write_text("# Synthesis", encoding="utf-8")
    os.utime(topic_synth, (now_ts, now_ts))
    (config.topic_dir("ai") / "change_history.jsonl").write_text(
        "\n".join(
            [
                '{"generated_at":"2026-04-01T08:00:00","topic":"ai","summary":"+3 videos","counts":{"videos":3,"pages":0,"papers":0,"outputs":1}}',
                '{"generated_at":"2026-03-31T08:00:00","topic":"ai","summary":"+1 video","counts":{"videos":1,"pages":0,"papers":0,"outputs":0}}',
            ]
        ),
        encoding="utf-8",
    )

    original = cli.get_config
    original_root = _root.get_config
    original_dashboard = _dashboard.get_config
    cli.get_config = lambda: config
    _cli_impl.get_config = lambda: config
    _root.get_config = lambda: config
    _dashboard.get_config = lambda: config
    monkeypatch.setattr(_root, "show_banner", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(_root.console, "clear", lambda: None)

    try:
        result = runner.invoke(cli.app, [])
        assert result.exit_code == 0
        assert "What Changed" in result.output
        assert "ai" in result.output
        assert "+1 video" in result.output
        assert "synthesis refreshed" in result.output
        assert "trend: rising" in result.output
    finally:
        cli.get_config = original
        _cli_impl.get_config = original
        _root.get_config = original_root
        _dashboard.get_config = original_dashboard


def test_dashboard_shows_topic_and_source_spend_rollups(tmp_path, monkeypatch):
    config = DistillConfig(
        xai_api_key="test-key",
        gemini_api_key="test-gemini",
        distill_output_dir=tmp_path / "library",
    )
    lib = Library(config)
    lib.add_channel("ai", "https://www.youtube.com/@TestCh", "TestCh")
    log_file = config.library_dir / "cost_log.jsonl"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    recent_one = (datetime.now() - timedelta(days=2)).replace(microsecond=0).isoformat()
    recent_two = (datetime.now() - timedelta(days=1)).replace(microsecond=0).isoformat()
    log_file.write_text(
        "\n".join(
            [
                f'{{"timestamp":"{recent_one}","command":"learn","actual_cost":0.40,"elapsed_seconds":8.5,"metadata":{{"topic":"ai","source_type":"youtube"}}}}',
                f'{{"timestamp":"{recent_one}","command":"site-batch","actual_cost":0.70,"elapsed_seconds":22.0,"metadata":{{"topic":"vendor-site","source_type":"website"}}}}',
                f'{{"timestamp":"{recent_two}","command":"report","actual_cost":2.50,"elapsed_seconds":180.0,"metadata":{{"topic":"ai","workflow":"report"}}}}',
            ]
        ),
        encoding="utf-8",
    )

    original = cli.get_config
    original_root = _root.get_config
    original_dashboard = _dashboard.get_config
    cli.get_config = lambda: config
    _cli_impl.get_config = lambda: config
    _root.get_config = lambda: config
    _dashboard.get_config = lambda: config
    monkeypatch.setattr(_root, "show_banner", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(_root.console, "clear", lambda: None)

    try:
        result = runner.invoke(cli.app, [])
        assert result.exit_code == 0
        assert "Top Spend" in result.output
        assert "By Source" in result.output
        assert "ai" in result.output
        assert "youtube" in result.output or "website" in result.output or "report" in result.output
    finally:
        cli.get_config = original
        _cli_impl.get_config = original
        _root.get_config = original_root
        _dashboard.get_config = original_dashboard


def test_dashboard_surfaces_corpus_health_warnings(tmp_path, monkeypatch):
    config = DistillConfig(
        xai_api_key="test-key",
        gemini_api_key="test-gemini",
        distill_output_dir=tmp_path / "library",
    )
    lib = Library(config)
    lib.add_channel("ai", "https://www.youtube.com/@TestCh", "TestCh")

    video_dir = config.channel_dir("ai", "TestCh") / "videos" / "video-1"
    video_dir.mkdir(parents=True, exist_ok=True)
    (video_dir / "metadata.json").write_text(
        '{"title":"Long Video","duration":3600}',
        encoding="utf-8",
    )
    (video_dir / "transcript.txt").write_text("short", encoding="utf-8")
    (video_dir / "insights.md").write_text("brief", encoding="utf-8")

    original = cli.get_config
    original_root = _root.get_config
    original_dashboard = _dashboard.get_config
    cli.get_config = lambda: config
    _cli_impl.get_config = lambda: config
    _root.get_config = lambda: config
    _dashboard.get_config = lambda: config
    monkeypatch.setattr(_root, "show_banner", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(_root.console, "clear", lambda: None)

    try:
        result = runner.invoke(cli.app, [])
        assert result.exit_code == 0
        assert "Needs Attention" in result.output
        assert "transcript looks thin" in result.output
    finally:
        cli.get_config = original
        _cli_impl.get_config = original
        _root.get_config = original_root
        _dashboard.get_config = original_dashboard


def test_diff_command_uses_topic_watch_baseline_and_writes_artifacts(tmp_path, monkeypatch):
    config = DistillConfig(
        xai_api_key="test-key",
        gemini_api_key="test-gemini",
        distill_output_dir=tmp_path / "library",
    )
    lib = Library(config)
    lib.add_channel("ai", "https://www.youtube.com/@TestCh", "TestCh")
    lib.add_to_topic_watchlist(
        "ai-daily",
        "AI daily",
        topic="ai",
        cadence="daily",
    )
    baseline = datetime.now() - timedelta(days=1)
    assert lib.mark_topic_watch_run("ai-daily", baseline.isoformat()) is True

    video_dir = config.channel_dir("ai", "TestCh") / "videos" / "video-1"
    video_dir.mkdir(parents=True, exist_ok=True)
    (video_dir / "metadata.json").write_text(
        '{"title":"New Signal","upload_date":"20260401"}',
        encoding="utf-8",
    )
    insight_path = video_dir / "insights.md"
    insight_path.write_text("# Insight", encoding="utf-8")
    now_ts = datetime.now().timestamp()
    os.utime(insight_path, (now_ts, now_ts))

    original = cli.get_config
    cli.get_config = lambda: config
    _cli_impl.get_config = lambda: config
    _view.get_config = lambda: config

    try:
        result = runner.invoke(cli.app, ["diff", "ai"])
        assert result.exit_code == 0
        assert "Topic Diff: ai" in result.output
        assert "+1 video" in result.output
        assert "AI daily" in result.output

        diff_path = cli._topic_diff_output_path(config, "ai")
        assert diff_path.exists()
        assert "New Signal" in diff_path.read_text(encoding="utf-8")

        history_path = config.topic_dir("ai") / "change_history.jsonl"
        assert history_path.exists()
        assert "ai-daily" in history_path.read_text(encoding="utf-8")
    finally:
        cli.get_config = original
        _cli_impl.get_config = original
        _dashboard.get_config = original
        _view.get_config = original


def test_topic_watch_run_uses_popularity_ranking_mode(tmp_path, monkeypatch):
    config = DistillConfig(
        xai_api_key="test-key",
        gemini_api_key="test-gemini",
        distill_output_dir=tmp_path / "library",
    )
    lib = Library(config)
    lib.add_to_topic_watchlist(
        "ai-pop",
        "AI news",
        topic="ai",
        cadence="daily",
        ranking_mode="popularity",
    )

    original = cli.get_config
    cli.get_config = lambda: config
    _cli_impl.get_config = lambda: config
    _topic_watch_cmd.get_config = lambda: config
    calls = []

    def fake_run_learning_command(query, **kwargs):
        calls.append((query, kwargs))

    monkeypatch.setattr(_topic_watch_cmd, "_run_learning_command", fake_run_learning_command)

    try:
        result = runner.invoke(cli.app, ["topic-watch", "run", "ai-pop"])
        assert result.exit_code == 0
        assert calls
        _query, kwargs = calls[0]
        assert kwargs["sort"] == "relevance"
        assert kwargs["rerank"] is False
        assert "popularity-biased" in result.output
    finally:
        cli.get_config = original
        _cli_impl.get_config = original
        _topic_watch_cmd.get_config = original
        _dashboard.get_config = original


def test_topic_watch_preview_uses_freshness_ranking_mode(tmp_path, monkeypatch):
    config = DistillConfig(
        xai_api_key="test-key",
        gemini_api_key="test-gemini",
        distill_output_dir=tmp_path / "library",
    )
    lib = Library(config)
    lib.add_to_topic_watchlist(
        "ai-fresh",
        "AI news",
        topic="ai",
        cadence="daily",
        ranking_mode="freshness",
    )

    original = cli.get_config
    cli.get_config = lambda: config
    _cli_impl.get_config = lambda: config
    _topic_watch_cmd.get_config = lambda: config
    calls = []

    from distill.pipeline.costs import CostTracker as _CostTracker

    def fake_preview_learning_selection(query, **kwargs):
        calls.append((query, kwargs))
        # topic-watch preview now unpacks (config, tracker, selected) so it can
        # log preview cost — return a real shape, not None.
        return config, _CostTracker(), []

    monkeypatch.setattr(
        _topic_watch_cmd, "_preview_learning_selection", fake_preview_learning_selection
    )

    try:
        result = runner.invoke(cli.app, ["topic-watch", "run", "ai-fresh", "--preview"])
        assert result.exit_code == 0
        assert calls
        _query, kwargs = calls[0]
        assert kwargs["sort"] == "date"
        assert kwargs["rerank"] is False
    finally:
        cli.get_config = original
        _cli_impl.get_config = original
        _topic_watch_cmd.get_config = original
        _dashboard.get_config = original


def test_topic_watch_ranking_command_updates_mode(tmp_path):
    config = DistillConfig(
        xai_api_key="test-key",
        gemini_api_key="test-gemini",
        distill_output_dir=tmp_path / "library",
    )
    lib = Library(config)
    lib.add_to_topic_watchlist("msft", "Microsoft AI news")

    original = cli.get_config
    cli.get_config = lambda: config
    _cli_impl.get_config = lambda: config
    _topic_watch_cmd.get_config = lambda: config
    try:
        result = runner.invoke(cli.app, ["topic-watch", "ranking", "msft", "popularity"])
        assert result.exit_code == 0
        assert "popularity-biased" in result.output
        assert Library(config).get_topic_watch_entry("msft").ranking_mode == "popularity"
    finally:
        cli.get_config = original
        _cli_impl.get_config = original
        _topic_watch_cmd.get_config = original
        _dashboard.get_config = original


def test_trends_command_handles_empty_history(tmp_path):
    config = DistillConfig(
        xai_api_key="test-key",
        gemini_api_key="test-gemini",
        distill_output_dir=tmp_path / "library",
    )
    config.topic_dir("ai").mkdir(parents=True, exist_ok=True)

    original = cli.get_config
    cli.get_config = lambda: config
    _cli_impl.get_config = lambda: config
    _view.get_config = lambda: config
    try:
        result = runner.invoke(cli.app, ["trends", "ai"])
        assert result.exit_code == 0
        assert "Topic Trends: ai" in result.output
        assert "No topic change history has been recorded yet" in result.output

        trends_path = cli._topic_trends_output_path(config, "ai")
        assert trends_path.exists()
    finally:
        cli.get_config = original
        _cli_impl.get_config = original
        _dashboard.get_config = original
        _view.get_config = original


def test_trends_command_summarizes_recent_windows(tmp_path):
    config = DistillConfig(
        xai_api_key="test-key",
        gemini_api_key="test-gemini",
        distill_output_dir=tmp_path / "library",
    )
    topic_dir = config.topic_dir("ai")
    topic_dir.mkdir(parents=True, exist_ok=True)
    history_path = topic_dir / "change_history.jsonl"
    history_path.write_text(
        "\n".join(
            [
                '{"generated_at":"2026-04-01T08:00:00","topic":"ai","watch_name":"ai-daily","summary":"+3 videos · topic synthesis refreshed","counts":{"videos":3,"pages":0,"papers":0,"outputs":1}}',
                '{"generated_at":"2026-03-31T08:00:00","topic":"ai","watch_name":"ai-daily","summary":"+1 video","counts":{"videos":1,"pages":0,"papers":0,"outputs":0}}',
                '{"generated_at":"2026-03-30T08:00:00","topic":"ai","watch_name":"ai-daily","summary":"+2 pages","counts":{"videos":0,"pages":2,"papers":0,"outputs":0}}',
            ]
        ),
        encoding="utf-8",
    )

    original = cli.get_config
    cli.get_config = lambda: config
    _cli_impl.get_config = lambda: config
    _view.get_config = lambda: config
    try:
        result = runner.invoke(cli.app, ["trends", "ai", "--limit", "3"])
        assert result.exit_code == 0
        assert "activity is increasing" in result.output
        assert "+4 videos" in result.output or "+4 video" in result.output
        assert "+2 pages" in result.output or "+2 page" in result.output
        assert "ai-daily" in result.output

        trends_path = cli._topic_trends_output_path(config, "ai")
        assert trends_path.exists()
        trends_text = trends_path.read_text(encoding="utf-8")
        assert "# Topic Trends: ai" in trends_text
        assert "## Recent Windows" in trends_text
        assert "ai_Topic_Diff.md" in trends_text
    finally:
        cli.get_config = original
        _cli_impl.get_config = original
        _dashboard.get_config = original
        _view.get_config = original


def test_topic_watch_list_shows_trend_label_when_history_exists(tmp_path):
    config = DistillConfig(
        xai_api_key="test-key",
        gemini_api_key="test-gemini",
        distill_output_dir=tmp_path / "library",
    )
    lib = Library(config)
    lib.add_to_topic_watchlist("microsoft-news", "Microsoft AI news", topic="microsoft-news")
    topic_dir = config.topic_dir("microsoft-news")
    topic_dir.mkdir(parents=True, exist_ok=True)
    (topic_dir / "change_history.jsonl").write_text(
        "\n".join(
            [
                '{"generated_at":"2026-04-01T08:00:00","topic":"microsoft-news","summary":"+3 videos","counts":{"videos":3,"pages":0,"papers":0,"outputs":0}}',
                '{"generated_at":"2026-03-31T08:00:00","topic":"microsoft-news","summary":"+1 video","counts":{"videos":1,"pages":0,"papers":0,"outputs":0}}',
            ]
        ),
        encoding="utf-8",
    )

    original = cli.get_config
    cli.get_config = lambda: config
    _cli_impl.get_config = lambda: config
    _topic_watch_cmd.get_config = lambda: config
    try:
        listed = runner.invoke(cli.app, ["topic-watch"])
        assert listed.exit_code == 0
        assert "trend: rising" in listed.output
    finally:
        cli.get_config = original
        _cli_impl.get_config = original
        _topic_watch_cmd.get_config = original
        _dashboard.get_config = original


def test_topic_watch_run_prints_alert_digest_for_notable_change(tmp_path, monkeypatch):
    config = DistillConfig(
        xai_api_key="test-key",
        gemini_api_key="test-gemini",
        distill_output_dir=tmp_path / "library",
    )
    lib = Library(config)
    lib.add_channel("ai", "https://www.youtube.com/@TestCh", "TestCh")
    lib.add_to_topic_watchlist("ai-daily", "AI daily", topic="ai", cadence="daily")
    baseline = datetime.now() - timedelta(days=1)
    assert lib.mark_topic_watch_run("ai-daily", baseline.isoformat()) is True

    def fake_run_learning_command(query, **kwargs):
        for idx in range(3):
            video_dir = config.channel_dir("ai", "TestCh") / "videos" / f"video-{idx}"
            video_dir.mkdir(parents=True, exist_ok=True)
            (video_dir / "metadata.json").write_text(
                f'{{"title":"Signal {idx}","upload_date":"20260401"}}',
                encoding="utf-8",
            )
            (video_dir / "insights.md").write_text("# Insight", encoding="utf-8")

    original = cli.get_config
    cli.get_config = lambda: config
    _cli_impl.get_config = lambda: config
    _topic_watch_cmd.get_config = lambda: config
    monkeypatch.setattr(_topic_watch_cmd, "_run_learning_command", fake_run_learning_command)

    try:
        result = runner.invoke(cli.app, ["topic-watch", "run", "ai-daily"])
        assert result.exit_code == 0
        assert "Watch Alerts" in result.output
        assert "ai-daily" in result.output
        assert "+3 videos" in result.output or "+3 video" in result.output
    finally:
        cli.get_config = original
        _cli_impl.get_config = original
        _topic_watch_cmd.get_config = original
        _dashboard.get_config = original


def test_topic_watch_run_truncates_long_alert_digest(tmp_path, monkeypatch):
    config = DistillConfig(
        xai_api_key="test-key",
        gemini_api_key="test-gemini",
        distill_output_dir=tmp_path / "library",
    )
    lib = Library(config)
    lib.add_to_topic_watchlist("ai-daily", "AI daily", topic="ai", cadence="daily")

    _patch_topic_watch_config(monkeypatch, config)
    _patch_topic_watch_run_dependencies(monkeypatch)
    monkeypatch.setattr(_topic_watch_cmd, "_run_learning_command", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        _topic_watch_cmd,
        "collect_topic_change_details",
        lambda *_args, **_kwargs: {"summary": "+10 notable changes"},
    )
    monkeypatch.setattr(
        _topic_watch_cmd,
        "write_topic_change_briefing",
        lambda *_args, **_kwargs: config.topic_dir("ai") / "watch_update.md",
    )
    monkeypatch.setattr(
        _topic_watch_cmd, "topic_trend_label", lambda *_args, **_kwargs: "trend: rising"
    )
    monkeypatch.setattr(
        _topic_watch_cmd,
        "topic_watch_alert_lines",
        lambda **_kwargs: [f"alert {idx}" for idx in range(10)],
    )
    monkeypatch.setattr(
        _topic_watch_cmd,
        "write_watch_alert_digest",
        lambda *_args, **_kwargs: config.library_dir / "watch_alerts.md",
    )

    result = runner.invoke(cli.app, ["topic-watch", "run", "ai-daily"])

    assert result.exit_code == 0
    assert "trend: rising" in result.output
    assert "...and 2 more" in result.output

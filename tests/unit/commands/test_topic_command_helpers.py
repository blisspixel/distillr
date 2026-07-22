"""Tests for topic command helper and wrapper boundaries."""

from __future__ import annotations

import json
import shlex
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
import typer
from typer.testing import CliRunner

from distill import _cli_impl, cli
from distill.commands import topic as _topic
from distill.commands._json import ExitCode, set_json_active
from distill.config import DistillConfig
from distill.library import Library
from distill.library.paths import artifact_path
from distill.pipeline.costs import ProjectedBudgetExceededError, TokenUsage

runner = CliRunner()


@pytest.fixture
def mock_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> DistillConfig:
    config = DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "library")
    monkeypatch.setattr(_cli_impl, "get_config", lambda: config)
    monkeypatch.setattr(_topic, "get_config", lambda: config)
    return config


def test_load_topic_profile_rejects_malformed_and_non_object_profiles(
    mock_config: DistillConfig,
) -> None:
    profile_path = mock_config.topic_dir("t") / "topic_profile.json"
    profile_path.parent.mkdir(parents=True, exist_ok=True)

    profile_path.write_text("{", encoding="utf-8")
    assert _topic._load_topic_profile(mock_config, "t") is None

    profile_path.write_text("[1, 2, 3]", encoding="utf-8")
    assert _topic._load_topic_profile(mock_config, "t") is None


def test_profile_value_helpers_parse_only_matching_shapes() -> None:
    profile: dict[str, object] = {
        "goal": 42,
        "videos": "7",
        "papers": "not-int",
        "days": True,
        "shorts": "yes",
    }

    assert _topic._profile_str(profile, "goal", "fallback") == "fallback"
    assert _topic._profile_int(profile, "videos", 0) == 7
    assert _topic._profile_int(profile, "papers", 3) == 3
    assert _topic._profile_int(profile, "days", 30) == 30
    assert _topic._profile_bool(profile, "shorts", False) is False


@pytest.mark.parametrize(
    "kwargs",
    [
        {"goal": "   ", "days": 30, "videos": 1, "papers": 0},
        {"goal": "goal", "days": 0, "videos": 1, "papers": 0},
        {"goal": "goal", "days": 30, "videos": -1, "papers": 0},
        {"goal": "goal", "days": 30, "videos": 0, "papers": -1},
        {"goal": "goal", "days": 30, "videos": 0, "papers": 0},
    ],
)
def test_resolve_topic_workflow_config_rejects_invalid_structure(
    mock_config: DistillConfig,
    kwargs: dict[str, Any],
) -> None:
    with pytest.raises(typer.Exit) as exc_info:
        _topic._resolve_topic_workflow_config(
            mock_config,
            topic="",
            shorts=False,
            **kwargs,
        )

    assert exc_info.value.exit_code == int(ExitCode.USAGE_ERROR)


def test_resolve_topic_workflow_config_normalizes_goal_and_infers_topic(
    mock_config: DistillConfig,
) -> None:
    resolved = _topic._resolve_topic_workflow_config(
        mock_config,
        topic="",
        goal="  Agent   memory systems  ",
        videos=3,
        papers=0,
        days=7,
        shorts=True,
    )

    assert resolved.goal == "Agent memory systems"
    assert resolved.topic == "agent-memory-systems"
    assert resolved.mixed_sources is False


def test_topic_preview_videos_only_uses_preview_selection(
    mock_config: DistillConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    preview_logs: list[tuple[object, Path, str, dict[str, str]]] = []
    tracker = object()

    def preview_learning_selection(query: str, **kwargs: Any) -> tuple[DistillConfig, object, list]:
        captured["query"] = query
        captured.update(kwargs)
        return mock_config, tracker, []

    def log_preview_cost(
        received_tracker: object,
        log_dir: Path,
        command: str,
        *,
        metadata: dict[str, str],
    ) -> None:
        preview_logs.append((received_tracker, log_dir, command, metadata))

    monkeypatch.setattr(_topic, "_preview_learning_selection", preview_learning_selection)
    monkeypatch.setattr(_topic, "log_preview_cost", log_preview_cost, raising=False)

    result = runner.invoke(
        cli.app,
        ["topic", "preview", "Agent memory", "--topic", "memory", "--videos", "4", "--papers", "0"],
    )

    assert result.exit_code == 0, result.output
    assert captured["query"] == "Agent memory"
    assert captured["limit"] == 4
    assert captured["header"] == "Topic Preview"
    assert preview_logs == [
        (tracker, mock_config.library_dir, "topic", {"topic": "memory", "source_type": "video"})
    ]
    expected_goal = _topic._quote_cli_value("Agent memory")
    assert (
        "distill --cost-mode auto topic create --topic=memory "
        f"--videos 4 --papers 0 --days 30 --no-shorts {expected_goal}"
    ) in result.output
    normalized_output = " ".join(result.output.split())
    assert "selection is refreshed when you run it" in normalized_output
    assert "No corpus artifacts were written" in normalized_output
    assert not (mock_config.topic_dir("memory") / "topic_profile.json").exists()


def test_topic_mixed_preview_emits_one_exact_topic_continuation(
    mock_config: DistillConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def invoke(command, **kwargs: Any) -> str:
        captured.update(kwargs)
        return "abc123def4"

    monkeypatch.setattr(_topic, "_invoke_command", invoke)

    result = runner.invoke(
        cli.app,
        [
            "topic",
            "preview",
            "Agent memory",
            "--topic",
            "memory",
            "--videos",
            "4",
            "--papers",
            "3",
            "--days",
            "14",
            "--shorts",
        ],
    )

    assert result.exit_code == 0, result.output
    assert captured["emit_replay_command"] is False
    assert result.output.count("distill --cost-mode auto topic create") == 1
    assert (
        "distill --cost-mode auto topic create --from-preview abc123def4 --topic=memory "
        "--videos 4 --papers 3 --days 14 --shorts"
    ) in result.output
    assert "distill discover --from-preview" not in result.output
    assert "exactly this saved set" in result.output


def test_topic_preview_json_emits_one_structured_continuation(
    mock_config: DistillConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        _topic,
        "_preview_learning_selection",
        lambda *args, **kwargs: (mock_config, object(), []),
    )
    monkeypatch.setattr(_topic, "log_preview_cost", lambda *args, **kwargs: None)

    result = runner.invoke(
        cli.app,
        [
            "--json",
            "topic",
            "preview",
            "Research agents",
            "--topic",
            "memory",
            "--videos",
            "2",
            "--papers",
            "0",
        ],
    )
    payload = json.loads(result.stdout)

    assert result.exit_code == 0, result.output
    assert payload["status"] == "ok"
    assert payload["data"]["topic"] == "memory"
    assert payload["data"]["goal"] == "Research agents"
    assert payload["data"]["selection_replay"] == "refreshed"
    assert payload["data"]["preview_id"] is None
    assert "topic create" in payload["data"]["command"]


@pytest.mark.parametrize(
    "value",
    [
        'Research "quoted" agents',
        "topic;whoami",
        "topic&whoami",
        "$(whoami)",
        "@args",
        "%PATH%",
    ],
)
def test_topic_preview_command_declines_cross_shell_unsafe_values(value: str) -> None:
    with pytest.raises(ValueError, match="portable command"):
        _topic._quote_cli_value(value)


def test_topic_preview_command_quotes_markup_like_literal_text() -> None:
    assert _topic._quote_cli_value("memory[red]") == '"memory[red]"'


def test_render_topic_preview_treats_command_values_as_plain_text(
    mock_config: DistillConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_json_active(False)
    resolved = _topic._TopicWorkflowConfig(
        topic="memory[red]",
        goal="Research [red] agents",
        videos=2,
        papers=0,
        days=7,
        shorts=False,
    )
    output: list[object] = []

    class PlainConsole:
        def print(self, value: object = "", **kwargs: object) -> None:
            output.append(value)

    monkeypatch.setattr(_topic, "console", PlainConsole())

    _topic._render_topic_preview(mock_config, resolved, "")

    rendered = "\n".join(str(value) for value in output)
    assert "memory[red]" in rendered
    assert "Research [red] agents" in rendered


def test_topic_preview_leading_dash_goal_uses_end_of_options_marker(
    mock_config: DistillConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        _topic,
        "_preview_learning_selection",
        lambda *args, **kwargs: (mock_config, object(), []),
    )
    monkeypatch.setattr(_topic, "log_preview_cost", lambda *args, **kwargs: None)

    result = runner.invoke(
        cli.app,
        ["topic", "preview", "--papers", "0", "--", "--report"],
    )

    assert result.exit_code == 0, result.output
    assert "--no-shorts -- --report" in result.output


def test_topic_preview_leading_dash_topic_round_trips_as_one_option_value(
    mock_config: DistillConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_json: dict[str, Any] = {}
    resolved = _topic._TopicWorkflowConfig(
        topic="-research",
        goal="Agent memory",
        videos=2,
        papers=0,
        days=7,
        shorts=False,
    )
    monkeypatch.setattr(_topic, "emit_json", lambda data: captured_json.update(data))
    set_json_active(True)
    try:
        _topic._render_topic_preview(mock_config, resolved, "")
    finally:
        set_json_active(False)

    command = captured_json["command"]
    assert isinstance(command, str)
    argv = shlex.split(command)[1:]
    assert "--topic=-research" in argv

    captured_workflow: dict[str, Any] = {}
    monkeypatch.setattr(
        _topic,
        "_run_topic_workflow",
        lambda **kwargs: captured_workflow.update(kwargs),
    )
    result = runner.invoke(cli.app, argv)

    assert result.exit_code == 0, result.output
    assert captured_workflow["topic"] == "-research"


def test_topic_create_videos_only_runs_brief_and_report_hooks(
    mock_config: DistillConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, Any] = {}

    monkeypatch.setattr(
        _topic,
        "_run_learning_command",
        lambda query, **kwargs: calls.setdefault("learning", (query, kwargs)),
    )
    monkeypatch.setattr(
        _topic,
        "_generate_and_export_topic_brief",
        lambda topic, config, tracker: calls.setdefault("brief", topic),
    )
    monkeypatch.setattr(
        _topic,
        "_invoke_command",
        lambda command, **kwargs: calls.setdefault("report", kwargs),
    )

    result = runner.invoke(
        cli.app,
        [
            "topic",
            "create",
            "Agent memory",
            "--topic",
            "memory",
            "--videos",
            "2",
            "--papers",
            "0",
            "--brief",
            "--report",
        ],
    )

    assert result.exit_code == 0, result.output
    assert calls["learning"][1]["topic"] == "memory"
    assert calls["brief"] == "memory"
    assert calls["report"] == {"topic": "memory", "test": False}
    assert (mock_config.topic_dir("memory") / "topic_profile.json").exists()


def test_topic_create_brief_uses_topic_brief_budget(
    mock_config: DistillConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_config.distill_cost_workflow_budgets = "topic-brief=0.25"
    budgets: list[float | None] = []

    monkeypatch.setattr(_topic, "_run_learning_command", lambda *args, **kwargs: None)

    def fake_brief(topic: str, config: DistillConfig, tracker: Any) -> None:
        budgets.append(tracker.budget)
        tracker.record(TokenUsage(prompt_tokens=1000, completion_tokens=0, model="grok-4.3"))

    monkeypatch.setattr(
        _topic,
        "_generate_and_export_topic_brief",
        fake_brief,
    )

    result = runner.invoke(
        cli.app,
        [
            "topic",
            "create",
            "Agent memory",
            "--topic",
            "memory",
            "--videos",
            "2",
            "--papers",
            "0",
            "--brief",
        ],
    )

    assert result.exit_code == 0, result.output
    assert budgets == [0.25]
    log_path = mock_config.library_dir / ".distill" / "cost_log.jsonl"
    rows = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    assert rows[-1]["command"] == "topic-brief"
    assert rows[-1]["metadata"] == {"topic": "memory"}
    assert rows[-1]["actual_cost"] > 0


def test_topic_update_missing_profile_is_clean_exit(
    mock_config: DistillConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_topic, "_preflight", lambda: None)

    result = runner.invoke(cli.app, ["topic", "update", "missing"])

    assert result.exit_code == int(ExitCode.NOT_FOUND)
    assert "No topic profile found for missing" in result.output


def test_topic_watch_missing_profile_is_clean_exit(mock_config: DistillConfig) -> None:
    result = runner.invoke(cli.app, ["topic", "watch", "missing"])

    assert result.exit_code == int(ExitCode.NOT_FOUND)
    assert "No topic profile found for missing" in result.output


def test_topic_brief_rejects_missing_topic(mock_config: DistillConfig) -> None:
    result = runner.invoke(cli.app, ["topic", "brief", "missing"])

    assert result.exit_code == int(ExitCode.NOT_FOUND)
    assert "Topic not found: missing" in result.output


def test_topic_brief_refuses_projected_budget_before_generation(
    mock_config: DistillConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DISTILL_PROVIDER", "xai")
    monkeypatch.setenv("XAI_API_KEY", "test-key")
    mock_config.topic_dir("t").mkdir(parents=True, exist_ok=True)
    mock_config.distill_cost_workflow_budgets = "topic-brief=0.0001"
    generate_brief = MagicMock()

    monkeypatch.setattr(_topic, "_generate_and_export_topic_brief", generate_brief)

    result = runner.invoke(cli.app, ["topic", "brief", "t"])

    assert result.exit_code != 0
    assert isinstance(result.exception, ProjectedBudgetExceededError)
    generate_brief.assert_not_called()


def test_topic_brief_report_hook_runs_for_existing_topic(
    mock_config: DistillConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_config.topic_dir("t").mkdir(parents=True, exist_ok=True)
    mock_config.distill_cost_workflow_budgets = "topic-brief=0.25"
    calls: dict[str, Any] = {}

    monkeypatch.setattr(
        _topic,
        "_generate_and_export_topic_brief",
        lambda topic, config, tracker: calls.setdefault("brief", (topic, tracker.budget)),
    )
    monkeypatch.setattr(
        _topic,
        "_invoke_command",
        lambda command, **kwargs: calls.setdefault("report", kwargs),
    )

    result = runner.invoke(cli.app, ["topic", "brief", "t", "--report"])

    assert result.exit_code == 0, result.output
    assert calls == {"brief": ("t", 0.25), "report": {"topic": "t", "test": False}}


def test_topic_show_dispatches_synthesis_report_and_unknown_modes(
    mock_config: DistillConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from distill.commands import view

    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(view, "synthesis", lambda topic, channel=None: calls.append(("s", topic)))
    monkeypatch.setattr(view, "findings", lambda topic, channel=None: calls.append(("r", topic)))

    synthesis_result = runner.invoke(cli.app, ["topic", "show", "t", "--what", "synthesis"])
    report_result = runner.invoke(cli.app, ["topic", "show", "t", "--what", "report"])
    unknown_result = runner.invoke(cli.app, ["topic", "show", "t", "--what", "other"])

    assert synthesis_result.exit_code == 0
    assert report_result.exit_code == 0
    assert unknown_result.exit_code == int(ExitCode.USAGE_ERROR)
    assert calls == [("s", "t"), ("r", "t")]
    assert "Unknown --what" in unknown_result.output


def test_topic_export_delegates_to_report_export(
    mock_config: DistillConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from distill.commands import reports

    captured: dict[str, Any] = {}
    monkeypatch.setattr(reports, "export", lambda **kwargs: captured.update(kwargs))

    result = runner.invoke(
        cli.app,
        ["topic", "export", "t", "--what", "bundle", "--format", "deepr"],
    )

    assert result.exit_code == 0
    assert captured == {
        "topic": "t",
        "what": "bundle",
        "channel": None,
        "bundle_format": "deepr",
    }


def test_render_topic_summary_rejects_missing_topic(mock_config: DistillConfig) -> None:
    result = runner.invoke(cli.app, ["topic", "show", "missing"])

    assert result.exit_code == int(ExitCode.NOT_FOUND)
    assert "Topic not found: missing" in result.output


def test_render_topic_summary_lists_existing_artifacts(mock_config: DistillConfig) -> None:
    topic_dir = mock_config.topic_dir("t")
    topic_dir.mkdir(parents=True, exist_ok=True)
    artifact_path(topic_dir, "topic_synthesis", identity="t").write_text(
        "# Topic", encoding="utf-8"
    )
    artifact_path(topic_dir, "brief", identity="t").write_text("# Brief", encoding="utf-8")

    result = runner.invoke(cli.app, ["topic", "show", "t"])

    assert result.exit_code == 0
    assert "Artifacts:" in result.output
    assert "topic synthesis" in result.output
    assert "brief" in result.output


def test_collect_topic_bundle_files_filters_supported_artifacts(mock_config: DistillConfig) -> None:
    assert _topic._collect_topic_bundle_files(mock_config, "missing") == []

    topic_dir = mock_config.topic_dir("t")
    topic_dir.mkdir(parents=True, exist_ok=True)
    keep_md = topic_dir / "a.md"
    keep_json = topic_dir / "b.json"
    keep_txt = topic_dir / "nested" / "c.txt"
    drop_png = topic_dir / "d.png"
    keep_txt.parent.mkdir()
    for path in [keep_md, keep_json, keep_txt, drop_png]:
        path.write_text("x", encoding="utf-8")

    assert _topic._collect_topic_bundle_files(mock_config, "t") == [keep_md, keep_json, keep_txt]


def test_topic_bundle_manifest_counts_video_insights(mock_config: DistillConfig) -> None:
    lib = Library(mock_config)
    lib.add_to_watchlist("https://youtube.com/@NoVideos", "NoVideos", topic="t")
    lib.add_to_watchlist("https://youtube.com/@WithVideos", "WithVideos", topic="t")

    videos_dir = mock_config.channel_dir("t", "WithVideos") / "videos"
    (videos_dir / "with-insights").mkdir(parents=True)
    (videos_dir / "without-insights").mkdir()
    artifact_path(videos_dir / "with-insights", "insights").write_text(
        "# Insight", encoding="utf-8"
    )
    file_path = mock_config.topic_dir("t") / "topic.json"
    file_path.write_text("{}", encoding="utf-8")

    manifest = _topic._topic_bundle_manifest(mock_config, "t", "bundle", [file_path])

    assert manifest["source_types"] == {"youtube": True, "website": False, "papers": False}
    assert manifest["counts"]["channels"] == 2
    assert manifest["counts"]["videos"] == 1
    assert manifest["counts"]["files"] == 1


def test_export_topic_bundle_rejects_invalid_or_empty_inputs(mock_config: DistillConfig) -> None:
    with pytest.raises(typer.BadParameter):
        _topic._export_topic_bundle(mock_config, "t", "bad")

    with pytest.raises(typer.Exit) as missing_topic:
        _topic._export_topic_bundle(mock_config, "missing", "bundle")
    assert missing_topic.value.exit_code == int(ExitCode.NOT_FOUND)

    mock_config.topic_dir("empty").mkdir(parents=True, exist_ok=True)
    with pytest.raises(typer.Exit) as empty_topic:
        _topic._export_topic_bundle(mock_config, "empty", "bundle")
    assert empty_topic.value.exit_code == int(ExitCode.NOT_FOUND)

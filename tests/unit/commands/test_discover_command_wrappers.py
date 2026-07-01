"""Tests for discover-panel command wrapper boundaries."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

from distill import _cli_impl, cli
from distill.commands import discover as _discover
from distill.config import DistillConfig
from distill.ingestors.papers.arxiv import PaperRecord
from distill.pipeline.costs import ProjectedBudgetExceededError
from distill.pipeline.discovery import RankedDiscoverItem

runner = CliRunner()


@pytest.fixture
def mock_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> DistillConfig:
    config = DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "library")
    monkeypatch.setattr(_cli_impl, "get_config", lambda: config)
    monkeypatch.setattr(_discover, "get_config", lambda: config)
    return config


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        (["discover", "goal", "--rigor", "unknown"], "Unknown --rigor"),
        (
            ["discover", "goal", "--papers-only", "--videos-only"],
            "--papers-only and --videos-only",
        ),
        (["discover", "goal", "--paper-limit", "-1"], "Source limits cannot be negative"),
        (["discover", "goal", "--video-limit", "-1"], "Source limits cannot be negative"),
        (["discover", "goal", "--site-limit", "-1"], "Source limits cannot be negative"),
        (["discover", "goal", "--site-crawl-depth", "-1"], "Site crawl depth"),
        (["discover", "goal", "--site-crawl-pages", "0"], "Site crawl depth"),
        (["discover", "--from-gaps"], "--from-gaps requires --topic"),
        (["discover"], "Goal is empty"),
        (["discover", "--from-preview", "abcabc1234", "--from-gaps"], "can't combine"),
    ],
)
def test_discover_rejects_invalid_structural_options(
    mock_config: DistillConfig,
    args: list[str],
    expected: str,
) -> None:
    result = runner.invoke(cli.app, args)

    assert result.exit_code == 1
    assert expected in result.output


def test_discover_rejects_missing_goal_file(
    mock_config: DistillConfig,
    tmp_path: Path,
) -> None:
    missing_goal = tmp_path / "missing-goal.md"

    result = runner.invoke(cli.app, ["discover", "--goal-file", str(missing_goal)])

    assert result.exit_code == 1
    assert "Goal file not found" in result.output


def test_discover_goal_file_requires_at_least_one_source(
    mock_config: DistillConfig,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    goal_file = tmp_path / "goal.md"
    goal_file.write_text("Use file goal.", encoding="utf-8")

    monkeypatch.setattr(_discover, "_require_model", lambda: None)

    result = runner.invoke(
        cli.app,
        [
            "discover",
            "ignored positional goal",
            "--goal-file",
            str(goal_file),
            "--topic",
            "t",
            "--paper-limit",
            "0",
            "--video-limit",
            "0",
        ],
    )

    assert result.exit_code == 1
    assert "Specify at least one source" in result.output


@pytest.mark.parametrize(
    ("source_flag", "expected_counts"),
    [
        ("--papers-only", (5, 0)),
        ("--videos-only", (0, 5)),
    ],
)
def test_discover_single_source_flags_disable_opposite_query_count(
    mock_config: DistillConfig,
    monkeypatch: pytest.MonkeyPatch,
    source_flag: str,
    expected_counts: tuple[int, int],
) -> None:
    query_counts: list[tuple[int, int]] = []

    def generate_queries(
        goal: str,
        config: DistillConfig,
        tracker: object,
        *,
        paper_count: int,
        video_count: int,
    ) -> tuple[list[str], list[str]]:
        query_counts.append((paper_count, video_count))
        return [], []

    monkeypatch.setattr(_discover, "_require_model", lambda: None)
    monkeypatch.setattr(_discover, "_discover_generate_queries", generate_queries)

    result = runner.invoke(cli.app, ["discover", "goal", "--topic", "t", source_flag])

    assert result.exit_code == 1
    assert query_counts == [expected_counts]
    assert "Query generation produced no queries" in result.output


def test_discover_rejects_missing_site_seed_file(
    mock_config: DistillConfig,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    missing_seeds = tmp_path / "missing-seeds.json"

    monkeypatch.setattr(_discover, "_require_model", lambda: None)

    result = runner.invoke(
        cli.app,
        [
            "discover",
            "goal",
            "--topic",
            "t",
            "--paper-limit",
            "0",
            "--video-limit",
            "0",
            "--site-seeds",
            str(missing_seeds),
            "--site-limit",
            "1",
        ],
    )

    assert result.exit_code == 1
    assert "Site seed file not found" in result.output


def test_discover_no_candidates_found_is_clean_exit(
    mock_config: DistillConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_discover, "_require_model", lambda: None)
    monkeypatch.setattr(_discover, "_discover_generate_queries", lambda *a, **k: (["q"], []))
    monkeypatch.setattr(_discover, "search_arxiv_multi", lambda *a, **k: [])

    result = runner.invoke(cli.app, ["discover", "goal", "--topic", "t", "--yes"])

    assert result.exit_code == 1
    assert "No candidates found" in result.output


def test_discover_rerank_parse_error_is_clean_exit(
    mock_config: DistillConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paper = PaperRecord(paper_id="2601.00001v1", title="Paper", abstract="Abstract")

    monkeypatch.setattr(_discover, "_require_model", lambda: None)
    monkeypatch.setattr(_discover, "_discover_generate_queries", lambda *a, **k: (["q"], []))
    monkeypatch.setattr(_discover, "search_arxiv_multi", lambda *a, **k: [paper])
    monkeypatch.setattr(
        _discover,
        "_discover_rerank",
        lambda *a, **k: (_ for _ in ()).throw(ValueError("bad score")),
    )

    result = runner.invoke(cli.app, ["discover", "goal", "--topic", "t", "--yes"])

    assert result.exit_code == 1
    assert "Rerank produced malformed output: bad score" in result.output


def test_discover_empty_rerank_is_clean_exit(
    mock_config: DistillConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paper = PaperRecord(paper_id="2601.00001v1", title="Paper", abstract="Abstract")

    monkeypatch.setattr(_discover, "_require_model", lambda: None)
    monkeypatch.setattr(_discover, "_discover_generate_queries", lambda *a, **k: (["q"], []))
    monkeypatch.setattr(_discover, "search_arxiv_multi", lambda *a, **k: [paper])
    monkeypatch.setattr(_discover, "_discover_rerank", lambda *a, **k: [])

    result = runner.invoke(cli.app, ["discover", "goal", "--topic", "t", "--yes"])

    assert result.exit_code == 1
    assert "Rerank produced no ranked items" in result.output


def test_discover_rigor_refuses_all_low_scoring_candidates(
    mock_config: DistillConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paper = PaperRecord(paper_id="2601.00001v1", title="Paper", abstract="Abstract")
    ranked = RankedDiscoverItem(
        kind="paper",
        identifier=paper.paper_id,
        title=paper.title,
        subtitle="-",
        date="2026-01-01",
        final_score=0.1,
        goal_fit=0.1,
        depth_score=0.1,
        complementarity_score=0.1,
        rationale="below threshold",
        paper=paper,
    )

    monkeypatch.setattr(_discover, "_require_model", lambda: None)
    monkeypatch.setattr(_discover, "_discover_generate_queries", lambda *a, **k: (["q"], []))
    monkeypatch.setattr(_discover, "search_arxiv_multi", lambda *a, **k: [paper])
    monkeypatch.setattr(_discover, "_discover_rerank", lambda *a, **k: [ranked])

    result = runner.invoke(cli.app, ["discover", "goal", "--topic", "t", "--yes"])

    assert result.exit_code == 1
    assert "No candidates clear the 'balanced' bar" in result.output


def test_synthesize_rejects_blank_topic_list() -> None:
    result = runner.invoke(
        cli.app,
        ["synthesize", "--topic", ",", "--name", "brief", "--context", "Summarize."],
    )

    assert result.exit_code == 1
    assert "At least one --topic is required" in result.output


def test_synthesize_rejects_missing_context_file(tmp_path: Path) -> None:
    missing_context = tmp_path / "missing-context.md"

    result = runner.invoke(
        cli.app,
        [
            "synthesize",
            "--topic",
            "topic",
            "--name",
            "brief",
            "--context-file",
            str(missing_context),
        ],
    )

    assert result.exit_code == 1
    assert "--context-file not found" in result.output


def test_synthesize_rejects_missing_context() -> None:
    result = runner.invoke(cli.app, ["synthesize", "--topic", "topic", "--name", "brief"])

    assert result.exit_code == 1
    assert "Provide --context or --context-file" in result.output


def test_synthesize_exits_when_synthesis_returns_no_output(
    mock_config: DistillConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, Any] = {}

    def run_synthesis(**kwargs: Any) -> None:
        calls.update(kwargs)

    monkeypatch.setattr(_discover, "_require_model", lambda: None)
    monkeypatch.setattr(_discover, "run_synthesis", run_synthesis)

    result = runner.invoke(
        cli.app,
        [
            "synthesize",
            "--topic",
            "alpha,beta",
            "--topic",
            "gamma",
            "--name",
            "brief",
            "--context",
            "Summarize.",
        ],
    )

    assert result.exit_code == 1
    assert calls["topics"] == ["alpha", "beta", "gamma"]
    assert calls["context"] == "Summarize."


def test_synthesize_refuses_projected_budget_before_synthesis(
    mock_config: DistillConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_config.distill_cost_workflow_budgets = "synthesize=0.0001"
    run_synthesis = MagicMock()

    monkeypatch.setattr(_discover, "_require_model", lambda: None)
    monkeypatch.setattr(_discover, "run_synthesis", run_synthesis)

    result = runner.invoke(
        cli.app,
        [
            "synthesize",
            "--topic",
            "alpha",
            "--name",
            "brief",
            "--context",
            "Summarize.",
        ],
    )

    assert result.exit_code != 0
    assert isinstance(result.exception, ProjectedBudgetExceededError)
    run_synthesis.assert_not_called()


def test_synthesize_combines_inline_and_file_context(
    mock_config: DistillConfig,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    context_file = tmp_path / "context.md"
    context_file.write_text("File instructions.", encoding="utf-8")
    output_path = tmp_path / "synthesis.md"
    calls: dict[str, Any] = {}

    def run_synthesis(**kwargs: Any) -> Path:
        calls.update(kwargs)
        return output_path

    monkeypatch.setattr(_discover, "_require_model", lambda: None)
    monkeypatch.setattr(_discover, "run_synthesis", run_synthesis)

    result = runner.invoke(
        cli.app,
        [
            "synthesize",
            "--topic",
            "alpha",
            "--name",
            "brief",
            "--context",
            "Inline instructions.",
            "--context-file",
            str(context_file),
        ],
    )

    assert result.exit_code == 0, result.output
    assert calls["context"] == "Inline instructions.\n\nFile instructions."
    assert "Tokens:" in result.output

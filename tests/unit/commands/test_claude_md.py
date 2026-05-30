"""CLI tests for `distill claude-md` (agent-orientation file generation)."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from distill import cli
from distill.config import DistillConfig

runner = CliRunner()


def _seed_topic(library_dir: Path, topic: str = "tkg") -> Path:
    topic_dir = library_dir / "topics" / topic
    d = topic_dir / "papers" / "a"
    d.mkdir(parents=True)
    (d / "a_Insights.md").write_text("---\n---\n# a\nbody\n", encoding="utf-8")
    (topic_dir / f"{topic}_Topic_Synthesis.md").write_text(
        '---\ntype: "topic-synthesis"\n---\n\nA real summary line.\n', encoding="utf-8"
    )
    return topic_dir


@pytest.fixture
def fixture_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> DistillConfig:
    cfg = DistillConfig(xai_api_key="test", distill_output_dir=tmp_path / "library")
    monkeypatch.setattr("distill.commands._logic.get_config", lambda: cfg)
    return cfg


def test_help() -> None:
    result = runner.invoke(cli.app, ["claude-md", "--help"])
    assert result.exit_code == 0
    assert "orientation" in result.output.lower()


def test_single_topic_writes_file(fixture_config: DistillConfig) -> None:
    topic_dir = _seed_topic(fixture_config.library_dir)
    result = runner.invoke(cli.app, ["claude-md", "tkg"])
    assert result.exit_code == 0
    assert (topic_dir / "CLAUDE.md").exists()
    assert (fixture_config.library_dir / "CLAUDE.md").exists()


def test_no_topic_and_no_all_errors(fixture_config: DistillConfig) -> None:
    result = runner.invoke(cli.app, ["claude-md"])
    assert result.exit_code == 1


def test_missing_topic_dir_errors(fixture_config: DistillConfig) -> None:
    result = runner.invoke(cli.app, ["claude-md", "ghost"])
    assert result.exit_code == 1
    assert "does not exist" in result.output.lower()


def test_all_regenerates_every_topic(fixture_config: DistillConfig) -> None:
    _seed_topic(fixture_config.library_dir, "tkg")
    _seed_topic(fixture_config.library_dir, "rag")
    result = runner.invoke(cli.app, ["claude-md", "--all"])
    assert result.exit_code == 0
    assert "2 topic" in result.output
    assert (fixture_config.library_dir / "topics" / "tkg" / "CLAUDE.md").exists()
    assert (fixture_config.library_dir / "topics" / "rag" / "CLAUDE.md").exists()
    assert (fixture_config.library_dir / "CLAUDE.md").exists()

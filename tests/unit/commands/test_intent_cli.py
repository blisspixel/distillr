"""Tests for the `distill intent` command group and --lens persistence."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from distill import _cli_impl, cli
from distill.config import DistillConfig
from distill.library.intent import load_intent

runner = CliRunner()


@pytest.fixture
def mock_config(tmp_path):
    config = DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "library")
    orig, orig_impl = cli.get_config, _cli_impl.get_config
    cli.get_config = lambda: config
    _cli_impl.get_config = lambda: config
    yield config
    cli.get_config, _cli_impl.get_config = orig, orig_impl


def test_intent_set_creates_intent(mock_config):
    result = runner.invoke(cli.app, ["intent", "set", "mytopic", "--lens", "research"])
    assert result.exit_code == 0
    intent = load_intent(mock_config.topic_dir("mytopic"))
    assert intent is not None
    assert intent.lens == "research"


def test_intent_set_infers_lens_from_goal(mock_config):
    result = runner.invoke(
        cli.app, ["intent", "set", "t", "--goal", "vendor pricing and enterprise positioning"]
    )
    assert result.exit_code == 0
    assert load_intent(mock_config.topic_dir("t")).lens == "competitive"


def test_intent_set_merges_preserving_goal(mock_config):
    runner.invoke(
        cli.app, ["intent", "set", "t", "--goal", "study prior art", "--lens", "research"]
    )
    # Update only the lens; the goal must survive.
    runner.invoke(cli.app, ["intent", "set", "t", "--lens", "academic"])
    intent = load_intent(mock_config.topic_dir("t"))
    assert intent.lens == "academic"
    assert intent.goal == "study prior art"


def test_intent_show_reports_lens(mock_config):
    runner.invoke(cli.app, ["intent", "set", "t", "--lens", "practitioner"])
    result = runner.invoke(cli.app, ["intent", "show", "t"])
    assert result.exit_code == 0
    assert "practitioner" in result.output


def test_intent_show_missing_is_graceful(mock_config):
    result = runner.invoke(cli.app, ["intent", "show", "nope"])
    assert result.exit_code == 0
    assert "general" in result.output.lower()


def test_intent_clear_removes(mock_config):
    runner.invoke(cli.app, ["intent", "set", "t", "--lens", "research"])
    result = runner.invoke(cli.app, ["intent", "clear", "t"])
    assert result.exit_code == 0
    assert load_intent(mock_config.topic_dir("t")) is None


def test_persist_lens_preserves_existing_goal(mock_config):
    # The helper papers/latest use: --lens must not clobber a discover-set goal.
    from distill.commands._logic import _persist_lens
    from distill.library.intent import make_intent, save_intent

    save_intent(mock_config.topic_dir("t"), make_intent("deep research goal", lens="research"))
    _persist_lens(mock_config, "t", "fallback query", "practitioner")
    intent = load_intent(mock_config.topic_dir("t"))
    assert intent.lens == "practitioner"
    assert intent.goal == "deep research goal"

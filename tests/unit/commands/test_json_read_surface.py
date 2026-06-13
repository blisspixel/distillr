"""--json coverage on the read surface (library, videos, synthesis, findings, show).

The June 2026 CLI audit's P0: an agent looping these commands with --json must
get a structured envelope on stdout (never silent), stdout must stay pure JSON
even while diagnostics go to stderr, and --json must be read-only (no spend).
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from distill import _cli_impl, cli
from distill.config import DistillConfig

runner = CliRunner()


@pytest.fixture
def mock_config(tmp_path, monkeypatch):
    config = DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "library")
    monkeypatch.setattr(_cli_impl, "get_config", lambda: config)
    # `library` moved to commands/view.py (decomposition); it resolves get_config
    # from its own module namespace, so patch there too.
    monkeypatch.setattr("distill.commands.view.get_config", lambda: config)
    return config


def _envelope(result):
    """Parse the JSON envelope from stdout, asserting stdout is pure JSON."""
    assert result.exit_code == 0, result.stdout
    return json.loads(result.stdout)


def test_library_json_empty(mock_config):
    env = _envelope(runner.invoke(cli.app, ["--json", "library"]))
    assert env["status"] == "ok"
    assert env["data"] == {"topics": [], "count": 0}


def test_library_json_lists_topics(mock_config):
    # Register a topic (get_topics reads library.json, not the filesystem).
    from distill.library import Library

    lib = Library(mock_config)
    lib.add_channel("memory", "https://www.youtube.com/@Example", "Example")
    topic_dir = mock_config.topic_dir("memory")
    topic_dir.mkdir(parents=True, exist_ok=True)
    (topic_dir / "memory_Topic_Synthesis.md").write_text("syn", encoding="utf-8")

    env = _envelope(runner.invoke(cli.app, ["--json", "library"]))
    topics = {t["topic"]: t for t in env["data"]["topics"]}
    assert "memory" in topics
    assert "topic_synthesis" in topics["memory"]["topic_artifacts"]


def test_synthesis_json_is_read_only_when_missing(mock_config, monkeypatch):
    # If --json triggered generation it would spend; assert it never calls synth.
    called = {"gen": False}
    monkeypatch.setattr(
        _cli_impl, "synthesize_topic", lambda *a, **k: called.__setitem__("gen", True)
    )
    mock_config.topic_dir("memory").mkdir(parents=True)

    env = _envelope(runner.invoke(cli.app, ["--json", "synthesis", "memory"]))
    assert env["status"] == "ok"
    assert env["data"]["found"] is False
    assert env["data"]["content"] is None
    assert called["gen"] is False


def test_synthesis_json_returns_content(mock_config):
    topic_dir = mock_config.topic_dir("memory")
    topic_dir.mkdir(parents=True)
    (topic_dir / "memory_Topic_Synthesis.md").write_text("# Synthesis body", encoding="utf-8")

    env = _envelope(runner.invoke(cli.app, ["--json", "synthesis", "memory"]))
    assert env["data"]["found"] is True
    assert "Synthesis body" in env["data"]["content"]


def test_findings_json_when_missing(mock_config):
    mock_config.topic_dir("memory").mkdir(parents=True)
    env = _envelope(runner.invoke(cli.app, ["--json", "findings", "memory"]))
    assert env["data"]["found"] is False


def test_json_stdout_is_pure_even_with_diagnostics(mock_config):
    """Under --json, stdout is parseable JSON and nothing else; any human/
    diagnostic output is on stderr (console redirected), not stdout."""
    result = runner.invoke(cli.app, ["--json", "library"])
    # The whole of stdout parses as one JSON document -- no leading/trailing chrome.
    json.loads(result.stdout)


def test_human_mode_unaffected(mock_config):
    # Non-JSON library prints human chrome to stdout (console back on stdout).
    result = runner.invoke(cli.app, ["library"])
    assert result.exit_code == 0
    # Not JSON; the empty-library panel text is present.
    assert "Library" in result.stdout

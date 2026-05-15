"""CLI tests for `distill concepts <topic>`."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from distill import cli
from distill.config import DistillConfig

runner = CliRunner()


def _seed_topic(library_dir: Path, topic: str = "tkg") -> Path:
    topic_dir = library_dir / "topics" / topic
    for slug, sid in (("a", "A"), ("b", "B"), ("c", "C")):
        d = topic_dir / "papers" / slug
        d.mkdir(parents=True)
        (d / f"{slug}_Insights.md").write_text(
            f"---\npaper_id: {sid}\n---\n# {slug}\nbody\n", encoding="utf-8"
        )
    return topic_dir


@pytest.fixture
def fixture_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> DistillConfig:
    cfg = DistillConfig(xai_api_key="test", distill_output_dir=tmp_path / "library")
    monkeypatch.setattr("distill.commands._logic.get_config", lambda: cfg)
    return cfg


class _StubResponse:
    def __init__(self, payload: list) -> None:
        self.text = json.dumps(payload)
        self.model = "stub-model"
        self.input_tokens = 10
        self.output_tokens = 5


def _stub_llm(rows: list[list]):
    queue = list(rows)

    def _side(*_args, **_kwargs):
        return _StubResponse(queue.pop(0) if queue else [])

    return _side


class TestConceptsCommand:
    def test_help_describes_purpose(self) -> None:
        result = runner.invoke(cli.app, ["concepts", "--help"])
        assert result.exit_code == 0
        assert "playbook" in result.output.lower()

    def test_rejects_missing_topic_dir(self, fixture_config: DistillConfig) -> None:
        result = runner.invoke(cli.app, ["concepts", "ghost-topic"])
        assert result.exit_code == 1
        assert "does not exist" in result.output.lower()

    def test_runs_end_to_end(self, fixture_config: DistillConfig) -> None:
        _seed_topic(fixture_config.library_dir)
        rows = [
            [{"name": "X", "normalized_name": "x", "kind": "technique", "polarity": "helpful"}],
            [{"name": "X", "normalized_name": "x", "kind": "technique", "polarity": "helpful"}],
            [{"name": "X", "normalized_name": "x", "kind": "technique", "polarity": "helpful"}],
        ]
        with patch("distill.concepts.extract.llm_call", side_effect=_stub_llm(rows)):
            result = runner.invoke(cli.app, ["concepts", "tkg", "--threshold", "3"])
        assert result.exit_code == 0
        assert "Concept playbook" in result.output
        assert "Insights scanned:" in result.output
        # Verify the on-disk artifacts
        topic_dir = fixture_config.topic_dir("tkg")
        assert (topic_dir / "concepts" / "x.md").exists()
        assert (topic_dir / "concepts.jsonl").exists()

    def test_json_output(self, fixture_config: DistillConfig) -> None:
        _seed_topic(fixture_config.library_dir)
        rows = [
            [{"name": "X", "normalized_name": "x", "kind": "technique", "polarity": "helpful"}]
        ] * 3
        with patch("distill.concepts.extract.llm_call", side_effect=_stub_llm(rows)):
            result = runner.invoke(cli.app, ["concepts", "tkg", "--threshold", "3", "--json"])
        assert result.exit_code == 0
        json_blob = result.output[result.output.index("{") :]
        assert "topic" in json_blob
        assert "insights_scanned" in json_blob
        assert "success" in json_blob or "data" in json_blob

    def test_refresh_re_extracts(self, fixture_config: DistillConfig) -> None:
        _seed_topic(fixture_config.library_dir)
        rows = [
            [{"name": "X", "normalized_name": "x", "kind": "technique", "polarity": "helpful"}]
        ] * 3
        with patch("distill.concepts.extract.llm_call", side_effect=_stub_llm(rows)) as mock_llm:
            runner.invoke(cli.app, ["concepts", "tkg", "--threshold", "3"])
        assert mock_llm.call_count == 3

        rows_2 = [
            [{"name": "X", "normalized_name": "x", "kind": "technique", "polarity": "helpful"}]
        ] * 3
        with patch("distill.concepts.extract.llm_call", side_effect=_stub_llm(rows_2)) as mock_llm:
            runner.invoke(cli.app, ["concepts", "tkg", "--threshold", "3", "--refresh"])
        assert mock_llm.call_count == 3  # refresh re-extracts all

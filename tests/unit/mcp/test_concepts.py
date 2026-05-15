"""MCP tool tests for find_concepts, read_concept, list_contested."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from distill.config import DistillConfig
from distill.mcp.tools.concepts import find_concepts, list_contested, read_concept


@pytest.fixture
def mock_config(tmp_path: Path) -> DistillConfig:
    config = DistillConfig(xai_api_key="t", distill_output_dir=tmp_path / "library")
    config.library_dir.mkdir(parents=True, exist_ok=True)
    return config


def _seed_topic(config: DistillConfig, topic: str = "tkg") -> Path:
    topic_dir = config.topic_dir(topic)
    topic_dir.mkdir(parents=True)
    (topic_dir / "concepts.jsonl").write_text(
        "\n".join(
            json.dumps(r)
            for r in [
                {
                    "name": "Rotational Embeddings",
                    "slug": "rotational_embedding",
                    "kind": "technique",
                    "topic": "tkg",
                    "source_count": 5,
                    "helpful_count": 5,
                    "harmful_count": 0,
                    "contested": False,
                },
                {
                    "name": "Disputed Method",
                    "slug": "disputed_method",
                    "kind": "technique",
                    "topic": "tkg",
                    "source_count": 4,
                    "helpful_count": 2,
                    "harmful_count": 2,
                    "contested": True,
                },
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (topic_dir / "entities.jsonl").write_text(
        json.dumps(
            {
                "name": "OpenAI",
                "slug": "openai",
                "kind": "vendor",
                "topic": "tkg",
                "source_count": 3,
                "helpful_count": 3,
                "harmful_count": 0,
                "contested": False,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    # Also write actual concept .md files for read_concept
    (topic_dir / "concepts").mkdir()
    (topic_dir / "concepts" / "rotational_embedding.md").write_text(
        "---\ntype: concept\n---\n\n# Rotational Embeddings\n\nbody\n", encoding="utf-8"
    )
    (topic_dir / "concepts" / "disputed_method.md").write_text(
        "---\ntype: concept\n---\n\n# Disputed\nbody\n", encoding="utf-8"
    )
    (topic_dir / "entities").mkdir()
    (topic_dir / "entities" / "openai.md").write_text(
        "---\ntype: entity\n---\n\n# OpenAI\nbody\n", encoding="utf-8"
    )
    return topic_dir


class TestFindConcepts:
    def test_missing_topic_returns_error(self, mock_config: DistillConfig) -> None:
        with patch("distill.mcp.server._config", return_value=mock_config):
            result = json.loads(find_concepts("ghost"))
        assert result["status"] == "error"

    def test_returns_all_when_no_filters(self, mock_config: DistillConfig) -> None:
        _seed_topic(mock_config)
        with patch("distill.mcp.server._config", return_value=mock_config):
            result = json.loads(find_concepts("tkg"))
        assert result["count"] == 3
        # Sorted by source_count desc
        assert result["results"][0]["name"] == "Rotational Embeddings"

    def test_contested_only_filter(self, mock_config: DistillConfig) -> None:
        _seed_topic(mock_config)
        with patch("distill.mcp.server._config", return_value=mock_config):
            result = json.loads(find_concepts("tkg", contested_only=True))
        assert result["count"] == 1
        assert result["results"][0]["name"] == "Disputed Method"

    def test_query_substring_match(self, mock_config: DistillConfig) -> None:
        _seed_topic(mock_config)
        with patch("distill.mcp.server._config", return_value=mock_config):
            result = json.loads(find_concepts("tkg", query="rotation"))
        assert result["count"] == 1
        assert result["results"][0]["name"] == "Rotational Embeddings"

    def test_kind_filter(self, mock_config: DistillConfig) -> None:
        _seed_topic(mock_config)
        with patch("distill.mcp.server._config", return_value=mock_config):
            result = json.loads(find_concepts("tkg", kind="vendor"))
        assert result["count"] == 1
        assert result["results"][0]["name"] == "OpenAI"

    def test_path_uses_entities_dir_for_entities(self, mock_config: DistillConfig) -> None:
        _seed_topic(mock_config)
        with patch("distill.mcp.server._config", return_value=mock_config):
            result = json.loads(find_concepts("tkg", kind="vendor"))
        assert "entities/openai.md" in result["results"][0]["path"]

    def test_limit_applied(self, mock_config: DistillConfig) -> None:
        _seed_topic(mock_config)
        with patch("distill.mcp.server._config", return_value=mock_config):
            result = json.loads(find_concepts("tkg", limit=1))
        assert result["count"] == 1


class TestReadConcept:
    def test_reads_concept_strips_frontmatter(self, mock_config: DistillConfig) -> None:
        _seed_topic(mock_config)
        with patch("distill.mcp.server._config", return_value=mock_config):
            result = json.loads(read_concept("topics/tkg/concepts/rotational_embedding.md"))
        assert "type: concept" not in result["content"]  # frontmatter stripped
        assert "Rotational Embeddings" in result["content"]

    def test_absolute_path_rejected(self, mock_config: DistillConfig) -> None:
        with patch("distill.mcp.server._config", return_value=mock_config):
            result = json.loads(read_concept("/etc/passwd"))
        assert result["status"] == "error"

    def test_non_concept_path_rejected(self, mock_config: DistillConfig) -> None:
        topic_dir = _seed_topic(mock_config)
        rogue = topic_dir / "rogue.md"
        rogue.write_text("body", encoding="utf-8")
        with patch("distill.mcp.server._config", return_value=mock_config):
            result = json.loads(read_concept("topics/tkg/rogue.md"))
        assert result["status"] == "error"
        assert "concept" in result["error"].lower()

    def test_missing_file_error(self, mock_config: DistillConfig) -> None:
        with patch("distill.mcp.server._config", return_value=mock_config):
            result = json.loads(read_concept("topics/ghost/concepts/x.md"))
        assert result["status"] == "error"


class TestListContested:
    def test_missing_topic_error(self, mock_config: DistillConfig) -> None:
        with patch("distill.mcp.server._config", return_value=mock_config):
            result = json.loads(list_contested("ghost"))
        assert result["status"] == "error"

    def test_returns_contested_only(self, mock_config: DistillConfig) -> None:
        _seed_topic(mock_config)
        with patch("distill.mcp.server._config", return_value=mock_config):
            result = json.loads(list_contested("tkg"))
        assert result["count"] == 1
        assert result["contested"][0]["name"] == "Disputed Method"

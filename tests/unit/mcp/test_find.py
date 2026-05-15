"""Property-based and unit tests for distill/mcp/tools/find.py."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from distill.config import DistillConfig


@pytest.fixture
def mock_config(tmp_path):
    """Create a test DistillConfig with a populated corpus."""
    config = DistillConfig(
        xai_api_key="test",
        distill_output_dir=tmp_path / "library",
    )
    # Create a topic with artifacts
    topic_dir = config.topic_dir("ai")
    topic_dir.mkdir(parents=True, exist_ok=True)

    # Create an insight file
    vid_dir = topic_dir / "channels" / "ch1" / "videos" / "v1"
    vid_dir.mkdir(parents=True, exist_ok=True)
    (vid_dir / "insights.md").write_text(
        "---\ntitle: Test Video\n---\n\n# Key Findings\n\nMachine learning is transforming AI.\n\n## Details\n\nMore info here.",
        encoding="utf-8",
    )

    # Create a synthesis
    (topic_dir / "synthesis.md").write_text(
        "---\ntitle: AI Synthesis\n---\n\n# Overview\n\nAI synthesis content.",
        encoding="utf-8",
    )
    return config


# ── Property 5: read_insight round-trip preserves body content ──
# Feature: mcp-first-surface, Property 5: read_insight round-trip preserves body content
# **Validates: Requirements 2.1, 2.5**


@settings(
    max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None
)
@given(
    body=st.text(
        alphabet=st.characters(whitelist_categories=("L", "N", "Z", "P")),
        min_size=1,
        max_size=200,
    ).filter(lambda t: t.strip() and "---" not in t),
)
def test_read_insight_round_trip_preserves_body(tmp_path, body):
    """Property 5: read_insight round-trip preserves body content."""
    config = DistillConfig(
        xai_api_key="test",
        distill_output_dir=tmp_path / "library",
    )
    # Write a file with frontmatter + body
    topic_dir = config.topic_dir("rt")
    topic_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = topic_dir / "test_artifact.md"
    content = f"---\ntitle: test\ntype: insights\n---\n\n{body}"
    artifact_path.write_text(content, encoding="utf-8")

    rel_path = str(artifact_path.relative_to(config.library_dir))

    with patch("distill.mcp.server._config", return_value=config):
        from distill.mcp.tools.find import read_insight

        result = json.loads(read_insight(rel_path))

    assert "content" in result
    # Body should be preserved (stripped of frontmatter)
    assert body.strip() in result["content"] or result["content"].strip() == body.strip()


# ── Unit tests ──


class TestFindInsights:
    def test_topic_not_found(self, mock_config):
        with patch("distill.mcp.server._config", return_value=mock_config):
            from distill.mcp.tools.find import find_insights

            result = json.loads(find_insights("nonexistent", "test"))
        assert result["status"] == "error"
        assert "not found" in result["error"]
        assert "ai" in result["error"]  # lists available topics

    def test_empty_results(self, mock_config):
        with patch("distill.mcp.server._config", return_value=mock_config):
            from distill.mcp.tools.find import find_insights

            result = json.loads(find_insights("ai", "xyzzyplugh"))
        assert result["count"] == 0
        assert "No results" in result.get("message", "")

    def test_successful_search(self, mock_config):
        with patch("distill.mcp.server._config", return_value=mock_config):
            from distill.mcp.tools.find import find_insights

            result = json.loads(find_insights("ai", "machine learning"))
        assert result["count"] > 0
        assert result["topic"] == "ai"
        assert all("path" in r and "preview" in r and "score" in r for r in result["results"])


class TestReadInsight:
    def test_path_not_found(self, mock_config):
        with patch("distill.mcp.server._config", return_value=mock_config):
            from distill.mcp.tools.find import read_insight

            result = json.loads(read_insight("nonexistent/path.md"))
        assert result["status"] == "error"
        assert "not found" in result["error"].lower()

    def test_rejects_absolute_path(self, mock_config, tmp_path):
        outside = tmp_path / "secret.txt"
        outside.write_text("XAI_API_KEY=secret", encoding="utf-8")

        with patch("distill.mcp.server._config", return_value=mock_config):
            from distill.mcp.tools.find import read_insight

            result = json.loads(read_insight(str(outside)))

        assert result["status"] == "error"
        assert "relative path inside the library root" in result["error"]
        assert "secret" not in json.dumps(result)

    def test_rejects_relative_traversal(self, mock_config):
        outside = mock_config.library_dir.parent / ".env"
        outside.write_text("XAI_API_KEY=secret", encoding="utf-8")

        with patch("distill.mcp.server._config", return_value=mock_config):
            from distill.mcp.tools.find import read_insight

            result = json.loads(read_insight("../.env"))

        assert result["status"] == "error"
        assert "relative path inside the library root" in result["error"]
        assert "secret" not in json.dumps(result)

    def test_rejects_windows_rooted_path(self, mock_config):
        with patch("distill.mcp.server._config", return_value=mock_config):
            from distill.mcp.tools.find import read_insight

            result = json.loads(read_insight(r"\Users\nicks\.env"))

        assert result["status"] == "error"
        assert "relative path inside the library root" in result["error"]

    def test_read_full_content(self, mock_config):
        # Get relative path to the insight file
        topic_dir = mock_config.topic_dir("ai")
        insight_path = topic_dir / "channels" / "ch1" / "videos" / "v1" / "insights.md"
        rel_path = str(insight_path.relative_to(mock_config.library_dir))

        with patch("distill.mcp.server._config", return_value=mock_config):
            from distill.mcp.tools.find import read_insight

            result = json.loads(read_insight(rel_path))
        assert "content" in result
        assert "Machine learning" in result["content"]
        # Frontmatter should be stripped
        assert "---" not in result["content"]

    def test_section_found(self, mock_config):
        topic_dir = mock_config.topic_dir("ai")
        insight_path = topic_dir / "channels" / "ch1" / "videos" / "v1" / "insights.md"
        rel_path = str(insight_path.relative_to(mock_config.library_dir))

        with patch("distill.mcp.server._config", return_value=mock_config):
            from distill.mcp.tools.find import read_insight

            result = json.loads(read_insight(rel_path, section="Key Findings"))
        assert result["section_found"] is True
        assert "Machine learning" in result["content"]

    def test_section_not_found_returns_full_with_warning(self, mock_config):
        topic_dir = mock_config.topic_dir("ai")
        insight_path = topic_dir / "channels" / "ch1" / "videos" / "v1" / "insights.md"
        rel_path = str(insight_path.relative_to(mock_config.library_dir))

        with patch("distill.mcp.server._config", return_value=mock_config):
            from distill.mcp.tools.find import read_insight

            result = json.loads(read_insight(rel_path, section="Nonexistent"))
        assert result["section_found"] is False
        assert "warning" in result
        assert "content" in result

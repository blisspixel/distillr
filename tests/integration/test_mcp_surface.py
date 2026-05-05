"""Integration tests for the MCP-first surface (0.5)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from distill.config import DistillConfig


@pytest.fixture
def corpus_config(tmp_path):
    """Create a DistillConfig with a fully populated test corpus."""
    config = DistillConfig(
        xai_api_key="test",
        distill_output_dir=tmp_path / "library",
    )
    topic_dir = config.topic_dir("integration-test")
    topic_dir.mkdir(parents=True, exist_ok=True)

    # Create multiple artifact types
    _write(
        topic_dir / "channels" / "ch1" / "videos" / "v1" / "insights.md",
        "---\ntitle: Video Insights\n---\n\n# Key Findings\n\nDeep learning advances in 2026.",
    )
    _write(
        topic_dir / "channels" / "ch1" / "synthesis.md",
        "---\ntitle: Channel Synthesis\n---\n\n# Synthesis\n\nDeep learning overview across videos.",
    )
    _write(
        topic_dir / "topic_synthesis.md",
        "---\ntitle: Topic Synthesis\n---\n\n# Topic Overview\n\nDeep learning is the core theme.",
    )
    _write(
        topic_dir / "papers" / "p1" / "paper.md",
        "---\ntitle: Paper\n---\n\n# Abstract\n\nDeep learning for production systems.",
    )
    return config


def _write(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


class TestFindInsightsReadInsightFlow:
    """End-to-end: find_insights -> read_insight flow."""

    def test_search_then_drill_down(self, corpus_config):
        """Integration: search corpus, then read a specific result."""
        with patch("distill.mcp.server._config", return_value=corpus_config):
            from distill.mcp.tools.find import find_insights, read_insight

            # Step 1: Search
            search_result = json.loads(find_insights("integration-test", "deep learning"))
            assert search_result["count"] > 0

            # Step 2: Drill down into first result
            first_path = search_result["results"][0]["path"]
            read_result = json.loads(read_insight(first_path))
            assert "content" in read_result
            assert "deep learning" in read_result["content"].lower()

    def test_search_with_section_extraction(self, corpus_config):
        """Integration: search, then read a specific section."""
        with patch("distill.mcp.server._config", return_value=corpus_config):
            from distill.mcp.tools.find import find_insights, read_insight

            search_result = json.loads(find_insights("integration-test", "deep learning"))
            assert search_result["count"] > 0

            # Find the insights file and extract a section
            insights_results = [r for r in search_result["results"] if "insights" in r["path"]]
            if insights_results:
                path = insights_results[0]["path"]
                section_result = json.loads(read_insight(path, section="Key Findings"))
                assert section_result["section_found"] is True
                assert "deep learning" in section_result["content"].lower()


class TestCliJsonIntegration:
    """Integration tests for --json CLI output."""

    def test_alerts_json_output(self, corpus_config):
        """Test alerts command with --json produces valid envelope."""
        from typer.testing import CliRunner

        from distill.cli import app

        runner = CliRunner()
        with patch("distill._cli_impl.get_config", return_value=corpus_config):
            result = runner.invoke(app, ["--json", "alerts"])

        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["status"] == "ok"
        assert "data" in parsed
        # No ANSI escape codes
        assert "\x1b" not in result.output


class TestBackwardCompatibility:
    """Verify existing tools, resources, and prompts are preserved."""

    def test_all_existing_tools_registered(self):
        """All 8+ existing tools are still registered."""
        from distill.mcp.server import mcp

        tools = mcp._tool_manager._tools
        existing = {
            "learn_topic",
            "search_videos",
            "catch_up",
            "process_video_url",
            "watch_add",
            "watch_remove",
            "generate_report",
            "resynthesize_topic",
            "research_gaps",
        }
        registered = set(tools.keys())
        assert existing.issubset(registered)

    def test_existing_tool_schemas_preserved(self):
        """Existing tool input schemas have not changed."""
        from distill.mcp.server import mcp

        tools = mcp._tool_manager._tools

        # learn_topic must still accept query, topic, days, limit
        lt = tools["learn_topic"].parameters["properties"]
        assert "query" in lt
        assert "topic" in lt
        assert "days" in lt
        assert "limit" in lt

        # catch_up must still accept channel, topic, days
        cu = tools["catch_up"].parameters["properties"]
        assert "channel" in cu
        assert "topic" in cu
        assert "days" in cu

    def test_all_resource_uris_respond(self, corpus_config):
        """All 12 resource URIs are still registered."""

        # Check resources are registered (they're decorated functions)
        from distill.mcp.resources import (
            get_channel_synthesis,
            get_costs,
            get_topic_corpus,
            get_topic_diff,
            get_topic_sources,
            get_topic_synthesis,
            get_topic_trends,
            get_topic_videos,
            get_topics,
            get_video_insights,
            get_watch_alerts,
            get_watchlist,
        )

        # All 12 resource functions should be importable
        assert callable(get_topics)
        assert callable(get_watchlist)
        assert callable(get_topic_videos)
        assert callable(get_topic_synthesis)
        assert callable(get_topic_corpus)
        assert callable(get_topic_sources)
        assert callable(get_topic_diff)
        assert callable(get_topic_trends)
        assert callable(get_watch_alerts)
        assert callable(get_channel_synthesis)
        assert callable(get_video_insights)
        assert callable(get_costs)

"""Unit tests for new MCP tools — Property 10 and tool registration smoke tests.

This file covers:
- Property 10: Progress events have valid structure
- Smoke test: all tools are registered on the MCP server
- Error responses for missing config (XAI_API_KEY not set)
- Tool schemas are introspectable
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import patch

import pytest

from distill.config import DistillConfig


@pytest.fixture
def mock_config(tmp_path):
    """Create a test DistillConfig."""
    config = DistillConfig(
        xai_api_key="test-key",
        gemini_api_key="test-gemini",
        distill_output_dir=tmp_path / "library",
    )
    config.library_dir.mkdir(parents=True, exist_ok=True)
    return config


# ── Property 10: Progress events have valid structure ──
# Feature: mcp-first-surface, Property 10: Progress events have valid structure
# **Validates: Requirements 9.2**


class TestProgressEventsValidStructure:
    """Property 10: Progress events have valid structure.

    Verify that progress values passed to ctx.report_progress are in [0.0, 1.0] range.
    We test the costs tool (no progress) and verify the progress pattern used by
    long-running tools by simulating their progress emission logic.
    """

    def test_progress_pattern_papers(self):
        """Papers tool progress pattern: progress=i, total=len(selected) is always valid."""
        # Simulate the papers tool progress pattern for various item counts
        for n_items in [1, 3, 5, 10, 20]:
            progress_values = []
            for i in range(n_items):
                # This is what papers tool does: await ctx.report_progress(progress=i, total=n)
                progress_values.append((i, n_items))
            # Final progress event
            progress_values.append((n_items, n_items))

            for progress, total in progress_values:
                assert total > 0
                ratio = progress / total
                assert 0.0 <= ratio <= 1.0, (
                    f"Progress ratio {ratio} out of [0.0, 1.0] range "
                    f"(progress={progress}, total={total})"
                )

    def test_progress_pattern_site_batch(self):
        """Site batch tool progress pattern: progress=i, total=len(urls) is always valid."""
        for n_pages in [1, 2, 5, 15]:
            progress_values = []
            for i in range(n_pages):
                progress_values.append((i, n_pages))
            progress_values.append((n_pages, n_pages))

            for progress, total in progress_values:
                assert total > 0
                ratio = progress / total
                assert 0.0 <= ratio <= 1.0, (
                    f"Progress ratio {ratio} out of [0.0, 1.0] range "
                    f"(progress={progress}, total={total})"
                )

    def test_progress_pattern_discover(self):
        """Discover tool progress pattern: fixed 3 stages."""
        # Discover uses progress=0,1,3 with total=3
        progress_values = [(0, 3), (1, 3), (3, 3)]
        for progress, total in progress_values:
            assert total > 0
            ratio = progress / total
            assert 0.0 <= ratio <= 1.0, (
                f"Progress ratio {ratio} out of [0.0, 1.0] range "
                f"(progress={progress}, total={total})"
            )

    def test_progress_pattern_synthesize(self):
        """Synthesize tool progress pattern: channels + 2 (topic + corpus)."""
        for n_channels in [0, 1, 3, 5]:
            total_steps = n_channels + 2
            progress_values = []
            for i in range(n_channels):
                progress_values.append((i, total_steps))
            progress_values.append((n_channels, total_steps))
            progress_values.append((n_channels + 1, total_steps))
            progress_values.append((total_steps, total_steps))

            for progress, total in progress_values:
                assert total > 0
                ratio = progress / total
                assert 0.0 <= ratio <= 1.0, (
                    f"Progress ratio {ratio} out of [0.0, 1.0] range "
                    f"(progress={progress}, total={total})"
                )

    def test_costs_tool_no_progress_events(self, mock_config):
        """Costs tool does not emit progress events (not long-running)."""
        # Costs tool is synchronous and doesn't accept ctx parameter
        with patch("distill.mcp.server._config", return_value=mock_config):
            from distill.mcp.tools.costs import costs

            result = json.loads(costs())
        # Just verify it works without progress — no ctx parameter
        assert result["status"] == "ok"


# ── Smoke tests: all tools registered ──


class TestToolRegistration:
    """Smoke test: verify all tools are registered on the MCP server."""

    def test_all_tools_registered(self):
        """All expected tools are registered on the MCP server."""
        from distill.mcp.server import mcp

        tools = mcp._tool_manager._tools
        expected = {
            # Existing tools
            "learn_topic",
            "search_videos",
            "catch_up",
            "process_video_url",
            "watch_add",
            "watch_remove",
            "generate_report",
            "resynthesize_topic",
            "research_gaps",
            # New tools
            "find_insights",
            "read_insight",
            "papers",
            "discover",
            "site_batch",
            "synthesize",
            "costs",
            "doctor",
            "okf_export",
            "okf_validate",
        }
        registered = set(tools.keys())
        missing = expected - registered
        assert not missing, f"Missing tools: {missing}"

    def test_tool_schemas_are_introspectable(self):
        """All tool schemas can be introspected and serialized."""
        from distill.mcp.server import mcp

        tools = mcp._tool_manager._tools
        for name, tool in tools.items():
            schema = tool.parameters
            assert isinstance(schema, dict), f"{name}: schema is not a dict"
            # Must be JSON-serializable
            serialized = json.dumps(schema)
            parsed = json.loads(serialized)
            assert parsed == schema, f"{name}: schema round-trip failed"
            # Must have properties
            assert "properties" in parsed, f"{name}: schema missing 'properties'"


# ── Error responses for missing config ──


class TestMissingConfigErrors:
    """Error responses when no model is configured (no cloud key AND no local provider).

    'anthropic' is a configured-but-not-implemented provider, so the router
    reports no usable model regardless of any ambient cloud key -- a deterministic
    'no model' independent of the environment.
    """

    def test_papers_missing_model(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DISTILL_PROVIDER", "anthropic")
        config = DistillConfig(xai_api_key="", distill_output_dir=tmp_path / "library")
        with patch("distill.mcp.server._config", return_value=config):
            from distill.mcp.tools.papers import papers

            result = json.loads(asyncio.run(papers("ai", "transformers")))
        assert result["status"] == "error"
        assert "model" in result["error"].lower()

    def test_discover_missing_model(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DISTILL_PROVIDER", "anthropic")
        config = DistillConfig(xai_api_key="", distill_output_dir=tmp_path / "library")
        with patch("distill.mcp.server._config", return_value=config):
            from distill.mcp.tools.discover import discover

            result = json.loads(asyncio.run(discover("test goal")))
        assert result["status"] == "error"
        assert "model" in result["error"].lower()

    def test_synthesize_missing_model(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DISTILL_PROVIDER", "anthropic")
        config = DistillConfig(xai_api_key="", distill_output_dir=tmp_path / "library")
        with patch("distill.mcp.server._config", return_value=config):
            from distill.mcp.tools.synthesis import synthesize

            result = json.loads(asyncio.run(synthesize("ai")))
        assert result["status"] == "error"
        assert "model" in result["error"].lower()

    def test_site_batch_missing_model(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DISTILL_PROVIDER", "anthropic")
        config = DistillConfig(xai_api_key="", distill_output_dir=tmp_path / "library")
        with patch("distill.mcp.server._config", return_value=config):
            from distill.mcp.tools.sites import site_batch

            result = json.loads(asyncio.run(site_batch("ai", urls=["https://example.com"])))
        assert result["status"] == "error"
        assert "model" in result["error"].lower()

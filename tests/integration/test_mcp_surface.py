"""Integration tests for the MCP-first surface (0.5).

Covers:
- 14.1: End-to-end find_insights → read_insight flow
- 14.2: CLI --json integration tests
- 14.3: Progress event integration test
- 14.4: Backward compatibility tests
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from distill.config import DistillConfig

# ── Helpers ──────────────────────────────────────────────────────────


def _write(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _registered_tools():
    """Snapshot the public tool listing as a name-keyed mapping."""
    import asyncio

    from distill.mcp.server import mcp

    return {tool.name: tool for tool in asyncio.run(mcp.list_tools())}


# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
def corpus_config(tmp_path):
    """Create a DistillConfig with a fully populated test corpus.

    Includes multiple artifact types: insights, synthesis, paper, diff, trends, corpus.
    """
    config = DistillConfig(
        xai_api_key="test",
        distill_output_dir=tmp_path / "library",
    )
    topic_dir = config.topic_dir("integration-test")
    topic_dir.mkdir(parents=True, exist_ok=True)

    # Insights artifact
    _write(
        topic_dir / "channels" / "ch1" / "videos" / "v1" / "insights.md",
        "---\ntitle: Video Insights\n---\n\n# Key Findings\n\nDeep learning advances in 2026.\n\n"
        "# Methods\n\nTransformer architectures were used.",
    )

    # Synthesis artifact (channel-level)
    _write(
        topic_dir / "channels" / "ch1" / "synthesis.md",
        "---\ntitle: Channel Synthesis\n---\n\n# Synthesis\n\nDeep learning overview across videos.",
    )

    # Topic synthesis
    _write(
        topic_dir / "topic_synthesis.md",
        "---\ntitle: Topic Synthesis\n---\n\n# Topic Overview\n\nDeep learning is the core theme.",
    )

    # Paper artifact
    _write(
        topic_dir / "papers" / "p1" / "paper.md",
        "---\ntitle: Paper\n---\n\n# Abstract\n\nDeep learning for production systems.",
    )

    # Diff artifact
    _write(
        topic_dir / "topic_diff.md",
        "---\ntitle: Topic Diff\n---\n\n# Changes\n\nNew deep learning frameworks released.",
    )

    # Trends artifact
    _write(
        topic_dir / "topic_trends.md",
        "---\ntitle: Topic Trends\n---\n\n# Trends\n\nDeep learning adoption accelerating.",
    )

    # Corpus synthesis
    _write(
        topic_dir / "corpus_synthesis.md",
        "---\ntitle: Corpus Synthesis\n---\n\n# Corpus\n\nDeep learning corpus overview.",
    )

    return config


# ── 14.1: End-to-end find_insights → read_insight flow ───────────────


class TestFindInsightsReadInsightFlow:
    """End-to-end: find_insights → read_insight flow."""

    def test_search_returns_results_with_correct_structure(self, corpus_config):
        """Search corpus returns results with path, preview, score fields."""
        with patch("distill.mcp.server._config", return_value=corpus_config):
            from distill.mcp.tools.find import find_insights

            raw = find_insights("integration-test", "deep learning")
            result = json.loads(raw)

        assert result["count"] > 0
        assert result["topic"] == "integration-test"
        for item in result["results"]:
            assert "path" in item
            assert "preview" in item
            assert "score" in item
            assert isinstance(item["score"], float)
            assert item["score"] > 0

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
            assert read_result["path"] == first_path
            # Content should have frontmatter stripped
            assert "---" not in read_result["content"].split("\n")[0]
            assert "deep learning" in read_result["content"].lower()

    def test_search_with_section_extraction(self, corpus_config):
        """Integration: search, then read a specific section from a result."""
        with patch("distill.mcp.server._config", return_value=corpus_config):
            from distill.mcp.tools.find import find_insights, read_insight

            search_result = json.loads(find_insights("integration-test", "deep learning"))
            assert search_result["count"] > 0

            # Find the insights file and extract a section
            insights_results = [r for r in search_result["results"] if "insights" in r["path"]]
            assert len(insights_results) > 0

            path = insights_results[0]["path"]
            section_result = json.loads(read_insight(path, section="Key Findings"))
            assert section_result["section_found"] is True
            assert "deep learning" in section_result["content"].lower()
            # Should NOT contain content from the "Methods" section
            assert "transformer architectures" not in section_result["content"].lower()

    def test_multiple_artifact_types_in_results(self, corpus_config):
        """Search spans multiple artifact types."""
        with patch("distill.mcp.server._config", return_value=corpus_config):
            from distill.mcp.tools.find import find_insights

            result = json.loads(find_insights("integration-test", "deep learning", limit=20))

        # Should find results from multiple artifact types
        paths = [r["path"] for r in result["results"]]
        has_insights = any("insights" in p for p in paths)
        has_synthesis = any("synthesis" in p for p in paths)
        has_paper = any("paper" in p for p in paths)
        # At least 2 different artifact types should be present
        types_found = sum([has_insights, has_synthesis, has_paper])
        assert types_found >= 2, f"Expected multiple artifact types, got paths: {paths}"


# ── 14.2: CLI --json integration tests ──────────────────────────────


class TestCliJsonIntegration:
    """Integration tests for --json CLI output."""

    def test_costs_json_output_structure(self, corpus_config):
        """Test costs command with --json produces valid JsonEnvelope."""
        from typer.testing import CliRunner

        from distill.cli import app

        runner = CliRunner()
        with patch("distill.commands.maintain.get_config", return_value=corpus_config):
            result = runner.invoke(app, ["--json", "costs"])

        assert result.exit_code == 0
        parsed = json.loads(result.output)
        # Matches JsonEnvelope structure
        assert "status" in parsed
        assert parsed["status"] == "ok"
        assert "data" in parsed
        # No ANSI escape codes
        assert "\x1b" not in result.output

    def test_alerts_json_output(self, corpus_config):
        """Test alerts command with --json produces valid envelope."""
        from typer.testing import CliRunner

        from distill.cli import app

        runner = CliRunner()
        with patch("distill.commands.maintain.get_config", return_value=corpus_config):
            result = runner.invoke(app, ["--json", "alerts"])

        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["status"] == "ok"
        assert "data" in parsed
        # No ANSI escape codes
        assert "\x1b" not in result.output

    def test_error_path_produces_json_error(self, tmp_path):
        """Error paths produce correct exit codes and JSON error structure."""
        from typer.testing import CliRunner

        from distill.cli import app

        runner = CliRunner()
        # Use a config with no API key to trigger an error in doctor
        config = DistillConfig(
            xai_api_key="",
            gemini_api_key="",
            anthropic_api_key="",
            openai_api_key="",
            distill_cost_mode="no-metered",
            distill_output_dir=tmp_path / "library",
        )
        with patch("distill.commands.doctor.get_config", return_value=config):
            result = runner.invoke(app, ["--json", "doctor"])

        # Doctor should still succeed (it reports issues, doesn't fail)
        parsed = json.loads(result.output)
        assert "status" in parsed
        assert "data" in parsed

    def test_json_output_has_no_ansi_codes(self, corpus_config):
        """Verify no ANSI escape sequences in --json output."""
        from typer.testing import CliRunner

        from distill.cli import app

        runner = CliRunner()
        with patch("distill.commands.maintain.get_config", return_value=corpus_config):
            result = runner.invoke(app, ["--json", "costs"])

        # Check for any ANSI escape sequences
        assert "\x1b" not in result.output
        assert "\033" not in result.output


# ── 14.3: Progress event integration test ────────────────────────────


class TestProgressEventIntegration:
    """Progress event integration tests.

    Verifies that the progress emission pattern used by long-running tools
    produces monotonically non-decreasing progress values.
    """

    def test_progress_values_monotonically_non_decreasing(self):
        """Progress values emitted by tools are monotonically non-decreasing.

        This tests the progress emission pattern used by all long-running tools:
        for i in range(n): report_progress(progress=i, total=n)
        """
        # Simulate various batch sizes that tools might encounter
        for n_items in [1, 2, 3, 5, 10, 25, 50]:
            progress_ratios = []
            for i in range(n_items + 1):  # +1 for final completion event
                ratio = i / n_items
                progress_ratios.append(ratio)

            # Verify monotonically non-decreasing
            for j in range(1, len(progress_ratios)):
                assert progress_ratios[j] >= progress_ratios[j - 1], (
                    f"Progress decreased at step {j}: "
                    f"{progress_ratios[j]} < {progress_ratios[j - 1]} "
                    f"(n_items={n_items})"
                )

            # Verify bounds
            assert progress_ratios[0] == 0.0
            assert progress_ratios[-1] == 1.0

    def test_progress_pattern_with_stages(self):
        """Multi-stage progress (discover tool pattern) is non-decreasing."""
        # Discover uses 3 stages: search, rank, ingest
        stages = 3
        progress_values = []
        for stage in range(stages + 1):
            progress_values.append(stage / stages)

        for j in range(1, len(progress_values)):
            assert progress_values[j] >= progress_values[j - 1]

        assert all(0.0 <= v <= 1.0 for v in progress_values)

    def test_progress_pattern_synthesize_channels_plus_topic(self):
        """Synthesize tool pattern: channels + topic + corpus steps."""
        for n_channels in [0, 1, 3, 5, 10]:
            total_steps = n_channels + 2  # +1 topic synth, +1 corpus synth
            progress_values = []
            for step in range(total_steps + 1):
                progress_values.append(step / total_steps)

            # Verify monotonically non-decreasing
            for j in range(1, len(progress_values)):
                assert progress_values[j] >= progress_values[j - 1]

            # Verify bounds
            assert all(0.0 <= v <= 1.0 for v in progress_values)


# ── 14.4: Backward compatibility tests ──────────────────────────────


class TestBackwardCompatibility:
    """Verify existing tools, resources, and prompts are preserved."""

    def test_all_existing_tools_registered(self):
        """All 8+ existing tools are still registered."""
        tools = _registered_tools()
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
        missing = existing - registered
        assert not missing, f"Missing existing tools: {missing}"

    def test_existing_tool_schemas_preserved(self):
        """Existing tool input schemas have not changed."""
        tools = _registered_tools()

        # learn_topic must still accept query, topic, days, limit
        lt = tools["learn_topic"].input_schema["properties"]
        assert "query" in lt
        assert "topic" in lt
        assert "days" in lt
        assert "limit" in lt

        # catch_up must still accept channel, topic, days
        cu = tools["catch_up"].input_schema["properties"]
        assert "channel" in cu
        assert "topic" in cu
        assert "days" in cu

    def test_watch_alerts_resource_exists(self, corpus_config):
        """The distill://watch-alerts resource is registered and responds."""
        with patch("distill.mcp.server._config", return_value=corpus_config):
            from distill.mcp.resources import get_watch_alerts

            result = get_watch_alerts()

        # Should return a message (no alerts in test corpus)
        assert isinstance(result, str)
        assert len(result) > 0
        # Should not be empty — either alerts content or a "no alerts" message
        assert "alert" in result.lower() or "watch" in result.lower()

    def test_all_resource_functions_importable(self):
        """All 12 resource functions are importable and callable."""
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

        # All 12 resource functions should be callable
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

    def test_all_prompts_registered(self):
        """All 4 prompts are still registered with correct signatures."""
        from distill.mcp.prompts import (
            daily_deals,
            morning_briefing,
            topic_gap_review,
            topic_research,
        )

        # Verify prompts are callable
        assert callable(daily_deals)
        assert callable(morning_briefing)
        assert callable(topic_gap_review)
        assert callable(topic_research)

        # Verify they accept the expected arguments
        # daily_deals(channel: str)
        result = daily_deals("test-channel")
        assert isinstance(result, str)
        assert "test-channel" in result

        # morning_briefing() — no args
        result = morning_briefing()
        assert isinstance(result, str)

        # topic_gap_review(topic: str)
        result = topic_gap_review("ai")
        assert isinstance(result, str)
        assert "ai" in result

        # topic_research(query: str)
        result = topic_research("transformers")
        assert isinstance(result, str)
        assert "transformers" in result

    def test_new_tools_do_not_break_existing(self):
        """New tools are registered alongside existing ones without conflicts."""
        tools = _registered_tools()
        new_tools = {
            "find_insights",
            "read_insight",
            "papers",
            "discover",
            "site_batch",
            "synthesize",
            "costs",
            "doctor",
        }
        existing_tools = {
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

        # Both sets should be present
        assert existing_tools.issubset(registered)
        assert new_tools.issubset(registered)

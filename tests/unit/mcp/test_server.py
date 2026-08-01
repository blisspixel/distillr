"""Tests for distill MCP server."""

import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from distill.config import DistillConfig
from distill.library import Library
from distill.library.state import ChannelState
from distill.mcp.prompts import (
    daily_deals,
    morning_briefing,
    topic_gap_review,
    topic_research,
)
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
from distill.mcp.server import (
    DistillMCPServer,
    _config,
    _lib,
    _read_markdown_resource,
    _strip_frontmatter,
    _telemetry_tool_name,
    _topic_gap_summary,
    _topic_source_inventory,
    _video_list,
    agent_visible_path,
    load_config,
    main,
    refuse_if_host_not_allowed,
)
from distill.mcp.tools.discover import learn_topic, search_videos
from distill.mcp.tools.gaps import research_gaps
from distill.mcp.tools.reports import generate_report, resynthesize_topic
from distill.mcp.tools.topics import process_video_url
from distill.mcp.tools.watch import catch_up, watch_add, watch_remove
from distill.pipeline.costs import TokenUsage

# Stable mock return for _cost_summary so we don't hit CostTracker.total_calls bug
_FAKE_COST = {"total_cost": 0, "total_input_tokens": 0, "total_output_tokens": 0, "calls": 0}


def _recent(days_ago: int = 1) -> str:
    return (datetime.now() - timedelta(days=days_ago)).strftime("%Y%m%d")


@pytest.fixture
def mock_config(tmp_path):
    """Create a test DistillConfig pointing at a temp directory."""
    return DistillConfig(
        xai_api_key="test-xai-key",
        gemini_api_key="test-gemini-key",
        openai_api_key="test-openai-key",
        distill_output_dir=tmp_path / "library",
        distill_default_months=3,
    )


def _populate_videos(config, topic, channel, count=3):
    """Create fake video directories with metadata, transcripts, and insights."""
    from distill.library.state import ChannelState

    for i in range(count):
        vid_id = f"vid{i:03d}"
        vid_dir = config.video_dir(topic, channel, vid_id)
        vid_dir.mkdir(parents=True, exist_ok=True)
        meta = {
            "video_id": vid_id,
            "title": f"Test Video {i}",
            "upload_date": _recent(i + 1),
            "duration": 600 + i * 100,
            "url": f"https://www.youtube.com/watch?v={vid_id}",
        }
        (vid_dir / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")
        (vid_dir / "transcript.txt").write_text(f"Transcript {i}", encoding="utf-8")
        (vid_dir / "insights.md").write_text(
            f'---\nvideo_title: "Test {i}"\n---\n\n## Summary\nInsight {i}',
            encoding="utf-8",
        )

    state_file = config.channel_dir(topic, channel) / "state.json"
    state = ChannelState(state_file)
    for i in range(count):
        state.mark_processed(f"vid{i:03d}", f"Test Video {i}", _recent(i + 1))


def _setup_library(config, topic="ai", channel="TestChannel"):
    """Register a channel in the library and return the Library instance."""
    lib = Library(config)
    lib.add_channel(topic, f"https://www.youtube.com/@{channel}", channel)
    return lib


# ── Helper tests ─────────────────────────────────────────────────────


class TestStripFrontmatter:
    def test_with_frontmatter(self):
        content = '---\ntitle: "hello"\n---\n\nBody text here.'
        assert _strip_frontmatter(content) == "Body text here."

    def test_without_frontmatter(self):
        content = "Just plain content."
        assert _strip_frontmatter(content) == "Just plain content."

    def test_with_empty_frontmatter(self):
        content = "---\n---\n\nContent after empty frontmatter."
        assert _strip_frontmatter(content) == "Content after empty frontmatter."

    def test_single_separator_not_stripped(self):
        content = "---\nNot real frontmatter, only one separator."
        result = _strip_frontmatter(content)
        # Only one "---" so parts has length 2, does not strip
        assert result == content


class TestReadMarkdownResource:
    def test_existing_file(self, tmp_path):
        path = tmp_path / "example.md"
        path.write_text("# Heading", encoding="utf-8")
        assert _read_markdown_resource(path, "missing") == "# Heading"

    def test_missing_file(self, tmp_path):
        path = tmp_path / "missing.md"
        assert _read_markdown_resource(path, "missing") == "missing"


class TestConfigHelpers:
    def test_config_loads_dotenv(self):
        fake_config = MagicMock()
        with (
            patch("distill.mcp.server.load_dotenv") as mock_load,
            patch("distill.mcp.server.DistillConfig", return_value=fake_config) as mock_ctor,
        ):
            result = _config()

        assert result is fake_config
        mock_load.assert_called_once_with()
        mock_ctor.assert_called_once_with()

    def test_public_load_config_uses_shared_loader(self):
        fake_config = MagicMock()
        with patch("distill.mcp.server._config", return_value=fake_config) as mock_config:
            result = load_config()

        assert result is fake_config
        mock_config.assert_called_once_with()

    def test_lib_uses_explicit_config(self, mock_config):
        lib = _lib(mock_config)

        assert isinstance(lib, Library)
        assert lib.config is mock_config


class TestCostSummary:
    def test_empty_tracker(self):
        """Test _cost_summary with a mock tracker to avoid missing total_calls attr."""
        from distill.mcp.server import _cost_summary

        tracker = MagicMock()
        tracker.total_cost = 0.0
        tracker.total_input_tokens = 0
        tracker.total_output_tokens = 0
        tracker.total_calls = 0

        result = _cost_summary(tracker)
        assert result == {
            "total_cost": 0,
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "calls": 0,
        }

    def test_populated_tracker(self):
        """Test _cost_summary with non-zero values."""
        from distill.mcp.server import _cost_summary

        tracker = MagicMock()
        tracker.total_cost = 0.003
        tracker.total_input_tokens = 300
        tracker.total_output_tokens = 150
        tracker.entries = [MagicMock(), MagicMock()]

        result = _cost_summary(tracker)
        assert result["total_input_tokens"] == 300
        assert result["total_output_tokens"] == 150
        assert result["total_cost"] == 0.003
        assert result["calls"] == 2


class TestTopicSourceInventory:
    def test_counts_mixed_source_inventory(self, mock_config):
        _setup_library(mock_config, "ai", "TestChannel")
        _populate_videos(mock_config, "ai", "TestChannel", count=2)
        site_dir = mock_config.site_dir("ai", "example.com")
        site_dir.mkdir(parents=True, exist_ok=True)
        (site_dir / "synthesis.md").write_text("# Site", encoding="utf-8")
        page_dir = mock_config.site_page_dir("ai", "example.com", "Example Page")
        page_dir.mkdir(parents=True, exist_ok=True)
        (page_dir / "content.md").write_text("content", encoding="utf-8")
        paper_dir = mock_config.paper_dir("ai", "Agent Memory Systems", "2602.12670")
        paper_dir.mkdir(parents=True, exist_ok=True)
        (paper_dir / "paper.md").write_text("# Paper", encoding="utf-8")
        inventory = _topic_source_inventory(mock_config, "ai")
        assert inventory["videos"] == 2
        assert inventory["sites"] == 1
        assert inventory["pages"] == 1
        assert inventory["papers"] == 1
        assert set(inventory["active_source_types"]) == {"youtube", "website", "paper"}


class TestTopicGapSummary:
    def test_detects_missing_artifacts_and_sparse_coverage(self, mock_config):
        _setup_library(mock_config, "ai", "TestChannel")
        summary = _topic_gap_summary(mock_config, "ai")
        assert summary["channels"] == 1
        assert "topic_synthesis" in summary["missing_artifacts"]
        assert any("Only 1 channel" in gap for gap in summary["gaps"])
        assert any("single-source" in gap for gap in summary["gaps"])
        assert any("Run distill diff ai" in action for action in summary["recommended_actions"])

    def test_detects_thin_and_incomplete_videos(self, mock_config):
        _setup_library(mock_config, "ai", "TestChannel")
        vid_dir = mock_config.video_dir("ai", "TestChannel", "vid001")
        vid_dir.mkdir(parents=True, exist_ok=True)
        (vid_dir / "metadata.json").write_text(
            json.dumps(
                {
                    "video_id": "vid001",
                    "title": "Thin Video",
                    "upload_date": _recent(10),
                    "duration": 120,
                    "url": "https://www.youtube.com/watch?v=vid001",
                }
            ),
            encoding="utf-8",
        )
        (vid_dir / "insights.md").write_text("short", encoding="utf-8")
        summary = _topic_gap_summary(mock_config, "ai")
        assert summary["recency_status"] == "stale"
        assert summary["missing_transcripts"] == ["TestChannel: Thin Video"]
        assert summary["thin_insights"] == ["TestChannel: Thin Video"]


class TestVideoList:
    def test_empty_dir(self, mock_config):
        result = _video_list(mock_config, "nonexistent", "NoCh")
        assert result == []

    def test_with_videos(self, mock_config):
        _setup_library(mock_config, "ai", "TestChannel")
        _populate_videos(mock_config, "ai", "TestChannel", count=3)
        result = _video_list(mock_config, "ai", "TestChannel")
        assert len(result) == 3
        # Sorted newest first
        assert result[0]["upload_date"] >= result[1]["upload_date"]
        assert result[0]["has_transcript"] is True
        assert result[0]["has_insights"] is True
        assert "_dir" in result[0]

    def test_skips_non_directories(self, mock_config):
        _setup_library(mock_config, "ai", "TestChannel")
        videos_dir = mock_config.videos_dir("ai", "TestChannel")
        videos_dir.mkdir(parents=True, exist_ok=True)
        # Create a regular file (not a directory)
        (videos_dir / "stray_file.txt").write_text("not a dir")
        result = _video_list(mock_config, "ai", "TestChannel")
        assert result == []

    def test_video_without_transcript(self, mock_config):
        """Video dir with metadata but no transcript or insights files."""
        _setup_library(mock_config, "ai", "TestChannel")
        vid_dir = mock_config.video_dir("ai", "TestChannel", "novid")
        vid_dir.mkdir(parents=True, exist_ok=True)
        meta = {"video_id": "novid", "title": "No Transcript", "upload_date": "20260101"}
        (vid_dir / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")
        result = _video_list(mock_config, "ai", "TestChannel")
        assert len(result) == 1
        assert result[0]["has_transcript"] is False
        assert result[0]["has_insights"] is False

    def test_video_without_upload_date_sorts_last(self, mock_config):
        _setup_library(mock_config, "ai", "TestChannel")
        older_dir = mock_config.video_dir("ai", "TestChannel", "older")
        older_dir.mkdir(parents=True, exist_ok=True)
        (older_dir / "metadata.json").write_text(
            json.dumps({"video_id": "older", "title": "Older", "upload_date": "20260101"}),
            encoding="utf-8",
        )

        missing_dir = mock_config.video_dir("ai", "TestChannel", "missing")
        missing_dir.mkdir(parents=True, exist_ok=True)
        (missing_dir / "metadata.json").write_text(
            json.dumps({"video_id": "missing", "title": "Missing Date"}),
            encoding="utf-8",
        )

        result = _video_list(mock_config, "ai", "TestChannel")

        assert result[0]["title"] == "Older"
        assert result[-1]["title"] == "Missing Date"


# ── Resource tests ───────────────────────────────────────────────────


class TestGetTopics:
    def test_empty_library(self, mock_config):
        with patch("distill.mcp.server._config", return_value=mock_config):
            result = json.loads(get_topics())
        assert result["topics"] == []

    def test_with_topics(self, mock_config):
        _setup_library(mock_config, "ai", "TestChannel")
        _populate_videos(mock_config, "ai", "TestChannel", count=2)
        with patch("distill.mcp.server._config", return_value=mock_config):
            result = json.loads(get_topics())
        assert len(result["topics"]) == 1
        assert result["topics"][0]["name"] == "ai"
        assert result["topics"][0]["channels"] == 1
        assert "TestChannel" in result["topics"][0]["channel_names"]
        assert result["topics"][0]["videos_analyzed"] == 2


class TestGetWatchlist:
    def test_empty_watchlist(self, mock_config):
        Library(mock_config)  # ensure library file exists
        with patch("distill.mcp.server._config", return_value=mock_config):
            result = json.loads(get_watchlist())
        assert result["watchlist"] == []

    def test_populated_watchlist(self, mock_config):
        lib = Library(mock_config)
        lib.add_to_watchlist(
            "https://youtube.com/@Chan",
            "Chan",
            topic="deals",
            instructions="Find deals",
            days=2,
        )
        with patch("distill.mcp.server._config", return_value=mock_config):
            result = json.loads(get_watchlist())
        assert len(result["watchlist"]) == 1
        entry = result["watchlist"][0]
        assert entry["name"] == "Chan"
        assert entry["topic"] == "deals"
        assert entry["days"] == 2
        assert entry["instructions"] == "Find deals"


class TestGetTopicVideos:
    def test_with_videos(self, mock_config):
        _setup_library(mock_config, "ai", "TestChannel")
        _populate_videos(mock_config, "ai", "TestChannel", count=2)
        with patch("distill.mcp.server._config", return_value=mock_config):
            result = json.loads(get_topic_videos("ai"))
        assert result["topic"] == "ai"
        assert len(result["videos"]) == 2
        assert result["videos"][0]["channel"] == "TestChannel"
        assert result["videos"][0]["duration"] > 0
        assert result["videos"][0]["url"].startswith("https://www.youtube.com/watch")
        assert result["videos"][0]["has_insights"] is True

    def test_empty_topic(self, mock_config):
        _setup_library(mock_config, "empty", "SomeCh")
        with patch("distill.mcp.server._config", return_value=mock_config):
            result = json.loads(get_topic_videos("empty"))
        assert result["videos"] == []

    def test_defaults_analysis_mode_when_missing(self, mock_config):
        _setup_library(mock_config, "ai", "TestChannel")
        vid_dir = mock_config.video_dir("ai", "TestChannel", "vid001")
        vid_dir.mkdir(parents=True, exist_ok=True)
        (vid_dir / "metadata.json").write_text(
            json.dumps(
                {
                    "video_id": "vid001",
                    "title": "No Mode",
                    "upload_date": "20260101",
                    "url": "https://example.com/v",
                }
            ),
            encoding="utf-8",
        )

        with patch("distill.mcp.server._config", return_value=mock_config):
            result = json.loads(get_topic_videos("ai"))

        assert result["videos"][0]["analysis_mode"] == "unknown"


class TestGetTopicCorpus:
    def test_existing_corpus(self, mock_config):
        topic_dir = mock_config.topic_dir("ai")
        topic_dir.mkdir(parents=True, exist_ok=True)
        (topic_dir / "corpus_synthesis.md").write_text(
            "# Corpus\nCross-source view.",
            encoding="utf-8",
        )
        with patch("distill.mcp.server._config", return_value=mock_config):
            result = get_topic_corpus("ai")
        assert "Cross-source view" in result

    def test_missing_corpus(self, mock_config):
        with patch("distill.mcp.server._config", return_value=mock_config):
            result = get_topic_corpus("ai")
        assert "No corpus synthesis found" in result


class TestGetTopicSources:
    def test_returns_source_inventory(self, mock_config):
        _setup_library(mock_config, "ai", "TestChannel")
        _populate_videos(mock_config, "ai", "TestChannel", count=1)
        site_dir = mock_config.site_dir("ai", "example.com")
        site_dir.mkdir(parents=True, exist_ok=True)
        (site_dir / "synthesis.md").write_text("# Site", encoding="utf-8")
        with patch("distill.mcp.server._config", return_value=mock_config):
            result = json.loads(get_topic_sources("ai"))
        assert result["videos"] == 1
        assert result["sites"] == 1
        assert "youtube" in result["active_source_types"]
        assert "website" in result["active_source_types"]


class TestGetTopicDiff:
    def test_existing_diff(self, mock_config):
        topic_dir = mock_config.topic_dir("ai")
        topic_dir.mkdir(parents=True, exist_ok=True)
        (topic_dir / "topic_diff.md").write_text(
            "# Topic Diff\nFresh changes.",
            encoding="utf-8",
        )
        with patch("distill.mcp.server._config", return_value=mock_config):
            result = get_topic_diff("ai")
        assert "Fresh changes" in result

    def test_missing_diff(self, mock_config):
        with patch("distill.mcp.server._config", return_value=mock_config):
            result = get_topic_diff("ai")
        assert "No topic diff found" in result


class TestGetTopicTrends:
    def test_existing_trends(self, mock_config):
        topic_dir = mock_config.topic_dir("ai")
        topic_dir.mkdir(parents=True, exist_ok=True)
        (topic_dir / "topic_trends.md").write_text(
            "# Topic Trends\nMomentum is rising.",
            encoding="utf-8",
        )
        with patch("distill.mcp.server._config", return_value=mock_config):
            result = get_topic_trends("ai")
        assert "Momentum is rising" in result

    def test_missing_trends(self, mock_config):
        with patch("distill.mcp.server._config", return_value=mock_config):
            result = get_topic_trends("ai")
        assert "No topic trends found" in result


class TestGetWatchAlerts:
    def test_existing_watch_alerts(self, mock_config):
        mock_config.library_dir.mkdir(parents=True, exist_ok=True)
        (mock_config.library_dir / "watch_alerts.md").write_text(
            "# Watch Alerts\n- AI watch is rising",
            encoding="utf-8",
        )
        with patch("distill.mcp.server._config", return_value=mock_config):
            result = get_watch_alerts()
        assert "AI watch is rising" in result

    def test_missing_watch_alerts(self, mock_config):
        with patch("distill.mcp.server._config", return_value=mock_config):
            result = get_watch_alerts()
        assert "No watch alerts found" in result


class TestGetTopicSynthesis:
    def test_existing_synthesis(self, mock_config):
        topic_dir = mock_config.topic_dir("ai")
        topic_dir.mkdir(parents=True, exist_ok=True)
        (topic_dir / "topic_synthesis.md").write_text(
            "# AI Synthesis\nGreat stuff.", encoding="utf-8"
        )
        with patch("distill.mcp.server._config", return_value=mock_config):
            result = get_topic_synthesis("ai")
        assert "AI Synthesis" in result

    def test_fallback_to_channel_synthesis(self, mock_config):
        _setup_library(mock_config, "ai", "TestChannel")
        ch_dir = mock_config.channel_dir("ai", "TestChannel")
        ch_dir.mkdir(parents=True, exist_ok=True)
        (ch_dir / "synthesis.md").write_text(
            "# Channel Synthesis\nFallback content.", encoding="utf-8"
        )
        with patch("distill.mcp.server._config", return_value=mock_config):
            result = get_topic_synthesis("ai")
        assert "Fallback content" in result

    def test_missing_synthesis(self, mock_config):
        _setup_library(mock_config, "ai", "TestChannel")
        with patch("distill.mcp.server._config", return_value=mock_config):
            result = get_topic_synthesis("ai")
        assert "No synthesis found" in result


class TestGetChannelSynthesis:
    def test_existing(self, mock_config):
        ch_dir = mock_config.channel_dir("ai", "TestChannel")
        ch_dir.mkdir(parents=True, exist_ok=True)
        (ch_dir / "synthesis.md").write_text("# Synthesis", encoding="utf-8")
        with patch("distill.mcp.server._config", return_value=mock_config):
            result = get_channel_synthesis("ai", "TestChannel")
        assert "# Synthesis" in result

    def test_missing(self, mock_config):
        with patch("distill.mcp.server._config", return_value=mock_config):
            result = get_channel_synthesis("ai", "NoChannel")
        assert "No synthesis for NoChannel" in result


class TestGetVideoInsights:
    def test_valid_index(self, mock_config):
        _setup_library(mock_config, "ai", "TestChannel")
        _populate_videos(mock_config, "ai", "TestChannel", count=3)
        with patch("distill.mcp.server._config", return_value=mock_config):
            result = get_video_insights("ai", "TestChannel", "1")
        assert "## Summary" in result
        assert "Video 1/3" in result

    def test_invalid_index_string(self, mock_config):
        with patch("distill.mcp.server._config", return_value=mock_config):
            result = get_video_insights("ai", "TestChannel", "abc")
        assert "Invalid index" in result

    def test_out_of_range(self, mock_config):
        _setup_library(mock_config, "ai", "TestChannel")
        _populate_videos(mock_config, "ai", "TestChannel", count=2)
        with patch("distill.mcp.server._config", return_value=mock_config):
            result = get_video_insights("ai", "TestChannel", "5")
        assert "not found" in result
        assert "2 videos" in result

    def test_zero_index(self, mock_config):
        _setup_library(mock_config, "ai", "TestChannel")
        _populate_videos(mock_config, "ai", "TestChannel", count=1)
        with patch("distill.mcp.server._config", return_value=mock_config):
            result = get_video_insights("ai", "TestChannel", "0")
        assert "not found" in result

    def test_no_insights_file(self, mock_config):
        """Video exists but insights.md is missing."""
        _setup_library(mock_config, "ai", "TestChannel")
        vid_dir = mock_config.video_dir("ai", "TestChannel", "vid000")
        vid_dir.mkdir(parents=True, exist_ok=True)
        meta = {"video_id": "vid000", "title": "No Insights", "upload_date": "20260101"}
        (vid_dir / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")
        with patch("distill.mcp.server._config", return_value=mock_config):
            result = get_video_insights("ai", "TestChannel", "1")
        assert "No insights" in result


class TestGetCosts:
    def test_no_log_file(self, mock_config):
        with patch("distill.mcp.server._config", return_value=mock_config):
            result = json.loads(get_costs())
        assert result["costs"] == []
        assert "No cost history" in result["message"]
        assert result["cost_history"]["complete"] is True

    def test_with_entries(self, mock_config):
        mock_config.library_dir.mkdir(parents=True, exist_ok=True)
        log_file = mock_config.library_dir / "cost_log.jsonl"
        entries = [
            {"command": "catch-up", "actual_cost": 0.05},
            {"command": "learn", "actual_cost": 0.10},
        ]
        log_file.write_text(
            "\n".join(json.dumps(e) for e in entries),
            encoding="utf-8",
        )
        with patch("distill.mcp.server._config", return_value=mock_config):
            result = json.loads(get_costs())
        assert result["runs_shown"] == 2
        assert result["total_cost"] == 0.15
        assert len(result["recent_runs"]) == 2

    def test_with_malformed_lines(self, mock_config):
        mock_config.library_dir.mkdir(parents=True, exist_ok=True)
        log_file = mock_config.library_dir / "cost_log.jsonl"
        log_file.write_text(
            '{"actual_cost": 0.01}\nBAD_JSON\n{"actual_cost": 0.02}',
            encoding="utf-8",
        )
        with patch("distill.mcp.server._config", return_value=mock_config):
            result = json.loads(get_costs())
        # Malformed line is skipped
        assert result["runs_shown"] == 2
        assert result["cost_history"]["malformed_rows"] == 1

    def test_projects_known_fields_without_arbitrary_payloads(self, mock_config):
        mock_config.library_dir.mkdir(parents=True, exist_ok=True)
        log_file = mock_config.library_dir / "cost_log.jsonl"
        log_file.write_text(
            json.dumps(
                {
                    "command": "catch-up",
                    "actual_cost": 0.05,
                    "metadata": {"private": "not-for-resource"},
                    "arbitrary_secret": "must-not-cross-mcp",
                }
            ),
            encoding="utf-8",
        )

        with patch("distill.mcp.server._config", return_value=mock_config):
            result = json.loads(get_costs())

        assert result["recent_runs"] == [{"command": "catch-up", "actual_cost": 0.05}]


def test_artifact_resources_do_not_follow_library_symlinks(mock_config):
    _setup_library(mock_config, "ai", "TestChannel")
    topic_dir = mock_config.topic_dir("ai")
    channel_dir = mock_config.channel_dir("ai", "TestChannel")
    topic_dir.mkdir(parents=True, exist_ok=True)
    channel_dir.mkdir(parents=True, exist_ok=True)
    outside = mock_config.library_dir.parent / "outside-secret.md"
    outside.write_text("MCP-RESOURCE-SECRET", encoding="utf-8")
    links = (
        topic_dir / "topic_synthesis.md",
        topic_dir / "corpus_synthesis.md",
        topic_dir / "topic_diff.md",
        topic_dir / "topic_trends.md",
        mock_config.library_dir / "watch_alerts.md",
        channel_dir / "synthesis.md",
    )
    try:
        for link in links:
            link.symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"file symlinks unavailable: {exc}")

    with patch("distill.mcp.server._config", return_value=mock_config):
        results = (
            get_topic_synthesis("ai"),
            get_topic_corpus("ai"),
            get_topic_diff("ai"),
            get_topic_trends("ai"),
            get_watch_alerts(),
            get_channel_synthesis("ai", "TestChannel"),
        )

    assert all("MCP-RESOURCE-SECRET" not in result for result in results)


def test_video_insights_resource_does_not_follow_library_symlink(mock_config):
    _setup_library(mock_config, "ai", "TestChannel")
    _populate_videos(mock_config, "ai", "TestChannel", count=1)
    insights = mock_config.video_dir("ai", "TestChannel", "vid000") / "insights.md"
    outside = mock_config.library_dir.parent / "outside-video-secret.md"
    outside.write_text("MCP-VIDEO-SECRET", encoding="utf-8")
    insights.unlink()
    try:
        insights.symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"file symlinks unavailable: {exc}")

    with patch("distill.mcp.server._config", return_value=mock_config):
        result = get_video_insights("ai", "TestChannel", "1")

    assert "MCP-VIDEO-SECRET" not in result


def test_cost_resource_does_not_follow_library_symlink(mock_config):
    ops_dir = mock_config.library_dir / ".distill"
    ops_dir.mkdir(parents=True, exist_ok=True)
    outside = mock_config.library_dir.parent / "outside-cost-secret.jsonl"
    outside.write_text(
        json.dumps({"command": "secret", "actual_cost": 1, "secret": "MCP-COST-SECRET"}),
        encoding="utf-8",
    )
    log_file = ops_dir / "cost_log.jsonl"
    try:
        log_file.symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"file symlinks unavailable: {exc}")

    with patch("distill.mcp.server._config", return_value=mock_config):
        result = get_costs()

    assert "MCP-COST-SECRET" not in result
    assert not outside.with_name(f".{outside.name}.lock").exists()


# ── Tool tests ───────────────────────────────────────────────────────


class TestWatchAdd:
    def test_invalid_url_is_refused_before_lookup_or_mutation(self, mock_config):
        raw_url = "https://user:pass@youtube.com/@Channel?token=WATCH-CANARY"

        with (
            patch("distill.mcp.server._config", return_value=mock_config),
            patch("distill.ingestors.youtube.discovery.resolve_channel_name") as resolve,
        ):
            result = json.loads(watch_add(url=raw_url))

        assert result["status"] == "invalid_url"
        assert "WATCH-CANARY" not in json.dumps(result)
        assert "pass" not in json.dumps(result)
        assert Library(mock_config).get_watchlist() == []
        resolve.assert_not_called()

    def test_add_new_channel(self, mock_config):
        Library(mock_config)  # init library

        with (
            patch("distill.mcp.server._config", return_value=mock_config),
            patch(
                "distill.ingestors.youtube.discovery.resolve_channel_name", return_value="NewChan"
            ),
            patch("distill.ingestors.youtube.discovery.discover_videos", return_value=[]),
        ):
            result = json.loads(
                watch_add(
                    url="https://youtube.com/@NewChan",
                    topic="tech",
                    days=7,
                    instructions="",
                )
            )
        assert result["status"] == "added"
        assert result["name"] == "NewChan"
        assert result["topic"] == "tech"

    def test_add_duplicate(self, mock_config):
        lib = Library(mock_config)
        lib.add_to_watchlist("https://youtube.com/@Dup", "Dup", topic="t")

        with (
            patch("distill.mcp.server._config", return_value=mock_config),
            patch(
                "distill.ingestors.youtube.discovery.resolve_channel_name", return_value="Dup"
            ) as resolve,
            patch("distill.ingestors.youtube.discovery.discover_videos") as discover,
        ):
            result = json.loads(watch_add(url="https://youtube.com/@Dup"))
        assert result["status"] == "already_watching"
        resolve.assert_not_called()
        discover.assert_not_called()

    def test_add_with_instructions(self, mock_config):
        Library(mock_config)

        with (
            patch("distill.mcp.server._config", return_value=mock_config),
            patch(
                "distill.ingestors.youtube.discovery.resolve_channel_name", return_value="DealCh"
            ),
        ):
            result = json.loads(
                watch_add(
                    url="https://youtube.com/@DealCh",
                    topic="deals",
                    days=2,
                    instructions="Find best deals with prices",
                )
            )
        assert result["status"] == "added"
        assert result["days"] == 2

    def test_auto_suggestion_requires_explicit_approval(self, mock_config):
        Library(mock_config)
        fake_vid = MagicMock(title="Daily Deals Rundown")

        def generate(name, titles, config, tracker=None):
            assert tracker is not None
            tracker.record(
                TokenUsage(
                    call_type="watch_instructions",
                    prompt_tokens=100,
                    completion_tokens=25,
                    model="grok-4.3",
                )
            )
            return "Extract prices and store names"

        with (
            patch("distill.mcp.server._config", return_value=mock_config),
            patch(
                "distill.ingestors.youtube.discovery.resolve_channel_name", return_value="DealCh"
            ),
            patch("distill.ingestors.youtube.discovery.discover_videos", return_value=[fake_vid]),
            patch(
                "distill.pipeline.analysis.video.generate_watch_instructions",
                side_effect=generate,
            ),
        ):
            result = json.loads(watch_add(url="https://youtube.com/@DealCh"))

        assert result["status"] == "added"
        assert result["instructions"] == "(none)"
        assert result["suggested_instructions"] == "Extract prices and store names"
        entry = Library(mock_config).get_watchlist()[0]
        assert entry.instructions == ""
        assert entry.instructions_approved is False
        assert entry.active_instructions == ""
        rows = [
            json.loads(line)
            for line in (mock_config.library_dir / ".distill" / "cost_log.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        assert len(rows) == 1
        assert rows[0]["command"] == "watch-add"
        assert rows[0]["grok_calls"] == 1

    def test_auto_suggestion_budget_stop_is_persisted_before_watch_mutation(self, mock_config):
        Library(mock_config)
        mock_config.distill_mcp_max_spend_per_call = 0.01
        fake_vid = MagicMock(title="Daily Deals Rundown")

        def exceed_budget(name, titles, config, tracker=None):
            assert tracker is not None
            tracker.record(
                TokenUsage(
                    call_type="watch_instructions",
                    prompt_tokens=1_000_000,
                    completion_tokens=1,
                    model="grok-4.3",
                )
            )
            return "unreachable"

        with (
            patch("distill.mcp.server._config", return_value=mock_config),
            patch(
                "distill.ingestors.youtube.discovery.resolve_channel_name",
                return_value="DealCh",
            ),
            patch("distill.ingestors.youtube.discovery.discover_videos", return_value=[fake_vid]),
            patch(
                "distill.pipeline.analysis.video.generate_watch_instructions",
                side_effect=exceed_budget,
            ),
        ):
            payload = json.loads(watch_add(url="https://youtube.com/@DealCh"))

        assert payload["status"] == "budget_exceeded"
        assert Library(mock_config).get_watchlist() == []
        rows = [
            json.loads(line)
            for line in (mock_config.library_dir / ".distill" / "cost_log.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        assert len(rows) == 1
        assert rows[0]["command"] == "watch-add"
        assert rows[0]["grok_calls"] == 1

    def test_auto_generation_failures_are_reported(self, mock_config):
        Library(mock_config)

        with (
            patch("distill.mcp.server._config", return_value=mock_config),
            patch(
                "distill.ingestors.youtube.discovery.resolve_channel_name", return_value="DealCh"
            ),
            patch(
                "distill.ingestors.youtube.discovery.discover_videos",
                side_effect=RuntimeError("boom"),
            ),
        ):
            result = json.loads(watch_add(url="https://youtube.com/@DealCh"))

        assert result["status"] == "added"
        assert result["instructions"] == "(none)"
        assert result["warning"] == "Auto-instructions skipped: boom"


class TestWatchRemove:
    def test_remove_existing(self, mock_config):
        lib = Library(mock_config)
        lib.add_to_watchlist("https://youtube.com/@Channel", "Ch", topic="t")

        with patch("distill.mcp.server._config", return_value=mock_config):
            result = json.loads(watch_remove("Ch"))
        assert result["status"] == "removed"

    def test_remove_nonexistent(self, mock_config):
        Library(mock_config)
        with patch("distill.mcp.server._config", return_value=mock_config):
            result = json.loads(watch_remove("Ghost"))
        assert result["status"] == "not_found"


class TestCatchUp:
    def test_empty_watchlist(self, mock_config):
        Library(mock_config)
        with patch("distill.mcp.server._config", return_value=mock_config):
            result = catch_up()
        assert "empty" in result.lower()

    def test_no_model(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DISTILL_PROVIDER", "openai")  # not implemented -> no model
        config = DistillConfig(
            xai_api_key="",
            distill_output_dir=tmp_path / "library",
        )
        with patch("distill.mcp.server._config", return_value=config):
            result = catch_up()
        assert "model" in result.lower()

    def test_channel_up_to_date(self, mock_config):
        lib = Library(mock_config)
        lib.add_to_watchlist(
            "https://youtube.com/@TestCh",
            "TestCh",
            topic="ai",
            days=7,
        )
        _populate_videos(mock_config, "ai", "TestCh", count=2)

        fake_vid = MagicMock()
        fake_vid.video_id = "vid000"
        fake_vid.title = "Test Video 0"

        with (
            patch("distill.mcp.server._config", return_value=mock_config),
            patch("distill.ingestors.youtube.discovery.discover_videos", return_value=[fake_vid]),
            patch("distill.mcp.server._cost_summary", return_value=_FAKE_COST),
            patch("distill.mcp.server.save_run_log"),
        ):
            result = json.loads(catch_up())
        # vid000 is already processed, so channel is up_to_date
        assert result["results"][0]["status"] == "up_to_date"

    def test_channel_with_new_videos(self, mock_config):
        lib = Library(mock_config)
        lib.add_to_watchlist(
            "https://youtube.com/@TestCh",
            "TestCh",
            topic="ai",
            days=7,
        )

        fake_vid = MagicMock()
        fake_vid.video_id = "new_vid_001"
        fake_vid.title = "Brand New Video"

        with (
            patch("distill.mcp.server._config", return_value=mock_config),
            patch("distill.ingestors.youtube.discovery.discover_videos", return_value=[fake_vid]),
            patch("distill.cli_shared.ensure_channel_context"),
            patch("distill.cli_shared.process_video", return_value=True),
            patch("distill.pipeline.synthesis.topic.synthesize_channel"),
            patch("distill.pipeline.synthesis.topic.synthesize_topic"),
            patch("distill.mcp.server._cost_summary", return_value=_FAKE_COST),
            patch("distill.mcp.server.save_run_log"),
        ):
            result = json.loads(catch_up())
        assert result["results"][0]["status"] == "processed"
        assert result["results"][0]["new_videos"] == 1

    def test_channel_not_found(self, mock_config):
        lib = Library(mock_config)
        lib.add_to_watchlist(
            "https://youtube.com/@Channel",
            "Ch",
            topic="ai",
            days=7,
        )
        with patch("distill.mcp.server._config", return_value=mock_config):
            result = catch_up(channel="NoSuchChannel")
        assert "not on watch list" in result.lower()

    def test_topic_filter_no_match(self, mock_config):
        lib = Library(mock_config)
        lib.add_to_watchlist(
            "https://youtube.com/@Channel",
            "Ch",
            topic="ai",
            days=7,
        )
        with patch("distill.mcp.server._config", return_value=mock_config):
            result = catch_up(topic="security")
        assert "No watched channels" in result

    def test_discovery_error(self, mock_config):
        lib = Library(mock_config)
        lib.add_to_watchlist(
            "https://youtube.com/@Err",
            "Err",
            topic="ai",
            days=7,
        )
        with (
            patch("distill.mcp.server._config", return_value=mock_config),
            patch(
                "distill.ingestors.youtube.discovery.discover_videos",
                side_effect=RuntimeError("network fail"),
            ),
            patch("distill.mcp.server._cost_summary", return_value=_FAKE_COST),
            patch("distill.mcp.server.save_run_log"),
        ):
            result = json.loads(catch_up())
        assert result["results"][0]["status"] == "error"
        assert "network fail" in result["results"][0]["error"]

    def test_days_override_is_used(self, mock_config):
        lib = Library(mock_config)
        lib.add_to_watchlist("https://youtube.com/@TestCh", "TestCh", topic="ai", days=7)

        with (
            patch("distill.mcp.server._config", return_value=mock_config),
            patch(
                "distill.ingestors.youtube.discovery.discover_videos", return_value=[]
            ) as mock_discover,
            patch("distill.mcp.server._cost_summary", return_value=_FAKE_COST),
            patch("distill.mcp.server.save_run_log"),
        ):
            json.loads(catch_up(days=2))

        assert mock_discover.call_args.kwargs["days"] == 2


class TestResearchGaps:
    def test_returns_structured_gap_report(self, mock_config):
        _setup_library(mock_config, "ai", "TestChannel")
        with patch("distill.mcp.server._config", return_value=mock_config):
            result = json.loads(research_gaps("ai"))
        assert result["topic"] == "ai"
        assert "recommended_actions" in result
        assert any("Run distill diff ai" in action for action in result["recommended_actions"])


class TestSearchVideos:
    def test_no_results(self, mock_config):
        with (
            patch("distill.mcp.server._config", return_value=mock_config),
            patch(
                "distill.ingestors.youtube.browser_search.search_youtube_results", return_value=[]
            ),
            patch("distill.ingestors.youtube.discovery.search_videos", return_value=[]),
        ):
            result = json.loads(search_videos("nonexistent topic"))
        assert result["results"] == []
        assert "No videos found" in result["message"]

    def test_with_results(self, mock_config):
        fake_vid = MagicMock()
        fake_vid.video_id = "abc123"
        fake_vid.title = "Great AI Video"
        fake_vid.channel_name = "TechCh"
        fake_vid.upload_date = "20260301"
        fake_vid.url = "https://youtube.com/watch?v=abc123"
        fake_vid.duration = 1200
        fake_vid.view_count = 50000
        fake_vid.channel_url = "https://youtube.com/@TechCh"

        fake_ranked = MagicMock()
        fake_ranked.video = fake_vid
        fake_ranked.final_score = 0.95
        fake_ranked.rationale = "Very relevant"
        fake_ranked.selected_by = "llm"

        with (
            patch("distill.mcp.server._config", return_value=mock_config),
            patch(
                "distill.ingestors.youtube.browser_search.search_youtube_results",
                return_value=[fake_vid],
            ),
            patch("distill.ingestors.youtube.discovery.enrich_videos", return_value=[fake_vid]),
            patch("distill.pipeline.ranking.rerank_videos", return_value=[fake_ranked]),
            patch("distill.mcp.server._cost_summary", return_value=_FAKE_COST),
        ):
            result = json.loads(search_videos("AI updates", limit=1))
        assert len(result["results"]) == 1
        assert result["results"][0]["title"] == "Great AI Video"
        assert result["results"][0]["score"] == 0.95

    def test_falls_back_and_dedupes(self, mock_config):
        vid1 = MagicMock()
        vid1.video_id = "same"
        vid1.title = "First"
        vid1.channel_name = "Chan"
        vid1.upload_date = "20260301"
        vid1.url = "https://youtube.com/watch?v=same"
        vid1.duration = 100
        vid1.view_count = 10
        vid1.channel_url = "https://youtube.com/@Chan"
        vid2 = MagicMock()
        vid2.video_id = "same"
        vid2.title = "Duplicate"
        vid2.channel_name = "Chan"
        vid2.upload_date = "20260302"
        vid2.url = "https://youtube.com/watch?v=same"
        vid2.duration = 110
        vid2.view_count = 20
        vid2.channel_url = "https://youtube.com/@Chan"

        ranked = MagicMock(video=vid1, final_score=0.9, rationale="strong", selected_by="llm")

        with (
            patch("distill.mcp.server._config", return_value=mock_config),
            patch(
                "distill.ingestors.youtube.browser_search.search_youtube_results", return_value=[]
            ),
            patch("distill.ingestors.youtube.discovery.search_videos", return_value=[vid1, vid2]),
            patch(
                "distill.ingestors.youtube.discovery.enrich_videos",
                side_effect=lambda videos, **_: videos,
            ) as mock_enrich,
            patch("distill.pipeline.ranking.rerank_videos", return_value=[ranked]),
            patch("distill.mcp.server._cost_summary", return_value=_FAKE_COST),
        ):
            result = json.loads(search_videos("AI updates", limit=1))

        assert len(result["results"]) == 1
        assert mock_enrich.call_args.args[0] == [vid1]

    def test_surfaces_ranked_by_and_no_model_notice(self, mock_config):
        # P2: an agent consumer must be able to see HOW the set was ranked. A
        # no-model fallback carries ranked_by="no-model" + an explicit notice so
        # the degradation is visible, not mistaken for a model ranking.
        vid = MagicMock(
            video_id="x",
            title="T",
            channel_name="C",
            upload_date="20260301",
            url="u",
            duration=600,
            view_count=10,
        )
        ranked = MagicMock(video=vid, final_score=0.4, rationale="r", selected_by="no-model")
        with (
            patch("distill.mcp.server._config", return_value=mock_config),
            patch(
                "distill.ingestors.youtube.browser_search.search_youtube_results",
                return_value=[vid],
            ),
            patch(
                "distill.ingestors.youtube.discovery.enrich_videos",
                side_effect=lambda videos, **_: videos,
            ),
            patch("distill.pipeline.ranking.rerank_videos", return_value=[ranked]),
            patch("distill.mcp.server._cost_summary", return_value=_FAKE_COST),
        ):
            result = json.loads(search_videos("AI updates", limit=1))
        assert result["ranked_by"] == "no-model"
        assert result["results"][0]["ranked_by"] == "no-model"
        assert "No model configured" in result["notice"]


class TestLearnTopic:
    def test_no_model(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DISTILL_PROVIDER", "openai")  # not implemented -> no model
        config = DistillConfig(xai_api_key="", distill_output_dir=tmp_path / "library")
        with patch("distill.mcp.server._config", return_value=config):
            result = learn_topic("ai agents")
        assert "model" in result.lower()

    def test_no_videos_found(self, mock_config):
        with (
            patch("distill.mcp.server._config", return_value=mock_config),
            patch(
                "distill.ingestors.youtube.browser_search.search_youtube_results", return_value=[]
            ),
            patch("distill.ingestors.youtube.discovery.search_videos", return_value=[]),
        ):
            result = json.loads(learn_topic("ai agents"))

        assert result["error"] == "No videos found for this query"

    def test_processes_ranked_results_and_respects_existing_state(self, mock_config):
        already = MagicMock()
        already.video_id = "done"
        already.title = "Already Done"
        already.channel_name = "TestCh"
        already.channel_url = "https://youtube.com/@TestCh"
        already.upload_date = "20260401"
        already.url = "https://youtube.com/watch?v=done"
        fresh = MagicMock()
        fresh.video_id = "fresh"
        fresh.title = "Fresh"
        fresh.channel_name = "TestCh"
        fresh.channel_url = "https://youtube.com/@TestCh"
        fresh.upload_date = "20260402"
        fresh.url = "https://youtube.com/watch?v=fresh"
        ranked_done = MagicMock(video=already)
        ranked_fresh = MagicMock(video=fresh)

        state_path = mock_config.channel_dir("derived-topic", "TestCh") / "state.json"
        state_path.parent.mkdir(parents=True, exist_ok=True)
        ChannelState(state_path).mark_processed("done", "Already Done", "20260401")

        with (
            patch("distill.mcp.server._config", return_value=mock_config),
            patch("distill.cli_shared.topic_from_query", return_value="derived-topic"),
            patch(
                "distill.ingestors.youtube.browser_search.search_youtube_results",
                return_value=[already, fresh],
            ),
            patch(
                "distill.ingestors.youtube.discovery.enrich_videos", return_value=[already, fresh]
            ),
            patch(
                "distill.pipeline.ranking.rerank_videos", return_value=[ranked_done, ranked_fresh]
            ),
            patch("distill.cli_shared.ensure_channel_context"),
            patch("distill.cli_shared.process_video", return_value=True),
            patch("distill.pipeline.synthesis.topic.synthesize_channel"),
            patch("distill.pipeline.synthesis.topic.synthesize_topic"),
            patch("distill.mcp.server.save_run_log"),
            patch("distill.mcp.server._cost_summary", return_value=_FAKE_COST),
        ):
            result = json.loads(learn_topic("ai agents", limit=2))

        statuses = {item["title"]: item["status"] for item in result["videos"]}
        assert result["topic"] == "derived-topic"
        assert statuses["Already Done"] == "already_done"
        assert statuses["Fresh"] == "ok"


class TestProcessVideoUrl:
    def test_no_model(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DISTILL_PROVIDER", "openai")  # not implemented -> no model
        config = DistillConfig(xai_api_key="", distill_output_dir=tmp_path / "library")
        with patch("distill.mcp.server._config", return_value=config):
            result = process_video_url("https://youtube.com/watch?v=abc")
        assert "model" in result.lower()

    def test_missing_video_info(self, mock_config):
        with (
            patch("distill.mcp.server._config", return_value=mock_config),
            patch("distill.ingestors.youtube.discovery.get_video_info", return_value=None),
        ):
            result = process_video_url("https://youtube.com/watch?v=abc")
        assert "Could not get video info" in result

    def test_success_includes_insights(self, mock_config):
        info = MagicMock()
        info.video_id = "abc"
        info.title = "AI Overview"
        info.channel_url = "https://youtube.com/@Chan"

        def _process(*args, **kwargs):
            insights_file = (
                mock_config.video_dir_slug("ai", "Chan", "AI Overview", "abc") / "insights.md"
            )
            insights_file.parent.mkdir(parents=True, exist_ok=True)
            insights_file.write_text("---\ntitle: x\n---\n\nUseful insight", encoding="utf-8")
            return True

        with (
            patch("distill.mcp.server._config", return_value=mock_config),
            patch("distill.ingestors.youtube.discovery.get_video_info", return_value=info),
            patch("distill.cli_shared.resolve_video_channel_name", return_value="Chan"),
            patch("distill.cli_shared.ensure_channel_context"),
            patch("distill.cli_shared.process_video", side_effect=_process),
            patch("distill.mcp.server.save_run_log"),
            patch("distill.mcp.server._cost_summary", return_value=_FAKE_COST),
        ):
            result = json.loads(process_video_url("https://youtube.com/watch?v=abc"))

        assert result["success"] is True
        assert result["channel"] == "Chan"
        assert result["insights"] == "Useful insight"


class TestGenerateReport:
    def test_no_gemini_key(self, tmp_path):
        config = DistillConfig(gemini_api_key="", distill_output_dir=tmp_path / "library")
        with patch("distill.mcp.server._config", return_value=config):
            result = generate_report("ai")
        assert "GEMINI_API_KEY" in result

    def test_handles_report_exceptions(self, mock_config):
        with (
            patch("distill.mcp.server._config", return_value=mock_config),
            patch(
                "distill.pipeline.report.accordion.run_accordion_research",
                side_effect=RuntimeError("bad run"),
            ),
        ):
            result = json.loads(generate_report("ai"))

        assert result["error"] == "bad run"

    def test_returns_complete_payload(self, mock_config):
        report = "word " * 1200
        with (
            patch("distill.mcp.server._config", return_value=mock_config),
            patch("distill.pipeline.report.accordion.run_accordion_research", return_value=report),
            patch("distill.mcp.server.save_run_log"),
            patch("distill.mcp.server._cost_summary", return_value=_FAKE_COST),
        ):
            result = json.loads(generate_report("ai", channel="TestChannel"))

        assert result["status"] == "complete"
        assert result["words"] == len(report.split())
        assert result["characters"] == len(report)
        assert "(truncated" in result["report"]

    def test_returns_failed_when_runner_returns_none(self, mock_config):
        with (
            patch("distill.mcp.server._config", return_value=mock_config),
            patch("distill.pipeline.report.accordion.run_accordion_research", return_value=None),
            patch("distill.mcp.server.save_run_log"),
            patch("distill.mcp.server._cost_summary", return_value=_FAKE_COST),
        ):
            result = json.loads(generate_report("ai"))

        assert result["status"] == "failed"


class TestResynthesizeTopic:
    def test_no_model(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DISTILL_PROVIDER", "openai")  # not implemented -> no model
        config = DistillConfig(
            xai_api_key="",
            distill_output_dir=tmp_path / "library",
        )
        with patch("distill.mcp.server._config", return_value=config):
            result = resynthesize_topic("ai")
        assert "model" in result.lower()

    def test_resynthesize_all_channels(self, mock_config):
        _setup_library(mock_config, "ai", "TestChannel")

        with (
            patch("distill.mcp.server._config", return_value=mock_config),
            patch("distill.pipeline.synthesis.topic.synthesize_channel") as mock_ch,
            patch("distill.pipeline.synthesis.topic.synthesize_topic") as mock_tp,
            patch("distill.mcp.server._cost_summary", return_value=_FAKE_COST),
        ):
            result = json.loads(resynthesize_topic("ai"))

        mock_ch.assert_called_once()
        mock_tp.assert_called_once()
        assert any(
            r.get("channel") == "TestChannel" and r["status"] == "ok" for r in result["results"]
        )
        assert any(r.get("topic") == "ai" and r["status"] == "ok" for r in result["results"])

    def test_resynthesize_specific_channel(self, mock_config):
        _setup_library(mock_config, "ai", "TestChannel")

        with (
            patch("distill.mcp.server._config", return_value=mock_config),
            patch("distill.pipeline.synthesis.topic.synthesize_channel") as mock_ch,
            patch("distill.pipeline.synthesis.topic.synthesize_topic") as mock_tp,
            patch("distill.mcp.server._cost_summary", return_value=_FAKE_COST),
        ):
            json.loads(resynthesize_topic("ai", channel="TestChannel"))

        mock_ch.assert_called_once()
        # When channel is specified, topic synthesis is NOT called
        mock_tp.assert_not_called()

    def test_synthesis_error(self, mock_config):
        _setup_library(mock_config, "ai", "TestChannel")

        with (
            patch("distill.mcp.server._config", return_value=mock_config),
            patch(
                "distill.pipeline.synthesis.topic.synthesize_channel",
                side_effect=RuntimeError("LLM fail"),
            ),
            patch("distill.pipeline.synthesis.topic.synthesize_topic"),
            patch("distill.mcp.server._cost_summary", return_value=_FAKE_COST),
        ):
            result = json.loads(resynthesize_topic("ai"))
        error_result = [r for r in result["results"] if r.get("channel") == "TestChannel"]
        assert error_result[0]["status"] == "error"
        assert "LLM fail" in error_result[0]["error"]

    def test_corpus_skipped_when_no_mixed_source_material(self, mock_config):
        _setup_library(mock_config, "ai", "TestChannel")

        with (
            patch("distill.mcp.server._config", return_value=mock_config),
            patch("distill.pipeline.synthesis.topic.synthesize_channel"),
            patch("distill.pipeline.synthesis.topic.synthesize_topic"),
            patch("distill.pipeline.synthesis.corpus.synthesize_corpus", return_value=""),
            patch("distill.mcp.server._cost_summary", return_value=_FAKE_COST),
        ):
            result = json.loads(resynthesize_topic("ai"))

        assert any(r.get("corpus") == "ai" and r["status"] == "skipped" for r in result["results"])

    def test_corpus_error_is_reported(self, mock_config):
        _setup_library(mock_config, "ai", "TestChannel")

        with (
            patch("distill.mcp.server._config", return_value=mock_config),
            patch("distill.pipeline.synthesis.topic.synthesize_channel"),
            patch("distill.pipeline.synthesis.topic.synthesize_topic"),
            patch(
                "distill.pipeline.synthesis.corpus.synthesize_corpus",
                side_effect=RuntimeError("corpus fail"),
            ),
            patch("distill.mcp.server._cost_summary", return_value=_FAKE_COST),
        ):
            result = json.loads(resynthesize_topic("ai"))

        corpus_rows = [r for r in result["results"] if r.get("corpus") == "ai"]
        assert corpus_rows[0]["status"] == "error"
        assert corpus_rows[0]["error"] == "corpus fail"


# ── Prompt tests ─────────────────────────────────────────────────────


class TestPrompts:
    def test_daily_deals(self):
        result = daily_deals("DealChannel")
        assert "DealChannel" in result
        assert "catch_up" in result

    def test_morning_briefing(self):
        result = morning_briefing()
        assert "catch_up" in result
        assert "distill://watch-alerts" in result
        assert "distill://topics/{topic}/diff" in result
        assert "distill://topics/{topic}/trends" in result

    def test_topic_gap_review(self):
        result = topic_gap_review("ai")
        assert "research_gaps" in result
        assert "ai" in result
        assert "generate_report" in result

    def test_topic_research(self):
        result = topic_research("quantum computing")
        assert "quantum computing" in result
        assert "search_videos" in result
        assert "learn_topic" in result


class TestEntryPoint:
    def test_main_runs_stdio_transport(self):
        with patch("distill.mcp.server.mcp.run") as mock_run:
            main()

        mock_run.assert_called_once_with(transport="stdio")


def test_every_mcp_tool_call_gets_a_distinct_correlated_run(mock_config):
    server = DistillMCPServer("telemetry-test")

    @server.tool()
    def ping() -> str:
        return "pong"

    async def invoke_twice() -> None:
        await server.call_tool("ping", {})
        await server.call_tool("ping", {})

    with patch("distill.mcp.server._config", return_value=mock_config):
        asyncio.run(invoke_twice())

    path = mock_config.library_dir / ".distill" / "phase_telemetry.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [row["command"] for row in rows] == ["ping", "ping"]
    assert all(row["invocation_type"] == "mcp" for row in rows)
    assert rows[0]["run_id"] != rows[1]["run_id"]


def test_mcp_telemetry_tool_name_rejects_unvalidated_content():
    assert _telemetry_tool_name("find_insights") == "find_insights"
    assert _telemetry_tool_name("https://example.test/private") == "unknown-tool"
    assert _telemetry_tool_name("") == "unknown-tool"


def test_agent_visible_path_is_root_relative_posix(tmp_path: Path) -> None:
    root = tmp_path / "library"
    nested = root / ".distill" / "cost_log.jsonl"
    nested.parent.mkdir(parents=True)
    nested.write_text("", encoding="utf-8")

    assert agent_visible_path(root, nested) == ".distill/cost_log.jsonl"
    assert agent_visible_path(root, tmp_path / "outside.txt") == "outside.txt"


def test_agent_safe_error_redacts_oserror_filenames_and_drive_paths() -> None:
    from distill.mcp.server import agent_safe_error

    os_err = FileNotFoundError(2, "No such file or directory", r"C:\Users\op\secret\file.md")
    text = agent_safe_error(os_err)
    assert "FileNotFoundError" in text
    assert "No such file or directory" in text
    assert r"C:\Users" not in text
    assert "secret" not in text

    free = agent_safe_error(ValueError(r"bad seed at C:\GitHub\distillr\library\x.json"))
    assert "<path>" in free
    assert r"C:\GitHub" not in free


def test_mcp_host_allowlist_refusal_marks_correlated_run(tmp_path):
    config = DistillConfig(
        distill_output_dir=tmp_path / "library",
        distill_mcp_ingest_allowlist="allowed.test",
    )
    server = DistillMCPServer("allowlist-telemetry-test")

    @server.tool()
    def gated_ingest(url: str) -> str:
        return refuse_if_host_not_allowed(url) or "allowed"

    async def invoke() -> None:
        await server.call_tool("gated_ingest", {"url": "https://blocked.test/private"})

    with patch("distill.mcp.server._config", return_value=config):
        asyncio.run(invoke())

    path = config.library_dir / ".distill" / "phase_telemetry.jsonl"
    row = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert row["command"] == "gated_ingest"
    assert row["outcome"] == "refused"

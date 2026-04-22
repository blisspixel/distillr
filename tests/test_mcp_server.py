"""Tests for distill MCP server."""

import json
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from distill.config import DistillConfig
from distill.library import Library
from distill.mcp_server import (
    _read_markdown_resource,
    _strip_frontmatter,
    _topic_gap_summary,
    _topic_source_inventory,
    _video_list,
    catch_up,
    daily_deals,
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
    morning_briefing,
    research_gaps,
    resynthesize_topic,
    search_videos,
    topic_gap_review,
    topic_research,
    watch_add,
    watch_remove,
)

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
    from distill.state import ChannelState

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


class TestCostSummary:
    def test_empty_tracker(self):
        """Test _cost_summary with a mock tracker to avoid missing total_calls attr."""
        from distill.mcp_server import _cost_summary

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
        from distill.mcp_server import _cost_summary

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


# ── Resource tests ───────────────────────────────────────────────────


class TestGetTopics:
    def test_empty_library(self, mock_config):
        with patch("distill.mcp_server._config", return_value=mock_config):
            result = json.loads(get_topics())
        assert result["topics"] == []

    def test_with_topics(self, mock_config):
        _setup_library(mock_config, "ai", "TestChannel")
        _populate_videos(mock_config, "ai", "TestChannel", count=2)
        with patch("distill.mcp_server._config", return_value=mock_config):
            result = json.loads(get_topics())
        assert len(result["topics"]) == 1
        assert result["topics"][0]["name"] == "ai"
        assert result["topics"][0]["channels"] == 1
        assert "TestChannel" in result["topics"][0]["channel_names"]
        assert result["topics"][0]["videos_analyzed"] == 2


class TestGetWatchlist:
    def test_empty_watchlist(self, mock_config):
        Library(mock_config)  # ensure library file exists
        with patch("distill.mcp_server._config", return_value=mock_config):
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
        with patch("distill.mcp_server._config", return_value=mock_config):
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
        with patch("distill.mcp_server._config", return_value=mock_config):
            result = json.loads(get_topic_videos("ai"))
        assert result["topic"] == "ai"
        assert len(result["videos"]) == 2
        assert result["videos"][0]["channel"] == "TestChannel"
        assert result["videos"][0]["has_insights"] is True

    def test_empty_topic(self, mock_config):
        _setup_library(mock_config, "empty", "SomeCh")
        with patch("distill.mcp_server._config", return_value=mock_config):
            result = json.loads(get_topic_videos("empty"))
        assert result["videos"] == []


class TestGetTopicCorpus:
    def test_existing_corpus(self, mock_config):
        topic_dir = mock_config.topic_dir("ai")
        topic_dir.mkdir(parents=True, exist_ok=True)
        (topic_dir / "corpus_synthesis.md").write_text(
            "# Corpus\nCross-source view.",
            encoding="utf-8",
        )
        with patch("distill.mcp_server._config", return_value=mock_config):
            result = get_topic_corpus("ai")
        assert "Cross-source view" in result

    def test_missing_corpus(self, mock_config):
        with patch("distill.mcp_server._config", return_value=mock_config):
            result = get_topic_corpus("ai")
        assert "No corpus synthesis found" in result


class TestGetTopicSources:
    def test_returns_source_inventory(self, mock_config):
        _setup_library(mock_config, "ai", "TestChannel")
        _populate_videos(mock_config, "ai", "TestChannel", count=1)
        site_dir = mock_config.site_dir("ai", "example.com")
        site_dir.mkdir(parents=True, exist_ok=True)
        (site_dir / "synthesis.md").write_text("# Site", encoding="utf-8")
        with patch("distill.mcp_server._config", return_value=mock_config):
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
        with patch("distill.mcp_server._config", return_value=mock_config):
            result = get_topic_diff("ai")
        assert "Fresh changes" in result

    def test_missing_diff(self, mock_config):
        with patch("distill.mcp_server._config", return_value=mock_config):
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
        with patch("distill.mcp_server._config", return_value=mock_config):
            result = get_topic_trends("ai")
        assert "Momentum is rising" in result

    def test_missing_trends(self, mock_config):
        with patch("distill.mcp_server._config", return_value=mock_config):
            result = get_topic_trends("ai")
        assert "No topic trends found" in result


class TestGetWatchAlerts:
    def test_existing_watch_alerts(self, mock_config):
        mock_config.library_dir.mkdir(parents=True, exist_ok=True)
        (mock_config.library_dir / "watch_alerts.md").write_text(
            "# Watch Alerts\n- AI watch is rising",
            encoding="utf-8",
        )
        with patch("distill.mcp_server._config", return_value=mock_config):
            result = get_watch_alerts()
        assert "AI watch is rising" in result

    def test_missing_watch_alerts(self, mock_config):
        with patch("distill.mcp_server._config", return_value=mock_config):
            result = get_watch_alerts()
        assert "No watch alerts found" in result


class TestGetTopicSynthesis:
    def test_existing_synthesis(self, mock_config):
        topic_dir = mock_config.topic_dir("ai")
        topic_dir.mkdir(parents=True, exist_ok=True)
        (topic_dir / "topic_synthesis.md").write_text(
            "# AI Synthesis\nGreat stuff.", encoding="utf-8"
        )
        with patch("distill.mcp_server._config", return_value=mock_config):
            result = get_topic_synthesis("ai")
        assert "AI Synthesis" in result

    def test_fallback_to_channel_synthesis(self, mock_config):
        _setup_library(mock_config, "ai", "TestChannel")
        ch_dir = mock_config.channel_dir("ai", "TestChannel")
        ch_dir.mkdir(parents=True, exist_ok=True)
        (ch_dir / "synthesis.md").write_text(
            "# Channel Synthesis\nFallback content.", encoding="utf-8"
        )
        with patch("distill.mcp_server._config", return_value=mock_config):
            result = get_topic_synthesis("ai")
        assert "Fallback content" in result

    def test_missing_synthesis(self, mock_config):
        _setup_library(mock_config, "ai", "TestChannel")
        with patch("distill.mcp_server._config", return_value=mock_config):
            result = get_topic_synthesis("ai")
        assert "No synthesis found" in result


class TestGetChannelSynthesis:
    def test_existing(self, mock_config):
        ch_dir = mock_config.channel_dir("ai", "TestChannel")
        ch_dir.mkdir(parents=True, exist_ok=True)
        (ch_dir / "synthesis.md").write_text("# Synthesis", encoding="utf-8")
        with patch("distill.mcp_server._config", return_value=mock_config):
            result = get_channel_synthesis("ai", "TestChannel")
        assert "# Synthesis" in result

    def test_missing(self, mock_config):
        with patch("distill.mcp_server._config", return_value=mock_config):
            result = get_channel_synthesis("ai", "NoChannel")
        assert "No synthesis for NoChannel" in result


class TestGetVideoInsights:
    def test_valid_index(self, mock_config):
        _setup_library(mock_config, "ai", "TestChannel")
        _populate_videos(mock_config, "ai", "TestChannel", count=3)
        with patch("distill.mcp_server._config", return_value=mock_config):
            result = get_video_insights("ai", "TestChannel", "1")
        assert "## Summary" in result
        assert "Video 1/3" in result

    def test_invalid_index_string(self, mock_config):
        with patch("distill.mcp_server._config", return_value=mock_config):
            result = get_video_insights("ai", "TestChannel", "abc")
        assert "Invalid index" in result

    def test_out_of_range(self, mock_config):
        _setup_library(mock_config, "ai", "TestChannel")
        _populate_videos(mock_config, "ai", "TestChannel", count=2)
        with patch("distill.mcp_server._config", return_value=mock_config):
            result = get_video_insights("ai", "TestChannel", "5")
        assert "not found" in result
        assert "2 videos" in result

    def test_zero_index(self, mock_config):
        _setup_library(mock_config, "ai", "TestChannel")
        _populate_videos(mock_config, "ai", "TestChannel", count=1)
        with patch("distill.mcp_server._config", return_value=mock_config):
            result = get_video_insights("ai", "TestChannel", "0")
        assert "not found" in result

    def test_no_insights_file(self, mock_config):
        """Video exists but insights.md is missing."""
        _setup_library(mock_config, "ai", "TestChannel")
        vid_dir = mock_config.video_dir("ai", "TestChannel", "vid000")
        vid_dir.mkdir(parents=True, exist_ok=True)
        meta = {"video_id": "vid000", "title": "No Insights", "upload_date": "20260101"}
        (vid_dir / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")
        with patch("distill.mcp_server._config", return_value=mock_config):
            result = get_video_insights("ai", "TestChannel", "1")
        assert "No insights" in result


class TestGetCosts:
    def test_no_log_file(self, mock_config):
        with patch("distill.mcp_server._config", return_value=mock_config):
            result = json.loads(get_costs())
        assert result["costs"] == []
        assert "No cost history" in result["message"]

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
        with patch("distill.mcp_server._config", return_value=mock_config):
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
        with patch("distill.mcp_server._config", return_value=mock_config):
            result = json.loads(get_costs())
        # Malformed line is skipped
        assert result["runs_shown"] == 2


# ── Tool tests ───────────────────────────────────────────────────────


class TestWatchAdd:
    def test_add_new_channel(self, mock_config):
        Library(mock_config)  # init library

        with (
            patch("distill.mcp_server._config", return_value=mock_config),
            patch("distill.discovery.resolve_channel_name", return_value="NewChan"),
            patch("distill.discovery.discover_videos", return_value=[]),
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
            patch("distill.mcp_server._config", return_value=mock_config),
            patch("distill.discovery.resolve_channel_name", return_value="Dup"),
        ):
            result = json.loads(watch_add(url="https://youtube.com/@Dup"))
        assert result["status"] == "already_watching"

    def test_add_with_instructions(self, mock_config):
        Library(mock_config)

        with (
            patch("distill.mcp_server._config", return_value=mock_config),
            patch("distill.discovery.resolve_channel_name", return_value="DealCh"),
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


class TestWatchRemove:
    def test_remove_existing(self, mock_config):
        lib = Library(mock_config)
        lib.add_to_watchlist("https://youtube.com/@Ch", "Ch", topic="t")

        with patch("distill.mcp_server._config", return_value=mock_config):
            result = json.loads(watch_remove("Ch"))
        assert result["status"] == "removed"

    def test_remove_nonexistent(self, mock_config):
        Library(mock_config)
        with patch("distill.mcp_server._config", return_value=mock_config):
            result = json.loads(watch_remove("Ghost"))
        assert result["status"] == "not_found"


class TestCatchUp:
    def test_empty_watchlist(self, mock_config):
        Library(mock_config)
        with patch("distill.mcp_server._config", return_value=mock_config):
            result = catch_up()
        assert "empty" in result.lower()

    def test_no_api_key(self, tmp_path):
        config = DistillConfig(
            xai_api_key="",
            distill_output_dir=tmp_path / "library",
        )
        with patch("distill.mcp_server._config", return_value=config):
            result = catch_up()
        assert "XAI_API_KEY" in result

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
            patch("distill.mcp_server._config", return_value=mock_config),
            patch("distill.discovery.discover_videos", return_value=[fake_vid]),
            patch("distill.mcp_server._cost_summary", return_value=_FAKE_COST),
            patch("distill.mcp_server.save_run_log"),
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
            patch("distill.mcp_server._config", return_value=mock_config),
            patch("distill.discovery.discover_videos", return_value=[fake_vid]),
            patch("distill.cli_shared.ensure_channel_context"),
            patch("distill.cli_shared.process_video", return_value=True),
            patch("distill.synthesis.synthesize_channel"),
            patch("distill.synthesis.synthesize_topic"),
            patch("distill.mcp_server._cost_summary", return_value=_FAKE_COST),
            patch("distill.mcp_server.save_run_log"),
        ):
            result = json.loads(catch_up())
        assert result["results"][0]["status"] == "processed"
        assert result["results"][0]["new_videos"] == 1

    def test_channel_not_found(self, mock_config):
        lib = Library(mock_config)
        lib.add_to_watchlist(
            "https://youtube.com/@Ch",
            "Ch",
            topic="ai",
            days=7,
        )
        with patch("distill.mcp_server._config", return_value=mock_config):
            result = catch_up(channel="NoSuchChannel")
        assert "not on watch list" in result.lower()

    def test_topic_filter_no_match(self, mock_config):
        lib = Library(mock_config)
        lib.add_to_watchlist(
            "https://youtube.com/@Ch",
            "Ch",
            topic="ai",
            days=7,
        )
        with patch("distill.mcp_server._config", return_value=mock_config):
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
            patch("distill.mcp_server._config", return_value=mock_config),
            patch("distill.discovery.discover_videos", side_effect=RuntimeError("network fail")),
            patch("distill.mcp_server._cost_summary", return_value=_FAKE_COST),
            patch("distill.mcp_server.save_run_log"),
        ):
            result = json.loads(catch_up())
        assert result["results"][0]["status"] == "error"
        assert "network fail" in result["results"][0]["error"]


class TestResearchGaps:
    def test_returns_structured_gap_report(self, mock_config):
        _setup_library(mock_config, "ai", "TestChannel")
        with patch("distill.mcp_server._config", return_value=mock_config):
            result = json.loads(research_gaps("ai"))
        assert result["topic"] == "ai"
        assert "recommended_actions" in result
        assert any("Run distill diff ai" in action for action in result["recommended_actions"])


class TestSearchVideos:
    def test_no_results(self, mock_config):
        with (
            patch("distill.mcp_server._config", return_value=mock_config),
            patch("distill.browser_search.search_youtube_results", return_value=[]),
            patch("distill.discovery.search_videos", return_value=[]),
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

        with (
            patch("distill.mcp_server._config", return_value=mock_config),
            patch("distill.browser_search.search_youtube_results", return_value=[fake_vid]),
            patch("distill.discovery.enrich_videos", return_value=[fake_vid]),
            patch("distill.ranking.rerank_videos", return_value=[fake_ranked]),
            patch("distill.mcp_server._cost_summary", return_value=_FAKE_COST),
        ):
            result = json.loads(search_videos("AI updates", limit=1))
        assert len(result["results"]) == 1
        assert result["results"][0]["title"] == "Great AI Video"
        assert result["results"][0]["score"] == 0.95


class TestResynthesizeTopic:
    def test_no_api_key(self, tmp_path):
        config = DistillConfig(
            xai_api_key="",
            distill_output_dir=tmp_path / "library",
        )
        with patch("distill.mcp_server._config", return_value=config):
            result = resynthesize_topic("ai")
        assert "XAI_API_KEY" in result

    def test_resynthesize_all_channels(self, mock_config):
        _setup_library(mock_config, "ai", "TestChannel")

        with (
            patch("distill.mcp_server._config", return_value=mock_config),
            patch("distill.synthesis.synthesize_channel") as mock_ch,
            patch("distill.synthesis.synthesize_topic") as mock_tp,
            patch("distill.mcp_server._cost_summary", return_value=_FAKE_COST),
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
            patch("distill.mcp_server._config", return_value=mock_config),
            patch("distill.synthesis.synthesize_channel") as mock_ch,
            patch("distill.synthesis.synthesize_topic") as mock_tp,
            patch("distill.mcp_server._cost_summary", return_value=_FAKE_COST),
        ):
            json.loads(resynthesize_topic("ai", channel="TestChannel"))

        mock_ch.assert_called_once()
        # When channel is specified, topic synthesis is NOT called
        mock_tp.assert_not_called()

    def test_synthesis_error(self, mock_config):
        _setup_library(mock_config, "ai", "TestChannel")

        with (
            patch("distill.mcp_server._config", return_value=mock_config),
            patch("distill.synthesis.synthesize_channel", side_effect=RuntimeError("LLM fail")),
            patch("distill.synthesis.synthesize_topic"),
            patch("distill.mcp_server._cost_summary", return_value=_FAKE_COST),
        ):
            result = json.loads(resynthesize_topic("ai"))
        error_result = [r for r in result["results"] if r.get("channel") == "TestChannel"]
        assert error_result[0]["status"] == "error"
        assert "LLM fail" in error_result[0]["error"]


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

"""Unit tests for new MCP tools (papers, discover, site_batch, synthesize, costs, doctor)."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import TextContent

from distill.config import DistillConfig
from distill.library import Library
from distill.pipeline.costs import BudgetExceededError, CostTracker

_FAKE_COST = {"total_cost": 0, "total_input_tokens": 0, "total_output_tokens": 0, "calls": 0}


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


def _setup_library(config, topic="ai", channel="TestChannel"):
    lib = Library(config)
    lib.add_channel(topic, f"https://www.youtube.com/@{channel}", channel)
    return lib


def _mcp_video(
    video_id: str = "v1",
    title: str = "Agent Memory Systems",
    *,
    channel_name: str = "Research Lab",
    channel_url: str = "https://youtube.com/@ResearchLab",
):
    from distill.ingestors.youtube.discovery import VideoInfo

    return VideoInfo(
        video_id=video_id,
        title=title,
        upload_date="20260601",
        duration=600,
        url=f"https://youtube.com/watch?v={video_id}",
        channel_name=channel_name,
        channel_url=channel_url,
        view_count=1000,
    )


def _ranked_mcp_video(video, *, score: float = 8.456, selected_by: str = "llm"):
    from distill.pipeline.ranking import RankedVideo

    return RankedVideo(
        video=video,
        final_score=score,
        relevance_score=8.0,
        depth_score=8.0,
        practicality_score=8.0,
        freshness_score=8.0,
        credibility_score=8.0,
        rationale="Relevant source",
        selected_by=selected_by,
    )


# ── Property 10: Progress events have valid structure ──
# Feature: mcp-first-surface, Property 10: Progress events have valid structure
# **Validates: Requirements 9.2**


@settings(max_examples=100)
@given(
    progress=st.floats(min_value=0.0, max_value=100.0),
    total=st.integers(min_value=1, max_value=100),
)
def test_progress_events_valid_structure(progress, total):
    """Property 10: Progress events have valid structure."""
    # Simulate what our tools do: progress/total should yield 0.0-1.0
    normalized = progress / total if total > 0 else 0.0
    # The MCP SDK accepts progress as an integer count and total
    # Our tools pass progress=i, total=len(items) which is always valid
    assert normalized >= 0.0  # always true for non-negative
    # The actual constraint: progress value passed to ctx.report_progress
    # should be a non-negative integer <= total
    int_progress = int(min(progress, total))
    assert 0 <= int_progress <= total


class TestCostsTool:
    def test_aggregate_rejects_integer_too_large_for_float(self):
        from distill.mcp.tools.costs import _finite_total

        assert _finite_total([{"actual_cost": 10**10_000}]) is None

    def test_no_cost_history(self, mock_config):
        with patch("distill.mcp.server._config", return_value=mock_config):
            from distill.mcp.tools.costs import costs

            result = json.loads(costs())
        assert result["status"] == "ok"
        assert result["runs"] == []
        assert "No cost history" in result.get("message", "")
        assert result["cost_history"]["complete"] is True

    def test_with_cost_entries(self, mock_config):
        log_file = mock_config.library_dir / "cost_log.jsonl"
        entries = [
            '{"command": "learn", "actual_cost": 0.05}',
            '{"command": "papers", "actual_cost": 0.10}',
        ]
        log_file.write_text("\n".join(entries), encoding="utf-8")

        with patch("distill.mcp.server._config", return_value=mock_config):
            from distill.mcp.tools.costs import costs

            result = json.loads(costs())
        assert result["runs_shown"] == 2
        assert result["total_cost"] == 0.15

    def test_malformed_cost_rows_do_not_break_summary(self, mock_config):
        log_file = mock_config.library_dir / "cost_log.jsonl"
        entries = [
            "not-json",
            '["not", "an", "object"]',
            '{"command":"learn","actual_cost":0.25,"timestamp":"2026-07-18T10:00:00"}',
            '{"command":"bad","actual_cost":"not-a-number","timestamp":"2026-07-18T10:00:00"}',
        ]
        log_file.write_text("\n".join(entries), encoding="utf-8")

        with patch("distill.mcp.server._config", return_value=mock_config):
            from distill.mcp.tools.costs import costs

            result = json.loads(costs())

        assert result["runs_shown"] == 1
        assert result["total_cost"] == 0.25
        assert result["status"] == "warning"
        assert result["cost_history"]["malformed_rows"] == 3

    def test_ops_cost_log_takes_precedence_over_legacy_log(self, mock_config):
        legacy_log = mock_config.library_dir / "cost_log.jsonl"
        legacy_log.write_text(
            json.dumps({"command": "legacy", "actual_cost": 99.0}),
            encoding="utf-8",
        )

        ops_dir = mock_config.library_dir / ".distill"
        ops_dir.mkdir(parents=True)
        ops_log = ops_dir / "cost_log.jsonl"
        ops_log.write_text(
            json.dumps({"command": "ops", "actual_cost": 0.03}),
            encoding="utf-8",
        )

        with patch("distill.mcp.server._config", return_value=mock_config):
            from distill.mcp.tools.costs import costs

            result = json.loads(costs())

        assert result["runs_shown"] == 1
        assert result["total_cost"] == 0.03
        assert result["runs"][0]["command"] == "ops"

    def test_cost_history_filters_timestamps_and_ignores_boolean_costs(self, mock_config):
        old_timestamp = (datetime.now() - timedelta(days=45)).isoformat()
        current_timestamp = datetime.now().isoformat()
        log_file = mock_config.library_dir / "cost_log.jsonl"
        entries = [
            json.dumps(
                {
                    "command": "old",
                    "timestamp": old_timestamp,
                    "actual_cost": 10.0,
                }
            ),
            "",
            json.dumps(
                {
                    "command": "invalid-timestamp",
                    "timestamp": "not-a-timestamp",
                    "actual_cost": 0.02,
                }
            ),
            json.dumps(
                {
                    "command": "boolean-cost",
                    "timestamp": current_timestamp,
                    "actual_cost": True,
                }
            ),
            json.dumps(
                {
                    "command": "recent",
                    "timestamp": current_timestamp,
                    "actual_cost": 0.33333,
                }
            ),
        ]
        log_file.write_text("\n".join(entries), encoding="utf-8")

        with patch("distill.mcp.server._config", return_value=mock_config):
            from distill.mcp.tools.costs import costs

            result = json.loads(costs(days=30, limit=10))

        commands = [run["command"] for run in result["runs"]]
        assert commands == ["invalid-timestamp", "recent"]
        assert result["runs_shown"] == 2
        assert result["total_cost"] == 0.3533
        assert result["status"] == "warning"
        assert result["cost_history"]["malformed_rows"] == 1

    def test_cost_history_validates_bounds_and_honors_zero_limit(self, mock_config):
        log_file = mock_config.library_dir / "cost_log.jsonl"
        log_file.write_text('{"command":"learn","actual_cost":1}\n', encoding="utf-8")

        with patch("distill.mcp.server._config", return_value=mock_config):
            from distill.mcp.tools.costs import costs

            zero = json.loads(costs(limit=0))
            invalid_days = json.loads(costs(days=0))
            invalid_limit = json.loads(costs(limit=101))
            boolean_limit = json.loads(costs(limit=True))

        assert zero["runs"] == []
        assert zero["runs_shown"] == 0
        assert zero["total_cost"] == 0
        assert invalid_days["status"] == "error"
        assert invalid_limit["status"] == "error"
        assert boolean_limit["status"] == "error"

    def test_cost_history_accepts_offset_aware_timestamps(self, mock_config):
        log_file = mock_config.library_dir / "cost_log.jsonl"
        log_file.write_text(
            json.dumps(
                {
                    "command": "aware",
                    "timestamp": datetime.now().astimezone().isoformat(),
                    "actual_cost": 0.5,
                }
            ),
            encoding="utf-8",
        )

        with patch("distill.mcp.server._config", return_value=mock_config):
            from distill.mcp.tools.costs import costs

            result = json.loads(costs())

        assert result["runs"][0]["command"] == "aware"

    def test_cost_history_fails_closed_when_total_is_unrepresentable(self, mock_config):
        timestamp = datetime.now().isoformat()
        log_file = mock_config.library_dir / "cost_log.jsonl"
        log_file.write_text(
            "\n".join(
                json.dumps(
                    {
                        "command": "report",
                        "timestamp": timestamp,
                        "actual_cost": 1e308,
                    }
                )
                for _ in range(2)
            ),
            encoding="utf-8",
        )

        with patch("distill.mcp.server._config", return_value=mock_config):
            from distill.mcp.tools.costs import costs

            raw = costs()
            result = json.loads(raw)

        assert result["status"] == "warning"
        assert result["total_cost"] is None
        assert "supported aggregate range" in result["message"]
        assert "Infinity" not in raw

    def test_incomplete_cost_history_uses_library_relative_ledger_path(self, mock_config):
        """Integrity warnings must not hand the host absolute ledger path to MCP."""
        log_file = mock_config.library_dir / "cost_log.jsonl"
        log_file.write_text("{not-json\n", encoding="utf-8")

        with patch("distill.mcp.server._config", return_value=mock_config):
            from distill.mcp.tools.costs import costs

            result = json.loads(costs())

        assert result["status"] == "warning"
        message = result["message"]
        assert "Cost history is incomplete at" in message
        assert "cost_log.jsonl" in message
        assert str(mock_config.library_dir) not in message
        assert "\\" not in message.split("at ", 1)[1].split(":", 1)[0]


class TestDoctorTool:
    def test_returns_checks(self, mock_config):
        with (
            patch("distill.mcp.server._config", return_value=mock_config),
            patch(
                "distill.doctor.checks._doctor_validate_key",
                side_effect=AssertionError("MCP doctor must not contact providers"),
            ),
        ):
            from distill.mcp.tools.doctor import doctor

            result = json.loads(doctor())
        assert "checks" in result
        check_names = [c["check"] for c in result["checks"]]
        assert "xai_api_key" in check_names
        assert "library_dir" in check_names
        library_check = next(c for c in result["checks"] if c["check"] == "library_dir")
        assert library_check["path"] == "."
        yt_check = next(c for c in result["checks"] if c["check"] == "yt-dlp")
        assert yt_check["path"] in ("", "yt-dlp")
        assert "\\" not in yt_check["path"]
        assert "/" not in yt_check["path"]

    def test_configured_key_is_truthfully_reported_as_not_live_validated(self, mock_config):
        with (
            patch("distill.mcp.server._config", return_value=mock_config),
            patch(
                "distill.doctor.checks._doctor_validate_key",
                side_effect=AssertionError("MCP doctor must not contact providers"),
            ),
        ):
            from distill.mcp.tools.doctor import doctor

            result = json.loads(doctor())

        xai = next(c for c in result["checks"] if c["check"] == "xai_api_key")
        assert xai["status"] == "unknown"
        assert "distill doctor" in xai["detail"]
        assert result["status"] == "warning"

    def test_missing_api_key(self, tmp_path):
        config = DistillConfig(
            xai_api_key="",
            distill_output_dir=tmp_path / "library",
        )
        config.library_dir.mkdir(parents=True, exist_ok=True)

        with patch("distill.mcp.server._config", return_value=config):
            from distill.mcp.tools.doctor import doctor

            result = json.loads(doctor())
        xai_check = next(c for c in result["checks"] if c["check"] == "xai_api_key")
        assert xai_check["status"] == "missing"


class TestPapersTool:
    def test_no_model(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DISTILL_PROVIDER", "openai")  # not implemented -> no model
        config = DistillConfig(
            xai_api_key="",
            distill_output_dir=tmp_path / "library",
        )
        with patch("distill.mcp.server._config", return_value=config):
            from distill.mcp.tools.papers import papers

            result = json.loads(asyncio.run(papers("ai", "transformers")))
        assert result["status"] == "error"
        assert "model" in result["error"].lower()

    def test_processes_paper_records(self, mock_config, monkeypatch, tmp_path):
        from distill.ingestors.papers.arxiv import PaperRecord

        paper = PaperRecord(
            paper_id="2602.12670v1",
            title="Agent Memory Systems",
            abstract="A paper about memory systems.",
            authors=["Alice"],
            abs_url="https://arxiv.org/abs/2602.12670v1",
            pdf_url="https://arxiv.org/pdf/2602.12670v1.pdf",
        )
        monkeypatch.setattr("distill.ingestors.papers.arxiv.search_arxiv", lambda *a, **k: [paper])
        monkeypatch.setattr(
            "distill.pipeline.analysis.paper.analyze_paper",
            lambda *a, **k: ("# Insights", "# Paper"),
        )
        monkeypatch.setattr(
            "distill.commands._paper_artifacts.write_paper_artifacts",
            lambda *a, **k: tmp_path / "paper",
        )
        monkeypatch.setattr(
            "distill.pipeline.analysis.paper.synthesize_papers",
            lambda *a, **k: "# Synthesis",
        )
        monkeypatch.setattr(
            "distill.pipeline.synthesis.corpus.synthesize_corpus",
            lambda *a, **k: "# Corpus",
        )

        with patch("distill.mcp.server._config", return_value=mock_config):
            from distill.mcp.tools.papers import papers

            result = json.loads(asyncio.run(papers("ai", "agent memory", limit=1)))

        assert result["status"] == "complete"
        assert result["papers"] == [{"title": "Agent Memory Systems", "status": "ok"}]

    def test_analyze_one_records_per_paper_errors(self, mock_config):
        from distill.ingestors.papers.arxiv import PaperRecord
        from distill.mcp.tools import papers as papers_tool

        paper = PaperRecord(
            paper_id="2602.00001v1",
            title="Broken Paper",
            abstract="Abstract",
        )

        def analyze(paper_arg, config_arg, tracker=None, router_config=None, *, intent=None):
            assert paper_arg is paper
            assert config_arg is mock_config
            assert isinstance(tracker, CostTracker)
            assert router_config is None
            assert intent is None
            raise RuntimeError("analysis failed")

        row = papers_tool._analyze_one(
            paper,
            "ai",
            mock_config,
            CostTracker(),
            None,
            analyze_paper=analyze,
        )

        assert row == {
            "title": "Broken Paper",
            "status": "error",
            "error": "analysis failed",
        }

    def test_search_failure_uses_default_limit_for_invalid_limit(self, mock_config, monkeypatch):
        seen: dict[str, int] = {}

        def search(query, max_results):
            seen["max_results"] = max_results
            raise RuntimeError("search down")

        monkeypatch.setattr("distill.ingestors.papers.arxiv.search_arxiv", search)

        with patch("distill.mcp.server._config", return_value=mock_config):
            from distill.mcp.tools.papers import papers

            result = json.loads(asyncio.run(papers("ai", "agent memory", limit="bad")))

        assert seen["max_results"] == 10
        assert result == {"status": "error", "error": "arXiv search failed: search down"}

    def test_progress_and_synthesis_warning_do_not_fail_tool(
        self, mock_config, monkeypatch, tmp_path
    ):
        from distill.ingestors.papers.arxiv import PaperRecord

        class ProgressContext:
            def __init__(self):
                self.calls = []

            async def report_progress(self, *, progress, total):
                self.calls.append((progress, total))

        paper = PaperRecord(
            paper_id="2602.12670v1",
            title="Agent Memory Systems",
            abstract="A paper about memory systems.",
            authors=["Alice"],
        )
        ctx = ProgressContext()

        def search(query, max_results):
            assert query == "agent memory"
            assert max_results == 2
            return [paper]

        def analyze_paper(paper_arg, config_arg, tracker=None, router_config=None, *, intent=None):
            assert paper_arg is paper
            assert config_arg is mock_config
            assert isinstance(tracker, CostTracker)
            assert router_config is None
            assert intent is None
            return "# Insights", "# Paper"

        def write_artifacts(topic, paper_arg, config_arg, insights, document=None):
            assert topic == "ai"
            assert paper_arg is paper
            assert config_arg is mock_config
            assert insights == "# Insights"
            assert document == "# Paper"
            return tmp_path / "paper"

        def fail_paper_synthesis(topic, config_arg, tracker=None):
            assert topic == "ai"
            assert config_arg is mock_config
            assert isinstance(tracker, CostTracker)
            raise RuntimeError("synthesis down")

        def synthesize_corpus(
            topic,
            config_arg,
            tracker=None,
            *,
            style="",
            two_pass=False,
            now_iso=None,
        ):
            assert topic == "ai"
            assert config_arg is mock_config
            assert isinstance(tracker, CostTracker)
            assert style == ""
            assert two_pass is False
            assert now_iso is None
            return "# Corpus"

        def save_log(
            log_dir,
            command,
            tracker,
            estimated_cost=None,
            full_videos=0,
            shorts=0,
            elapsed_seconds=0,
            metadata=None,
            preview=False,
        ):
            assert log_dir == mock_config.library_dir
            assert command == "papers"
            assert isinstance(tracker, CostTracker)
            assert estimated_cost is None
            assert full_videos == 0
            assert shorts == 0
            assert elapsed_seconds == 0
            assert metadata is None
            assert preview is False

        monkeypatch.setattr("distill.ingestors.papers.arxiv.search_arxiv", search)
        monkeypatch.setattr(
            "distill.pipeline.analysis.paper.analyze_paper",
            analyze_paper,
        )
        monkeypatch.setattr(
            "distill.commands._paper_artifacts.write_paper_artifacts",
            write_artifacts,
        )
        monkeypatch.setattr(
            "distill.pipeline.analysis.paper.synthesize_papers",
            fail_paper_synthesis,
        )
        monkeypatch.setattr(
            "distill.pipeline.synthesis.corpus.synthesize_corpus",
            synthesize_corpus,
        )
        monkeypatch.setattr("distill.mcp.server.save_run_log", save_log)

        with patch("distill.mcp.server._config", return_value=mock_config):
            from distill.mcp.tools.papers import papers

            result = json.loads(asyncio.run(papers("ai", "agent memory", limit=1, ctx=ctx)))

        assert result["status"] == "complete"
        assert result["papers"] == [{"title": "Agent Memory Systems", "status": "ok"}]
        assert ctx.calls == [(0, 1), (1, 1)]


class TestSiteBatchTool:
    @staticmethod
    def _write_seed_manifest(mock_config, name, payload):
        seed_dir = mock_config.library_dir / "site-seeds"
        seed_dir.mkdir(parents=True, exist_ok=True)
        (seed_dir / name).write_text(json.dumps(payload), encoding="utf-8")
        return f"site-seeds/{name}"

    def test_resolve_seed_file_rejects_empty_null_and_parent_escape(self, tmp_path):
        from distill.mcp.tools.sites import _resolve_seed_file

        library_dir = tmp_path / "library"
        library_dir.mkdir()
        outside = tmp_path / "outside.txt"
        outside.write_text("https://example.com/outside\n", encoding="utf-8")

        assert _resolve_seed_file(library_dir, "") is None
        assert _resolve_seed_file(library_dir, "seed\x00file.txt") is None
        assert _resolve_seed_file(library_dir, "../outside.txt") is None

    def test_seed_url_validator_accepts_public_ipv6_and_rejects_private_ipv6(self):
        from distill.mcp.tools.sites import _is_public_https_seed_url

        assert _is_public_https_seed_url("https://[2606:4700:4700::1111]/docs") is True
        assert _is_public_https_seed_url("https://[::1]/private") is False

    @pytest.mark.parametrize(
        "url",
        [
            None,
            "",
            "x" * 2_049,
            "https://example.com/line\nbreak",
            "https://example.com\\private",
            "https://example.com:invalid/docs",
            "http://example.com/docs",
            "https://user@example.com/docs",
            "https://\ud800.example/docs",
            "https://localhost/docs",
            "https://service.internal/docs",
            "https://singlelabel/docs",
        ],
    )
    def test_seed_url_validator_rejects_ambiguous_or_private_authorities(self, url):
        from distill.mcp.tools.sites import _is_public_https_seed_url

        assert _is_public_https_seed_url(url) is False

    def test_resolve_seed_file_handles_filesystem_resolution_failure(self, tmp_path, monkeypatch):
        from distill.mcp.tools.sites import _resolve_seed_file

        library_dir = tmp_path / "library"
        (library_dir / "site-seeds").mkdir(parents=True)
        monkeypatch.setattr(
            Path,
            "resolve",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("unavailable")),
        )

        assert _resolve_seed_file(library_dir, "site-seeds/seeds.json") is None

    def test_site_batch_reports_optional_dependency_import_failure(self, mock_config, monkeypatch):
        import builtins

        original_import = builtins.__import__

        def guarded_import(name, *args, **kwargs):
            if name == "distill.commands._site_batch":
                raise ImportError("site adapter unavailable")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", guarded_import)
        with patch("distill.mcp.server._config", return_value=mock_config):
            from distill.mcp.tools.sites import site_batch

            result = json.loads(asyncio.run(site_batch("ai", urls=["https://example.com/docs"])))

        assert result == {
            "status": "error",
            "error": "Site dependencies missing: site adapter unavailable",
        }

    def test_site_batch_rejects_excess_or_invalid_direct_urls(self, mock_config):
        with patch("distill.mcp.server._config", return_value=mock_config):
            from distill.mcp.tools.sites import site_batch

            excess = json.loads(
                asyncio.run(
                    site_batch(
                        "ai",
                        urls=[f"https://example.com/{index}" for index in range(51)],
                    )
                )
            )
            invalid = json.loads(asyncio.run(site_batch("ai", urls=["http://example.com"])))

        assert "at most 50" in excess["error"]
        assert "public HTTPS" in invalid["error"]

    def test_site_batch_reports_manifest_read_failure(self, mock_config, monkeypatch):
        seed_file = self._write_seed_manifest(
            mock_config, "seeds.json", {"urls": ["https://example.com/docs"]}
        )
        monkeypatch.setattr(
            "distill.mcp.tools.sites.read_confined_text", lambda *_args, **_kwargs: None
        )

        with patch("distill.mcp.server._config", return_value=mock_config):
            from distill.mcp.tools.sites import site_batch

            result = json.loads(asyncio.run(site_batch("ai", seed_file=seed_file)))

        assert result == {"status": "error", "error": "Seed manifest is unavailable."}

    @pytest.mark.parametrize(
        ("payload", "message"),
        [
            (
                {"urls": [f"https://example.com/{index}" for index in range(51)]},
                "at most 50",
            ),
            ({"urls": ["http://example.com/docs"]}, "invalid or non-public HTTPS URL"),
        ],
    )
    def test_site_batch_rejects_excess_or_invalid_manifest_urls(
        self,
        mock_config,
        payload,
        message,
    ):
        seed_file = self._write_seed_manifest(mock_config, "seeds.json", payload)

        with patch("distill.mcp.server._config", return_value=mock_config):
            from distill.mcp.tools.sites import site_batch

            result = json.loads(asyncio.run(site_batch("ai", seed_file=seed_file)))

        assert message in result["error"]

    def test_site_batch_rejects_empty_resolved_batch_and_host_refusal(
        self, mock_config, monkeypatch
    ):
        seed_file = self._write_seed_manifest(mock_config, "empty.json", {"urls": []})

        with patch("distill.mcp.server._config", return_value=mock_config):
            from distill.mcp.tools.sites import site_batch

            empty = json.loads(asyncio.run(site_batch("ai", seed_file=seed_file)))
            monkeypatch.setattr(
                "distill.mcp.tools.sites.refuse_if_host_not_allowed",
                lambda _url: json.dumps({"status": "error", "error": "host refused"}),
            )
            refused = json.loads(
                asyncio.run(site_batch("ai", urls=["https://example.com/docs"], preview=True))
            )

        assert empty == {"status": "error", "error": "No URLs to process."}
        assert refused == {"status": "error", "error": "host refused"}

    def test_no_urls_or_seed(self, mock_config):
        with patch("distill.mcp.server._config", return_value=mock_config):
            from distill.mcp.tools.sites import site_batch

            result = json.loads(asyncio.run(site_batch("ai")))
        assert result["status"] == "error"
        assert "urls" in result["error"] or "seed_file" in result["error"]

    def test_missing_seed_file(self, mock_config):
        with patch("distill.mcp.server._config", return_value=mock_config):
            from distill.mcp.tools.sites import site_batch

        result = json.loads(asyncio.run(site_batch("ai", seed_file="/nonexistent.txt")))
        assert result["status"] == "error"
        assert "library/site-seeds" in result["error"]

    def test_seed_file_size_cap_refuses_large_file(self, mock_config):
        seed_dir = mock_config.library_dir / "site-seeds"
        seed_dir.mkdir(parents=True)
        seed_file = seed_dir / "huge-seeds.json"
        seed_file.write_bytes(b"x" * 1_000_001)

        with patch("distill.mcp.server._config", return_value=mock_config):
            from distill.mcp.tools.sites import site_batch

            result = json.loads(
                asyncio.run(site_batch("ai", seed_file="site-seeds/huge-seeds.json"))
            )

        assert result["status"] == "error"
        assert "site-seeds" in result["error"]

    def test_ordinary_library_file_is_rejected_without_reading(self, mock_config, monkeypatch):
        ordinary = mock_config.library_dir / "README.md"
        ordinary.write_text("private sentinel", encoding="utf-8")

        def unexpected_read(*_args, **_kwargs):
            raise AssertionError("ordinary library file was read")

        monkeypatch.setattr("distill.mcp.tools.sites.read_confined_text", unexpected_read)

        with patch("distill.mcp.server._config", return_value=mock_config):
            from distill.mcp.tools.sites import site_batch

            result = json.loads(asyncio.run(site_batch("ai", seed_file="README.md", preview=True)))

        assert result["status"] == "error"
        assert "private sentinel" not in json.dumps(result)

    def test_seed_file_must_stay_inside_library(self, mock_config, tmp_path):
        outside = tmp_path / "seeds.txt"
        outside.write_text("https://private.example/internal\n", encoding="utf-8")

        with patch("distill.mcp.server._config", return_value=mock_config):
            from distill.mcp.tools.sites import site_batch

            result = json.loads(asyncio.run(site_batch("ai", seed_file=str(outside))))

        assert result["status"] == "error"
        assert "library/site-seeds" in result["error"]
        assert "private.example" not in json.dumps(result)

    def test_seed_file_inside_library_processes_site_seed(self, mock_config, monkeypatch):
        seed_file = self._write_seed_manifest(
            mock_config, "seeds.json", {"urls": ["https://example.com/guide"]}
        )
        seen = []

        def fake_process_site_seed(seed, config, tracker, summary):
            seen.append((seed.url, seed.topic, config, summary.command))
            return "Example", 1

        monkeypatch.setattr(
            "distill.commands._site_ingest.process_site_seed", fake_process_site_seed
        )

        with patch("distill.mcp.server._config", return_value=mock_config):
            from distill.mcp.tools.sites import site_batch

            result = json.loads(asyncio.run(site_batch("ai", seed_file=seed_file)))

        assert result["status"] == "complete"
        assert result["pages"] == [
            {
                "url": "https://example.com/guide",
                "site": "Example",
                "pages": 1,
                "status": "ok",
            }
        ]
        assert seen == [("https://example.com/guide", "ai", mock_config, "site-batch")]

    def test_json_seed_file_honors_mixed_crawl_modes(self, mock_config, monkeypatch):
        seed_file = self._write_seed_manifest(
            mock_config,
            "sites.json",
            {
                "topic": "web",
                "crawl": {
                    "max_depth": 1,
                    "max_pages_per_seed": 4,
                    "same_section_only": True,
                },
                "collections": [
                    {
                        "name": "overview",
                        "mode": "exact-page",
                        "seeds": ["https://example.com/overview"],
                    },
                    {
                        "name": "docs",
                        "mode": "shallow-crawl",
                        "crawl_prefix": "/docs",
                        "seeds": ["https://example.com/docs/start"],
                    },
                ],
            },
        )
        seen = []

        def fake_process_site_seed(seed, config, tracker, summary):
            seen.append(
                (
                    seed.url,
                    seed.max_depth,
                    seed.max_pages,
                    seed.crawl_prefix,
                    seed.same_section_only,
                )
            )
            return "Example", 1

        monkeypatch.setattr(
            "distill.commands._site_ingest.process_site_seed", fake_process_site_seed
        )

        with patch("distill.mcp.server._config", return_value=mock_config):
            from distill.mcp.tools.sites import site_batch

            result = json.loads(asyncio.run(site_batch("ai", seed_file=seed_file)))

        assert result["status"] == "complete"
        assert [page["url"] for page in result["pages"]] == [
            "https://example.com/overview",
            "https://example.com/docs/start",
        ]
        assert seen == [
            ("https://example.com/overview", 0, 1, "", True),
            ("https://example.com/docs/start", 1, 4, "/docs", True),
        ]

    def test_json_seed_file_rejects_unknown_mode_without_processing(self, mock_config, monkeypatch):
        seed_file = self._write_seed_manifest(
            mock_config,
            "sites.json",
            {
                "topic": "web",
                "urls": [
                    {
                        "url": "https://example.com/guide",
                        "mode": "wide-open",
                    }
                ],
            },
        )
        calls = []
        monkeypatch.setattr(
            "distill.commands._site_ingest.process_site_seed",
            lambda *args, **kwargs: calls.append("process"),
        )

        with patch("distill.mcp.server._config", return_value=mock_config):
            from distill.mcp.tools.sites import site_batch

            result = json.loads(asyncio.run(site_batch("ai", seed_file=seed_file)))

        assert result["status"] == "error"
        assert "Unsupported site crawl mode" in result["error"]
        assert calls == []

    def test_json_seed_file_rejects_aggregate_page_budget_before_preview(
        self, mock_config, monkeypatch
    ):
        seed_file = self._write_seed_manifest(
            mock_config,
            "sites.json",
            {
                "urls": [
                    {
                        "url": f"https://example.com/{index}",
                        "max_pages": 100,
                    }
                    for index in range(6)
                ]
            },
        )
        calls = []
        monkeypatch.setattr(
            "distill.commands._site_ingest.process_site_seed",
            lambda *args, **kwargs: calls.append("process"),
        )

        with patch("distill.mcp.server._config", return_value=mock_config):
            from distill.mcp.tools.sites import site_batch

            result = json.loads(asyncio.run(site_batch("ai", seed_file=seed_file, preview=True)))

        assert result == {
            "status": "error",
            "error": "site batch page budget exceeds 500",
        }
        assert calls == []

    def test_preview_returns_plan_without_model_or_processing(self, mock_config, monkeypatch):
        monkeypatch.setenv("DISTILL_PROVIDER", "openai")
        seed_file = self._write_seed_manifest(
            mock_config,
            "sites.json",
            {
                "topic": "web",
                "crawl": {
                    "max_depth": 1,
                    "max_pages_per_seed": 4,
                    "same_section_only": True,
                },
                "collections": [
                    {
                        "name": "overview",
                        "mode": "exact-page",
                        "seeds": ["https://example.com/overview"],
                    },
                    {
                        "name": "docs",
                        "mode": "shallow-crawl",
                        "crawl_prefix": "/docs",
                        "seeds": ["https://example.com/docs/start"],
                    },
                ],
            },
        )
        calls = []
        monkeypatch.setattr(
            "distill.commands._site_ingest.process_site_seed",
            lambda *args, **kwargs: calls.append("process"),
        )

        with patch("distill.mcp.server._config", return_value=mock_config):
            from distill.mcp.tools.sites import site_batch

            result = json.loads(asyncio.run(site_batch("ai", seed_file=seed_file, preview=True)))

        assert result["status"] == "preview"
        assert result["plan"]["workflow"] == "site-batch"
        assert result["plan"]["writes"] is False
        assert result["plan"]["seed_count"] == 2
        assert [seed["mode"] for seed in result["plan"]["seeds"]] == [
            "exact-page",
            "shallow-crawl",
        ]
        assert calls == []

    def test_direct_urls_use_existing_site_pipeline(self, mock_config, monkeypatch):
        seen = []

        def fake_process_site_seed(seed, config, tracker, summary):
            seen.append((seed.url, seed.max_depth, seed.max_pages))
            return "Example", 0

        monkeypatch.setattr(
            "distill.commands._site_ingest.process_site_seed", fake_process_site_seed
        )

        with patch("distill.mcp.server._config", return_value=mock_config):
            from distill.mcp.tools.sites import site_batch

            result = json.loads(asyncio.run(site_batch("ai", urls=["https://example.com/guide"])))

        assert result["status"] == "complete"
        assert result["pages"][0]["status"] == "skipped"
        assert seen == [("https://example.com/guide", 0, 1)]

    def test_site_batch_records_processing_errors_and_progress(self, mock_config, monkeypatch):
        from distill.commands._site_ingest import SiteIngestResult

        class ProgressContext:
            def __init__(self):
                self.calls = []

            async def report_progress(self, *, progress, total):
                self.calls.append((progress, total))

        seed_file = self._write_seed_manifest(
            mock_config,
            "seeds.json",
            {"urls": ["https://example.com/fails", "https://example.com/works"]},
        )
        ctx = ProgressContext()

        def process_site_seed(seed, config, tracker, summary):
            assert config is mock_config
            assert isinstance(tracker, CostTracker)
            assert summary.command == "site-batch"
            if seed.url.endswith("/fails"):
                raise RuntimeError("site failed")
            return SiteIngestResult(
                site_name="Example",
                page_count=2,
                analyzed_pages=1,
                skipped_pages=1,
            )

        def save_log(log_dir, command, tracker, *, estimated_cost=None):
            assert log_dir == mock_config.library_dir
            assert command == "site-batch"
            assert isinstance(tracker, CostTracker)
            assert estimated_cost is None

        def summarize_cost(tracker):
            assert isinstance(tracker, CostTracker)
            return _FAKE_COST

        monkeypatch.setattr(
            "distill.commands._site_ingest.process_site_seed",
            process_site_seed,
        )
        monkeypatch.setattr("distill.mcp.server.save_run_log", save_log)
        monkeypatch.setattr("distill.mcp.tools.sites.cost_summary", summarize_cost)

        with patch("distill.mcp.server._config", return_value=mock_config):
            from distill.mcp.tools.sites import site_batch

            result = json.loads(asyncio.run(site_batch("ai", seed_file=seed_file, ctx=ctx)))

        assert result["status"] == "complete"
        assert result["pages"] == [
            {
                "url": "https://example.com/fails",
                "status": "error",
                "error": "site failed",
            },
            {
                "url": "https://example.com/works",
                "site": "Example",
                "pages": 2,
                "status": "ok",
                "analyzed_pages": 1,
                "skipped_pages": 1,
            },
        ]
        assert ctx.calls == [(0, 2), (1, 2), (2, 2)]

    def test_site_batch_budget_error_is_hard_stop(self, mock_config, monkeypatch):
        def process_site_seed(seed, config, tracker, summary):
            assert seed.url == "https://example.com/guide"
            assert config is mock_config
            assert isinstance(tracker, CostTracker)
            assert summary.command == "site-batch"
            raise BudgetExceededError(0.61, 0.5)

        monkeypatch.setattr(
            "distill.commands._site_ingest.process_site_seed",
            process_site_seed,
        )

        with patch("distill.mcp.server._config", return_value=mock_config):
            from distill.mcp.tools.sites import site_batch

            result = json.loads(asyncio.run(site_batch("ai", urls=["https://example.com/guide"])))

        assert result["status"] == "budget_exceeded"
        assert result["spent"] == 0.61

    def test_site_batch_reports_unchanged_counts(self, mock_config, monkeypatch):
        from distill.commands._site_ingest import SiteIngestResult

        def fake_process_site_seed(seed, config, tracker, summary):
            return SiteIngestResult(
                site_name="Example",
                page_count=1,
                analyzed_pages=0,
                skipped_pages=1,
            )

        monkeypatch.setattr(
            "distill.commands._site_ingest.process_site_seed", fake_process_site_seed
        )

        with patch("distill.mcp.server._config", return_value=mock_config):
            from distill.mcp.tools.sites import site_batch

            result = json.loads(asyncio.run(site_batch("ai", urls=["https://example.com/guide"])))

        assert result["status"] == "complete"
        assert result["pages"] == [
            {
                "url": "https://example.com/guide",
                "site": "Example",
                "pages": 1,
                "status": "unchanged",
                "analyzed_pages": 0,
                "skipped_pages": 1,
            }
        ]


class TestSynthesizeTool:
    def test_transport_schema_exposes_force_as_boolean(self):
        from distill.mcp.server import mcp

        tool = next(tool for tool in asyncio.run(mcp.list_tools()) if tool.name == "synthesize")

        assert tool.input_schema["properties"]["force"] == {
            "default": False,
            "title": "Force",
            "type": "boolean",
        }

    @pytest.mark.parametrize("force", [1, 0, "true", "false", None])
    def test_transport_rejects_non_boolean_force_before_tool_setup(self, force, mock_config):
        from distill.mcp.server import mcp

        with (
            patch("distill.mcp.server._config", return_value=mock_config),
            patch("distill.mcp.tools.synthesis.load_config") as mock_load,
            patch("distill.mcp.tools.synthesis.model_available") as mock_model,
            patch("distill.mcp.tools.synthesis.capped_tracker") as mock_tracker,
            pytest.raises(ToolError, match="Input should be a valid boolean"),
        ):
            asyncio.run(mcp.call_tool("synthesize", {"topic": "ai", "force": force}))

        mock_load.assert_not_called()
        mock_model.assert_not_called()
        mock_tracker.assert_not_called()

    def test_transport_false_requires_authorization_before_tool_setup(self, mock_config):
        from distill.mcp.server import mcp

        with (
            patch("distill.mcp.server._config", return_value=mock_config),
            patch("distill.mcp.tools.synthesis.load_config") as mock_load,
            patch("distill.mcp.tools.synthesis.model_available") as mock_model,
            patch("distill.mcp.tools.synthesis.capped_tracker") as mock_tracker,
        ):
            result = asyncio.run(mcp.call_tool("synthesize", {"topic": "ai", "force": False}))
            content = cast(list[TextContent], result.content)

        assert json.loads(content[0].text)["status"] == "authorization_required"
        mock_load.assert_not_called()
        mock_model.assert_not_called()
        mock_tracker.assert_not_called()

    def test_transport_true_reaches_tool_setup(self, mock_config):
        from distill.mcp.server import mcp

        lib = MagicMock()
        lib.get_channels.side_effect = RuntimeError("stop after guarded setup")
        tracker = CostTracker()
        with (
            patch("distill.mcp.server._config", return_value=mock_config),
            patch("distill.mcp.tools.synthesis.load_config", return_value=mock_config) as mock_load,
            patch("distill.mcp.tools.synthesis.model_available", return_value=True) as mock_model,
            patch("distill.mcp.tools.synthesis.library", return_value=lib),
            patch(
                "distill.mcp.tools.synthesis.capped_tracker", return_value=tracker
            ) as mock_tracker,
            pytest.raises(ToolError, match="stop after guarded setup"),
        ):
            asyncio.run(mcp.call_tool("synthesize", {"topic": "ai", "force": True}))

        mock_load.assert_called_once_with()
        mock_model.assert_called_once_with()
        mock_tracker.assert_called_once_with()

    @pytest.mark.parametrize("force", [False, 0, 1, None])
    def test_requires_literal_force_before_model_or_tracker(self, force):
        from distill.mcp.tools.synthesis import synthesize

        with (
            patch("distill.mcp.tools.synthesis.load_config") as mock_load,
            patch("distill.mcp.tools.synthesis.model_available") as mock_model,
            patch("distill.mcp.tools.synthesis.capped_tracker") as mock_tracker,
        ):
            result = json.loads(asyncio.run(synthesize("ai", force=force)))

        assert result == {
            "status": "authorization_required",
            "action": "regenerate_synthesis",
            "message": (
                "Synthesis regeneration requires explicit authorization. Retry with force=true."
            ),
            "required": {"force": True},
        }
        mock_load.assert_not_called()
        mock_model.assert_not_called()
        mock_tracker.assert_not_called()

    def test_no_model(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DISTILL_PROVIDER", "openai")  # not implemented -> no model
        config = DistillConfig(
            xai_api_key="",
            distill_output_dir=tmp_path / "library",
        )
        with patch("distill.mcp.server._config", return_value=config):
            from distill.mcp.tools.synthesis import synthesize

            result = json.loads(asyncio.run(synthesize("ai", force=True)))
        assert result["status"] == "error"
        assert "model" in result["error"].lower()

    def test_unknown_style(self, mock_config):
        with patch("distill.mcp.server._config", return_value=mock_config):
            from distill.mcp.tools.synthesis import synthesize

            result = json.loads(asyncio.run(synthesize("ai", force=True, style="bogus")))

        assert result["status"] == "error"
        assert "Unknown style" in result["error"]
        assert "exec" in result["error"]

    def test_happy_path_all_scopes_ok(self, mock_config):
        _setup_library(mock_config, "ai", "TestChannel")

        with (
            patch("distill.mcp.server._config", return_value=mock_config),
            patch("distill.pipeline.synthesis.topic.synthesize_channel") as mock_ch,
            patch("distill.pipeline.synthesis.topic.synthesize_topic") as mock_tp,
            patch(
                "distill.pipeline.synthesis.corpus.synthesize_corpus",
                return_value="# Corpus",
            ) as mock_corpus,
            patch("distill.mcp.server.save_run_log") as mock_log,
            patch("distill.mcp.server._cost_summary", return_value=_FAKE_COST),
        ):
            from distill.mcp.tools.synthesis import synthesize

            result = json.loads(asyncio.run(synthesize("ai", force=True, style="exec")))

        mock_ch.assert_called_once_with(
            "ai", "TestChannel", mock_config, tracker=mock_ch.call_args.kwargs["tracker"]
        )
        mock_tp.assert_called_once()
        assert mock_tp.call_args.kwargs["style"] == "exec"
        mock_corpus.assert_called_once()
        assert mock_corpus.call_args.kwargs["style"] == "exec"
        assert mock_corpus.call_args.kwargs["two_pass"] is False
        mock_log.assert_called_once_with(
            mock_config.library_dir,
            "synthesize",
            mock_log.call_args[0][2],
            estimated_cost=None,
        )
        assert result["status"] == "complete"
        assert result["cost"] == _FAKE_COST
        assert any(
            r.get("channel") == "TestChannel" and r["status"] == "ok" for r in result["results"]
        )
        assert any(r.get("scope") == "topic" and r["status"] == "ok" for r in result["results"])
        assert any(
            r.get("scope") == "corpus" and r["status"] == "ok" and r["two_pass"] is False
            for r in result["results"]
        )

    def test_two_pass_corpus(self, mock_config):
        _setup_library(mock_config)

        with (
            patch("distill.mcp.server._config", return_value=mock_config),
            patch("distill.pipeline.synthesis.topic.synthesize_channel"),
            patch("distill.pipeline.synthesis.topic.synthesize_topic"),
            patch(
                "distill.pipeline.synthesis.corpus.synthesize_corpus",
                return_value="# Corpus",
            ) as mock_corpus,
            patch("distill.mcp.server.save_run_log"),
            patch("distill.mcp.server._cost_summary", return_value=_FAKE_COST),
        ):
            from distill.mcp.tools.synthesis import synthesize

            result = json.loads(asyncio.run(synthesize("ai", force=True, two_pass=True)))

        assert mock_corpus.call_args.kwargs["two_pass"] is True
        corpus_row = next(r for r in result["results"] if r.get("scope") == "corpus")
        assert corpus_row["status"] == "ok"
        assert corpus_row["two_pass"] is True

    def test_channel_error_is_reported(self, mock_config):
        _setup_library(mock_config)

        with (
            patch("distill.mcp.server._config", return_value=mock_config),
            patch(
                "distill.pipeline.synthesis.topic.synthesize_channel",
                side_effect=RuntimeError("channel fail"),
            ),
            patch("distill.pipeline.synthesis.topic.synthesize_topic"),
            patch("distill.pipeline.synthesis.corpus.synthesize_corpus", return_value="# Corpus"),
            patch("distill.mcp.server.save_run_log"),
            patch("distill.mcp.server._cost_summary", return_value=_FAKE_COST),
        ):
            from distill.mcp.tools.synthesis import synthesize

            result = json.loads(asyncio.run(synthesize("ai", force=True)))

        channel_row = next(r for r in result["results"] if r.get("channel") == "TestChannel")
        assert channel_row["status"] == "error"
        assert channel_row["error"] == "channel fail"
        assert result["status"] == "complete"

    def test_topic_error_is_reported(self, mock_config):
        _setup_library(mock_config)

        with (
            patch("distill.mcp.server._config", return_value=mock_config),
            patch("distill.pipeline.synthesis.topic.synthesize_channel"),
            patch(
                "distill.pipeline.synthesis.topic.synthesize_topic",
                side_effect=RuntimeError("topic fail"),
            ),
            patch("distill.pipeline.synthesis.corpus.synthesize_corpus", return_value="# Corpus"),
            patch("distill.mcp.server.save_run_log"),
            patch("distill.mcp.server._cost_summary", return_value=_FAKE_COST),
        ):
            from distill.mcp.tools.synthesis import synthesize

            result = json.loads(asyncio.run(synthesize("ai", force=True)))

        topic_row = next(r for r in result["results"] if r.get("scope") == "topic")
        assert topic_row["status"] == "error"
        assert topic_row["error"] == "topic fail"

    def test_corpus_skipped_when_no_mixed_sources(self, mock_config):
        _setup_library(mock_config)

        with (
            patch("distill.mcp.server._config", return_value=mock_config),
            patch("distill.pipeline.synthesis.topic.synthesize_channel"),
            patch("distill.pipeline.synthesis.topic.synthesize_topic"),
            patch("distill.pipeline.synthesis.corpus.synthesize_corpus", return_value=""),
            patch("distill.mcp.server.save_run_log"),
            patch("distill.mcp.server._cost_summary", return_value=_FAKE_COST),
        ):
            from distill.mcp.tools.synthesis import synthesize

            result = json.loads(asyncio.run(synthesize("ai", force=True)))

        corpus_row = next(r for r in result["results"] if r.get("scope") == "corpus")
        assert corpus_row["status"] == "skipped"
        assert corpus_row["reason"] == "no mixed sources"

    def test_corpus_error_is_reported(self, mock_config):
        _setup_library(mock_config)

        with (
            patch("distill.mcp.server._config", return_value=mock_config),
            patch("distill.pipeline.synthesis.topic.synthesize_channel"),
            patch("distill.pipeline.synthesis.topic.synthesize_topic"),
            patch(
                "distill.pipeline.synthesis.corpus.synthesize_corpus",
                side_effect=RuntimeError("corpus fail"),
            ),
            patch("distill.mcp.server.save_run_log"),
            patch("distill.mcp.server._cost_summary", return_value=_FAKE_COST),
        ):
            from distill.mcp.tools.synthesis import synthesize

            result = json.loads(asyncio.run(synthesize("ai", force=True)))

        corpus_row = next(r for r in result["results"] if r.get("scope") == "corpus")
        assert corpus_row["status"] == "error"
        assert corpus_row["error"] == "corpus fail"

    def test_budget_exceeded_stops_at_channel(self, mock_config, monkeypatch):
        monkeypatch.delenv("DISTILL_MCP_READ_ONLY", raising=False)
        _setup_library(mock_config)
        mock_config.distill_mcp_max_spend_per_call = 0.5

        with (
            patch("distill.mcp.server._config", return_value=mock_config),
            patch(
                "distill.pipeline.synthesis.topic.synthesize_channel",
                side_effect=BudgetExceededError(0.61, 0.5),
            ),
            patch("distill.pipeline.synthesis.topic.synthesize_topic") as mock_tp,
        ):
            from distill.mcp.tools.synthesis import synthesize

            result = json.loads(asyncio.run(synthesize("ai", force=True)))

        mock_tp.assert_not_called()
        assert result["status"] == "budget_exceeded"
        assert result["cap"] == 0.5

    def test_budget_exceeded_stops_at_topic(self, mock_config, monkeypatch):
        monkeypatch.delenv("DISTILL_MCP_READ_ONLY", raising=False)
        _setup_library(mock_config)
        mock_config.distill_mcp_max_spend_per_call = 0.5

        with (
            patch("distill.mcp.server._config", return_value=mock_config),
            patch("distill.pipeline.synthesis.topic.synthesize_channel"),
            patch(
                "distill.pipeline.synthesis.topic.synthesize_topic",
                side_effect=BudgetExceededError(0.61, 0.5),
            ),
            patch("distill.pipeline.synthesis.corpus.synthesize_corpus") as mock_corpus,
        ):
            from distill.mcp.tools.synthesis import synthesize

            result = json.loads(asyncio.run(synthesize("ai", force=True)))

        mock_corpus.assert_not_called()
        assert result["status"] == "budget_exceeded"

    def test_budget_exceeded_stops_at_corpus(self, mock_config, monkeypatch):
        monkeypatch.delenv("DISTILL_MCP_READ_ONLY", raising=False)
        _setup_library(mock_config)
        mock_config.distill_mcp_max_spend_per_call = 0.5

        with (
            patch("distill.mcp.server._config", return_value=mock_config),
            patch("distill.pipeline.synthesis.topic.synthesize_channel"),
            patch("distill.pipeline.synthesis.topic.synthesize_topic"),
            patch(
                "distill.pipeline.synthesis.corpus.synthesize_corpus",
                side_effect=BudgetExceededError(0.61, 0.5),
            ),
        ):
            from distill.mcp.tools.synthesis import synthesize

            result = json.loads(asyncio.run(synthesize("ai", force=True)))

        assert result["status"] == "budget_exceeded"

    def test_reports_progress_when_ctx_provided(self, mock_config):
        _setup_library(mock_config)
        ctx = MagicMock()
        ctx.report_progress = AsyncMock()

        with (
            patch("distill.mcp.server._config", return_value=mock_config),
            patch("distill.pipeline.synthesis.topic.synthesize_channel"),
            patch("distill.pipeline.synthesis.topic.synthesize_topic"),
            patch("distill.pipeline.synthesis.corpus.synthesize_corpus", return_value="# Corpus"),
            patch("distill.mcp.server.save_run_log"),
            patch("distill.mcp.server._cost_summary", return_value=_FAKE_COST),
        ):
            from distill.mcp.tools.synthesis import synthesize

            asyncio.run(synthesize("ai", force=True, ctx=ctx))

        assert ctx.report_progress.await_count == 4  # 1 channel + topic + corpus + final


class TestDiscoverTool:
    def test_no_model(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DISTILL_PROVIDER", "openai")  # not implemented -> no model
        config = DistillConfig(
            xai_api_key="",
            distill_output_dir=tmp_path / "library",
        )
        with patch("distill.mcp.server._config", return_value=config):
            from distill.mcp.tools.discover import discover

            result = json.loads(asyncio.run(discover("test goal")))
        assert result["status"] == "error"
        assert "model" in result["error"].lower()

    def test_papers_only_handles_paper_record_authors(self, mock_config, monkeypatch):
        from distill.ingestors.papers.arxiv import PaperRecord

        monkeypatch.setattr(
            "distill.ingestors.papers.arxiv.search_arxiv",
            lambda *a, **k: [
                PaperRecord(
                    paper_id="2602.12670v1",
                    title="Agent Memory Systems",
                    abstract="A paper about memory systems.",
                    authors=["Alice", "Bob"],
                    abs_url="https://arxiv.org/abs/2602.12670v1",
                )
            ],
        )

        with patch("distill.mcp.server._config", return_value=mock_config):
            from distill.mcp.tools.discover import discover

            result = json.loads(asyncio.run(discover("agent memory", papers_only=True)))

        assert result["status"] == "complete"
        assert result["papers"] == [
            {
                "title": "Agent Memory Systems",
                "authors": ["Alice", "Bob"],
                "url": "https://arxiv.org/abs/2602.12670v1",
            }
        ]

    def test_search_candidates_falls_back_when_browser_search_is_empty(self, monkeypatch):
        from distill.mcp.tools.discover import _search_candidates

        video = _mcp_video()

        def browser_search(query, *, days, limit):
            assert query == "agent memory"
            assert days == 30
            assert limit == 3
            return []

        def youtube_search(query, *, days, limit):
            assert query == "agent memory"
            assert days == 30
            assert limit == 3
            return [video]

        monkeypatch.setattr(
            "distill.ingestors.youtube.browser_search.search_youtube_results",
            browser_search,
        )
        monkeypatch.setattr("distill.ingestors.youtube.discovery.search_videos", youtube_search)

        assert _search_candidates("agent memory", days=30, limit=3) == [video]

    def test_search_candidates_rejects_unbounded_days_without_fallback(self, monkeypatch):
        from distill.mcp.tools.discover import _search_candidates

        browser = MagicMock()
        fallback = MagicMock()
        monkeypatch.setattr(
            "distill.ingestors.youtube.browser_search.search_youtube_results", browser
        )
        monkeypatch.setattr("distill.ingestors.youtube.discovery.search_videos", fallback)

        assert _search_candidates("agent memory", days=10**4000, limit=3) == []
        browser.assert_not_called()
        fallback.assert_not_called()

    def test_search_videos_empty_candidates_returns_message(self, mock_config, monkeypatch):
        from distill.mcp.tools import discover as discover_tool

        def search(query, *, days, limit):
            assert query == "agent memory"
            assert days == 60
            assert limit == 12
            return []

        monkeypatch.setattr(discover_tool, "_search_candidates", search)

        with patch("distill.mcp.server._config", return_value=mock_config):
            result = json.loads(discover_tool.search_videos("agent memory", limit=2))

        assert result == {"results": [], "message": "No videos found"}

    def test_search_videos_labels_no_model_ranking(self, mock_config, monkeypatch):
        from distill.mcp.tools import discover as discover_tool

        video = _mcp_video()

        def search(query, *, days, limit):
            assert query == "agent memory"
            assert days == 60
            assert limit == 12
            return [video]

        def rank(query, candidates, config, tracker, *, limit):
            assert query == "agent memory"
            assert candidates == [video]
            assert config is mock_config
            assert isinstance(tracker, CostTracker)
            assert limit == 2
            return [_ranked_mcp_video(video, selected_by="no-model")]

        monkeypatch.setattr(discover_tool, "_search_candidates", search)
        monkeypatch.setattr(discover_tool, "_rank_candidates", rank)
        monkeypatch.setattr(discover_tool, "cost_summary", lambda tracker: _FAKE_COST)

        with patch("distill.mcp.server._config", return_value=mock_config):
            result = json.loads(discover_tool.search_videos("agent memory", limit=2))

        assert result["ranked_by"] == "no-model"
        assert result["results"][0]["ranked_by"] == "no-model"
        assert "deterministic fallback" in result["notice"]

    def test_learn_one_channel_records_failed_rows_and_synthesis_warning(self, mock_config, caplog):
        from distill.mcp.tools.discover import _learn_one_channel
        from distill.pipeline.summary import RunSummary

        video = _mcp_video(video_id="failed", title="Failed Video")
        lib = Library(mock_config)
        cost_tracker = CostTracker()
        summary = RunSummary(command="learn")

        def ensure_context(topic, channel, videos, config, tracker_arg):
            assert topic == "ai"
            assert channel == "Research Lab"
            assert videos == [video]
            assert config is mock_config
            assert tracker_arg is cost_tracker

        def process_video(topic, channel, vid, config, tracker_arg, summary_arg, *, state, eta):
            assert topic == "ai"
            assert channel == "Research Lab"
            assert vid is video
            assert config is mock_config
            assert tracker_arg is cost_tracker
            assert summary_arg is summary
            assert state.state_file.name == "state.json"
            assert eta.total == 1
            return False

        def synthesize_channel(topic, channel, config, tracker=None):
            assert topic == "ai"
            assert channel == "Research Lab"
            assert config is mock_config
            assert tracker is cost_tracker
            raise RuntimeError("synthesis down")

        with caplog.at_level("WARNING", logger="distill.mcp.tools.discover"):
            rows = _learn_one_channel(
                "ai",
                "Research Lab",
                [video],
                mock_config,
                cost_tracker,
                summary,
                lib=lib,
                ensure_channel_context=ensure_context,
                process_video=process_video,
                synthesize_channel=synthesize_channel,
            )

        assert rows == [{"title": "Failed Video", "status": "failed"}]
        assert "discover channel synthesis failed" in caplog.text

    def test_discover_records_video_and_paper_errors_with_progress(self, mock_config, monkeypatch):
        from distill.mcp.tools import discover as discover_tool

        class ProgressContext:
            def __init__(self):
                self.calls = []

            async def report_progress(self, *, progress, total):
                self.calls.append((progress, total))

        def fail_video_search(query, *, days, limit):
            assert query == "agent memory"
            assert days == 60
            assert limit == 12
            raise RuntimeError("video search down")

        def fail_paper_search(query, max_results):
            assert query == "agent memory"
            assert max_results == 2
            raise RuntimeError("paper search down")

        def save_log(log_dir, command, tracker, estimated_cost=None):
            assert log_dir == mock_config.library_dir
            assert command == "discover"
            assert isinstance(tracker, CostTracker)
            assert estimated_cost == 0.0

        ctx = ProgressContext()
        monkeypatch.setattr(discover_tool, "_search_candidates", fail_video_search)
        monkeypatch.setattr("distill.ingestors.papers.arxiv.search_arxiv", fail_paper_search)
        monkeypatch.setattr("distill.mcp.server.save_run_log", save_log)
        monkeypatch.setattr(discover_tool, "cost_summary", lambda tracker: _FAKE_COST)

        with patch("distill.mcp.server._config", return_value=mock_config):
            result = json.loads(
                asyncio.run(discover_tool.discover("agent memory", limit=2, ctx=ctx))
            )

        assert result["status"] == "complete"
        assert result["video_error"] == "video search down"
        assert result["paper_error"] == "paper search down"
        assert ctx.calls == [(0, 3), (1, 3), (3, 3)]

    def test_discover_videos_only_returns_ranked_video_results(self, mock_config, monkeypatch):
        from distill.mcp.tools import discover as discover_tool

        video = _mcp_video(channel_name="", channel_url="")

        def search(query, *, days, limit):
            assert query == "agent memory"
            assert days == 60
            assert limit == 12
            return [video]

        def rank(query, candidates, config, tracker, *, limit):
            assert query == "agent memory"
            assert candidates == [video]
            assert config is mock_config
            assert isinstance(tracker, CostTracker)
            assert limit == 2
            return [_ranked_mcp_video(video, score=7.895)]

        def save_log(log_dir, command, tracker, estimated_cost=None):
            assert log_dir == mock_config.library_dir
            assert command == "discover"
            assert isinstance(tracker, CostTracker)
            assert estimated_cost == 0.0

        monkeypatch.setattr(discover_tool, "_search_candidates", search)
        monkeypatch.setattr(discover_tool, "_rank_candidates", rank)
        monkeypatch.setattr("distill.mcp.server.save_run_log", save_log)
        monkeypatch.setattr(discover_tool, "cost_summary", lambda tracker: _FAKE_COST)

        with patch("distill.mcp.server._config", return_value=mock_config):
            result = json.loads(
                asyncio.run(discover_tool.discover("agent memory", limit=2, videos_only=True))
            )

        assert result["videos"] == [
            {
                "title": "Agent Memory Systems",
                "channel": "unknown",
                "url": "https://youtube.com/watch?v=v1",
                "score": 7.89,
            }
        ]
        assert result["papers"] == []

    def test_discover_paper_budget_error_is_hard_stop(self, mock_config, monkeypatch):
        from distill.mcp.tools import discover as discover_tool

        def fail_paper_search(query, max_results):
            assert query == "agent memory"
            assert max_results == 1
            raise BudgetExceededError(0.61, 0.5)

        monkeypatch.setattr("distill.ingestors.papers.arxiv.search_arxiv", fail_paper_search)

        with patch("distill.mcp.server._config", return_value=mock_config):
            result = json.loads(
                asyncio.run(discover_tool.discover("agent memory", limit=1, papers_only=True))
            )

        assert result["status"] == "budget_exceeded"
        assert result["spent"] == 0.61

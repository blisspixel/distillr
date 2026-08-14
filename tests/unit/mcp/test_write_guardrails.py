"""Tests for the narrower MCP write-side guardrails (0.12.9).

For deployments that DO expose the write tools (read-only off), two
finer-grained controls: DISTILL_MCP_MAX_SPEND_PER_CALL caps each tool call's
admitted and recorded spend, and DISTILL_MCP_INGEST_ALLOWLIST confines
URL-taking ingest tools to operator-approved hosts.
"""

from __future__ import annotations

import json

import pytest

from distill.config import DistillConfig
from distill.mcp import server as _server
from distill.pipeline.costs import (
    BudgetExceededError,
    CostTracker,
    ProjectedBudgetExceededError,
    TokenUsage,
    UnboundedProviderCostError,
)


def _usage(prompt: int = 100_000, completion: int = 50_000) -> TokenUsage:
    return TokenUsage(
        prompt_tokens=prompt, completion_tokens=completion, model="grok-4.3", call_type="x"
    )


class TestBudgetTracker:
    def test_crossing_call_stays_on_ledger_then_raises(self):
        tracker = CostTracker(budget=0.01)
        with pytest.raises(BudgetExceededError) as exc_info:
            tracker.record(_usage())
        assert len(tracker.entries) == 1  # no off-ledger spend, ever
        assert exc_info.value.spent > 0.01
        assert exc_info.value.budget == 0.01

    def test_under_budget_records_freely(self):
        tracker = CostTracker(budget=10.0)
        tracker.record(_usage())
        tracker.record(_usage())
        assert len(tracker.entries) == 2

    def test_no_budget_never_raises(self):
        tracker = CostTracker()
        for _ in range(5):
            tracker.record(_usage())
        assert tracker.total_cost > 1.0

    def test_transcription_spend_counts_against_budget(self):
        tracker = CostTracker(budget=0.01)
        with pytest.raises(BudgetExceededError):
            tracker.record_transcription("openai", duration_s=3600.0)
        assert len(tracker.transcriptions) == 1

    def test_capped_tracker_reads_config(self, monkeypatch):
        config = DistillConfig(xai_api_key="t", distill_mcp_max_spend_per_call=0.5)
        monkeypatch.setattr(_server, "_config", lambda: config)
        assert _server.capped_tracker().budget == 0.5

    def test_capped_tracker_unset_means_uncapped(self, monkeypatch):
        config = DistillConfig(xai_api_key="t")
        monkeypatch.setattr(_server, "_config", lambda: config)
        assert _server.capped_tracker().budget is None


class TestWriteToolBudgetCatch:
    def test_budget_error_becomes_structured_response(self, monkeypatch):
        config = DistillConfig(xai_api_key="t")
        monkeypatch.setattr(_server, "_config", lambda: config)

        @_server.write_tool("expensive_thing")
        def expensive_thing() -> str:
            raise BudgetExceededError(0.61, 0.5)

        result = json.loads(expensive_thing())
        assert result["status"] == "budget_exceeded"
        assert result["spent"] == 0.61
        assert result["cap"] == 0.5
        assert result["action"] == "expensive_thing"
        assert result["phase"] == "gate.budget"
        assert result["limit"]["kind"] == "max_spend_per_call"
        assert result["telemetry_path"] == ".distill/phase_telemetry.jsonl"
        assert "expensive_thing" in result["error"]
        assert "converges" in result["error"]

    def test_async_write_tool_budget_catch(self, monkeypatch):
        import asyncio

        config = DistillConfig(xai_api_key="t")
        monkeypatch.setattr(_server, "_config", lambda: config)

        @_server.write_tool("expensive_async")
        async def expensive_async() -> str:
            raise BudgetExceededError(1.2, 1.0)

        result = json.loads(asyncio.run(expensive_async()))
        assert result["status"] == "budget_exceeded"

    def test_projected_budget_response_is_explicit(self, monkeypatch):
        config = DistillConfig(xai_api_key="t")
        monkeypatch.setattr(_server, "_config", lambda: config)

        @_server.write_tool("projected_thing")
        def projected_thing() -> str:
            raise ProjectedBudgetExceededError(0.61, 0.5)

        result = json.loads(projected_thing())
        assert result["status"] == "budget_exceeded"
        assert result["projected"] is True
        assert result["projected_usd"] == 0.61

    def test_unbounded_provider_budget_response_does_not_suggest_raising_cap(self, monkeypatch):
        config = DistillConfig(xai_api_key="t")
        monkeypatch.setattr(_server, "_config", lambda: config)

        @_server.write_tool("deep_report")
        def deep_report() -> str:
            raise UnboundedProviderCostError("Gemini Deep Research", 0.0, 0.5)

        result = json.loads(deep_report())
        assert result["status"] == "budget_exceeded"
        assert result["unbounded_external_cost"] is True
        assert result["provider"] == "Gemini Deep Research"
        assert result["limit"]["kind"] == "provider_unbounded_cost"
        assert "Raising DISTILL_MCP_MAX_SPEND_PER_CALL cannot" in result["error"]


class TestIngestAllowlist:
    def _config_with(self, allowlist: str) -> DistillConfig:
        return DistillConfig(xai_api_key="t", distill_mcp_ingest_allowlist=allowlist)

    def test_unset_allows_everything(self, monkeypatch):
        monkeypatch.setattr(_server, "_config", lambda: self._config_with(""))
        assert _server.refuse_if_host_not_allowed("https://evil.example/x") is None

    def test_exact_host_allowed(self, monkeypatch):
        monkeypatch.setattr(_server, "_config", lambda: self._config_with("youtube.com"))
        assert _server.refuse_if_host_not_allowed("https://youtube.com/watch?v=x") is None

    def test_subdomain_allowed(self, monkeypatch):
        monkeypatch.setattr(_server, "_config", lambda: self._config_with("youtube.com"))
        assert _server.refuse_if_host_not_allowed("https://www.youtube.com/watch?v=x") is None

    def test_suffix_lookalike_refused(self, monkeypatch):
        # evilyoutube.com must not pass a youtube.com allowlist.
        monkeypatch.setattr(_server, "_config", lambda: self._config_with("youtube.com"))
        refusal = _server.refuse_if_host_not_allowed("https://evilyoutube.com/watch")
        assert refusal is not None
        assert json.loads(refusal)["status"] == "domain_not_allowed"

    def test_off_list_host_refused_with_list_named(self, monkeypatch):
        monkeypatch.setattr(
            _server, "_config", lambda: self._config_with("youtube.com, learn.microsoft.com")
        )
        result = json.loads(
            _server.refuse_if_host_not_allowed("https://pastebin.com/raw/x", action="site_batch")
        )
        assert result["status"] == "domain_not_allowed"
        assert "pastebin.com" in result["error"]
        assert "youtube.com" in result["error"]
        assert result["action"] == "site_batch"
        assert result["phase"] == "gate.ingest_allowlist"
        assert result["limit"]["kind"] == "ingest_allowlist"
        assert result["limit"]["requested_host"] == "pastebin.com"
        assert "youtube.com" in result["limit"]["hosts"]
        assert result["telemetry_path"] == ".distill/phase_telemetry.jsonl"

    def test_unparseable_url_refused_when_list_set(self, monkeypatch):
        monkeypatch.setattr(_server, "_config", lambda: self._config_with("youtube.com"))
        assert _server.refuse_if_host_not_allowed("not a url") is not None


class TestBudgetPassthroughInToolLoops:
    def test_papers_loop_reraises_budget_to_write_tool(self, tmp_path, monkeypatch):
        """The 0.12.13 harden-pass bug: the per-paper loop's `except Exception`
        swallowed BudgetExceededError, so a capped run kept burning spend paper
        after paper. The loop must re-raise it so write_tool answers."""
        import asyncio
        from types import SimpleNamespace

        monkeypatch.delenv("DISTILL_MCP_READ_ONLY", raising=False)
        import distill.pipeline.analysis.paper as paper_mod
        from distill.mcp.tools.papers import papers

        config = DistillConfig(
            xai_api_key="t",
            distill_output_dir=tmp_path / "lib",
            distill_mcp_max_spend_per_call=0.5,
        )
        monkeypatch.setattr(_server, "_config", lambda: config)

        fake_papers = [SimpleNamespace(title=f"p{i}", paper_id=f"260{i}") for i in range(3)]
        monkeypatch.setattr(
            "distill.ingestors.papers.arxiv.search_arxiv", lambda q, max_results: fake_papers
        )
        calls = {"n": 0}

        def exploding_analyze(paper, config, tracker=None, intent=None):
            calls["n"] += 1
            raise BudgetExceededError(0.61, 0.5)

        monkeypatch.setattr(paper_mod, "analyze_paper", exploding_analyze)

        result = json.loads(asyncio.run(papers("t", "query", limit=3)))

        assert result["status"] == "budget_exceeded"
        assert calls["n"] == 1  # the loop stopped at the cap; no further spend


class TestToolWiring:
    def test_process_video_url_refuses_off_list_host(self, monkeypatch):
        monkeypatch.delenv("DISTILL_MCP_READ_ONLY", raising=False)
        from distill.mcp.tools.topics import process_video_url

        config = DistillConfig(xai_api_key="t", distill_mcp_ingest_allowlist="learn.microsoft.com")
        monkeypatch.setattr(_server, "_config", lambda: config)
        result = json.loads(process_video_url("https://youtube.com/watch?v=x"))
        assert result["status"] == "domain_not_allowed"

    def test_watch_add_refuses_off_list_host(self, monkeypatch):
        monkeypatch.delenv("DISTILL_MCP_READ_ONLY", raising=False)
        from distill.mcp.tools.watch import watch_add

        config = DistillConfig(xai_api_key="t", distill_mcp_ingest_allowlist="learn.microsoft.com")
        monkeypatch.setattr(_server, "_config", lambda: config)
        result = json.loads(watch_add("https://youtube.com/@chan"))
        assert result["status"] == "domain_not_allowed"

    def test_catch_up_skips_off_list_stored_watch_urls(self, tmp_path, monkeypatch):
        """Stored watch URLs must re-check the allowlist on catch_up."""
        monkeypatch.delenv("DISTILL_MCP_READ_ONLY", raising=False)
        from distill.library import Library
        from distill.mcp.tools.watch import catch_up

        config = DistillConfig(
            xai_api_key="t",
            distill_output_dir=tmp_path / "lib",
            distill_mcp_ingest_allowlist="learn.microsoft.com",
        )
        config.library_dir.mkdir(parents=True, exist_ok=True)
        lib = Library(config)
        lib.add_to_watchlist(
            "https://www.youtube.com/@blocked",
            "blocked",
            topic="watch",
            days=7,
        )
        monkeypatch.setattr(_server, "_config", lambda: config)
        monkeypatch.setattr(
            "distill.mcp.tools.watch.model_available",
            lambda: True,
        )

        result = json.loads(catch_up())
        assert result["results"]
        assert result["results"][0]["status"] == "domain_not_allowed"
        assert "learn.microsoft.com" in result["results"][0]["error"]

    def test_site_batch_refuses_when_any_url_off_list(self, monkeypatch):
        import asyncio

        monkeypatch.delenv("DISTILL_MCP_READ_ONLY", raising=False)
        from distill.mcp.tools.sites import site_batch

        config = DistillConfig(xai_api_key="t", distill_mcp_ingest_allowlist="microsoft.com")
        monkeypatch.setattr(_server, "_config", lambda: config)
        result = json.loads(
            asyncio.run(
                site_batch("t", urls=["https://learn.microsoft.com/a", "https://evil.example/b"])
            )
        )
        assert result["status"] == "domain_not_allowed"
        assert "evil.example" in result["error"]

    def test_search_videos_budget_error_becomes_structured_response(self, tmp_path, monkeypatch):
        monkeypatch.delenv("DISTILL_MCP_READ_ONLY", raising=False)
        from distill.ingestors.youtube.discovery import VideoInfo
        from distill.mcp.tools.discover import search_videos

        config = DistillConfig(
            xai_api_key="t",
            distill_output_dir=tmp_path / "library",
            distill_mcp_max_spend_per_call=0.5,
        )
        monkeypatch.setattr(_server, "_config", lambda: config)
        monkeypatch.setattr(
            "distill.mcp.tools.discover._search_candidates",
            lambda *args, **kwargs: [
                VideoInfo(
                    video_id="v1",
                    title="V",
                    upload_date="20260101",
                    duration=100,
                    url="https://youtube.com/watch?v=v1",
                    channel_name="C",
                    view_count=1,
                )
            ],
        )

        def budget_stop(query, candidates, config, tracker, *, limit):
            tracker.record(_usage(prompt=10_000_000, completion=5_000_000))

        monkeypatch.setattr("distill.mcp.tools.discover._rank_candidates", budget_stop)

        result = json.loads(search_videos("budget"))

        assert result["status"] == "budget_exceeded"
        assert result["spent"] > 0.5
        rows = [
            json.loads(line)
            for line in (config.library_dir / ".distill" / "cost_log.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        assert len(rows) == 1
        assert rows[0]["command"] == "search-videos"
        assert rows[0]["grok_calls"] == 1
        assert rows[0]["actual_cost"] == result["spent"]

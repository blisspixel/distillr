"""Tests for the sub-agent summary engine (bounded, query-focused, revision-cached)."""

from __future__ import annotations

import json

import pytest

from distill.config import DistillConfig
from distill.llm.router import LLM_Response
from distill.pipeline import summary_query as sq_mod


@pytest.fixture
def config(tmp_path):
    return DistillConfig(xai_api_key="t", distill_output_dir=tmp_path / "library")


def _seed(config, name="checker", body=None):
    d = config.topic_dir("t") / "papers" / name
    d.mkdir(parents=True, exist_ok=True)
    text = body or "HHEM reaches 0.878 ROC-AUC on grounding verification benchmarks."
    (d / f"{name}_Insights.md").write_text(f"---\n---\n\n{text}\n", encoding="utf-8")
    return d / f"{name}_Insights.md"


def _patch_llm(monkeypatch, calls: list):
    def fake(rc, **kwargs):
        calls.append(kwargs)
        return LLM_Response(
            text="HHEM hits 0.878 ROC-AUC [checker_Insights].",
            input_tokens=10,
            output_tokens=10,
            model="grok-4.3",
        )

    monkeypatch.setattr(sq_mod, "llm_call", fake)


class TestSummarizeQuery:
    def test_summary_with_citations_and_cache_write(self, config, monkeypatch):
        _seed(config)
        calls: list = []
        _patch_llm(monkeypatch, calls)

        result = sq_mod.summarize_query(config, "t", "grounding verification")

        assert result is not None and not result.cached
        assert result.sources == ["checker_Insights"]
        assert len(calls) == 1
        cache_dir = config.library_dir / ".distill" / "summary_cache"
        assert len(list(cache_dir.glob("*.json"))) == 1

    def test_cache_hit_makes_no_model_call(self, config, monkeypatch):
        _seed(config)
        calls: list = []
        _patch_llm(monkeypatch, calls)

        first = sq_mod.summarize_query(config, "t", "grounding verification")
        second = sq_mod.summarize_query(config, "t", "grounding verification")

        assert first is not None and second is not None
        assert second.cached and second.summary == first.summary
        assert len(calls) == 1  # the whole point

    def test_corpus_change_invalidates_cache(self, config, monkeypatch):
        path = _seed(config)
        calls: list = []
        _patch_llm(monkeypatch, calls)
        sq_mod.summarize_query(config, "t", "grounding verification")

        # Touch the matched artifact: revision changes, cache misses.
        path.write_text(
            "---\n---\n\nHHEM reaches 0.878 ROC-AUC on grounding verification; "
            "v2 adds multilingual support.\n",
            encoding="utf-8",
        )
        result = sq_mod.summarize_query(config, "t", "grounding verification")

        assert result is not None and not result.cached
        assert len(calls) == 2

    def test_distinct_budgets_cache_separately(self, config, monkeypatch):
        _seed(config)
        calls: list = []
        _patch_llm(monkeypatch, calls)

        sq_mod.summarize_query(config, "t", "grounding verification", max_tokens=2000)
        sq_mod.summarize_query(config, "t", "grounding verification", max_tokens=8000)

        assert len(calls) == 2

    def test_no_matches_returns_none(self, config):
        assert sq_mod.summarize_query(config, "empty", "anything") is None

    def test_corrupt_cache_regenerates(self, config, monkeypatch):
        _seed(config)
        calls: list = []
        _patch_llm(monkeypatch, calls)
        sq_mod.summarize_query(config, "t", "grounding verification")
        cache_file = next((config.library_dir / ".distill" / "summary_cache").glob("*.json"))
        cache_file.write_text("{not json", encoding="utf-8")

        result = sq_mod.summarize_query(config, "t", "grounding verification")

        assert result is not None and not result.cached
        assert len(calls) == 2


class TestMcpTools:
    def test_find_insights_summary_gated_in_read_only(self, monkeypatch):
        from distill.mcp.tools.summaries import find_insights_summary

        monkeypatch.setenv("DISTILL_MCP_READ_ONLY", "1")
        result = json.loads(find_insights_summary("t", "q"))
        assert result["status"] == "read_only"

    def test_list_topic_summary_free_and_available_in_read_only(
        self, config, monkeypatch, tmp_path
    ):
        from distill.mcp import server as _server
        from distill.mcp.tools.summaries import list_topic_summary

        monkeypatch.setenv("DISTILL_MCP_READ_ONLY", "1")
        monkeypatch.setattr(_server, "_config", lambda: config)
        _seed(config)
        synth = config.topic_dir("t") / "t_Topic_Synthesis.md"
        synth.write_text(
            "---\n---\n\n# Overview\n\nThis topic tracks grounding checkers and their tradeoffs.\n",
            encoding="utf-8",
        )

        result = json.loads(list_topic_summary("t"))

        assert "grounding checkers" in result["summary"]
        assert result["insights"] == 1
        assert result["from"] == "t_Topic_Synthesis.md"

    def test_list_topic_summary_without_synthesis(self, config, monkeypatch):
        from distill.mcp import server as _server
        from distill.mcp.tools.summaries import list_topic_summary

        monkeypatch.setattr(_server, "_config", lambda: config)
        _seed(config)

        result = json.loads(list_topic_summary("t"))

        assert "No synthesis artifact yet" in result["summary"]
        assert result["insights"] == 1

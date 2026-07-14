"""Tests for the sub-agent summary engine (bounded, query-focused, revision-cached)."""

from __future__ import annotations

import json
import os
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from pydantic import SecretStr

from distill.config import DistillConfig
from distill.library.insights import insight_content_sha256
from distill.llm.router import LLM_Response
from distill.pipeline import summary_query as sq_mod
from distill.pipeline.costs import CostTracker
from distill.pipeline.summary_query import QuerySummary


@pytest.fixture
def config(tmp_path):
    return DistillConfig(xai_api_key=SecretStr("t"), distill_output_dir=tmp_path / "library")


def _seed(config, name="checker", body=None):
    d = config.topic_dir("t") / "papers" / name
    d.mkdir(parents=True, exist_ok=True)
    text = body or "HHEM reaches 0.878 ROC-AUC on grounding verification benchmarks."
    (d / f"{name}_Insights.md").write_text(f"---\n---\n\n{text}\n", encoding="utf-8")
    return d / f"{name}_Insights.md"


def _patch_llm(
    monkeypatch,
    calls: list,
    text: str = "HHEM hits 0.878 ROC-AUC [checker_Insights].",
):
    def fake(rc, **kwargs):
        calls.append(kwargs)
        return LLM_Response(
            text=text,
            input_tokens=10,
            output_tokens=10,
            model="grok-4.3",
        )

    monkeypatch.setattr(sq_mod, "llm_call", fake)


class TestSummarizeQuery:
    @pytest.mark.parametrize("cache_present", [False, True], ids=["no-cache", "matching-cache"])
    def test_missing_search_artifact_returns_none_without_model_call(
        self, config, monkeypatch, tmp_path, cache_present
    ):
        missing_path = "topics/t/papers/gone/gone_Insights.md"
        cache_file = tmp_path / "missing-source-cache.json"
        if cache_present:
            cache_file.write_text(
                json.dumps(
                    {
                        "summary": "Cached claim [gone_Insights].",
                        "model": "stale-model",
                    }
                ),
                encoding="utf-8",
            )
        monkeypatch.setattr(
            sq_mod,
            "search_corpus",
            lambda *_args, **_kwargs: [SimpleNamespace(path=missing_path)],
        )
        monkeypatch.setattr(sq_mod, "_cache_path", lambda *_args, **_kwargs: cache_file)
        monkeypatch.setattr(
            sq_mod,
            "llm_call",
            lambda *_args, **_kwargs: pytest.fail("missing sources must not reach the model"),
        )

        assert sq_mod.summarize_query(config, "t", "vanished source") is None

    def test_source_reread_rejects_path_swapped_to_outside_hardlink(
        self, config, monkeypatch, tmp_path
    ):
        insight = _seed(config)
        outside = tmp_path / "outside-secret.md"
        outside.write_text("grounding verification SECRET-OUTSIDE-LIBRARY", encoding="utf-8")
        real_search = sq_mod.search_corpus

        def search_then_swap(*args, **kwargs):
            results = real_search(*args, **kwargs)
            insight.unlink()
            try:
                insight.hardlink_to(outside)
            except OSError as exc:
                pytest.skip(f"hard links unavailable: {exc}")
            return results

        monkeypatch.setattr(sq_mod, "search_corpus", search_then_swap)
        monkeypatch.setattr(
            sq_mod,
            "llm_call",
            lambda *_args, **_kwargs: pytest.fail("unsafe source must not reach the model"),
        )

        assert sq_mod.summarize_query(config, "t", "grounding verification") is None

    def test_source_reread_rejects_regular_file_replaced_after_search(self, config, monkeypatch):
        insight = _seed(config)
        real_search = sq_mod.search_corpus

        def search_then_replace(*args, **kwargs):
            results = real_search(*args, **kwargs)
            replacement = insight.with_suffix(".replacement")
            replacement.write_text(
                "grounding verification UNVERIFIED-REPLACEMENT",
                encoding="utf-8",
            )
            replacement.replace(insight)
            return results

        monkeypatch.setattr(sq_mod, "search_corpus", search_then_replace)
        monkeypatch.setattr(
            sq_mod,
            "llm_call",
            lambda *_args, **_kwargs: pytest.fail("changed source must not reach the model"),
        )

        assert sq_mod.summarize_query(config, "t", "grounding verification") is None

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

    def test_cache_with_unknown_citation_is_deleted_and_regenerated(self, config, monkeypatch):
        _seed(config)
        calls: list = []
        _patch_llm(monkeypatch, calls)
        sq_mod.summarize_query(config, "t", "grounding verification")
        cache_file = next((config.library_dir / ".distill" / "summary_cache").glob("*.json"))
        cache_file.write_text(
            json.dumps(
                {
                    "summary": "Unsupported claim [fabricated_Insights].",
                    "model": "stale-model",
                }
            ),
            encoding="utf-8",
        )

        result = sq_mod.summarize_query(config, "t", "grounding verification")

        assert result is not None and not result.cached
        assert result.sources == ["checker_Insights"]
        assert len(calls) == 2
        assert "fabricated_Insights" not in cache_file.read_text(encoding="utf-8")

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

    def test_content_change_invalidates_cache_when_size_and_mtime_match(self, config, monkeypatch):
        path = _seed(config)
        calls: list = []
        _patch_llm(monkeypatch, calls)
        first = sq_mod.summarize_query(config, "t", "grounding verification")
        original = path.read_text(encoding="utf-8")
        original_stat = path.stat()
        replacement = original.replace("0.878", "0.123")
        assert len(replacement.encode()) == len(original.encode())
        path.write_text(replacement, encoding="utf-8")
        os.utime(path, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))

        second = sq_mod.summarize_query(config, "t", "grounding verification")

        assert first is not None and second is not None
        assert not second.cached
        assert len(calls) == 2

    def test_frontmatter_only_change_keeps_cache_for_unchanged_model_context(
        self, config, monkeypatch
    ):
        path = _seed(config)
        calls: list = []
        _patch_llm(monkeypatch, calls)
        first = sq_mod.summarize_query(config, "t", "grounding verification")
        original = path.read_text(encoding="utf-8")
        path.write_text(original.replace("---\n---", "---\ntitle: Updated\n---"), encoding="utf-8")

        second = sq_mod.summarize_query(config, "t", "grounding verification")

        assert first is not None and second is not None
        assert second.cached
        assert len(calls) == 1

    def test_source_rank_change_invalidates_cache(self, config, monkeypatch):
        first_path = _seed(config, name="first", body="grounding verification alpha")
        second_path = _seed(config, name="second", body="grounding verification beta")
        ranked_paths = [first_path, second_path]
        calls: list = []
        _patch_llm(
            monkeypatch,
            calls,
            text="Both sources discuss grounding [first_Insights].",
        )

        def ranked_results(*_args, **_kwargs):
            return [
                SimpleNamespace(
                    path=path.relative_to(config.library_dir).as_posix(),
                    content_sha256=insight_content_sha256(path.read_text(encoding="utf-8")),
                )
                for path in ranked_paths
            ]

        monkeypatch.setattr(sq_mod, "search_corpus", ranked_results)
        first = sq_mod.summarize_query(config, "t", "grounding verification")
        ranked_paths.reverse()

        second = sq_mod.summarize_query(config, "t", "grounding verification")

        assert first is not None and second is not None
        assert not second.cached
        assert len(calls) == 2

    def test_summary_refuses_unknown_source_citation_without_cache(self, config, monkeypatch):
        _seed(config)
        calls: list = []
        _patch_llm(
            monkeypatch,
            calls,
            text="HHEM hits 0.878 ROC-AUC [fabricated_Insights].",
        )

        result = sq_mod.summarize_query(config, "t", "grounding verification")

        assert result is not None and not result.cached
        assert "unknown source" in result.refused_reason
        assert "fabricated_Insights" in result.refused_reason
        assert result.sources == []
        cache_dir = config.library_dir / ".distill" / "summary_cache"
        assert not cache_dir.exists() or list(cache_dir.glob("*.json")) == []

    def test_summary_refuses_uncited_output_without_cache(self, config, monkeypatch):
        _seed(config)
        calls: list = []
        _patch_llm(monkeypatch, calls, text="HHEM hits 0.878 ROC-AUC.")

        result = sq_mod.summarize_query(config, "t", "grounding verification")

        assert result is not None and not result.cached
        assert "no valid source citations" in result.refused_reason
        assert result.sources == []
        cache_dir = config.library_dir / ".distill" / "summary_cache"
        assert not cache_dir.exists() or list(cache_dir.glob("*.json")) == []

    def test_distinct_budgets_cache_separately(self, config, monkeypatch):
        _seed(config)
        calls: list = []
        _patch_llm(monkeypatch, calls)

        sq_mod.summarize_query(config, "t", "grounding verification", max_tokens=2000)
        sq_mod.summarize_query(config, "t", "grounding verification", max_tokens=8000)

        assert len(calls) == 2

    def test_summary_records_model_usage(self, config, monkeypatch):
        _seed(config)
        calls: list = []
        _patch_llm(monkeypatch, calls)
        tracker = CostTracker()

        result = sq_mod.summarize_query(
            config,
            "t",
            "grounding verification",
            tracker=tracker,
        )

        assert result is not None
        assert len(tracker.entries) == 1
        assert tracker.entries[0].call_type == "find_summary"
        assert tracker.entries[0].prompt_tokens == 10
        assert tracker.entries[0].completion_tokens == 10

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

    def test_corrupt_cache_is_removed_before_failed_regeneration(self, config, monkeypatch):
        _seed(config)
        calls: list = []
        _patch_llm(monkeypatch, calls)
        sq_mod.summarize_query(config, "t", "grounding verification")
        cache_file = next((config.library_dir / ".distill" / "summary_cache").glob("*.json"))
        cache_file.write_text("{not json", encoding="utf-8")

        def fail_regeneration(*_args, **_kwargs):
            raise RuntimeError("model unavailable")

        monkeypatch.setattr(sq_mod, "llm_call", fail_regeneration)

        with pytest.raises(RuntimeError, match="model unavailable"):
            sq_mod.summarize_query(config, "t", "grounding verification")

        assert not cache_file.exists()

    def test_wrong_shape_cache_regenerates(self, config, monkeypatch):
        _seed(config)
        calls: list = []
        _patch_llm(monkeypatch, calls)
        sq_mod.summarize_query(config, "t", "grounding verification")
        cache_file = next((config.library_dir / ".distill" / "summary_cache").glob("*.json"))
        cache_file.write_text("[]", encoding="utf-8")

        result = sq_mod.summarize_query(config, "t", "grounding verification")

        assert result is not None and not result.cached
        assert len(calls) == 2

    def test_non_string_summary_cache_regenerates(self, config, monkeypatch):
        _seed(config)
        calls: list = []
        _patch_llm(monkeypatch, calls)
        sq_mod.summarize_query(config, "t", "grounding verification")
        cache_file = next((config.library_dir / ".distill" / "summary_cache").glob("*.json"))
        cache_file.write_text('{"summary": 123, "model": "grok-4.3"}', encoding="utf-8")

        result = sq_mod.summarize_query(config, "t", "grounding verification")

        assert result is not None and not result.cached
        assert len(calls) == 2


_FAKE_COST = {"total_cost": 0, "total_input_tokens": 0, "total_output_tokens": 0, "calls": 0}


class TestMcpTools:
    @staticmethod
    def _enable_model(monkeypatch):
        """MCP summary tools check model availability before topic/query work."""
        monkeypatch.setattr("distill.mcp.tools.summaries.model_available", lambda: True)

    def test_list_topics_no_topics_dir(self, config, monkeypatch):
        from distill.mcp import server as _server
        from distill.mcp.tools.summaries import list_topics

        monkeypatch.setattr(_server, "_config", lambda: config)

        result = json.loads(list_topics())

        assert result["topics"] == []
        assert result["count"] == 0
        assert "DISTILL_OUTPUT_DIR" in result["message"]

    def test_list_topics_returns_populated_topics(self, config, monkeypatch):
        from distill.mcp import server as _server
        from distill.mcp.tools.summaries import list_topics

        monkeypatch.setenv("DISTILL_MCP_READ_ONLY", "1")
        monkeypatch.setattr(_server, "_config", lambda: config)
        _seed(config)
        synth = config.topic_dir("t") / "t_Topic_Synthesis.md"
        synth.write_text(
            "---\n---\n\nThis topic tracks grounding checkers and their tradeoffs.\n",
            encoding="utf-8",
        )
        config.topic_dir("empty").mkdir(parents=True)

        result = json.loads(list_topics())

        assert result["count"] == 1
        assert result["topics"] == [
            {
                "topic": "t",
                "path": "topics/t",
                "sources": {
                    "papers": 1,
                    "videos": 0,
                    "pages": 0,
                    "other": 0,
                    "total": 1,
                },
                "has_synthesis": True,
                "summary": "This topic tracks grounding checkers and their tradeoffs.",
            }
        ]

    def test_find_insights_summary_gated_in_read_only(self, monkeypatch):
        from distill.mcp.tools.summaries import find_insights_summary

        monkeypatch.setenv("DISTILL_MCP_READ_ONLY", "1")
        result = json.loads(find_insights_summary("t", "q"))
        assert result["status"] == "read_only"

    def test_find_insights_summary_no_model(self, tmp_path, monkeypatch):
        from distill.mcp import server as _server
        from distill.mcp.tools.summaries import find_insights_summary

        monkeypatch.setenv("DISTILL_PROVIDER", "openai")
        config = DistillConfig(xai_api_key=SecretStr(""), distill_output_dir=tmp_path / "library")
        monkeypatch.setattr(_server, "_config", lambda: config)

        result = json.loads(find_insights_summary("t", "q"))

        assert result["status"] == "error"
        assert "model" in result["error"].lower()

    def test_find_insights_summary_topic_not_found(self, config, monkeypatch):
        from distill.mcp import server as _server
        from distill.mcp.tools.summaries import find_insights_summary

        self._enable_model(monkeypatch)
        monkeypatch.setattr(_server, "_config", lambda: config)

        result = json.loads(find_insights_summary("missing", "q"))

        assert result["status"] == "error"
        assert "not found" in result["error"]

    def test_find_insights_summary_no_matches(self, config, monkeypatch):
        from distill.mcp import server as _server
        from distill.mcp.tools.summaries import find_insights_summary

        self._enable_model(monkeypatch)
        monkeypatch.setattr(_server, "_config", lambda: config)
        config.topic_dir("t").mkdir(parents=True)

        with patch("distill.pipeline.summary_query.summarize_query", return_value=None):
            result = json.loads(find_insights_summary("t", "q"))

        assert result["status"] == "no_matches"

    def test_find_insights_summary_happy_path(self, config, monkeypatch):
        from distill.mcp import server as _server
        from distill.mcp.tools.summaries import find_insights_summary

        self._enable_model(monkeypatch)
        monkeypatch.setattr(_server, "_config", lambda: config)
        config.topic_dir("t").mkdir(parents=True)
        summary = QuerySummary(
            summary="Brief [checker_Insights].",
            sources=["checker_Insights"],
            cached=True,
            model="grok-4.3",
        )

        with (
            patch("distill.pipeline.summary_query.summarize_query", return_value=summary),
            patch("distill.mcp.server._cost_summary", return_value=_FAKE_COST),
        ):
            result = json.loads(find_insights_summary("t", "grounding", max_tokens=4000))

        assert result["summary"] == summary.summary
        assert result["sources"] == summary.sources
        assert result["cached"] is True
        assert result["model"] == "grok-4.3"
        assert result["cost"] == _FAKE_COST

    def test_find_insights_summary_refusal_status(self, config, monkeypatch):
        from distill.mcp import server as _server
        from distill.mcp.tools.summaries import find_insights_summary

        self._enable_model(monkeypatch)
        monkeypatch.setattr(_server, "_config", lambda: config)
        config.topic_dir("t").mkdir(parents=True)
        summary = QuerySummary(
            summary="Brief without citations.",
            sources=[],
            cached=False,
            model="grok-4.3",
            refused_reason="summary includes no valid source citations; nothing to cache",
        )

        with (
            patch("distill.pipeline.summary_query.summarize_query", return_value=summary),
            patch("distill.mcp.server._cost_summary", return_value=_FAKE_COST),
        ):
            result = json.loads(find_insights_summary("t", "grounding", max_tokens=4000))

        assert result["status"] == "refused"
        assert "no valid source citations" in result["error"]
        assert result["summary"] == summary.summary
        assert result["sources"] == []
        assert result["cost"] == _FAKE_COST

    def test_find_insights_summary_clamps_max_tokens(self, config, monkeypatch):
        from distill.mcp import server as _server
        from distill.mcp.tools.summaries import find_insights_summary

        self._enable_model(monkeypatch)
        monkeypatch.setattr(_server, "_config", lambda: config)
        config.topic_dir("t").mkdir(parents=True)
        seen: list[int] = []

        def capture(_config, topic, query, *, max_tokens, tracker):
            seen.append(max_tokens)
            return

        with patch("distill.pipeline.summary_query.summarize_query", side_effect=capture):
            json.loads(find_insights_summary("t", "q", max_tokens=100))
            json.loads(find_insights_summary("t", "q", max_tokens=99_999))

        assert seen == [500, 16_000]

    def test_list_topic_summary_topic_not_found(self, config, monkeypatch):
        from distill.mcp import server as _server
        from distill.mcp.tools.summaries import list_topic_summary

        monkeypatch.setattr(_server, "_config", lambda: config)

        result = json.loads(list_topic_summary("missing"))

        assert result["status"] == "error"
        assert "not found" in result["error"]

    def test_list_topic_summary_uses_newest_synthesis_file(self, config, monkeypatch):
        import os

        from distill.mcp import server as _server
        from distill.mcp.tools.summaries import list_topic_summary

        monkeypatch.setattr(_server, "_config", lambda: config)
        config.topic_dir("t").mkdir(parents=True)
        older = config.topic_dir("t") / "t_Topic_Synthesis.md"
        older.write_text(
            "---\n---\n\nOlder topic synthesis paragraph should lose.\n",
            encoding="utf-8",
        )
        newer = config.topic_dir("t") / "t_Corpus_Synthesis.md"
        newer.write_text(
            "---\n---\n\n# Overview\n\nNewest corpus synthesis paragraph wins.\n",
            encoding="utf-8",
        )
        os.utime(older, (1_000_000, 1_000_000))
        os.utime(newer, (2_000_000, 2_000_000))

        result = json.loads(list_topic_summary("t"))

        assert "Newest corpus synthesis paragraph wins." in result["summary"]
        assert result["from"] == "t_Corpus_Synthesis.md"

    def test_list_topic_summary_skips_unreadable_synthesis(self, config, monkeypatch):
        from distill.mcp import server as _server
        from distill.mcp.tools.summaries import list_topic_summary

        monkeypatch.setattr(_server, "_config", lambda: config)
        config.topic_dir("t").mkdir(parents=True)
        unreadable = config.topic_dir("t") / "t_Topic_Synthesis.md"
        unreadable.write_text("---\n---\n\nShould not be read.\n", encoding="utf-8")
        fallback = config.topic_dir("t") / "t_Paper_Synthesis.md"
        fallback.write_text(
            "---\n---\n\nReadable paper synthesis paragraph after read failure.\n",
            encoding="utf-8",
        )

        original_read_text = type(unreadable).read_text

        def flaky_read_text(self, *args, **kwargs):
            if self.name == "t_Topic_Synthesis.md":
                raise OSError("denied")
            return original_read_text(self, *args, **kwargs)

        monkeypatch.setattr(type(unreadable), "read_text", flaky_read_text)

        result = json.loads(list_topic_summary("t"))

        assert "Readable paper synthesis paragraph after read failure." in result["summary"]
        assert result["from"] == "t_Paper_Synthesis.md"

    def test_list_topic_summary_skips_heading_only_blocks(self, config, monkeypatch):
        from distill.mcp import server as _server
        from distill.mcp.tools.summaries import list_topic_summary

        monkeypatch.setattr(_server, "_config", lambda: config)
        config.topic_dir("t").mkdir(parents=True)
        synth = config.topic_dir("t") / "t_Paper_Synthesis.md"
        synth.write_text(
            "---\n---\n\n# Only Headings\n\n## Still Not Prose\n\n",
            encoding="utf-8",
        )

        result = json.loads(list_topic_summary("t"))

        assert "No synthesis artifact yet" in result["summary"]
        assert result["from"] == ""

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

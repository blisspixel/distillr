# pyright: strict
"""Tests for agentic-balance-compliant chunk selection."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from distill.llm.cost_policy import CostPolicyError
from distill.llm.errors import ProviderBusyTimeoutError
from distill.llm.router import LLM_Response, RouterConfig
from distill.pipeline.analysis.chunk_selection import (
    PassSelectionSpec,
    build_chunk_selection_plan,
    format_selection_modes,
    parse_section_blocks,
    select_chunks_for_category,
)
from distill.pipeline.analysis.chunking import Chunk
from distill.pipeline.costs import BudgetExceededError, CostTracker


def _chunk(
    text: str,
    *,
    index: int = 0,
    total: int = 1,
    heading_context: str = "## Methods",
) -> Chunk:
    return Chunk(
        text=text,
        heading_context=heading_context,
        index=index,
        total_chunks=total,
    )


class TestStructuralSelection:
    @patch("distill.pipeline.analysis.chunk_selection.model_available", return_value=False)
    def test_heading_patterns_match_heading_metadata_only(self, _model_available) -> None:
        chunks = [
            _chunk(
                "The algorithm uses a novel approach with a framework and pipeline.",
                index=0,
                total=2,
                heading_context="## Introduction",
            ),
            _chunk("The cat sat on the mat.", index=1, total=2, heading_context="## Methods"),
        ]
        selected, mode = select_chunks_for_category(
            chunks,
            "Methods and Evidence",
            10_000,
            RouterConfig(xai_api_key="t"),
            heading_patterns=("method", "algorithm"),
        )
        assert mode == "structural"
        assert [sc.chunk.index for sc in selected] == [1]

    @patch("distill.pipeline.analysis.chunk_selection.model_available", return_value=False)
    def test_positional_spread_when_no_heading_patterns(self, _model_available) -> None:
        chunks = [_chunk(f"paragraph {index} " * 20, index=index, total=6) for index in range(6)]
        selected, mode = select_chunks_for_category(
            chunks,
            "Summary",
            10_000,
            RouterConfig(xai_api_key="t"),
        )
        assert mode == "positional_order"
        indices = {sc.chunk.index for sc in selected}
        assert 0 in indices
        assert 5 in indices


class TestModelSelection:
    @patch("distill.pipeline.analysis.chunk_selection.model_available", return_value=True)
    @patch("distill.pipeline.analysis.chunk_selection.call")
    def test_model_ranking_selects_requested_indices(self, mock_call, _model_available) -> None:
        mock_call.return_value = LLM_Response(
            text='{"indices": [1, 0]}',
            input_tokens=10,
            output_tokens=5,
            model="grok-4.3",
        )
        chunks = [
            _chunk("Introduction only.", index=0, total=2, heading_context="## Introduction"),
            _chunk(
                "Methods and experiments with benchmarks and evaluation results.",
                index=1,
                total=2,
                heading_context="## Results",
            ),
        ]
        tracker = CostTracker()
        selected, mode = select_chunks_for_category(
            chunks,
            "Methods and Evidence",
            10_000,
            RouterConfig(xai_api_key="t"),
            focus="methods and evaluation",
            heading_patterns=("neuroimaging", "atlas"),
            tracker=tracker,
        )
        assert mode == "model"
        assert [sc.chunk.index for sc in selected] == [1, 0]
        mock_call.assert_called_once()
        assert len(tracker.entries) == 1
        usage = tracker.entries[0]
        assert usage.call_type == "chunk_rank"
        assert usage.prompt_tokens == 10
        assert usage.completion_tokens == 5

    @patch("distill.pipeline.analysis.chunk_selection.model_available", return_value=True)
    @patch("distill.pipeline.analysis.chunk_selection.call")
    def test_budget_crossing_call_is_recorded_then_raised(
        self, mock_call, _model_available
    ) -> None:
        mock_call.return_value = LLM_Response(
            text='{"indices": [0]}',
            input_tokens=10,
            output_tokens=5,
            model="grok-4.3",
            provider_name="xai",
            provider_type="metered-api",
        )
        tracker = CostTracker(budget=0.0)

        with pytest.raises(BudgetExceededError):
            select_chunks_for_category(
                [_chunk("body", heading_context="## Appendix")],
                "Summary",
                10_000,
                RouterConfig(xai_api_key="t"),
                heading_patterns=("missing",),
                tracker=tracker,
            )

        assert len(tracker.entries) == 1
        assert tracker.entries[0].call_type == "chunk_rank"
        assert tracker.total_cost > 0

    @pytest.mark.parametrize(
        "error",
        [
            CostPolicyError("blocked"),
            ProviderBusyTimeoutError(
                provider="ollama",
                requested_model="qwen2.5:14b",
                active_models=("qwen2.5-coder:32b",),
                timeout_seconds=1,
            ),
        ],
    )
    @patch("distill.pipeline.analysis.chunk_selection.model_available", return_value=True)
    def test_policy_and_busy_errors_do_not_degrade_to_fallback(
        self, _model_available, error: Exception
    ) -> None:
        with (
            patch("distill.pipeline.analysis.chunk_selection.call", side_effect=error),
            pytest.raises(type(error)),
        ):
            select_chunks_for_category(
                [_chunk("body", heading_context="## Appendix")],
                "Summary",
                10_000,
                RouterConfig(xai_api_key="t"),
                heading_patterns=("missing",),
                tracker=CostTracker(),
            )


class TestHonestDegradation:
    @patch("distill.pipeline.analysis.chunk_selection.model_available", return_value=False)
    def test_paper_pass_names_use_positional_not_keyword(self, _model_available) -> None:
        chunks = [
            _chunk(f"section {index} " * 30, index=index, total=4, heading_context="## Appendix")
            for index in range(4)
        ]
        plan = build_chunk_selection_plan(
            chunks,
            (
                PassSelectionSpec(
                    section="front matter",
                    heading_patterns=("abstract", "introduction"),
                ),
                PassSelectionSpec(
                    section="methods and evidence",
                    heading_patterns=("method", "experiment"),
                ),
            ),
            10_000,
            RouterConfig(xai_api_key="t"),
        )
        assert plan.modes["front matter"] == "positional_order"
        assert plan.modes["methods and evidence"] == "positional_order"
        assert plan.by_section["front matter"]
        assert plan.by_section["methods and evidence"]

    @patch("distill.pipeline.analysis.chunk_selection.model_available", return_value=False)
    def test_legacy_category_can_use_keyword_fallback(self, _model_available) -> None:
        chunks = [
            _chunk("Introduction only.", index=0, total=2, heading_context="## Intro"),
            _chunk(
                "The algorithm approach technique method framework model pipeline design.",
                index=1,
                total=2,
                heading_context="## Body",
            ),
        ]
        selected, mode = select_chunks_for_category(
            chunks,
            "Methods",
            10_000,
            RouterConfig(xai_api_key="t"),
            heading_patterns=("neuroimaging",),
        )
        assert mode == "keyword_fallback"
        assert any(sc.chunk.index == 1 for sc in selected)


class TestHelpers:
    def test_format_selection_modes_sorts_sections(self) -> None:
        serialized = format_selection_modes(
            {"Methods": "model", "Summary": "structural"},
        )
        assert serialized == "Methods:model; Summary:structural"

    def test_parse_section_blocks_extracts_bodies(self) -> None:
        text = "## Summary\nOne line.\n\n## Methods\nFirst.\nSecond."
        blocks = parse_section_blocks(text)
        assert blocks == {"Summary": "One line.", "Methods": "First.\nSecond."}

    def test_parse_section_blocks_skips_empty_sections(self) -> None:
        assert parse_section_blocks("## Empty\n\n## Filled\nBody") == {"Filled": "Body"}
        assert parse_section_blocks("No headers here") == {}


class TestPlanBuilder:
    @patch("distill.pipeline.analysis.chunk_selection.model_available", return_value=False)
    def test_empty_chunks_returns_empty_plan(self, _model_available) -> None:
        plan = build_chunk_selection_plan(
            [],
            (PassSelectionSpec(section="Summary"),),
            10_000,
            RouterConfig(xai_api_key="t"),
        )
        assert plan.by_section == {}
        assert plan.modes == {}

    @patch("distill.pipeline.analysis.chunk_selection.model_available", return_value=False)
    def test_token_budget_limits_positional_selection(self, _model_available) -> None:
        chunks = [_chunk("x" * 100, index=index, total=3) for index in range(3)]
        selected, mode = select_chunks_for_category(
            chunks,
            "Summary",
            30,
            RouterConfig(xai_api_key="t"),
        )
        assert mode == "positional_order"
        assert len(selected) == 1


class TestBatchModelSelection:
    @patch("distill.pipeline.analysis.chunk_selection.model_available", return_value=True)
    @patch("distill.pipeline.analysis.chunk_selection.call")
    def test_model_batch_assigns_multiple_sections(self, mock_call, _model_available) -> None:
        mock_call.return_value = LLM_Response(
            text='{"assignments": {"limits": [1], "summary": [0]}}',
            input_tokens=10,
            output_tokens=5,
            model="grok-4.3",
        )
        chunks = [
            _chunk("Opening summary text.", index=0, total=2, heading_context="## Intro"),
            _chunk(
                "Limitations and future work.", index=1, total=2, heading_context="## Discussion"
            ),
        ]
        tracker = CostTracker()
        plan = build_chunk_selection_plan(
            chunks,
            (
                PassSelectionSpec(
                    section="summary",
                    heading_patterns=("abstract",),
                ),
                PassSelectionSpec(
                    section="limits",
                    heading_patterns=("limitation",),
                ),
            ),
            10_000,
            RouterConfig(xai_api_key="t"),
            tracker=tracker,
        )
        assert plan.modes["summary"] == "model_batch"
        assert plan.modes["limits"] == "model_batch"
        assert plan.by_section["summary"][0].chunk.index == 0
        assert plan.by_section["limits"][0].chunk.index == 1
        assert len(tracker.entries) == 1
        assert tracker.entries[0].call_type == "chunk_rank_batch"

    @patch("distill.pipeline.analysis.chunk_selection.model_available", return_value=True)
    @patch("distill.pipeline.analysis.chunk_selection.call", side_effect=RuntimeError("down"))
    def test_model_failure_falls_back_to_positional(self, _mock_call, _model_available) -> None:
        chunks = [_chunk(f"body {index}", index=index, total=2) for index in range(2)]
        tracker = CostTracker()
        selected, mode = select_chunks_for_category(
            chunks,
            "Core Contribution",
            10_000,
            RouterConfig(xai_api_key="t"),
            heading_patterns=("missing",),
            tracker=tracker,
        )
        assert mode == "positional_order"
        assert selected
        assert tracker.entries == []

    @patch("distill.pipeline.analysis.chunk_selection.model_available", return_value=True)
    @patch("distill.pipeline.analysis.chunk_selection.call")
    def test_invalid_model_json_falls_back_to_positional(self, mock_call, _model_available) -> None:
        mock_call.return_value = LLM_Response(
            text="not json",
            input_tokens=1,
            output_tokens=1,
            model="grok-4.3",
        )
        chunks = [_chunk("only chunk", index=0, total=1)]
        selected, mode = select_chunks_for_category(
            chunks,
            "Summary",
            10_000,
            RouterConfig(xai_api_key="t"),
            heading_patterns=("nope",),
        )
        assert mode == "positional_order"
        assert selected

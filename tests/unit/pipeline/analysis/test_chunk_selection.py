# pyright: strict
"""Tests for agentic-balance-compliant chunk selection."""

from __future__ import annotations

from unittest.mock import patch

from distill.llm.router import LLM_Response, RouterConfig
from distill.pipeline.analysis.chunk_selection import (
    PassSelectionSpec,
    build_chunk_selection_plan,
    select_chunks_for_category,
)
from distill.pipeline.analysis.chunking import Chunk


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
        selected, mode = select_chunks_for_category(
            chunks,
            "Methods and Evidence",
            10_000,
            RouterConfig(xai_api_key="t"),
            focus="methods and evaluation",
            heading_patterns=("neuroimaging", "atlas"),
        )
        assert mode == "model"
        assert [sc.chunk.index for sc in selected] == [1, 0]
        mock_call.assert_called_once()


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

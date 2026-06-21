# pyright: strict
"""Unit tests for multi-pass analysis assembly.

Feature: local-inference
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from distill.llm.metadata import ProviderMetadata
from distill.llm.router import LLM_Response, RouterConfig
from distill.pipeline.analysis.chunking import Chunk
from distill.pipeline.analysis.multipass import (
    CATEGORY_DESCRIPTIONS,
    INSIGHT_CATEGORIES,
    PAPER_ANALYSIS_PASSES,
    PAPER_CANONICAL_SECTIONS,
    PassResult,
    _build_focused_prompt,
    _deduplicate_content,
    merge_paper_pass_results,
    merge_pass_results,
    multi_pass_analysis,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_chunk(text: str, index: int = 0, total: int = 1) -> Chunk:
    """Create a test chunk."""
    return Chunk(text=text, heading_context="## Test", index=index, total_chunks=total)


def _make_config() -> RouterConfig:
    """Create a minimal RouterConfig for testing."""
    return RouterConfig(
        provider="ollama",
        fast_model="qwen2.5:14b",
        xai_api_key="test",
    )


def _make_metadata(context_window: int = 32768) -> ProviderMetadata:
    """Create test provider metadata."""
    return ProviderMetadata(
        context_window=context_window,
        provider_type="local",
        provider_name="ollama",
    )


# ---------------------------------------------------------------------------
# Tests: merge_pass_results
# ---------------------------------------------------------------------------


class TestMergePaperPassResults:
    def test_produces_paper_section_headings(self) -> None:
        results = [
            PassResult(
                category="front matter",
                insights="## Summary\n\nPlain summary.\n\n## Core Contribution\n\nNovel idea.",
                chunks_used=1,
            ),
            PassResult(
                category="methods and evidence",
                insights="## Methods and Evidence\n\nUsed X.",
                chunks_used=2,
            ),
        ]
        merged = merge_paper_pass_results(results, body="")
        assert "## Summary" in merged
        assert "Plain summary." in merged
        assert "## Methods and Evidence" in merged
        assert "Used X." in merged
        for section in PAPER_CANONICAL_SECTIONS:
            assert f"## {section}" in merged
        assert len(PAPER_ANALYSIS_PASSES) == 3


class TestMergePassResults:
    """Tests for merge_pass_results producing correct output structure."""

    def test_produces_yaml_frontmatter(self) -> None:
        results = [
            PassResult(
                category="Key Findings", insights="Found something important.", chunks_used=2
            ),
            PassResult(category="Methods", insights="Used an algorithm.", chunks_used=1),
        ]
        output = merge_pass_results(results, "Test Paper", "2401.12345", "qwen2.5:14b")

        assert output.startswith("---\n")
        assert 'paper_title: "Test Paper"' in output
        assert "paper_id: 2401.12345" in output
        assert "source: arxiv" in output
        assert "analyzed_by: qwen2.5:14b" in output
        assert "source_mode: chunked_local" in output
        # Frontmatter closes
        assert output.count("---\n") >= 2

    def test_has_all_section_headings(self) -> None:
        results = [
            PassResult(category="Key Findings", insights="Finding 1.", chunks_used=1),
            PassResult(category="Methods", insights="Method 1.", chunks_used=1),
            PassResult(category="Limits", insights="Limit 1.", chunks_used=1),
            PassResult(category="Open Questions", insights="Question 1.", chunks_used=1),
        ]
        output = merge_pass_results(results, "Test Paper", "2401.12345", "qwen2.5:14b")

        for category in INSIGHT_CATEGORIES:
            assert f"### {category}" in output

    def test_missing_categories_still_have_headings(self) -> None:
        # Only one category has results
        results = [
            PassResult(category="Methods", insights="Method 1.", chunks_used=1),
        ]
        output = merge_pass_results(results, "Test Paper", "2401.12345", "qwen2.5:14b")

        # All headings should still be present
        for category in INSIGHT_CATEGORIES:
            assert f"### {category}" in output

    def test_escapes_quotes_in_title(self) -> None:
        results = [PassResult(category="Key Findings", insights="Found it.", chunks_used=1)]
        output = merge_pass_results(results, 'Paper with "quotes"', "2401.12345", "qwen2.5:14b")

        assert 'Paper with \\"quotes\\"' in output

    def test_empty_results_produces_skeleton(self) -> None:
        output = merge_pass_results([], "Empty Paper", "2401.00000", "qwen2.5:14b")

        assert "---\n" in output
        assert 'paper_title: "Empty Paper"' in output
        for category in INSIGHT_CATEGORIES:
            assert f"### {category}" in output


# ---------------------------------------------------------------------------
# Tests: _build_focused_prompt
# ---------------------------------------------------------------------------


class TestBuildFocusedPrompt:
    """Tests for focused prompt construction."""

    def test_includes_category_name(self) -> None:
        prompt = _build_focused_prompt(
            "Methods",
            ["chunk text here"],
            description=CATEGORY_DESCRIPTIONS["Methods"],
        )
        assert "Methods" in prompt

    def test_includes_chunk_content(self) -> None:
        prompt = _build_focused_prompt(
            "Methods",
            ["first chunk", "second chunk"],
            description=CATEGORY_DESCRIPTIONS["Methods"],
        )
        assert "first chunk" in prompt
        assert "second chunk" in prompt

    def test_includes_category_description(self) -> None:
        prompt = _build_focused_prompt(
            "Methods",
            ["text"],
            description=CATEGORY_DESCRIPTIONS["Methods"],
        )
        assert "approaches" in prompt or "algorithms" in prompt


# ---------------------------------------------------------------------------
# Tests: _deduplicate_content
# ---------------------------------------------------------------------------


class TestDeduplicateContent:
    """Tests for deduplication of overlapping insights."""

    def test_removes_duplicate_from_less_specific(self) -> None:
        result_map = {
            "Methods": "The algorithm uses backpropagation.",
            "Key Findings": "The algorithm uses backpropagation.\nWe found great results.",
        }
        # Key Findings is less specific than Methods
        deduplicated = _deduplicate_content(result_map["Key Findings"], "Key Findings", result_map)
        assert "great results" in deduplicated
        # The duplicate line should be removed from Key Findings
        assert "backpropagation" not in deduplicated

    def test_keeps_unique_content(self) -> None:
        result_map = {
            "Methods": "The algorithm uses backpropagation.",
            "Key Findings": "We achieved state-of-the-art results.",
        }
        deduplicated = _deduplicate_content(result_map["Key Findings"], "Key Findings", result_map)
        assert "state-of-the-art" in deduplicated


# ---------------------------------------------------------------------------
# Tests: multi_pass_analysis integration (mocked LLM)
# ---------------------------------------------------------------------------


class TestMultiPassAnalysisIntegration:
    """Integration test for full multi-pass flow with mocked LLM."""

    @patch("distill.pipeline.analysis.chunk_selection.model_available", return_value=False)
    @patch("distill.pipeline.analysis.multipass.call")
    def test_full_flow_with_mocked_llm(self, mock_call: MagicMock, _model_available) -> None:
        """Full multi-pass flow produces results for relevant categories."""
        # Create chunks with method-related content
        chunks = [
            _make_chunk(
                "The algorithm uses a novel approach with a framework "
                "and implementation technique for the model pipeline. "
                "This method achieves significant results.",
                index=0,
                total=3,
            ),
            _make_chunk(
                "The limitation of this approach is the constraint on memory. "
                "A major drawback is the challenge of scaling. "
                "This issue remains a bottleneck.",
                index=1,
                total=3,
            ),
            _make_chunk(
                "Future work should investigate the open question of scalability. "
                "The potential for exploring new directions remains. "
                "An unresolved gap exists in the hypothesis.",
                index=2,
                total=3,
            ),
        ]

        # Mock LLM responses for each category
        mock_call.return_value = LLM_Response(
            text="Mocked insight content for this category.",
            input_tokens=100,
            output_tokens=50,
            model="qwen2.5:14b",
        )

        config = _make_config()
        metadata = _make_metadata(context_window=100000)

        multipass = multi_pass_analysis(chunks, config, metadata)
        results = multipass.passes

        # Should have produced results for categories with relevant chunks
        assert len(results) > 0
        # Each result should have content
        for result in results:
            assert result.insights
            assert result.chunks_used > 0
            assert result.category in INSIGHT_CATEGORIES

    @patch("distill.pipeline.analysis.chunk_selection.model_available", return_value=False)
    @patch("distill.pipeline.analysis.multipass.call")
    def test_merge_after_multipass(self, mock_call: MagicMock, _model_available) -> None:
        """Merged output has correct structure."""
        mock_call.return_value = LLM_Response(
            text="Some insight content.",
            input_tokens=100,
            output_tokens=50,
            model="qwen2.5:14b",
        )

        chunks = [
            _make_chunk(
                "The algorithm approach technique method framework model "
                "pipeline design system process strategy mechanism. "
                "A finding result discovery demonstrates significant novel contribution.",
                index=0,
                total=1,
            ),
        ]

        config = _make_config()
        metadata = _make_metadata(context_window=100000)

        multipass = multi_pass_analysis(chunks, config, metadata)
        merged = merge_pass_results(multipass.passes, "Test Paper", "2401.12345", "qwen2.5:14b")

        # Verify structure
        assert merged.startswith("---\n")
        assert "paper_title" in merged
        assert "paper_id" in merged
        assert "analyzed_by" in merged
        assert "source_mode: chunked_local" in merged

# pyright: strict
"""Unit tests for the per-category reranker.

Feature: local-inference
"""

from __future__ import annotations

from distill.pipeline.analysis.chunking import Chunk
from distill.pipeline.analysis.reranker import (
    CATEGORY_KEYWORDS,
    INSIGHT_CATEGORIES,
    _score_chunk_for_category,
    rerank_for_category,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_chunk(text: str, index: int = 0, total: int = 1) -> Chunk:
    """Create a test chunk."""
    return Chunk(text=text, heading_context="## Test", index=index, total_chunks=total)


# ---------------------------------------------------------------------------
# Tests: keyword scoring
# ---------------------------------------------------------------------------


class TestKeywordScoring:
    """Tests for _score_chunk_for_category."""

    def test_no_keywords_match_returns_zero(self) -> None:
        chunk = _make_chunk("The cat sat on the mat.")
        score = _score_chunk_for_category(chunk, "Methods")
        assert score == 0.0

    def test_single_keyword_match(self) -> None:
        chunk = _make_chunk("We used a novel algorithm to solve this.")
        score = _score_chunk_for_category(chunk, "Methods")
        assert score > 0.0

    def test_multiple_keywords_score_higher(self) -> None:
        chunk_few = _make_chunk("The algorithm works well.")
        chunk_many = _make_chunk(
            "The algorithm uses a novel approach with a framework "
            "and implementation technique for the model pipeline."
        )
        score_few = _score_chunk_for_category(chunk_few, "Methods")
        score_many = _score_chunk_for_category(chunk_many, "Methods")
        assert score_many > score_few

    def test_unknown_category_returns_zero(self) -> None:
        chunk = _make_chunk("Some text about methods and algorithms.")
        score = _score_chunk_for_category(chunk, "NonexistentCategory")
        assert score == 0.0

    def test_case_insensitive_matching(self) -> None:
        chunk = _make_chunk("The METHOD and ALGORITHM are described here.")
        score = _score_chunk_for_category(chunk, "Methods")
        assert score > 0.0

    def test_all_categories_have_keywords(self) -> None:
        for category in INSIGHT_CATEGORIES:
            assert category in CATEGORY_KEYWORDS
            assert len(CATEGORY_KEYWORDS[category]) > 0


# ---------------------------------------------------------------------------
# Tests: threshold skip
# ---------------------------------------------------------------------------


class TestThresholdSkip:
    """Tests for category skip when all chunks below threshold."""

    def test_all_below_threshold_returns_empty(self) -> None:
        # Chunks with no relevant keywords for "Methods"
        chunks = [
            _make_chunk("The cat sat on the mat.", index=0, total=3),
            _make_chunk("A dog ran in the park.", index=1, total=3),
            _make_chunk("Birds fly in the sky.", index=2, total=3),
        ]
        result = rerank_for_category(chunks, "Methods", context_window=10000)
        assert result == []

    def test_empty_chunks_returns_empty(self) -> None:
        result = rerank_for_category([], "Methods", context_window=10000)
        assert result == []

    def test_some_above_threshold_returns_those(self) -> None:
        chunks = [
            _make_chunk("The cat sat on the mat.", index=0, total=3),
            _make_chunk(
                "The algorithm uses a novel approach with a framework "
                "and implementation technique for the model pipeline.",
                index=1,
                total=3,
            ),
            _make_chunk("Birds fly in the sky.", index=2, total=3),
        ]
        result = rerank_for_category(chunks, "Methods", context_window=10000)
        assert len(result) >= 1
        # The relevant chunk should be included
        assert any(sc.chunk.index == 1 for sc in result)


# ---------------------------------------------------------------------------
# Tests: top-k selection
# ---------------------------------------------------------------------------


class TestTopKSelection:
    """Tests for top-k selection fitting within context window."""

    def test_respects_context_window(self) -> None:
        # Create chunks that together exceed the window
        # Each chunk is ~100 chars = ~25 tokens
        chunks = [
            _make_chunk(
                f"The method approach algorithm technique framework implementation "
                f"model pipeline design system process strategy mechanism #{i}",
                index=i,
                total=10,
            )
            for i in range(10)
        ]
        # Set a small window that can only fit a few chunks
        result = rerank_for_category(chunks, "Methods", context_window=50)
        # Should not exceed 50 tokens total
        from distill.pipeline.analysis.chunking import estimate_tokens

        total_tokens = sum(estimate_tokens(sc.chunk.text) for sc in result)
        assert total_tokens <= 50

    def test_ordered_by_score_descending(self) -> None:
        chunks = [
            _make_chunk("The cat sat on the mat with a method.", index=0, total=3),
            _make_chunk(
                "The algorithm uses a novel approach with a framework "
                "and implementation technique for the model pipeline.",
                index=1,
                total=3,
            ),
            _make_chunk("A simple technique was used.", index=2, total=3),
        ]
        result = rerank_for_category(chunks, "Methods", context_window=10000)
        if len(result) >= 2:
            for i in range(len(result) - 1):
                assert result[i].score >= result[i + 1].score

    def test_scored_chunk_has_correct_category(self) -> None:
        chunks = [
            _make_chunk(
                "The algorithm uses a novel approach with a framework.",
                index=0,
                total=1,
            ),
        ]
        result = rerank_for_category(chunks, "Methods", context_window=10000)
        for sc in result:
            assert sc.category == "Methods"

    def test_large_window_includes_all_above_threshold(self) -> None:
        # With a very large window, all above-threshold chunks should be included
        chunks = [
            _make_chunk(
                "The algorithm approach technique method framework.",
                index=i,
                total=5,
            )
            for i in range(5)
        ]
        result = rerank_for_category(chunks, "Methods", context_window=1_000_000)
        # All chunks have the same keywords, so all should be above threshold
        assert len(result) == 5

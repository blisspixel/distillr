# pyright: strict
"""Unit and property tests for report compaction.

Feature: local-inference
"""

from __future__ import annotations

import math
from unittest.mock import MagicMock, patch

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from distill.llm.router import LLM_Response, RouterConfig
from distill.pipeline.report.compaction import (
    CompactionResult,
    compact_between_phases,
    compact_phase_output,
    extract_named_entities,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_config() -> RouterConfig:
    """Create a minimal RouterConfig for testing."""
    return RouterConfig(
        provider="ollama",
        fast_model="qwen2.5:14b",
        premium_model="qwen2.5:14b",
        xai_api_key="test",
    )


# ---------------------------------------------------------------------------
# Tests: extract_named_entities
# ---------------------------------------------------------------------------


class TestExtractNamedEntities:
    """Tests for regex-based named entity extraction."""

    def test_extracts_proper_nouns(self) -> None:
        text = "The work by Machine Learning Research Group was significant."
        entities = extract_named_entities(text)
        assert "Machine Learning Research Group" in entities

    def test_extracts_acronyms(self) -> None:
        text = "The GPT-4 model outperforms BERT and RoBERTa on NLP tasks."
        entities = extract_named_entities(text)
        assert "GPT" in entities or "GPT-4" in entities
        assert "BERT" in entities
        assert "NLP" in entities

    def test_extracts_numbers(self) -> None:
        text = "The model achieved 95.3% accuracy with 1.5B parameters."
        entities = extract_named_entities(text)
        assert any("95.3" in e for e in entities)

    def test_extracts_dates(self) -> None:
        text = "Published on 2024-01-15 and updated in March 2024."
        entities = extract_named_entities(text)
        assert "2024-01-15" in entities
        assert "March 2024" in entities

    def test_extracts_quoted_terms(self) -> None:
        text = 'The concept of "attention is all you need" revolutionized NLP.'
        entities = extract_named_entities(text)
        assert "attention is all you need" in entities

    def test_empty_text_returns_empty(self) -> None:
        entities = extract_named_entities("")
        assert entities == set()

    def test_no_entities_returns_empty(self) -> None:
        text = "the cat sat on the mat and looked around."
        entities = extract_named_entities(text)
        # Should have no or very few entities from plain lowercase text
        # (numbers or acronyms might still match)
        assert all(len(e) >= 2 for e in entities)


# ---------------------------------------------------------------------------
# Property 9: Compaction length bound
# Feature: local-inference, Property 9: Compaction length bound
# ---------------------------------------------------------------------------


@st.composite
def _text_with_entities(draw: st.DrawFn) -> str:
    """Generate text that has some structure and named entities."""
    # Generate sentences with proper nouns, numbers, and regular text
    proper_nouns = draw(
        st.lists(
            st.from_regex(r"[A-Z][a-z]{3,8} [A-Z][a-z]{3,8}", fullmatch=True),
            min_size=1,
            max_size=5,
        )
    )
    numbers = draw(
        st.lists(
            st.from_regex(r"[1-9][0-9]{0,3}\.[0-9]%", fullmatch=True),
            min_size=1,
            max_size=3,
        )
    )
    filler = draw(
        st.lists(
            st.text(
                alphabet=st.characters(
                    whitelist_categories=("Ll",),
                ),
                min_size=20,
                max_size=100,
            ),
            min_size=3,
            max_size=10,
        )
    )

    parts: list[str] = []
    for i, f in enumerate(filler):
        parts.append(f)
        if i < len(proper_nouns):
            parts.append(f"The {proper_nouns[i]} team reported results.")
        if i < len(numbers):
            parts.append(f"Achieving {numbers[i]} on the benchmark.")

    return " ".join(parts)


@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
@given(
    text=st.text(
        alphabet=st.characters(
            whitelist_categories=("L", "N", "Z", "P"), blacklist_characters="\x00"
        ),
        min_size=100,
        max_size=2000,
    )
)
def test_compaction_length_bound(text: str) -> None:
    """Compacted output length <= ceil(0.25 * original_length).

    **Validates: Requirements 12.2, 18.6**
    """
    # Mock the LLM to return a compacted version that respects the ratio
    original_length = len(text)
    max_allowed = math.ceil(0.25 * original_length)

    # The LLM mock returns text that is within the 25% bound
    # We simulate the LLM doing its job correctly
    compacted_text = text[:max_allowed] if len(text) > max_allowed else text

    with patch("distill.pipeline.report.compaction.call") as mock_call:
        mock_call.return_value = LLM_Response(
            text=compacted_text,
            input_tokens=100,
            output_tokens=50,
            model="qwen2.5:14b",
        )

        config = _make_config()
        result = compact_phase_output(text, config, context_window=1_000_000)

        # The compacted length should be <= 25% of original
        assert result.compacted_length <= max_allowed, (
            f"Compacted length {result.compacted_length} exceeds "
            f"25% bound {max_allowed} (original: {original_length})"
        )


# ---------------------------------------------------------------------------
# Property 10: Entity preservation through compaction
# Feature: local-inference, Property 10: Entity preservation through compaction
# ---------------------------------------------------------------------------


@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
@given(text=_text_with_entities())
def test_entity_preservation(text: str) -> None:
    """Named entities from original appear in compacted output.

    **Validates: Requirements 12.6, 18.6**
    """
    original_entities = extract_named_entities(text)

    if not original_entities:
        # If no entities found, nothing to verify
        return

    # Mock the LLM to return text that preserves all entities
    # (simulating a well-behaved compaction LLM)
    # Build a compacted text that includes all entities
    entity_text = ". ".join(sorted(original_entities)[:20])  # Cap for sanity
    compacted_text = f"Summary preserving entities: {entity_text}."

    with patch("distill.pipeline.report.compaction.call") as mock_call:
        mock_call.return_value = LLM_Response(
            text=compacted_text,
            input_tokens=100,
            output_tokens=50,
            model="qwen2.5:14b",
        )

        config = _make_config()
        result = compact_phase_output(text, config, context_window=1_000_000)

        # Entities in the compacted output should be a superset of original entities
        compacted_entities = extract_named_entities(result.compacted_text)

        # Check that original entities appear in the compacted text
        # (either as extracted entities or as substrings)
        for entity in original_entities:
            assert entity in result.compacted_text or entity in compacted_entities, (
                f"Entity '{entity}' lost during compaction"
            )


# ---------------------------------------------------------------------------
# Tests: compact_phase_output
# ---------------------------------------------------------------------------


class TestCompactPhaseOutput:
    """Unit tests for compact_phase_output."""

    @patch("distill.pipeline.report.compaction.call")
    def test_empty_input_returns_empty(self, mock_call: MagicMock) -> None:
        config = _make_config()
        result = compact_phase_output("", config, context_window=10000)
        assert result.compacted_text == ""
        assert result.original_length == 0
        assert result.compacted_length == 0
        mock_call.assert_not_called()

    @patch("distill.pipeline.report.compaction.call")
    def test_first_pass_within_window(self, mock_call: MagicMock) -> None:
        """First pass fits within window — no second pass needed."""
        mock_call.return_value = LLM_Response(
            text="Short summary.",
            input_tokens=100,
            output_tokens=10,
            model="qwen2.5:14b",
        )

        config = _make_config()
        text = "A " * 1000  # 2000 chars
        result = compact_phase_output(text, config, context_window=1_000_000)

        assert result.compacted_text == "Short summary."
        assert result.original_length == len(text)
        assert result.compacted_length == len("Short summary.")
        # Only one call (no precision pass)
        assert mock_call.call_count == 1

    @patch("distill.pipeline.report.compaction.call")
    def test_second_pass_when_first_exceeds_window(self, mock_call: MagicMock) -> None:
        """Second precision pass triggered when first pass exceeds window."""
        # First call returns something too large for the window
        # Second call returns something smaller
        mock_call.side_effect = [
            LLM_Response(
                text="x" * 500,  # 500 chars = 125 tokens, exceeds window of 50
                input_tokens=100,
                output_tokens=125,
                model="qwen2.5:14b",
            ),
            LLM_Response(
                text="Compact.",
                input_tokens=50,
                output_tokens=5,
                model="qwen2.5:14b",
            ),
        ]

        config = _make_config()
        text = "A " * 1000
        # Set a very small window to trigger second pass
        result = compact_phase_output(text, config, context_window=50)

        assert result.compacted_text == "Compact."
        assert mock_call.call_count == 2

    @patch("distill.pipeline.report.compaction.call")
    def test_result_dataclass_fields(self, mock_call: MagicMock) -> None:
        """CompactionResult has all expected fields."""
        mock_call.return_value = LLM_Response(
            text="Summary with GPT-4 and BERT.",
            input_tokens=100,
            output_tokens=10,
            model="qwen2.5:14b",
        )

        config = _make_config()
        text = "The GPT-4 model and BERT were compared. " * 50
        result = compact_phase_output(text, config, context_window=1_000_000)

        assert isinstance(result, CompactionResult)
        assert result.original_length == len(text)
        assert result.compacted_length == len("Summary with GPT-4 and BERT.")
        assert isinstance(result.entities_preserved, list)


# ---------------------------------------------------------------------------
# Tests: compact_between_phases (integration)
# ---------------------------------------------------------------------------


class TestCompactBetweenPhases:
    """Integration tests for compaction between report phases."""

    @patch("distill.pipeline.report.compaction.call")
    def test_empty_input_returns_empty(self, mock_call: MagicMock) -> None:
        config = _make_config()
        result = compact_between_phases("", config, context_window=10000)
        assert result == ""
        mock_call.assert_not_called()

    @patch("distill.pipeline.report.compaction.call")
    def test_returns_compacted_text(self, mock_call: MagicMock) -> None:
        mock_call.return_value = LLM_Response(
            text="Compacted summary of the dossier.",
            input_tokens=500,
            output_tokens=20,
            model="qwen2.5:14b",
        )

        config = _make_config()
        dossier = "A very long research dossier with many findings. " * 100
        result = compact_between_phases(dossier, config, context_window=1_000_000)

        assert result == "Compacted summary of the dossier."
        mock_call.assert_called_once()

    @patch("distill.pipeline.report.compaction.call")
    def test_applied_for_cloud_provider(self, mock_call: MagicMock) -> None:
        """Compaction works for cloud providers too (universal application)."""
        mock_call.return_value = LLM_Response(
            text="Cloud-compacted output.",
            input_tokens=500,
            output_tokens=20,
            model="grok-4.3",
        )

        config = RouterConfig(
            provider="xai",
            fast_model="grok-4.3",
            premium_model="grok-4.3",
            xai_api_key="test-key",
        )
        text = "Phase 1 output with lots of content. " * 50
        result = compact_between_phases(text, config, context_window=1_000_000)

        assert result == "Cloud-compacted output."
        mock_call.assert_called_once()

# pyright: strict
"""Tests for robust JSON extraction from LLM responses.

Feature: local-inference — handles different model output formats.
"""

from __future__ import annotations

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from distill.llm.json_extract import extract_json


class TestDirectParse:
    """Strategy 1: text is already valid JSON."""

    def test_clean_dict(self) -> None:
        result = extract_json('{"paper_queries": ["q1", "q2"]}')
        assert result == {"paper_queries": ["q1", "q2"]}

    def test_clean_list(self) -> None:
        result = extract_json('[{"id": 1}, {"id": 2}]')
        assert result == [{"id": 1}, {"id": 2}]

    def test_empty_string(self) -> None:
        assert extract_json("") is None

    def test_whitespace_only(self) -> None:
        assert extract_json("   \n  ") is None


class TestCodeBlockStripping:
    """Strategy 2: JSON wrapped in markdown code blocks."""

    def test_json_code_block(self) -> None:
        text = '```json\n{"queries": ["a", "b"]}\n```'
        result = extract_json(text)
        assert result == {"queries": ["a", "b"]}

    def test_plain_code_block(self) -> None:
        text = '```\n{"queries": ["a", "b"]}\n```'
        result = extract_json(text)
        assert result == {"queries": ["a", "b"]}

    def test_code_block_with_language_tag(self) -> None:
        text = '```json\n{\n  "paper_queries": ["transformer memory"],\n  "video_queries": ["LLM memory tutorial"]\n}\n```'
        result = extract_json(text)
        assert result is not None
        assert "paper_queries" in result

    def test_code_block_with_trailing_whitespace(self) -> None:
        text = '```json\n{"key": "value"}\n```\n\n'
        result = extract_json(text)
        assert result == {"key": "value"}


class TestPreambleStripping:
    """Strategy 3: JSON preceded by preamble text."""

    def test_preamble_then_json(self) -> None:
        text = 'Here are the queries:\n\n{"paper_queries": ["q1"], "video_queries": ["q2"]}'
        result = extract_json(text)
        assert result == {"paper_queries": ["q1"], "video_queries": ["q2"]}

    def test_thinking_trace_then_json(self) -> None:
        text = (
            "Let me think about this...\n"
            "The user wants queries about agentic memory.\n"
            "I should generate diverse search terms.\n\n"
            '{"paper_queries": ["agentic memory LLM"], "video_queries": ["memory systems tutorial"]}'
        )
        result = extract_json(text)
        assert result is not None
        assert "paper_queries" in result

    def test_json_followed_by_explanation(self) -> None:
        text = (
            '{"ranked_videos": [{"video_id": "abc", "final_score": 0.9}]}\n\n'
            "These are the top videos based on relevance and depth."
        )
        result = extract_json(text)
        assert result is not None
        assert "ranked_videos" in result

    def test_preamble_with_code_block(self) -> None:
        text = (
            "Here are the search queries I recommend:\n\n"
            "```json\n"
            '{"paper_queries": ["memory architecture"], "video_queries": ["RAG tutorial"]}\n'
            "```\n"
        )
        result = extract_json(text)
        assert result is not None
        assert result["paper_queries"] == ["memory architecture"]


class TestEdgeCases:
    """Edge cases and malformed responses."""

    def test_no_json_at_all(self) -> None:
        text = "I cannot generate queries for this topic because it is too broad."
        assert extract_json(text) is None

    def test_partial_json(self) -> None:
        text = '{"paper_queries": ["q1", "q2"'  # missing closing
        assert extract_json(text) is None

    def test_nested_json(self) -> None:
        text = '{"ranked_items": [{"identifier": "2401.123", "kind": "paper", "scores": {"fit": 0.9}}]}'
        result = extract_json(text)
        assert result is not None
        assert len(result["ranked_items"]) == 1

    def test_json_with_escaped_quotes(self) -> None:
        text = '{"title": "Paper about \\"memory\\" systems"}'
        result = extract_json(text)
        assert result is not None
        assert "memory" in result["title"]

    def test_multiline_json(self) -> None:
        text = """{
  "paper_queries": [
    "agentic memory LLM agents",
    "knowledge graph memory systems"
  ],
  "video_queries": [
    "LLM memory tutorial",
    "RAG long term memory"
  ]
}"""
        result = extract_json(text)
        assert result is not None
        assert len(result["paper_queries"]) == 2
        assert len(result["video_queries"]) == 2


class TestGemma4Patterns:
    """Patterns specifically seen from Gemma 4 models."""

    def test_gemma_preamble_with_json(self) -> None:
        """Gemma often adds a brief preamble before JSON."""
        text = (
            "Based on the research goal, here are optimized search queries:\n\n"
            "```json\n"
            "{\n"
            '  "paper_queries": [\n'
            '    "agentic memory architecture LLM",\n'
            '    "persistent knowledge graph agents"\n'
            "  ],\n"
            '  "video_queries": [\n'
            '    "building agent memory systems",\n'
            '    "LLM knowledge base tutorial"\n'
            "  ]\n"
            "}\n"
            "```"
        )
        result = extract_json(text)
        assert result is not None
        assert len(result["paper_queries"]) == 2
        assert len(result["video_queries"]) == 2

    def test_gemma_bullet_list_not_json(self) -> None:
        """Gemma might return a bullet list instead of JSON — should return None."""
        text = (
            "Here are the queries:\n\n"
            "Paper queries:\n"
            "- agentic memory LLM\n"
            "- knowledge graph agents\n\n"
            "Video queries:\n"
            "- memory systems tutorial\n"
        )
        assert extract_json(text) is None


# Property test: any valid JSON dict/list round-trips through extract_json
@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
@given(
    data=st.one_of(
        st.dictionaries(
            st.text(min_size=1, max_size=10, alphabet="abcdefghijklmnop"),
            st.one_of(st.integers(), st.text(max_size=20), st.booleans()),
            max_size=5,
        ),
        st.lists(st.integers(), max_size=5),
    )
)
def test_valid_json_round_trips(data: dict | list) -> None:
    """Any valid JSON serialized to string extracts back correctly."""
    import json

    text = json.dumps(data)
    result = extract_json(text)
    assert result == data

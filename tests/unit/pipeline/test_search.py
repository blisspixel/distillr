"""Property-based and unit tests for distill/pipeline/search.py."""

from __future__ import annotations

from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from distill.config import DistillConfig
from distill.pipeline.search import SearchResult, extract_section, search_corpus


@pytest.fixture
def corpus_config(tmp_path):
    """Create a DistillConfig with a populated test corpus."""
    config = DistillConfig(
        xai_api_key="test",
        distill_output_dir=tmp_path / "library",
    )
    topic_dir = config.topic_dir("test-topic")

    # Create artifacts of each type
    _write_artifact(
        topic_dir / "channels" / "ch1" / "videos" / "v1" / "insights.md",
        "---\ntitle: test\n---\n# Key Findings\nMachine learning transforms data.",
    )
    _write_artifact(
        topic_dir / "channels" / "ch1" / "synthesis.md",
        "---\ntitle: synth\n---\n# Synthesis\nAI and machine learning overview.",
    )
    _write_artifact(
        topic_dir / "topic_diff.md",
        "---\ntitle: diff\n---\n# Changes\nNew machine learning papers added.",
    )
    _write_artifact(
        topic_dir / "topic_trends.md",
        "---\ntitle: trends\n---\n# Trends\nMachine learning adoption growing.",
    )
    _write_artifact(
        topic_dir / "corpus_synthesis.md",
        "---\ntitle: corpus\n---\n# Corpus\nCross-source machine learning view.",
    )
    _write_artifact(
        topic_dir / "papers" / "p1" / "paper.md",
        "---\ntitle: paper\n---\n# Paper\nMachine learning in production systems.",
    )
    return config


def _write_artifact(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


# ── Property 1: Search results are sorted by score descending ──
# Feature: mcp-first-surface, Property 1: Search results are sorted by score descending
# **Validates: Requirements 1.1**


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    query=st.text(
        alphabet=st.characters(whitelist_categories=("L", "N", "Z")),
        min_size=1,
        max_size=30,
    ).filter(lambda q: any(c.isalnum() for c in q)),
)
def test_search_results_sorted_by_score_descending(corpus_config, query):
    """Property 1: Search results are sorted by score descending."""
    results = search_corpus(corpus_config, "test-topic", query)
    for i in range(len(results) - 1):
        assert results[i].score >= results[i + 1].score


# ── Property 3: Limit parameter bounds result count ──
# Feature: mcp-first-surface, Property 3: Limit parameter bounds result count
# **Validates: Requirements 1.4**


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(limit=st.integers(min_value=1, max_value=100))
def test_limit_bounds_result_count(corpus_config, limit):
    """Property 3: Limit parameter bounds result count."""
    results = search_corpus(corpus_config, "test-topic", "machine learning", limit=limit)
    assert len(results) <= limit


# ── Property 4: Preview is a single line within 120 characters ──
# Feature: mcp-first-surface, Property 4: Preview is a single line within 120 characters
# **Validates: Requirements 1.5**


@settings(max_examples=100)
@given(
    content=st.text(min_size=1, max_size=500).filter(lambda t: any(c.isalnum() for c in t)),
)
def test_preview_single_line_within_120_chars(content):
    """Property 4: Preview is a single line within 120 characters."""
    from distill.pipeline.search import _generate_preview, _tokenize

    terms = _tokenize("test data")
    preview = _generate_preview(content, terms)
    # Preview should have no newlines
    assert "\n" not in preview
    # Preview should be <= 120 chars
    assert len(preview) <= 120


# ── Property 2: Search spans all artifact types ──
# Feature: mcp-first-surface, Property 2: Search spans all artifact types
# **Validates: Requirements 1.3**


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(data=st.data())
def test_search_spans_all_artifact_types(corpus_config, data):
    """Property 2: Search spans all artifact types when all types contain the query."""
    # The corpus_config fixture has all types with "machine learning"
    results = search_corpus(corpus_config, "test-topic", "machine learning", limit=100)
    types_found = {r.artifact_type for r in results}
    # All major types should be represented
    expected_types = {"insights", "synthesis", "diff", "trends", "corpus", "paper"}
    assert expected_types.issubset(types_found), f"Missing types: {expected_types - types_found}"


# ── Property 6: Section extraction returns only the named section ──
# Feature: mcp-first-surface, Property 6: Section extraction returns only the named section
# **Validates: Requirements 2.2**


@settings(max_examples=100)
@given(
    section_content=st.text(
        alphabet=st.characters(whitelist_categories=("L", "N", "Z", "P")),
        min_size=1,
        max_size=100,
    ).filter(lambda t: t.strip() and "#" not in t),
    other_content=st.text(
        alphabet=st.characters(whitelist_categories=("L", "N", "Z", "P")),
        min_size=1,
        max_size=100,
    ).filter(lambda t: t.strip() and "#" not in t),
)
def test_section_extraction_boundaries(section_content, other_content):
    """Property 6: Section extraction returns only the named section."""
    doc = f"## Introduction\n{other_content}\n## Target\n{section_content}\n## Conclusion\n{other_content}"
    extracted, found = extract_section(doc, "Target")
    assert found is True
    assert section_content.strip() in extracted
    # Should not contain content from other sections (unless it happens to match)
    assert extracted.startswith("## Target")


# ── Unit tests ──


class TestSearchCorpus:
    def test_empty_query_returns_empty(self, corpus_config):
        results = search_corpus(corpus_config, "test-topic", "")
        assert results == []

    def test_nonexistent_topic_returns_empty(self, corpus_config):
        results = search_corpus(corpus_config, "nonexistent", "machine learning")
        assert results == []

    def test_no_match_returns_empty(self, corpus_config):
        results = search_corpus(corpus_config, "test-topic", "xyzzyplugh")
        assert results == []

    def test_basic_search_returns_results(self, corpus_config):
        results = search_corpus(corpus_config, "test-topic", "machine learning")
        assert len(results) > 0
        assert all(isinstance(r, SearchResult) for r in results)
        assert all(r.score > 0 for r in results)


class TestExtractSection:
    def test_found_section(self):
        content = "# Intro\nHello\n## Details\nSome details here\n## End\nBye"
        extracted, found = extract_section(content, "Details")
        assert found is True
        assert "Some details here" in extracted
        assert "Bye" not in extracted

    def test_not_found_returns_full(self):
        content = "# Intro\nHello\n## Details\nSome details"
        extracted, found = extract_section(content, "Missing")
        assert found is False
        assert extracted == content

    def test_case_insensitive(self):
        content = "## KEY FINDINGS\nImportant stuff\n## Next\nOther"
        extracted, found = extract_section(content, "key findings")
        assert found is True
        assert "Important stuff" in extracted

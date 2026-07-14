"""Property-based and unit tests for distill/pipeline/search.py."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from distill.config import DistillConfig
from distill.library.insights import discover_insights, insight_content_sha256
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
@given(limit=st.integers(min_value=1, max_value=50))
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
    results = search_corpus(corpus_config, "test-topic", "machine learning", limit=50)
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
    @pytest.mark.parametrize("limit", [-1, 0, 51])
    def test_rejects_result_limits_outside_security_bounds(self, corpus_config, limit):
        with pytest.raises(ValueError, match="search limit must be between 1 and 50"):
            search_corpus(corpus_config, "test-topic", "machine learning", limit=limit)

    def test_accepts_result_limit_at_security_boundary(self, corpus_config):
        results = search_corpus(corpus_config, "test-topic", "machine learning", limit=50)

        assert len(results) == 6

    def test_rejects_query_above_character_bound_before_corpus_walk(
        self, corpus_config, monkeypatch
    ):
        def unexpected_walk(*_args, **_kwargs):
            raise AssertionError("oversized query reached the corpus walk")

        monkeypatch.setattr(Path, "rglob", unexpected_walk)

        with pytest.raises(ValueError, match="search query exceeds 4096 characters"):
            search_corpus(corpus_config, "test-topic", "x" * 4097)

    def test_accepts_query_at_character_boundary(self, corpus_config):
        assert search_corpus(corpus_config, "test-topic", "x" * 4096) == []

    def test_rejects_too_many_unique_terms_before_corpus_walk(self, corpus_config, monkeypatch):
        def unexpected_walk(*_args, **_kwargs):
            raise AssertionError("oversized term set reached the corpus walk")

        monkeypatch.setattr(Path, "rglob", unexpected_walk)
        query = " ".join(f"term{index}" for index in range(129))

        with pytest.raises(ValueError, match="search query exceeds 128 unique terms"):
            search_corpus(corpus_config, "test-topic", query)

    def test_repeated_terms_are_deduplicated_before_scoring(self):
        from distill.pipeline.search import _tokenize

        assert _tokenize("alpha ALPHA beta alpha") == ["alpha", "beta"]

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

    @pytest.mark.parametrize("filename", ("unsafe_Insights.md", "unsafe_insights.md"))
    def test_skips_insight_with_mismatched_required_verification_binding(self, tmp_path, filename):
        config = DistillConfig(
            xai_api_key="test",
            distill_output_dir=tmp_path / "library",
        )
        insight_dir = config.topic_dir("test-topic") / "answers" / "unsafe"
        insight = insight_dir / filename
        _write_artifact(
            insight,
            "---\nverification_required: true\n---\n\nuntrustedneedle",
        )
        (insight_dir / "unsafe_Verify.json").write_text(
            json.dumps(
                {
                    "insight": insight.name,
                    "insight_sha256": "0" * 64,
                }
            ),
            encoding="utf-8",
        )

        assert search_corpus(config, "test-topic", "untrustedneedle") == []

    def test_never_indexes_raw_answer_artifacts(self, tmp_path):
        config = DistillConfig(
            xai_api_key="test",
            distill_output_dir=tmp_path / "library",
        )
        answers_dir = config.topic_dir("test-topic") / "answers"
        _write_artifact(answers_dir / "refused_Answer.md", "refusedanswerneedle")
        _write_artifact(answers_dir / "tampered_Answer.md", "tamperedanswerneedle")
        (answers_dir / "tampered_Verify.json").write_text(
            json.dumps(
                {
                    "insight": "tampered_Answer.md",
                    "insight_sha256": "0" * 64,
                }
            ),
            encoding="utf-8",
        )

        assert search_corpus(config, "test-topic", "refusedanswerneedle") == []
        assert search_corpus(config, "test-topic", "tamperedanswerneedle") == []

    def test_saved_answer_cannot_downgrade_its_verification_requirement(self, tmp_path):
        config = DistillConfig(
            xai_api_key="test",
            distill_output_dir=tmp_path / "library",
        )
        insight = config.topic_dir("test-topic") / "answers" / "tampered" / "tampered_Insights.md"
        _write_artifact(insight, "downgradecanary")

        assert (
            discover_insights(
                config.topic_dir("test-topic"),
                confinement_root=config.library_dir,
            )
            == []
        )
        assert search_corpus(config, "test-topic", "downgradecanary") == []

    def test_indexes_only_the_content_snapshot_validated_by_discovery(self, tmp_path, monkeypatch):
        import distill.pipeline.search as search_mod

        config = DistillConfig(
            xai_api_key="test",
            distill_output_dir=tmp_path / "library",
        )
        insight_dir = config.topic_dir("test-topic") / "answers" / "verified"
        insight = insight_dir / "verified_Insights.md"
        original = "---\nverification_required: true\n---\n\ntrusted content"
        _write_artifact(insight, original)
        (insight_dir / "verified_Verify.json").write_text(
            json.dumps(
                {
                    "insight": insight.name,
                    "insight_sha256": insight_content_sha256(original),
                }
            ),
            encoding="utf-8",
        )
        real_discover = search_mod.discover_insights

        def discover_then_replace(*args, **kwargs):
            refs = real_discover(*args, **kwargs)
            insight.write_text("racebypassneedle", encoding="utf-8")
            return refs

        monkeypatch.setattr(search_mod, "discover_insights", discover_then_replace)

        assert search_mod.search_corpus(config, "test-topic", "racebypassneedle") == []

    def test_rejects_hardlinked_artifacts_from_outside_the_corpus(self, tmp_path):
        config = DistillConfig(
            xai_api_key="test",
            distill_output_dir=tmp_path / "library",
        )
        topic_dir = config.topic_dir("test-topic")
        topic_dir.mkdir(parents=True)
        outside = tmp_path / "outside-secret.md"
        outside.write_text("outsidehardlinkneedle", encoding="utf-8")
        try:
            (topic_dir / "linked.md").hardlink_to(outside)
            linked_insight = topic_dir / "linked_Insights.md"
            linked_insight.hardlink_to(outside)
        except OSError as exc:
            pytest.skip(f"hard links unavailable: {exc}")

        assert discover_insights(topic_dir) == []
        assert search_corpus(config, "test-topic", "outsidehardlinkneedle") == []

    def test_rejects_symlinked_artifacts_from_outside_the_corpus(self, tmp_path):
        config = DistillConfig(
            xai_api_key="test",
            distill_output_dir=tmp_path / "library",
        )
        topic_dir = config.topic_dir("test-topic")
        topic_dir.mkdir(parents=True)
        outside = tmp_path / "outside-secret.md"
        outside.write_text("outsidesymlinkneedle", encoding="utf-8")
        try:
            (topic_dir / "linked.md").symlink_to(outside)
            linked_insight = topic_dir / "linked_Insights.md"
            linked_insight.symlink_to(outside)
        except OSError as exc:
            pytest.skip(f"file symlinks unavailable: {exc}")

        assert discover_insights(topic_dir) == []
        assert search_corpus(config, "test-topic", "outsidesymlinkneedle") == []

    def test_rejects_topic_directory_linked_outside_the_library(self, tmp_path):
        config = DistillConfig(
            xai_api_key="test",
            distill_output_dir=tmp_path / "library",
        )
        (config.library_dir / "topics").mkdir(parents=True)
        outside_topic = tmp_path / "outside-topic"
        _write_artifact(outside_topic / "outside_Insights.md", "outsidetopicneedle")
        topic_dir = config.topic_dir("test-topic")
        try:
            topic_dir.symlink_to(outside_topic, target_is_directory=True)
        except OSError as exc:
            pytest.skip(f"directory symlinks unavailable: {exc}")

        assert (
            discover_insights(
                topic_dir,
                confinement_root=config.library_dir,
            )
            == []
        )
        assert search_corpus(config, "test-topic", "outsidetopicneedle") == []

    def test_artifact_type_unaffected_by_absolute_ancestor_names(self, tmp_path):
        """Classification must not key off ancestor directories outside the library.

        Regression: ``_detect_artifact_type`` previously inspected
        ``path.parts`` (the absolute path), so a library rooted under a
        directory named ``papers`` or ``sites`` mis-labeled every artifact.
        Now scoped to the library-relative path.
        """
        # Library lives under a directory named "papers" — would have poisoned
        # the classifier under the old code.
        ancestor = tmp_path / "papers" / "library"
        config = DistillConfig(xai_api_key="test", distill_output_dir=ancestor)
        topic_dir = config.topic_dir("test-topic")
        # Place an insights-style artifact NOT inside a "papers/" subtree.
        target = topic_dir / "channels" / "ch1" / "videos" / "v1" / "x_Insights.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            "---\ntitle: t\n---\n# Heading\nMachine learning content here.",
            encoding="utf-8",
        )
        results = search_corpus(config, "test-topic", "machine learning")
        assert len(results) == 1
        assert results[0].artifact_type == "insights"  # not "paper"

    def test_skips_directories_unreadable_files_and_empty_bodies(self, tmp_path):
        config = DistillConfig(
            xai_api_key="test",
            distill_output_dir=tmp_path / "library",
        )
        topic_dir = config.topic_dir("test-topic")
        (topic_dir / "skip.md").mkdir(parents=True)
        empty_artifact = topic_dir / "empty.md"
        unreadable_artifact = topic_dir / "unreadable.md"
        readable_artifact = topic_dir / "artifact.md"
        _write_artifact(empty_artifact, "---\ntitle: empty\n---\n   \n")
        unreadable_artifact.write_bytes(b"machine learning hidden\xff")
        _write_artifact(readable_artifact, "machine learning visible")

        results = search_corpus(config, "test-topic", "machine learning")

        assert [Path(result.path) for result in results] == [Path("topics/test-topic/artifact.md")]

    @pytest.mark.parametrize(
        ("relative_path", "expected_type"),
        [
            (Path("topics/test-topic/papers/source/artifact.md"), "paper"),
            (Path("topics/test-topic/sites/source/artifact.md"), "insights"),
            (Path("topics/test-topic/channels/source/artifact.md"), "insights"),
        ],
    )
    def test_artifact_type_falls_back_to_library_relative_parent_dirs(
        self,
        tmp_path,
        relative_path,
        expected_type,
    ):
        config = DistillConfig(
            xai_api_key="test",
            distill_output_dir=tmp_path / "library",
        )
        _write_artifact(
            config.library_dir / relative_path,
            "machine learning visible",
        )

        results = search_corpus(config, "test-topic", "machine learning")

        assert len(results) == 1
        assert results[0].artifact_type == expected_type


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

    def test_ignores_malformed_headings_and_keeps_nested_content(self):
        content = (
            "#Intro\n"
            "ignored malformed heading\n"
            "## Details\n"
            "parent text\n"
            "### Nested\n"
            "nested text\n"
            "#Not a real boundary\n"
            "still details\n"
            "## End\n"
            "outside"
        )

        extracted, found = extract_section(content, "Details")

        assert found is True
        assert "nested text" in extracted
        assert "still details" in extracted
        assert "outside" not in extracted

    def test_extracts_final_section_without_following_heading(self):
        content = "# Intro\nignored\n## Tail\nfinal text"

        extracted, found = extract_section(content, "Tail")

        assert found is True
        assert extracted == "## Tail\nfinal text"


class TestPreviewGeneration:
    def test_preview_falls_back_to_first_content_line_and_strips_markdown(self):
        from distill.pipeline.search import _generate_preview, _tokenize

        body = "\n#\n- **Alpha** and *beta* with [docs](https://example.test) plus `code`."

        preview = _generate_preview(body, _tokenize("missing"))

        assert preview == "Alpha and beta with docs plus code."

    def test_preview_returns_empty_for_blank_and_marker_only_content(self):
        from distill.pipeline.search import _generate_preview, _tokenize

        preview = _generate_preview("\n   \n###\n", _tokenize("missing"))

        assert preview == ""

    def test_preview_hard_truncates_when_no_word_boundary_exists(self):
        from distill.pipeline.search import _generate_preview, _tokenize

        preview = _generate_preview("x" * 140, _tokenize("missing"))

        assert preview == ("x" * 117) + "..."

    def test_truncates_at_word_boundary_when_available(self):
        from distill.pipeline.search import _truncate_at_word

        preview = _truncate_at_word("alpha beta gamma delta", 18)

        assert preview == "alpha beta gamma..."

"""Unit tests for distill.library.wikilinks edge cases.

Feature: living-wiki-0-7
Requirements: 1.7
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from distill.library.wikilinks import WikiLink, emit_wiki_link, parse_wiki_links

# ---------------------------------------------------------------------------
# WikiLink.from_source edge cases
# ---------------------------------------------------------------------------


class TestWikiLinkFromSourceEdgeCases:
    """Test WikiLink.from_source with unusual inputs."""

    def test_empty_title(self) -> None:
        """Empty title with source_id produces slug from source_id only."""
        link = WikiLink.from_source("", "abc123", "insights")
        # slugify_title("", "abc123") → "_abc123" (empty base + source_id suffix)
        assert link.slug == "_abc123"
        assert link.display_title == ""
        assert link.suffix == "Insights"

    def test_empty_title_no_source_id(self) -> None:
        """Empty title with no source_id produces 'untitled' slug."""
        link = WikiLink.from_source("", "", "insights")
        assert link.slug == "untitled"
        assert link.display_title == ""
        assert link.suffix == "Insights"

    def test_title_with_only_special_chars(self) -> None:
        """Title with only special characters uses source_id for slug."""
        link = WikiLink.from_source("!@#$%^&*()", "id1", "insights")
        # slugify_title strips all special chars → empty base, appends source_id
        assert link.slug == "_id1"
        assert link.display_title == "!@#$%^&*()"

    def test_very_long_title(self) -> None:
        """Very long title is truncated in slug but preserved in display_title."""
        long_title = "A" * 500
        link = WikiLink.from_source(long_title, "src1", "insights")
        # Slug should be truncated (max_len=60 by default + source_id suffix)
        assert len(link.slug) <= 70
        # Display title is preserved in full
        assert link.display_title == long_title

    def test_unknown_artifact_type_uses_title_case(self) -> None:
        """Unknown artifact type falls back to artifact_type.title()."""
        link = WikiLink.from_source("Test", "id1", "custom_thing")
        assert link.suffix == "Custom_Thing"

    def test_render_format(self) -> None:
        """Render produces correct [[slug_Suffix|Display Title]] format."""
        link = WikiLink(slug="my-slug", suffix="Insights", display_title="My Title")
        assert link.render() == "[[my-slug_Insights|My Title]]"


# ---------------------------------------------------------------------------
# emit_wiki_link edge cases
# ---------------------------------------------------------------------------


class TestEmitWikiLinkFallback:
    """Test emit_wiki_link fallback to plain text when corpus_dir provided but target missing."""

    def test_fallback_when_target_missing(self) -> None:
        """Returns plain text title when corpus_dir is provided but target not found."""
        with tempfile.TemporaryDirectory() as tmp:
            corpus_dir = Path(tmp)
            result = emit_wiki_link("Missing Source", "xyz", "insights", corpus_dir=corpus_dir)
            # Should fall back to plain text (the title)
            assert result == "Missing Source"

    def test_no_fallback_when_corpus_dir_none(self) -> None:
        """Returns wiki-link when corpus_dir is None (no validation)."""
        result = emit_wiki_link("Any Title", "abc", "insights", corpus_dir=None)
        assert result.startswith("[[")
        assert result.endswith("]]")
        assert "Any Title" in result

    def test_no_fallback_when_target_exists(self) -> None:
        """Returns wiki-link when target file exists in corpus_dir."""
        with tempfile.TemporaryDirectory() as tmp:
            corpus_dir = Path(tmp)
            # Create a file matching the expected pattern
            link = WikiLink.from_source("Found Source", "abc", "insights")
            target_file = corpus_dir / f"{link.slug}_{link.suffix}.md"
            target_file.write_text("# Content", encoding="utf-8")

            result = emit_wiki_link("Found Source", "abc", "insights", corpus_dir=corpus_dir)
            assert result.startswith("[[")
            assert "Found Source" in result

    def test_fallback_with_empty_title(self) -> None:
        """Empty title with missing target returns empty string (the title)."""
        with tempfile.TemporaryDirectory() as tmp:
            corpus_dir = Path(tmp)
            result = emit_wiki_link("", "id1", "insights", corpus_dir=corpus_dir)
            assert result == ""


# ---------------------------------------------------------------------------
# parse_wiki_links edge cases
# ---------------------------------------------------------------------------


class TestParseWikiLinksEdgeCases:
    """Test parse_wiki_links with malformed links, nested brackets, etc."""

    def test_standard_link_with_display(self) -> None:
        """Standard [[slug_Suffix|Display Title]] is parsed correctly."""
        content = "See [[my-article_Insights|My Article]] for details."
        links = parse_wiki_links(content)
        assert len(links) == 1
        assert links[0].slug == "my-article"
        assert links[0].suffix == "Insights"
        assert links[0].display_title == "My Article"

    def test_link_without_display_text(self) -> None:
        """Link without pipe uses slug portion as display_title."""
        content = "See [[my-article_Insights]] for details."
        links = parse_wiki_links(content)
        assert len(links) == 1
        assert links[0].slug == "my-article"
        assert links[0].suffix == "Insights"
        assert links[0].display_title == "my-article_Insights"

    def test_malformed_unclosed_bracket(self) -> None:
        """Unclosed [[ is not matched."""
        content = "See [[broken-link for details."
        links = parse_wiki_links(content)
        assert len(links) == 0

    def test_malformed_single_bracket(self) -> None:
        """Single brackets [text] are not matched."""
        content = "See [not-a-link] for details."
        links = parse_wiki_links(content)
        assert len(links) == 0

    def test_nested_brackets(self) -> None:
        """Nested brackets [[outer[[inner]]]] — regex matches innermost valid pair."""
        content = "[[outer[[inner_Suffix|Title]]]]"
        links = parse_wiki_links(content)
        # The regex should match the innermost valid [[...]] pattern
        assert len(links) == 1
        assert links[0].display_title == "Title"

    def test_empty_content(self) -> None:
        """Empty content returns empty list."""
        links = parse_wiki_links("")
        assert links == []

    def test_multiple_links(self) -> None:
        """Multiple links in content are all parsed."""
        content = "[[a_Insights|A]] and [[b_Report|B]] and [[c_Brief|C]]"
        links = parse_wiki_links(content)
        assert len(links) == 3
        assert links[0].display_title == "A"
        assert links[1].display_title == "B"
        assert links[2].display_title == "C"

    def test_link_with_no_underscore_in_slug(self) -> None:
        """Link with no underscore: entire slug portion becomes slug, suffix is empty."""
        content = "[[simple|Display]]"
        links = parse_wiki_links(content)
        assert len(links) == 1
        assert links[0].slug == "simple"
        assert links[0].suffix == ""
        assert links[0].display_title == "Display"

    def test_empty_brackets(self) -> None:
        """Empty [[]] is not matched (regex requires at least one char)."""
        content = "See [[]] for details."
        links = parse_wiki_links(content)
        assert len(links) == 0

    def test_link_with_spaces_in_display(self) -> None:
        """Display title with spaces is preserved."""
        content = "[[slug_Insights|A Title With Spaces]]"
        links = parse_wiki_links(content)
        assert len(links) == 1
        assert links[0].display_title == "A Title With Spaces"

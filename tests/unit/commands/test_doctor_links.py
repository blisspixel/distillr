"""Unit tests for `distill doctor --links` command options.

Feature: living-wiki-0-7
Tests: --links, --links --json, --links --fix
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from distill.library.links import BrokenLink, LinkCheckResult, check_links, fix_broken_links


@pytest.fixture
def corpus_dir(tmp_path: Path) -> Path:
    """Create a temporary corpus with valid and broken wiki-links."""
    lib = tmp_path / "library"
    lib.mkdir()

    # Create some artifact files (these are valid targets)
    topic_dir = lib / "topics" / "ai-agents"
    topic_dir.mkdir(parents=True)

    valid_target = topic_dir / "ai-agents_Insights.md"
    valid_target.write_text("# AI Agents Insights\n", encoding="utf-8")

    another_target = topic_dir / "ai-agents_Synthesis.md"
    another_target.write_text("# AI Agents Synthesis\n", encoding="utf-8")

    # Create a file with both valid and broken links
    referencing = topic_dir / "summary.md"
    referencing.write_text(
        "# Summary\n\n"
        "See [[ai-agents_Insights|AI Agents]] for details.\n"
        "Also check [[missing-artifact_Report|Missing Report]].\n"
        "And [[another-broken_Insights|Another Broken]].\n",
        encoding="utf-8",
    )

    return lib


class TestCheckLinks:
    """Tests for check_links function used by doctor --links."""

    def test_check_links_finds_broken_links(self, corpus_dir: Path) -> None:
        """check_links correctly identifies broken wiki-links."""
        result = check_links(corpus_dir)

        assert result.files_scanned >= 3
        assert result.total_links == 3
        assert len(result.broken_links) == 2
        assert not result.is_healthy

    def test_check_links_valid_corpus(self, tmp_path: Path) -> None:
        """check_links reports healthy when all links resolve."""
        lib = tmp_path / "library"
        lib.mkdir()

        # Create target
        (lib / "my-article_Insights.md").write_text("# Insights\n", encoding="utf-8")
        # Create file with valid link
        (lib / "index.md").write_text(
            "See [[my-article_Insights|My Article]].\n", encoding="utf-8"
        )

        result = check_links(lib)
        assert result.is_healthy
        assert result.total_links == 1
        assert len(result.broken_links) == 0

    def test_check_links_empty_corpus(self, tmp_path: Path) -> None:
        """check_links handles empty corpus gracefully."""
        lib = tmp_path / "library"
        lib.mkdir()

        result = check_links(lib)
        assert result.is_healthy
        assert result.total_links == 0
        assert result.files_scanned == 0

    def test_check_links_reports_correct_line_numbers(self, corpus_dir: Path) -> None:
        """Broken links include correct source file and line number."""
        result = check_links(corpus_dir)

        # The broken links should have line numbers
        for bl in result.broken_links:
            assert bl.line_number > 0
            assert bl.source_file.exists()
            assert bl.link_text.startswith("[[")
            assert bl.target_slug != ""


class TestLinkCheckResultJson:
    """Tests for --json output structure."""

    def test_to_dict_structure(self, corpus_dir: Path) -> None:
        """to_dict() produces valid JSON-serializable structure."""
        result = check_links(corpus_dir)
        d = result.to_dict()

        assert "total_links" in d
        assert "broken_links" in d
        assert "files_scanned" in d
        assert "is_healthy" in d

        # Verify it's JSON-serializable
        json_str = json.dumps(d)
        parsed = json.loads(json_str)
        assert parsed["total_links"] == result.total_links
        assert parsed["is_healthy"] == result.is_healthy

    def test_to_dict_broken_link_fields(self, corpus_dir: Path) -> None:
        """Each broken link in to_dict has required fields."""
        result = check_links(corpus_dir)
        d = result.to_dict()

        for bl in d["broken_links"]:
            assert "source_file" in bl
            assert "line_number" in bl
            assert "link_text" in bl
            assert "target_slug" in bl
            assert isinstance(bl["line_number"], int)
            assert isinstance(bl["source_file"], str)

    def test_to_dict_healthy_corpus(self, tmp_path: Path) -> None:
        """Healthy corpus produces is_healthy=True in dict."""
        lib = tmp_path / "library"
        lib.mkdir()
        (lib / "test.md").write_text("No links here.\n", encoding="utf-8")

        result = check_links(lib)
        d = result.to_dict()
        assert d["is_healthy"] is True
        assert d["broken_links"] == []


class TestFixBrokenLinks:
    """Tests for doctor --links --fix behavior."""

    def test_fix_replaces_broken_links_only(self, corpus_dir: Path) -> None:
        """fix_broken_links replaces only broken links, preserving valid ones."""
        result = check_links(corpus_dir)
        assert len(result.broken_links) == 2

        fixed_count = fix_broken_links(corpus_dir, result.broken_links)
        assert fixed_count == 2

        # Read the modified file
        summary_file = corpus_dir / "topics" / "ai-agents" / "summary.md"
        content = summary_file.read_text(encoding="utf-8")

        # Valid link should still be present
        assert "[[ai-agents_Insights|AI Agents]]" in content
        # Broken links should be replaced with plain text
        assert "[[missing-artifact_Report|Missing Report]]" not in content
        assert "Missing Report" in content
        assert "[[another-broken_Insights|Another Broken]]" not in content
        assert "Another Broken" in content

    def test_fix_with_no_broken_links(self, tmp_path: Path) -> None:
        """fix_broken_links with empty list does nothing."""
        lib = tmp_path / "library"
        lib.mkdir()
        (lib / "test.md").write_text("# Test\n", encoding="utf-8")

        fixed_count = fix_broken_links(lib, [])
        assert fixed_count == 0

    def test_fix_preserves_file_structure(self, corpus_dir: Path) -> None:
        """fix_broken_links preserves overall file structure."""
        result = check_links(corpus_dir)
        summary_file = corpus_dir / "topics" / "ai-agents" / "summary.md"
        original_lines = summary_file.read_text(encoding="utf-8").splitlines()

        fix_broken_links(corpus_dir, result.broken_links)

        new_lines = summary_file.read_text(encoding="utf-8").splitlines()
        # Same number of lines (links replaced inline, not removed)
        assert len(new_lines) == len(original_lines)

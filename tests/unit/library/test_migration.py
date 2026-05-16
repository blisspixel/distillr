"""Unit tests for distill.library.migration module.

Feature: living-wiki-0-7
Tests: dry-run, apply, conflict detection, summary report accuracy.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from distill.library.migration import (
    _compute_modern_name,
    apply_frontmatter_field_migration,
    apply_migration,
    scan_confidence_field,
    scan_legacy_artifacts,
)


@pytest.fixture
def library_dir(tmp_path: Path) -> Path:
    """Create a temporary library directory with legacy-named artifacts."""
    lib = tmp_path / "library"
    lib.mkdir()
    return lib


def _create_legacy_corpus(library_dir: Path) -> dict[str, Path]:
    """Create a sample corpus with legacy-named files. Returns created paths."""
    paths: dict[str, Path] = {}

    # Topic with legacy insights
    topic_dir = (
        library_dir
        / "topics"
        / "ai-agents"
        / "channels"
        / "AI-News"
        / "videos"
        / "gpt5-launch_abc12345"
    )
    topic_dir.mkdir(parents=True)
    insights = topic_dir / "insights.md"
    insights.write_text("# GPT-5 Launch Insights\n\nSee [[insights|related]].\n", encoding="utf-8")
    paths["insights"] = insights

    # Topic with legacy synthesis
    synth_dir = library_dir / "topics" / "ai-agents"
    synth_dir.mkdir(parents=True, exist_ok=True)
    synthesis = synth_dir / "synthesis.md"
    synthesis.write_text(
        "# AI Agents Synthesis\n\nReferences [[insights|GPT-5]].\n", encoding="utf-8"
    )
    paths["synthesis"] = synthesis

    # Topic with legacy transcript
    transcript = topic_dir / "transcript.txt"
    transcript.write_text("This is a transcript.\n", encoding="utf-8")
    paths["transcript"] = transcript

    return paths


class TestScanLegacyArtifacts:
    """Tests for scan_legacy_artifacts (dry-run behavior)."""

    def test_empty_library_returns_no_actions(self, library_dir: Path) -> None:
        """Empty library produces no migration actions."""
        actions = scan_legacy_artifacts(library_dir)
        assert actions == []

    def test_detects_legacy_insights(self, library_dir: Path) -> None:
        """Detects insights.md as a legacy artifact."""
        artifact_dir = library_dir / "topics" / "my-topic"
        artifact_dir.mkdir(parents=True)
        (artifact_dir / "insights.md").write_text("# Insights\n", encoding="utf-8")

        actions = scan_legacy_artifacts(library_dir)
        assert len(actions) == 1
        assert actions[0].action_type == "rename"
        assert actions[0].source_path.name == "insights.md"
        assert actions[0].target_path.name == "my-topic_Insights.md"

    def test_detects_legacy_transcript(self, library_dir: Path) -> None:
        """Detects transcript.txt as a legacy artifact."""
        artifact_dir = library_dir / "topics" / "video-slug"
        artifact_dir.mkdir(parents=True)
        (artifact_dir / "transcript.txt").write_text("Transcript content\n", encoding="utf-8")

        actions = scan_legacy_artifacts(library_dir)
        assert len(actions) == 1
        assert actions[0].target_path.name == "video-slug_Transcript.txt"

    def test_scan_does_not_modify_files(self, library_dir: Path) -> None:
        """Dry-run (scan) produces actions without modifying any files."""
        paths = _create_legacy_corpus(library_dir)

        # Record original content
        original_content = {name: path.read_text(encoding="utf-8") for name, path in paths.items()}

        # Scan
        actions = scan_legacy_artifacts(library_dir)
        assert len(actions) > 0

        # Verify no files were modified
        for name, path in paths.items():
            assert path.exists(), f"{name} should still exist"
            assert path.read_text(encoding="utf-8") == original_content[name]

    def test_ignores_files_at_library_root(self, library_dir: Path) -> None:
        """Files at the library root are skipped (no parent slug)."""
        (library_dir / "insights.md").write_text("# Root insights\n", encoding="utf-8")

        actions = scan_legacy_artifacts(library_dir)
        assert actions == []

    def test_ignores_modern_named_files(self, library_dir: Path) -> None:
        """Files already using modern naming are not detected."""
        artifact_dir = library_dir / "topics" / "my-topic"
        artifact_dir.mkdir(parents=True)
        (artifact_dir / "my-topic_Insights.md").write_text("# Modern\n", encoding="utf-8")

        actions = scan_legacy_artifacts(library_dir)
        assert actions == []

    def test_multiple_legacy_files_detected(self, library_dir: Path) -> None:
        """Multiple legacy files in different directories are all detected."""
        _create_legacy_corpus(library_dir)
        actions = scan_legacy_artifacts(library_dir)
        assert len(actions) >= 3  # insights.md, synthesis.md, transcript.txt


class TestApplyMigration:
    """Tests for apply_migration (executing renames and link updates)."""

    def test_apply_executes_renames(self, library_dir: Path) -> None:
        """Apply renames legacy files to modern names."""
        artifact_dir = library_dir / "topics" / "my-topic"
        artifact_dir.mkdir(parents=True)
        legacy_file = artifact_dir / "insights.md"
        legacy_file.write_text("# Insights content\n", encoding="utf-8")

        actions = scan_legacy_artifacts(library_dir)
        result = apply_migration(actions, library_dir=library_dir)

        assert result.files_renamed == 1
        assert not legacy_file.exists()
        assert (artifact_dir / "my-topic_Insights.md").exists()
        assert (artifact_dir / "my-topic_Insights.md").read_text(
            encoding="utf-8"
        ) == "# Insights content\n"

    def test_apply_updates_wiki_links(self, library_dir: Path) -> None:
        """Apply updates wiki-links in other files that reference renamed stems."""
        artifact_dir = library_dir / "topics" / "my-topic"
        artifact_dir.mkdir(parents=True)
        legacy_file = artifact_dir / "insights.md"
        legacy_file.write_text("# Insights\n", encoding="utf-8")

        # Another file referencing the old stem
        referencing_file = library_dir / "topics" / "other.md"
        referencing_file.write_text("See [[insights|My Insights]] for details.\n", encoding="utf-8")

        actions = scan_legacy_artifacts(library_dir)
        result = apply_migration(actions, library_dir=library_dir)

        assert result.files_renamed == 1
        # The link should be updated from [[insights...]] to [[my-topic_Insights...]]
        updated_content = referencing_file.read_text(encoding="utf-8")
        assert "[[insights" not in updated_content
        assert "[[my-topic_Insights" in updated_content

    def test_conflict_detection_skips_existing_target(self, library_dir: Path) -> None:
        """When target already exists, the rename is skipped as a conflict."""
        artifact_dir = library_dir / "topics" / "my-topic"
        artifact_dir.mkdir(parents=True)
        legacy_file = artifact_dir / "insights.md"
        legacy_file.write_text("# Legacy\n", encoding="utf-8")
        # Pre-create the target
        target_file = artifact_dir / "my-topic_Insights.md"
        target_file.write_text("# Already exists\n", encoding="utf-8")

        actions = scan_legacy_artifacts(library_dir)
        result = apply_migration(actions, library_dir=library_dir)

        assert result.conflicts_skipped == 1
        assert result.files_renamed == 0
        # Both files should still exist with original content
        assert legacy_file.read_text(encoding="utf-8") == "# Legacy\n"
        assert target_file.read_text(encoding="utf-8") == "# Already exists\n"

    def test_missing_source_reports_error(self, library_dir: Path) -> None:
        """When source disappears between scan and apply, it's reported as error."""
        artifact_dir = library_dir / "topics" / "my-topic"
        artifact_dir.mkdir(parents=True)
        legacy_file = artifact_dir / "insights.md"
        legacy_file.write_text("# Insights\n", encoding="utf-8")

        actions = scan_legacy_artifacts(library_dir)

        # Delete the source before applying
        legacy_file.unlink()

        result = apply_migration(actions, library_dir=library_dir)
        assert result.files_renamed == 0
        assert len(result.errors) == 1
        assert "disappeared" in result.errors[0].lower()

    def test_summary_report_accuracy(self, library_dir: Path) -> None:
        """Summary report accurately reflects the migration outcome."""
        # Create multiple legacy files, one with a conflict
        dir1 = library_dir / "topics" / "topic-a"
        dir1.mkdir(parents=True)
        (dir1 / "insights.md").write_text("# A insights\n", encoding="utf-8")

        dir2 = library_dir / "topics" / "topic-b"
        dir2.mkdir(parents=True)
        (dir2 / "insights.md").write_text("# B insights\n", encoding="utf-8")
        # Pre-create target for topic-b to cause conflict
        (dir2 / "topic-b_Insights.md").write_text("# Existing\n", encoding="utf-8")

        actions = scan_legacy_artifacts(library_dir)
        result = apply_migration(actions, library_dir=library_dir)

        assert result.files_renamed == 1  # Only topic-a succeeds
        assert result.conflicts_skipped == 1  # topic-b is a conflict
        assert isinstance(result.errors, list)


class TestComputeModernName:
    """Tests for _compute_modern_name helper."""

    def test_insights_md(self, tmp_path: Path) -> None:
        """insights.md → <parent>_Insights.md"""
        path = tmp_path / "my-slug" / "insights.md"
        path.parent.mkdir(parents=True)
        assert _compute_modern_name(path) == "my-slug_Insights.md"

    def test_transcript_txt(self, tmp_path: Path) -> None:
        """transcript.txt → <parent>_Transcript.txt"""
        path = tmp_path / "video-slug" / "transcript.txt"
        path.parent.mkdir(parents=True)
        assert _compute_modern_name(path) == "video-slug_Transcript.txt"

    def test_report_md(self, tmp_path: Path) -> None:
        """report.md → <parent>_Report.md"""
        path = tmp_path / "topic-name" / "report.md"
        path.parent.mkdir(parents=True)
        assert _compute_modern_name(path) == "topic-name_Report.md"

    def test_unknown_filename_returns_unchanged(self, tmp_path: Path) -> None:
        """Unknown filename is returned unchanged."""
        path = tmp_path / "my-slug" / "unknown_file.md"
        path.parent.mkdir(parents=True)
        assert _compute_modern_name(path) == "unknown_file.md"


# ---------------------------------------------------------------------------
# 0.8.1 — confidence: -> synthesis_scope: rename
# ---------------------------------------------------------------------------


def _write_md(path: Path, frontmatter_lines: list[str], body: str = "body") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fm = "---\n" + "\n".join(frontmatter_lines) + "\n---\n"
    path.write_text(fm + body + "\n", encoding="utf-8")


class TestScanConfidenceField:
    def test_finds_files_with_confidence_field(self, library_dir: Path) -> None:
        target = library_dir / "topics" / "tkg" / "papers" / "x" / "x_Insights.md"
        _write_md(
            target,
            ['title: "x"', 'type: "insights"', 'confidence: "single-paper"'],
        )
        actions = scan_confidence_field(library_dir)
        assert len(actions) == 1
        assert actions[0].path == target
        assert actions[0].old_field == "confidence"
        assert actions[0].new_field == "synthesis_scope"
        assert actions[0].value == '"single-paper"'

    def test_skips_files_already_migrated(self, library_dir: Path) -> None:
        already = library_dir / "topics" / "tkg" / "papers" / "y" / "y_Insights.md"
        _write_md(
            already,
            ['title: "y"', 'type: "insights"', 'synthesis_scope: "single-paper"'],
        )
        assert scan_confidence_field(library_dir) == []

    def test_skips_hidden_dirs(self, library_dir: Path) -> None:
        """``.history/``, ``.distill/``, ``.concepts/`` are immutable history."""
        for hidden in (".history", ".distill", ".concepts"):
            target = library_dir / "topics" / "tkg" / hidden / "snap.md"
            _write_md(target, ['confidence: "single-paper"'])
        assert scan_confidence_field(library_dir) == []

    def test_skips_files_without_frontmatter(self, library_dir: Path) -> None:
        plain = library_dir / "topics" / "tkg" / "notes.md"
        plain.parent.mkdir(parents=True)
        plain.write_text("# Just a note\nNo frontmatter, no confidence:\n", encoding="utf-8")
        assert scan_confidence_field(library_dir) == []


class TestApplyFrontmatterFieldMigration:
    def test_rewrites_confidence_to_synthesis_scope(self, library_dir: Path) -> None:
        target = library_dir / "topics" / "tkg" / "papers" / "x" / "x_Insights.md"
        _write_md(
            target,
            [
                'title: "x"',
                'type: "insights"',
                'confidence: "single-paper"',
                'generated_at: "2026-05-15"',
            ],
        )
        result = apply_frontmatter_field_migration(scan_confidence_field(library_dir))
        assert result.files_rewritten == 1
        assert result.errors == []
        text = target.read_text(encoding="utf-8")
        assert "synthesis_scope:" in text
        assert "confidence:" not in text
        # Other fields untouched
        assert 'title: "x"' in text
        assert 'generated_at: "2026-05-15"' in text
        # Body untouched
        assert text.endswith("body\n")

    def test_idempotent_second_run_is_noop(self, library_dir: Path) -> None:
        target = library_dir / "topics" / "tkg" / "papers" / "x" / "x_Insights.md"
        _write_md(target, ['confidence: "single-paper"'])
        first = apply_frontmatter_field_migration(scan_confidence_field(library_dir))
        assert first.files_rewritten == 1
        # Second pass finds nothing
        second = apply_frontmatter_field_migration(scan_confidence_field(library_dir))
        assert second.files_rewritten == 0
        assert second.files_skipped == 0  # no actions to process

    def test_drops_old_field_when_new_field_already_present(self, library_dir: Path) -> None:
        """Partial prior run / manual edit: both fields present, old one wins via removal."""
        target = library_dir / "topics" / "tkg" / "papers" / "x" / "x_Insights.md"
        _write_md(
            target,
            [
                'title: "x"',
                'synthesis_scope: "single-paper"',
                'confidence: "stale-value"',
            ],
        )
        result = apply_frontmatter_field_migration(scan_confidence_field(library_dir))
        assert result.files_rewritten == 1
        text = target.read_text(encoding="utf-8")
        assert "confidence:" not in text
        # The new field's original value is preserved (we drop the old, don't overwrite).
        assert 'synthesis_scope: "single-paper"' in text
        assert "stale-value" not in text

    def test_preserves_indentation_and_value_format(self, library_dir: Path) -> None:
        target = library_dir / "topics" / "tkg" / "papers" / "x" / "x_Insights.md"
        # Reproduce the exact dump_frontmatter output: ``key: value`` (single space).
        _write_md(target, ['confidence: "corpus-consensus"'])
        apply_frontmatter_field_migration(scan_confidence_field(library_dir))
        text = target.read_text(encoding="utf-8")
        assert 'synthesis_scope: "corpus-consensus"' in text

"""Unit tests for distill.library.migration module.

Feature: living-wiki-0-7
Tests: dry-run, apply, conflict detection, summary report accuracy.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from distill.library import migration as migration_mod
from distill.library.migration import (
    FrontmatterFieldAction,
    MigrationAction,
    _compute_modern_name,
    _find_library_root,
    apply_frontmatter_field_migration,
    apply_migration,
    scan_confidence_field,
    scan_legacy_artifacts,
)


def _raise_oserror(*args: object, **kwargs: object) -> None:
    """Test helper: unconditionally raise OSError to simulate an IO failure."""
    raise OSError("simulated IO failure")


def _legacy_insights_with_reference(
    library_dir: Path,
) -> tuple[Path, Path, list[MigrationAction]]:
    """Create a legacy ``insights.md`` plus a file that wiki-links its stem.

    Returns ``(artifact_dir, referencing_file, scanned_actions)`` for tests that
    exercise the rename-then-link-update path.
    """
    artifact_dir = library_dir / "topics" / "my-topic"
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "insights.md").write_text("# Insights\n", encoding="utf-8")
    ref = library_dir / "topics" / "ref.md"
    ref.write_text("See [[insights|X]].\n", encoding="utf-8")
    return artifact_dir, ref, scan_legacy_artifacts(library_dir)


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

    def test_skips_legacy_files_in_hidden_dirs(self, library_dir: Path) -> None:
        """Legacy-named files inside hidden dirs are immutable history, never migrated."""
        for hidden in (".history", ".distill", ".concepts"):
            snap_dir = library_dir / "topics" / "tkg" / hidden / "gpt5_abc123"
            snap_dir.mkdir(parents=True)
            (snap_dir / "insights.md").write_text("# Snapshot\n", encoding="utf-8")
        # A visible sibling is the positive control: it proves the scan discriminates
        # (finds live artifacts) rather than trivially skipping everything.
        visible = library_dir / "topics" / "tkg" / "live" / "insights.md"
        visible.parent.mkdir(parents=True)
        visible.write_text("# Live\n", encoding="utf-8")

        actions = scan_legacy_artifacts(library_dir)
        assert [action.source_path for action in actions] == [visible]


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

    def test_link_update_skips_hidden_ancestors(self, library_dir: Path) -> None:
        """Link repair uses the same hidden-ancestor exclusion as discovery."""
        artifact_dir, visible_ref, actions = _legacy_insights_with_reference(library_dir)
        hidden_ref = library_dir / "topics" / ".history" / "snapshot.md"
        hidden_ref.parent.mkdir(parents=True)
        hidden_ref.write_text("See [[insights|Snapshot]].\n", encoding="utf-8")

        result = apply_migration(actions, library_dir=library_dir)

        assert result.files_renamed == 1
        assert result.links_updated == 1
        assert result.errors == []
        assert "[[my-topic_Insights|X]]" in visible_ref.read_text(encoding="utf-8")
        assert hidden_ref.read_text(encoding="utf-8") == "See [[insights|Snapshot]].\n"
        assert (artifact_dir / "my-topic_Insights.md").exists()

    def test_link_update_accepts_exact_byte_ceiling(
        self, library_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A valid regular Markdown file exactly at the input ceiling is repaired."""
        _artifact_dir, ref, actions = _legacy_insights_with_reference(library_dir)
        prefix = "See [[insights|X]].\n"
        limit = len(prefix.encode("utf-8")) + 17
        ref.write_bytes((prefix + ("x" * 17)).encode("utf-8"))
        monkeypatch.setattr(migration_mod, "_MAX_WIKI_LINK_MARKDOWN_BYTES", limit)

        result = apply_migration(actions, library_dir=library_dir)

        assert result.links_updated == 1
        assert result.errors == []
        assert "[[my-topic_Insights|X]]" in ref.read_text(encoding="utf-8")

    def test_link_update_reports_oversized_and_invalid_utf8_files(
        self, library_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Bounded reads distinguish oversized input from an undecodable file."""
        _artifact_dir, ref, actions = _legacy_insights_with_reference(library_dir)
        oversized = library_dir / "topics" / "oversized.md"
        oversized.write_text("[[insights]] too large", encoding="utf-8")
        corrupt = library_dir / "topics" / "corrupt.md"
        corrupt.write_bytes(b"[[insights]]\xff")
        monkeypatch.setattr(migration_mod, "_MAX_WIKI_LINK_MARKDOWN_BYTES", 16)

        result = apply_migration(actions, library_dir=library_dir)

        assert result.files_renamed == 1
        assert result.links_updated == 0
        assert any(str(ref) in error and "exceeds" in error for error in result.errors)
        assert any(str(oversized) in error and "exceeds" in error for error in result.errors)
        assert any(str(corrupt) in error and "invalid UTF-8" in error for error in result.errors)

    def test_link_update_rejects_symlink_and_hardlink_candidates(self, library_dir: Path) -> None:
        """No-follow repair refuses link-like candidates without touching their targets."""
        _artifact_dir, _ref, actions = _legacy_insights_with_reference(library_dir)
        outside = library_dir.parent / "outside.md"
        outside.write_text("See [[insights|Outside]].\n", encoding="utf-8")
        symlink = library_dir / "topics" / "linked.md"
        try:
            symlink.symlink_to(outside)
        except OSError as exc:
            pytest.skip(f"symlinks unavailable: {exc}")
        hardlink = library_dir / "topics" / "hardlinked.md"
        try:
            hardlink.hardlink_to(outside)
        except OSError as exc:
            pytest.skip(f"hardlinks unavailable: {exc}")

        result = apply_migration(actions, library_dir=library_dir)

        assert result.files_renamed == 1
        assert (
            sum("not a confined single-link regular file" in error for error in result.errors) == 2
        )
        assert outside.read_text(encoding="utf-8") == "See [[insights|Outside]].\n"

    def test_out_of_root_action_is_rejected(self, library_dir: Path) -> None:
        """Manually supplied actions cannot rename files across the library boundary."""
        outside = library_dir.parent / "insights.md"
        outside.write_text("outside\n", encoding="utf-8")
        action = MigrationAction(
            source_path=outside,
            target_path=library_dir / "topics" / "outside_Insights.md",
            action_type="rename",
            details="outside",
        )

        result = apply_migration([action], library_dir=library_dir)

        assert result.files_renamed == 0
        assert outside.exists()
        assert any("outside the migration root" in error for error in result.errors)

    def test_duplicate_legacy_stems_update_only_colocated_links(
        self,
        library_dir: Path,
    ) -> None:
        topics = library_dir / "topics"
        first = topics / "first"
        second = topics / "second"
        first.mkdir(parents=True)
        second.mkdir(parents=True)
        (first / "insights.md").write_text("# First\n", encoding="utf-8")
        (second / "insights.md").write_text("# Second\n", encoding="utf-8")
        first_ref = first / "notes.md"
        second_ref = second / "notes.md"
        global_ref = topics / "index.md"
        first_ref.write_text("See [[insights|First]].\n", encoding="utf-8")
        second_ref.write_text("See [[insights|Second]].\n", encoding="utf-8")
        global_ref.write_text("See [[insights|Unknown]].\n", encoding="utf-8")

        result = apply_migration(scan_legacy_artifacts(library_dir), library_dir=library_dir)

        assert result.files_renamed == 2
        assert result.links_updated == 2
        assert "[[first_Insights|First]]" in first_ref.read_text(encoding="utf-8")
        assert "[[second_Insights|Second]]" in second_ref.read_text(encoding="utf-8")
        assert global_ref.read_text(encoding="utf-8") == "See [[insights|Unknown]].\n"
        assert len(result.errors) == 1
        assert "Ambiguous wiki-link stem 'insights'" in result.errors[0]
        assert "left unchanged" in result.errors[0]

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

    def test_skips_non_rename_actions(self, tmp_path: Path) -> None:
        """apply_migration only executes rename actions; other action types are ignored."""
        action = MigrationAction(
            source_path=tmp_path / "a.md",
            target_path=tmp_path / "b.md",
            action_type="link_update",
            details="not a rename",
        )
        result = apply_migration([action], library_dir=tmp_path)
        assert result.files_renamed == 0
        assert result.conflicts_skipped == 0
        assert result.errors == []

    def test_rename_failure_is_recorded_as_error(
        self, library_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An OSError during rename degrades to a recorded error, not a crash."""
        _artifact_dir, _ref, actions = _legacy_insights_with_reference(library_dir)

        monkeypatch.setattr(Path, "rename", _raise_oserror)
        result = apply_migration(actions, library_dir=library_dir)

        assert result.files_renamed == 0
        assert len(result.errors) == 1
        assert "rename failed" in result.errors[0].lower()

    def test_apply_without_library_dir_updates_links_via_common_ancestor(
        self, library_dir: Path
    ) -> None:
        """Without an explicit library_dir, links update under the actions' common ancestor."""
        topics = library_dir / "topics"
        (topics / "a").mkdir(parents=True)
        (topics / "a" / "insights.md").write_text("# A\n", encoding="utf-8")
        (topics / "b").mkdir(parents=True)
        (topics / "b" / "synthesis.md").write_text("# B\n", encoding="utf-8")
        ref = topics / "ref.md"
        ref.write_text("See [[insights|A]] and [[synthesis|B]].\n", encoding="utf-8")

        actions = scan_legacy_artifacts(library_dir)
        result = apply_migration(actions)  # no library_dir; common ancestor is topics/

        assert result.files_renamed == 2
        assert result.links_updated == 2
        updated = ref.read_text(encoding="utf-8")
        assert "[[insights" not in updated
        assert "[[synthesis" not in updated
        assert "[[a_Insights" in updated
        assert "[[b_Synthesis" in updated

    def test_link_update_read_failure_degrades_cleanly(
        self, library_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An unreadable file during link update is skipped; the rename still succeeds."""
        artifact_dir, _ref, actions = _legacy_insights_with_reference(library_dir)

        monkeypatch.setattr(migration_mod, "read_confined_text", lambda *_args, **_kwargs: None)
        result = apply_migration(actions, library_dir=library_dir)

        assert result.files_renamed == 1
        assert result.links_updated == 0
        assert any("unreadable, unstable, or invalid UTF-8" in error for error in result.errors)
        # The rename genuinely happened on disk even though link update could not read.
        assert not (artifact_dir / "insights.md").exists()
        assert (artifact_dir / "my-topic_Insights.md").exists()

    def test_link_update_write_failure_degrades_cleanly(
        self, library_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A write failure is returned exactly while the successful rename remains."""
        _artifact_dir, ref, actions = _legacy_insights_with_reference(library_dir)

        monkeypatch.setattr("distill.library.migration.atomic_write_text", _raise_oserror)
        result = apply_migration(actions, library_dir=library_dir)

        assert result.files_renamed == 1
        assert result.links_updated == 0
        assert len(result.errors) == 1
        assert str(ref) in result.errors[0]
        assert "simulated IO failure" in result.errors[0]
        # The referencing file is left untouched on disk.
        assert "[[insights|X]]" in ref.read_text(encoding="utf-8")

    def test_retry_after_link_write_failure_converges(
        self, library_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A retry reuses a completed rename and repairs the remaining stale link."""
        artifact_dir, ref, actions = _legacy_insights_with_reference(library_dir)
        real_writer = migration_mod.atomic_write_text
        monkeypatch.setattr(migration_mod, "atomic_write_text", _raise_oserror)

        first = apply_migration(actions, library_dir=library_dir)
        monkeypatch.setattr(migration_mod, "atomic_write_text", real_writer)
        second = apply_migration(actions, library_dir=library_dir)

        assert first.files_renamed == 1
        assert first.errors
        assert second.files_renamed == 0
        assert second.links_updated == 1
        assert second.errors == []
        assert (artifact_dir / "my-topic_Insights.md").exists()
        assert "[[my-topic_Insights|X]]" in ref.read_text(encoding="utf-8")


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


class TestFindLibraryRoot:
    """Tests for the _find_library_root common-ancestor fallback."""

    def test_empty_actions_returns_none(self) -> None:
        """No actions means there is no root to infer."""
        assert _find_library_root([]) is None

    def test_returns_shared_parent(self, tmp_path: Path) -> None:
        """Actions in the same directory resolve to that directory."""
        d = tmp_path / "topics" / "a"
        actions = [
            MigrationAction(d / "insights.md", d / "a_Insights.md", "rename", "x"),
            MigrationAction(d / "transcript.txt", d / "a_Transcript.txt", "rename", "y"),
        ]
        assert _find_library_root(actions) == d

    def test_walks_up_to_common_ancestor(self, tmp_path: Path) -> None:
        """Actions in sibling directories resolve to their nearest shared ancestor."""
        topics = tmp_path / "topics"
        a = topics / "a"
        b = topics / "b"
        actions = [
            MigrationAction(a / "insights.md", a / "a_Insights.md", "rename", "x"),
            MigrationAction(b / "synthesis.md", b / "b_Synthesis.md", "rename", "y"),
        ]
        assert _find_library_root(actions) == topics


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

    def test_skips_unterminated_frontmatter(self, library_dir: Path) -> None:
        """A frontmatter block with no closing marker is treated as absent, not a crash."""
        broken = library_dir / "topics" / "tkg" / "notes.md"
        broken.parent.mkdir(parents=True)
        broken.write_text('---\nconfidence: "x"\nnever closed\n', encoding="utf-8")
        # Positive control: a properly-closed sibling proves only the unterminated
        # block is skipped, not that the scan silently finds nothing.
        valid = library_dir / "topics" / "tkg" / "ok.md"
        valid.write_text('---\nconfidence: "y"\n---\nbody\n', encoding="utf-8")

        actions = scan_confidence_field(library_dir)
        assert [action.path for action in actions] == [valid]

    def test_skips_undecodable_file(self, library_dir: Path) -> None:
        """A file whose bytes are not valid UTF-8 is skipped rather than crashing the scan."""
        corrupt = library_dir / "topics" / "tkg" / "corrupt.md"
        corrupt.parent.mkdir(parents=True)
        corrupt.write_bytes(b"\xff\xfe\x00\x01 not utf-8")
        # Positive control: a valid sibling proves only the undecodable file is skipped.
        valid = library_dir / "topics" / "tkg" / "ok.md"
        valid.write_text('---\nconfidence: "y"\n---\nbody\n', encoding="utf-8")

        actions = scan_confidence_field(library_dir)
        assert [action.path for action in actions] == [valid]


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

    def test_missing_file_records_error(self, tmp_path: Path) -> None:
        """A file deleted between scan and apply becomes a recorded error, not a crash."""
        action = FrontmatterFieldAction(
            path=tmp_path / "gone.md",
            old_field="confidence",
            new_field="synthesis_scope",
            value='"single-paper"',
        )
        result = apply_frontmatter_field_migration([action])
        assert result.files_rewritten == 0
        assert len(result.errors) == 1
        assert "read failed" in result.errors[0].lower()

    def test_skips_file_without_frontmatter(self, tmp_path: Path) -> None:
        """If the file lost its frontmatter since scan, it is skipped."""
        plain = tmp_path / "plain.md"
        plain.write_text("# No frontmatter here\n", encoding="utf-8")
        action = FrontmatterFieldAction(
            path=plain,
            old_field="confidence",
            new_field="synthesis_scope",
            value='"x"',
        )
        result = apply_frontmatter_field_migration([action])
        assert result.files_skipped == 1
        assert result.files_rewritten == 0

    def test_skips_when_confidence_absent(self, tmp_path: Path) -> None:
        """If the confidence line vanished since scan, the rewrite is a no-op skip."""
        target = tmp_path / "already.md"
        target.write_text('---\ntitle: "x"\n---\nbody\n', encoding="utf-8")
        action = FrontmatterFieldAction(
            path=target,
            old_field="confidence",
            new_field="synthesis_scope",
            value='"x"',
        )
        result = apply_frontmatter_field_migration([action])
        assert result.files_skipped == 1
        assert result.files_rewritten == 0

    def test_write_failure_records_error(
        self, library_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An OSError while writing the rewritten file is recorded, not raised."""
        target = library_dir / "topics" / "tkg" / "papers" / "x" / "x_Insights.md"
        _write_md(target, ['confidence: "single-paper"'])
        actions = scan_confidence_field(library_dir)

        monkeypatch.setattr("distill.library.migration.atomic_write_text", _raise_oserror)
        result = apply_frontmatter_field_migration(actions)

        assert result.files_rewritten == 0
        assert len(result.errors) == 1
        assert "write failed" in result.errors[0].lower()

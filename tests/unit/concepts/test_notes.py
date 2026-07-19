"""Unit tests for distill.concepts.notes: rendering, .history versioning, mentions.jsonl."""

from __future__ import annotations

import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from dataclasses import replace
from pathlib import Path

import pytest

import distill.concepts.notes as notes_mod
import distill.library.links as links_mod
from distill.concepts.notes import (
    _extracted_sources_path,
    already_extracted_source_ids,
    append_mentions,
    build_playbook_ownership_index,
    concept_dir_for_topic,
    entity_dir_for_topic,
    history_path_for,
    mentions_jsonl_path,
    note_path_for,
    read_extracted_sources,
    read_mentions,
    record_extracted_sources,
    render_playbook,
    write_playbook,
)
from distill.concepts.records import (
    ConceptKind,
    ConceptMention,
    EvidenceInterval,
    MergedConcept,
    Polarity,
    SourceEvidence,
)
from distill.concepts.recovery import diff_notes, list_snapshots, note_path_for_slug
from distill.jsonl import JsonlIntegrityError
from distill.library.confined_state import ConfinedStateError, FileIdentity
from distill.library.links import check_links, fix_broken_links
from distill.library.source_ledger import SourceLedgerIntegrityError


def _concept(
    *,
    name: str = "Rotational Embeddings",
    normalized: str = "rotational embeddings",
    kind: ConceptKind = ConceptKind.TECHNIQUE,
    helpful: tuple[int, int] = (3, 5),
    harmful: tuple[int, int] = (0, 0),
    extra_sources: list[SourceEvidence] | None = None,
) -> MergedConcept:
    base_sources = [
        SourceEvidence(
            source_id="A",
            artifact_path="papers/romem/romem_Insights.md",
            polarity=Polarity.HELPFUL,
            claim_excerpt="Rotation outperforms discrete timestamps.",
            evidence_type="empirical_result",
            seen_at="2026-05-15T10:00:00Z",
        ),
        SourceEvidence(
            source_id="B",
            artifact_path="papers/est/est_Insights.md",
            polarity=Polarity.HELPFUL,
        ),
        SourceEvidence(
            source_id="C",
            artifact_path="papers/cid/cid_Insights.md",
            polarity=Polarity.NEUTRAL,
        ),
    ]
    sources = base_sources + (extra_sources or [])
    return MergedConcept(
        name=name,
        normalized_name=normalized,
        kind=kind,
        topic="tkg",
        sources=tuple(sources),
        helpful_evidence=EvidenceInterval(*helpful),
        harmful_evidence=EvidenceInterval(*harmful),
        first_seen="2026-04-12T10:00:00Z",
        last_seen="2026-05-15T14:30:00Z",
        provenance={"model": "grok-4.3", "prompt_id": "concepts.extract.v1"},
    )


def _mention_row(
    source_id: str,
    *,
    normalized_name: str = "x",
    polarity: Polarity = Polarity.HELPFUL,
) -> dict[str, object]:
    return ConceptMention(
        name=normalized_name.upper(),
        normalized_name=normalized_name,
        kind=ConceptKind.TECHNIQUE,
        polarity=polarity,
        source_id=source_id,
        artifact_path=f"papers/{source_id}/{source_id}_Insights.md",
    ).to_jsonl_row()


class TestPathResolution:
    def test_concept_dir(self, tmp_path: Path) -> None:
        assert concept_dir_for_topic(tmp_path) == tmp_path / "concepts"

    def test_entity_dir(self, tmp_path: Path) -> None:
        assert entity_dir_for_topic(tmp_path) == tmp_path / "entities"

    def test_concept_routes_to_concepts_dir(self, tmp_path: Path) -> None:
        c = _concept(kind=ConceptKind.TECHNIQUE)
        assert note_path_for(tmp_path, c) == tmp_path / "concepts" / "rotational_embeddings.md"

    def test_entity_routes_to_entities_dir(self, tmp_path: Path) -> None:
        c = _concept(normalized="deepmind", kind=ConceptKind.ORGANIZATION)
        assert note_path_for(tmp_path, c) == tmp_path / "entities" / "deepmind.md"

    def test_history_path_swaps_colons_for_filesystem_safety(self, tmp_path: Path) -> None:
        c = _concept()
        path = history_path_for(tmp_path, c, "2026-05-15T14:30:00Z")
        # ':' is invalid in Windows filenames; we swap to '-'
        assert ":" not in path.name
        assert path == tmp_path / ".history" / "rotational_embeddings" / "2026-05-15T14-30-00Z.md"

    @pytest.mark.parametrize(
        "storage_slug", ["", ".", "..", "../escape", "..\\escape", "C:escape", "bad\x00slug"]
    )
    def test_history_path_rejects_unsafe_storage_slug(
        self, tmp_path: Path, storage_slug: str
    ) -> None:
        with pytest.raises(ValueError, match="Unsafe history storage slug"):
            history_path_for(
                tmp_path,
                _concept(),
                "2026-05-15T14:30:00Z",
                storage_slug=storage_slug,
            )


class TestRenderPlaybook:
    def test_includes_frontmatter(self) -> None:
        output = render_playbook(_concept())
        assert output.startswith("---\n")
        assert 'type: "concept"' in output
        assert 'name: "Rotational Embeddings"' in output
        assert 'kind: "technique"' in output

    def test_evidence_intervals_as_yaml_lists(self) -> None:
        output = render_playbook(_concept(helpful=(2, 4), harmful=(1, 1)))
        assert "helpful_evidence: [2, 4]" in output
        assert "harmful_evidence: [1, 1]" in output

    def test_contested_flag_in_frontmatter(self) -> None:
        # Helpful + harmful both > 0
        out = render_playbook(_concept(helpful=(2, 2), harmful=(1, 1)))
        assert "contested: true" in out

    def test_helpful_section_has_wiki_links(self) -> None:
        output = render_playbook(_concept())
        assert "## Helpful evidence" in output
        assert "[[romem_Insights]]" in output
        assert "[[est_Insights]]" in output

    def test_harmful_section_omitted_when_no_harmful_sources(self) -> None:
        output = render_playbook(_concept(helpful=(3, 5), harmful=(0, 0)))
        assert "## Harmful or contradicting evidence" not in output

    def test_harmful_section_present_when_harmful_source_exists(self) -> None:
        harmful_source = SourceEvidence(
            source_id="X",
            artifact_path="papers/skeptic/skeptic_Insights.md",
            polarity=Polarity.HARMFUL,
            claim_excerpt="Fails at production scale.",
        )
        out = render_playbook(
            _concept(helpful=(2, 2), harmful=(1, 1), extra_sources=[harmful_source])
        )
        assert "## Harmful or contradicting evidence" in out
        assert "[[skeptic_Insights]]" in out
        assert "Fails at production scale." in out

    def test_cross_source_section_lists_counts(self) -> None:
        out = render_playbook(_concept(helpful=(3, 5)))
        assert "## Cross-source patterns" in out
        # 3 unambiguous, 5 generous of 3 sources -> mentions both bounds
        assert "3-5 of 3" in out

    def test_cross_source_section_marks_contested(self) -> None:
        harmful_source = SourceEvidence(
            source_id="X",
            artifact_path="papers/x/x_Insights.md",
            polarity=Polarity.HARMFUL,
        )
        out = render_playbook(
            _concept(helpful=(2, 2), harmful=(1, 1), extra_sources=[harmful_source])
        )
        assert "**[contested]**" in out

    def test_sources_section_lists_all_with_polarity(self) -> None:
        out = render_playbook(_concept())
        assert "## Sources" in out
        assert "`helpful`" in out
        assert "`neutral`" in out
        # All three source_ids should appear
        for sid in ("A", "B", "C"):
            assert f"source_id: `{sid}`" in out

    def test_deterministic_same_input_same_output(self) -> None:
        a = render_playbook(_concept())
        b = render_playbook(_concept())
        assert a == b

    def test_entity_kind_emits_type_entity(self) -> None:
        out = render_playbook(_concept(normalized="deepmind", kind=ConceptKind.ORGANIZATION))
        assert 'type: "entity"' in out

    def test_provenance_in_frontmatter(self) -> None:
        out = render_playbook(_concept())
        assert 'model: "grok-4.3"' in out
        assert 'prompt_id: "concepts.extract.v1"' in out


class TestWritePlaybook:
    def test_creates_file_on_first_write(self, tmp_path: Path) -> None:
        c = _concept()
        path, changed = write_playbook(tmp_path, c, now_iso="2026-05-15T14:30:00Z")
        assert changed is True
        assert path.exists()
        assert 'type: "concept"' in path.read_text(encoding="utf-8")

    def test_accepts_render_exactly_at_reader_byte_limit(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        concept = _concept()
        rendered = render_playbook(concept)
        monkeypatch.setattr(
            notes_mod,
            "_MAX_PLAYBOOK_NOTE_BYTES",
            len(rendered.encode("utf-8")),
        )

        path, changed = write_playbook(
            tmp_path,
            concept,
            now_iso="2026-05-15T14:30:00Z",
        )

        assert changed is True
        assert path.read_text(encoding="utf-8") == rendered

    def test_oversized_render_is_refused_before_live_or_history_mutation(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        note, _ = write_playbook(
            tmp_path,
            _concept(),
            now_iso="2026-05-15T14:30:00Z",
        )
        before = note.read_bytes()
        updated = _concept(
            extra_sources=[
                SourceEvidence(
                    source_id="D",
                    artifact_path="papers/new/new_Insights.md",
                    polarity=Polarity.HELPFUL,
                    claim_excerpt="New evidence must not partially publish.",
                )
            ]
        )
        rendered = render_playbook(updated)
        monkeypatch.setattr(
            notes_mod,
            "_MAX_PLAYBOOK_NOTE_BYTES",
            len(rendered.encode("utf-8")) - 1,
        )

        with pytest.raises(ConfinedStateError, match="Rendered playbook note exceeds"):
            write_playbook(
                tmp_path,
                updated,
                now_iso="2026-05-15T15:00:00Z",
            )

        assert note.read_bytes() == before
        assert not (tmp_path / ".history").exists()

    def test_idempotent_on_unchanged_content(self, tmp_path: Path) -> None:
        c = _concept()
        write_playbook(tmp_path, c, now_iso="2026-05-15T14:30:00Z")
        _, changed = write_playbook(tmp_path, c, now_iso="2026-05-15T15:00:00Z")
        assert changed is False
        # No history entry should have been created on the second call
        history_dir = tmp_path / ".history" / "rotational_embeddings"
        assert not history_dir.exists()

    def test_ownership_index_covers_both_note_families(self, tmp_path: Path) -> None:
        concept_path, _ = write_playbook(
            tmp_path,
            _concept(),
            now_iso="2026-05-15T10:00:00Z",
        )
        entity = _concept(
            name="DeepMind",
            normalized="deepmind",
            kind=ConceptKind.ORGANIZATION,
        )
        entity_path, _ = write_playbook(
            tmp_path,
            entity,
            now_iso="2026-05-15T10:00:01Z",
        )

        ownership = build_playbook_ownership_index(tmp_path)

        assert ownership == {
            "deepmind": [entity_path],
            "rotational embeddings": [concept_path],
        }

    def test_precomputed_ownership_uses_one_fresh_scan_after_target_race(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        real_update = notes_mod._update_playbook_target
        real_owned = notes_mod._owned_note_paths
        update_calls = 0
        ownership_scans = 0

        def collide_once(*args, **kwargs):
            nonlocal update_calls
            update_calls += 1
            if update_calls == 1:
                return None
            return real_update(*args, **kwargs)

        def count_scan(*args, **kwargs):
            nonlocal ownership_scans
            ownership_scans += 1
            return real_owned(*args, **kwargs)

        monkeypatch.setattr(notes_mod, "_update_playbook_target", collide_once)
        monkeypatch.setattr(notes_mod, "_owned_note_paths", count_scan)

        path, changed = write_playbook(
            tmp_path,
            _concept(),
            now_iso="2026-05-15T10:00:00Z",
            owned_paths=[],
        )

        assert changed is True
        assert path.is_file()
        assert update_calls == 2
        assert ownership_scans == 1

    def test_collision_suffix_bumps_distinct_concepts(self, tmp_path: Path) -> None:
        """Two distinct normalized_names that produce the same slug must not overwrite each other.

        Regression: MergedConcept.slug is lossy ("a b" and "a/b" both
        collapse to "a_b"). The writer previously assumed any existing
        file at <slug>.md was the same concept and overwrote it. The
        fix reads the existing note's normalized_name from frontmatter
        and suffix-bumps when the slugs collide but identities differ.
        """
        c1 = MergedConcept(
            name="A B",
            normalized_name="a b",
            kind=ConceptKind.TECHNIQUE,
            topic="t",
            sources=(
                SourceEvidence(source_id="S1", artifact_path="p.md", polarity=Polarity.HELPFUL),
            ),
            helpful_evidence=EvidenceInterval(1, 1),
            harmful_evidence=EvidenceInterval(0, 0),
            first_seen="x",
            last_seen="x",
        )
        c2 = MergedConcept(
            name="A/B",
            normalized_name="a/b",
            kind=ConceptKind.TECHNIQUE,
            topic="t",
            sources=(
                SourceEvidence(source_id="S2", artifact_path="q.md", polarity=Polarity.HELPFUL),
            ),
            helpful_evidence=EvidenceInterval(1, 1),
            harmful_evidence=EvidenceInterval(0, 0),
            first_seen="x",
            last_seen="x",
        )
        # Both have slug "a_b" but distinct normalized_names
        assert c1.slug == c2.slug == "a_b"

        path1, _ = write_playbook(tmp_path, c1, now_iso="2026-05-15T10:00:00Z")
        path2, _ = write_playbook(tmp_path, c2, now_iso="2026-05-15T10:00:01Z")

        # Distinct files: the second concept must not overwrite the first
        assert path1 != path2
        assert path1.exists()
        assert path2.exists()
        # The first concept's content is intact
        assert "a b" in path1.read_text(encoding="utf-8")
        # The second concept got a deterministic bounded hash fallback.
        assert path2.name.startswith("a_b__")

    def test_idempotent_same_concept_with_lossy_slug(self, tmp_path: Path) -> None:
        """Re-writing the same concept (same normalized_name) doesn't suffix-bump."""
        c = MergedConcept(
            name="A B",
            normalized_name="a b",
            kind=ConceptKind.TECHNIQUE,
            topic="t",
            sources=(
                SourceEvidence(source_id="S1", artifact_path="p.md", polarity=Polarity.HELPFUL),
            ),
            helpful_evidence=EvidenceInterval(1, 1),
            harmful_evidence=EvidenceInterval(0, 0),
            first_seen="x",
            last_seen="x",
        )
        path1, _ = write_playbook(tmp_path, c, now_iso="2026-05-15T10:00:00Z")
        path2, _ = write_playbook(tmp_path, c, now_iso="2026-05-15T11:00:00Z")
        assert path1 == path2  # same logical concept -> same file

    def test_collision_histories_follow_resolved_note_identity(self, tmp_path: Path) -> None:
        first = _concept(name="A B", normalized="a b", helpful=(1, 1))
        second = _concept(name="A/B", normalized="a/b", helpful=(1, 1))

        first_path, _ = write_playbook(tmp_path, first, now_iso="2026-05-15T10:00:00Z")
        second_path, _ = write_playbook(tmp_path, second, now_iso="2026-05-15T10:00:01Z")
        write_playbook(
            tmp_path,
            _concept(name="A B", normalized="a b", helpful=(2, 2)),
            now_iso="2026-05-15T11:00:00Z",
        )
        write_playbook(
            tmp_path,
            _concept(name="A/B", normalized="a/b", helpful=(3, 3)),
            now_iso="2026-05-15T11:00:01Z",
        )

        first_history = list((tmp_path / ".history" / first_path.stem).glob("*.md"))
        second_history = list((tmp_path / ".history" / second_path.stem).glob("*.md"))
        assert first_path.stem == "a_b"
        assert second_path.stem.startswith("a_b__")
        assert len(first_history) == len(second_history) == 1
        assert 'normalized_name: "a b"' in first_history[0].read_text(encoding="utf-8")
        assert 'normalized_name: "a/b"' in second_history[0].read_text(encoding="utf-8")
        assert note_path_for_slug(tmp_path, second_path.stem) == second_path

        second_snapshots = list_snapshots(tmp_path, second_path.stem)
        second_diff = diff_notes(
            second_snapshots[0].path.read_text(encoding="utf-8"),
            second_path.read_text(encoding="utf-8"),
        )
        assert {change.field for change in second_diff.field_changes} == {
            "helpful_count",
            "helpful_evidence",
        }

    def test_overwrites_and_snapshots_prior(self, tmp_path: Path) -> None:
        first = _concept(helpful=(2, 4))
        write_playbook(tmp_path, first, now_iso="2026-05-15T14:30:00Z")
        prior_content = (tmp_path / "concepts" / "rotational_embeddings.md").read_text(
            encoding="utf-8"
        )

        # Add a new helpful source -> different content
        second = _concept(
            helpful=(3, 5),
            extra_sources=[
                SourceEvidence(
                    source_id="D",
                    artifact_path="papers/new/new_Insights.md",
                    polarity=Polarity.HELPFUL,
                )
            ],
        )
        path, changed = write_playbook(tmp_path, second, now_iso="2026-05-16T10:00:00Z")
        assert changed is True

        history_files = list((tmp_path / ".history" / "rotational_embeddings").glob("*.md"))
        assert len(history_files) == 1
        assert history_files[0].read_text(encoding="utf-8") == prior_content

        # New file should reflect the new content
        new_content = path.read_text(encoding="utf-8")
        assert new_content != prior_content
        assert "[[new_Insights]]" in new_content

    def test_same_timestamp_updates_preserve_every_prior_version(self, tmp_path: Path) -> None:
        timestamp = "2026-05-16T10:00:00Z"
        first = _concept(helpful=(1, 1))
        second = _concept(helpful=(2, 2))
        third = _concept(helpful=(3, 3))

        write_playbook(tmp_path, first, now_iso=timestamp)
        write_playbook(tmp_path, second, now_iso=timestamp)
        live, _ = write_playbook(tmp_path, third, now_iso=timestamp)

        snapshots = list_snapshots(tmp_path, live.stem)
        assert [snapshot.safe_ts for snapshot in snapshots] == [
            "2026-05-16T10-00-00Z",
            "2026-05-16T10-00-00Z__2",
        ]
        assert "helpful_evidence: [1, 1]" in snapshots[0].path.read_text(encoding="utf-8")
        assert "helpful_evidence: [2, 2]" in snapshots[1].path.read_text(encoding="utf-8")
        assert "helpful_evidence: [3, 3]" in live.read_text(encoding="utf-8")

    def test_kind_change_moves_one_identity_between_note_families(self, tmp_path: Path) -> None:
        technique = _concept(
            name="DeepMind",
            normalized="deepmind",
            kind=ConceptKind.TECHNIQUE,
            helpful=(1, 1),
        )
        organization = _concept(
            name="DeepMind",
            normalized="deepmind",
            kind=ConceptKind.ORGANIZATION,
            helpful=(2, 2),
        )
        old_path, _ = write_playbook(
            tmp_path,
            technique,
            now_iso="2026-05-15T10:00:00Z",
        )
        new_path, changed = write_playbook(
            tmp_path,
            organization,
            now_iso="2026-05-15T11:00:00Z",
        )

        assert changed is True
        assert old_path == tmp_path / "concepts" / "deepmind.md"
        assert new_path == tmp_path / "entities" / "deepmind.md"
        assert not old_path.exists()
        assert new_path.is_file()
        assert 'kind: "organization"' in new_path.read_text(encoding="utf-8")
        snapshots = list_snapshots(tmp_path, "deepmind")
        assert len(snapshots) == 1
        assert 'kind: "technique"' in snapshots[0].path.read_text(encoding="utf-8")

    def test_failed_kind_migration_removes_only_new_snapshots(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        technique = _concept(
            name="DeepMind",
            normalized="deepmind",
            kind=ConceptKind.TECHNIQUE,
            helpful=(1, 1),
        )
        organization = _concept(
            name="DeepMind",
            normalized="deepmind",
            kind=ConceptKind.ORGANIZATION,
            helpful=(2, 2),
        )
        old_path, _ = write_playbook(
            tmp_path,
            technique,
            now_iso="2026-05-15T10:00:00Z",
        )
        before = old_path.read_bytes()
        real_write = notes_mod.atomic_write_confined_text

        def fail_target(
            path: Path,
            content: str,
            root: Path,
            *,
            exclusive: bool = False,
            expected: FileIdentity | None = None,
        ) -> None:
            if path.parent.name == "entities":
                raise OSError("entity publication failed")
            real_write(
                path,
                content,
                root,
                exclusive=exclusive,
                expected=expected,
            )

        monkeypatch.setattr(notes_mod, "atomic_write_confined_text", fail_target)

        with pytest.raises(OSError, match="entity publication failed"):
            write_playbook(
                tmp_path,
                organization,
                now_iso="2026-05-15T11:00:00Z",
            )

        assert old_path.read_bytes() == before
        assert not (tmp_path / "entities" / "deepmind.md").exists()
        assert list_snapshots(tmp_path, "deepmind") == []

    @pytest.mark.parametrize("link_kind", ["symlink", "hardlink"])
    def test_linked_note_cannot_steer_ownership_or_leak_into_history(
        self, tmp_path: Path, link_kind: str
    ) -> None:
        concept = _concept(normalized="deepmind", name="DeepMind", helpful=(1, 1))
        external = tmp_path / "external.md"
        external.write_text(render_playbook(concept) + "SECRET OUTSIDE NOTE\n", encoding="utf-8")
        occupied = tmp_path / "concepts" / "deepmind.md"
        occupied.parent.mkdir(parents=True)
        try:
            if link_kind == "symlink":
                occupied.symlink_to(external)
            else:
                os.link(external, occupied)
        except OSError as exc:
            pytest.skip(f"{link_kind} unavailable: {exc}")

        with pytest.raises(ConfinedStateError, match="unsafe"):
            write_playbook(
                tmp_path,
                concept,
                now_iso="2026-05-15T11:00:00Z",
            )

        assert external.read_text(encoding="utf-8").endswith("SECRET OUTSIDE NOTE\n")
        assert not (tmp_path / ".history").exists()

    def test_linked_concepts_directory_is_rejected_without_external_write(
        self,
        tmp_path: Path,
    ) -> None:
        external = tmp_path / "external-concepts"
        external.mkdir()
        sentinel = external / "sentinel.txt"
        sentinel.write_text("outside", encoding="utf-8")
        linked = tmp_path / "concepts"
        try:
            linked.symlink_to(external, target_is_directory=True)
        except OSError as exc:
            pytest.skip(f"directory symlinks unavailable: {exc}")

        with pytest.raises(ConfinedStateError, match="private directory"):
            write_playbook(tmp_path, _concept(), now_iso="2026-05-15T11:00:00Z")

        assert sentinel.read_text(encoding="utf-8") == "outside"
        assert sorted(path.name for path in external.iterdir()) == ["sentinel.txt"]

    def test_linked_history_directory_is_rejected_before_live_note_changes(
        self,
        tmp_path: Path,
    ) -> None:
        note, _ = write_playbook(
            tmp_path,
            _concept(),
            now_iso="2026-05-15T10:00:00Z",
        )
        before = note.read_bytes()
        external = tmp_path / "external-history"
        external.mkdir()
        linked = tmp_path / ".history"
        try:
            linked.symlink_to(external, target_is_directory=True)
        except OSError as exc:
            pytest.skip(f"directory symlinks unavailable: {exc}")
        updated = _concept(
            extra_sources=[
                SourceEvidence(
                    source_id="D",
                    artifact_path="papers/new/new_Insights.md",
                    polarity=Polarity.HELPFUL,
                    claim_excerpt="New evidence.",
                )
            ]
        )

        with pytest.raises(ConfinedStateError, match="private directory"):
            write_playbook(tmp_path, updated, now_iso="2026-05-15T11:00:00Z")

        assert note.read_bytes() == before
        assert list(external.iterdir()) == []

    def test_concepts_parent_swap_is_detected_before_external_write(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        concepts_dir = tmp_path / "concepts"
        concepts_dir.mkdir()
        preserved = tmp_path / "concepts-preserved"
        external = tmp_path / "external-concepts"
        external.mkdir()
        probe = tmp_path / "symlink-probe"
        try:
            probe.symlink_to(external, target_is_directory=True)
        except OSError as exc:
            pytest.skip(f"directory symlinks unavailable: {exc}")
        probe.unlink()
        real_write = notes_mod.atomic_write_confined_text

        def swapping_write(
            path: Path,
            content: str,
            root: Path,
            *,
            exclusive: bool = False,
            expected: FileIdentity | None = None,
        ) -> None:
            concepts_dir.rename(preserved)
            concepts_dir.symlink_to(external, target_is_directory=True)
            real_write(
                path,
                content,
                root,
                exclusive=exclusive,
                expected=expected,
            )

        monkeypatch.setattr(notes_mod, "atomic_write_confined_text", swapping_write)

        with pytest.raises((ConfinedStateError, PermissionError)):
            write_playbook(tmp_path, _concept(), now_iso="2026-05-15T11:00:00Z")

        assert list(external.iterdir()) == []
        assert not list(tmp_path.rglob("rotational_embeddings.md"))

    def test_history_parent_swap_is_detected_before_live_note_changes(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        note, _ = write_playbook(
            tmp_path,
            _concept(),
            now_iso="2026-05-15T10:00:00Z",
        )
        before = note.read_bytes()
        history_dir = tmp_path / ".history" / "rotational_embeddings"
        history_dir.mkdir(parents=True)
        preserved = tmp_path / ".history" / "rotational_embeddings-preserved"
        external = tmp_path / "external-history"
        external.mkdir()
        probe = tmp_path / "symlink-probe"
        try:
            probe.symlink_to(external, target_is_directory=True)
        except OSError as exc:
            pytest.skip(f"directory symlinks unavailable: {exc}")
        probe.unlink()
        updated = _concept(
            extra_sources=[
                SourceEvidence(
                    source_id="D",
                    artifact_path="papers/new/new_Insights.md",
                    polarity=Polarity.HELPFUL,
                    claim_excerpt="New evidence.",
                )
            ]
        )
        real_write = notes_mod.atomic_write_confined_text

        def swapping_write(
            path: Path,
            content: str,
            root: Path,
            *,
            exclusive: bool = False,
        ) -> None:
            if path.parent == history_dir:
                history_dir.rename(preserved)
                history_dir.symlink_to(external, target_is_directory=True)
            real_write(path, content, root, exclusive=exclusive)

        monkeypatch.setattr(notes_mod, "atomic_write_confined_text", swapping_write)

        with pytest.raises(ConfinedStateError, match="private directory"):
            write_playbook(tmp_path, updated, now_iso="2026-05-15T11:00:00Z")

        assert note.read_bytes() == before
        assert list(external.iterdir()) == []
        assert list(preserved.iterdir()) == []

    def test_link_repair_cannot_overwrite_a_concurrent_playbook_write(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        library_dir = tmp_path / "library"
        topic_dir = library_dir / "topics" / "tkg"
        topic_dir.mkdir(parents=True)
        initial = _concept()
        note_path, _ = write_playbook(
            topic_dir,
            initial,
            now_iso="2026-05-15T10:00:00Z",
        )
        repair_root, is_playbook = links_mod._link_repair_scope(library_dir, note_path)
        assert repair_root == topic_dir
        assert is_playbook is True
        assert notes_mod._note_lock_path(topic_dir, note_path, "note") == (
            links_mod.confined_state_lock_path(note_path, repair_root, "note")
        )
        broken = check_links(library_dir).broken_links
        assert broken

        updated = _concept(
            extra_sources=[
                SourceEvidence(
                    source_id="D",
                    artifact_path="papers/new/new_Insights.md",
                    polarity=Polarity.HELPFUL,
                    claim_excerpt="Newer evidence must survive link repair.",
                )
            ]
        )
        repair_read = threading.Event()
        release_repair = threading.Event()
        writer_finished = threading.Event()
        real_read_text = links_mod.read_confined_state_text
        intercepted = False
        intercept_lock = threading.Lock()

        def blocking_read_text(path: Path, root: Path, *, max_bytes: int) -> str | None:
            nonlocal intercepted
            content = real_read_text(path, root, max_bytes=max_bytes)
            if path == note_path:
                with intercept_lock:
                    should_block = not intercepted
                    intercepted = True
                if should_block:
                    repair_read.set()
                    assert release_repair.wait(timeout=5)
            return content

        def concurrent_writer() -> None:
            write_playbook(
                topic_dir,
                updated,
                now_iso="2026-05-15T11:00:00Z",
            )
            writer_finished.set()

        monkeypatch.setattr(links_mod, "read_confined_state_text", blocking_read_text)
        with ThreadPoolExecutor(max_workers=2) as executor:
            repair = executor.submit(fix_broken_links, library_dir, broken)
            assert repair_read.wait(timeout=5)
            writer = executor.submit(concurrent_writer)
            writer_finished_before_release = writer_finished.wait(timeout=0.25)
            release_repair.set()
            assert repair.result(timeout=5) > 0
            writer.result(timeout=5)

        assert writer_finished_before_release is False
        final_content = note_path.read_text(encoding="utf-8")
        assert "source_count: 4" in final_content
        assert "Newer evidence must survive link repair." in final_content

    def test_kind_migration_prevents_false_success_from_concurrent_link_repair(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        library_dir = tmp_path / "library"
        topic_dir = library_dir / "topics" / "tkg"
        topic_dir.mkdir(parents=True)
        old_path, _ = write_playbook(
            topic_dir,
            _concept(
                name="DeepMind",
                normalized="deepmind",
                kind=ConceptKind.TECHNIQUE,
            ),
            now_iso="2026-05-15T10:00:00Z",
        )
        broken = [
            item for item in check_links(library_dir).broken_links if item.source_file == old_path
        ]
        assert broken
        migration_waiting = threading.Event()
        release_migration = threading.Event()
        repair_finished = threading.Event()
        real_update = notes_mod._update_playbook_target

        def blocking_update(
            root: Path,
            concept: MergedConcept,
            target: Path,
            new_content: str,
            now_iso: str,
        ) -> bool | None:
            if target.parent.name == "entities":
                migration_waiting.set()
                assert release_migration.wait(timeout=5)
            return real_update(root, concept, target, new_content, now_iso)

        def repair() -> int:
            result = fix_broken_links(library_dir, broken)
            repair_finished.set()
            return result

        monkeypatch.setattr(notes_mod, "_update_playbook_target", blocking_update)
        with ThreadPoolExecutor(max_workers=2) as executor:
            migration = executor.submit(
                write_playbook,
                topic_dir,
                _concept(
                    name="DeepMind",
                    normalized="deepmind",
                    kind=ConceptKind.ORGANIZATION,
                ),
                now_iso="2026-05-15T11:00:00Z",
            )
            assert migration_waiting.wait(timeout=5)
            repair_future = executor.submit(repair)
            assert repair_finished.wait(timeout=0.25) is False
            release_migration.set()
            new_path, changed = migration.result(timeout=5)
            repaired = repair_future.result(timeout=5)

        assert changed is True
        assert new_path.parent.name == "entities"
        assert not old_path.exists()
        assert repaired == 0


class TestMentionsJsonl:
    def test_path_resolution(self, tmp_path: Path) -> None:
        assert mentions_jsonl_path(tmp_path) == tmp_path / ".concepts" / "mentions.jsonl"

    def test_append_creates_file_and_writes_rows(self, tmp_path: Path) -> None:
        rows = [
            _mention_row("A"),
            _mention_row("B", polarity=Polarity.HARMFUL),
        ]
        path = append_mentions(tmp_path, rows)
        assert path.exists()
        lines = path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 2
        assert json.loads(lines[0])["source_id"] == "A"

    def test_append_appends_does_not_overwrite(self, tmp_path: Path) -> None:
        append_mentions(tmp_path, [_mention_row("A")])
        append_mentions(tmp_path, [_mention_row("B")])
        rows = read_mentions(tmp_path)
        assert [r["source_id"] for r in rows] == ["A", "B"]

    def test_read_empty_when_missing(self, tmp_path: Path) -> None:
        assert read_mentions(tmp_path) == []

    def test_already_extracted_source_ids(self, tmp_path: Path) -> None:
        append_mentions(
            tmp_path,
            [
                _mention_row("A"),
                _mention_row("A", normalized_name="y"),
                _mention_row("B"),
            ],
        )
        assert already_extracted_source_ids(tmp_path) == {"A", "B"}

    def test_read_rejects_blank_lines(self, tmp_path: Path) -> None:
        path = mentions_jsonl_path(tmp_path)
        path.parent.mkdir(parents=True)
        first = json.dumps(_mention_row("A"))
        second = json.dumps(_mention_row("B"))
        path.write_text(f"{first}\n\n{second}\n", encoding="utf-8")

        with pytest.raises(JsonlIntegrityError, match="row 2 is empty"):
            read_mentions(tmp_path)

    @pytest.mark.parametrize("bad_row", ["not json", "[]", '"bare-string"'])
    def test_read_rejects_malformed_and_non_object_rows(self, tmp_path: Path, bad_row: str) -> None:
        path = mentions_jsonl_path(tmp_path)
        path.parent.mkdir(parents=True)
        path.write_text(f"{bad_row}\n", encoding="utf-8")

        with pytest.raises(JsonlIntegrityError) as caught:
            read_mentions(tmp_path)

        assert str(path) in str(caught.value)

    def test_append_rejects_invalid_schema_before_touching_store(self, tmp_path: Path) -> None:
        with pytest.raises(JsonlIntegrityError, match="ConceptMention schema"):
            append_mentions(tmp_path, [{"source_id": "A"}])

        assert not mentions_jsonl_path(tmp_path).exists()

    def test_append_rejects_oversized_source_id_but_reads_legacy_row(
        self,
        tmp_path: Path,
    ) -> None:
        from distill.library.source_ledger import MAX_SOURCE_ID_BYTES

        oversized = "x" * (MAX_SOURCE_ID_BYTES + 1)
        row = _mention_row(oversized)

        with pytest.raises(JsonlIntegrityError, match="source ID contract"):
            append_mentions(tmp_path, [row])
        assert not mentions_jsonl_path(tmp_path).exists()

        path = mentions_jsonl_path(tmp_path)
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(row) + "\n", encoding="utf-8")
        assert read_mentions(tmp_path) == [row]

    def test_append_refuses_row_capacity_overflow_without_touching_store(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(notes_mod, "_MAX_MENTIONS_HISTORY_ROWS", 2)
        append_mentions(tmp_path, [_mention_row("A"), _mention_row("B")])
        path = mentions_jsonl_path(tmp_path)
        before = path.read_bytes()

        with pytest.raises(JsonlIntegrityError, match="append would exceed the 2-row limit"):
            append_mentions(tmp_path, [_mention_row("C")])

        assert path.read_bytes() == before

    def test_append_refuses_byte_capacity_overflow_without_touching_store(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        append_mentions(tmp_path, [_mention_row("A")])
        path = mentions_jsonl_path(tmp_path)
        before = path.read_bytes()
        monkeypatch.setattr(notes_mod, "_MAX_MENTIONS_HISTORY_BYTES", len(before) + 10)

        with pytest.raises(JsonlIntegrityError, match="append would exceed"):
            append_mentions(tmp_path, [_mention_row("B", normalized_name="longer concept")])

        assert path.read_bytes() == before

    @pytest.mark.parametrize("damage", ["torn", "corrupt"])
    def test_append_refuses_damaged_history_without_touching_store(
        self,
        tmp_path: Path,
        damage: str,
    ) -> None:
        append_mentions(tmp_path, [_mention_row("A")])
        path = mentions_jsonl_path(tmp_path)
        content = path.read_bytes()
        damaged = content[:-1] if damage == "torn" else content + b"not-json\n"
        path.write_bytes(damaged)

        with pytest.raises(JsonlIntegrityError):
            append_mentions(tmp_path, [_mention_row("B")])

        assert path.read_bytes() == damaged

    def test_concurrent_batches_cannot_exceed_projected_capacity(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(notes_mod, "_MAX_MENTIONS_HISTORY_ROWS", 3)
        append_mentions(tmp_path, [_mention_row("seed")])
        batches = [
            [_mention_row("A1"), _mention_row("A2")],
            [_mention_row("B1"), _mention_row("B2")],
        ]

        def append_batch(batch: list[dict[str, object]]) -> str:
            try:
                append_mentions(tmp_path, batch)
            except JsonlIntegrityError:
                return "refused"
            return "stored"

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(append_batch, batches))

        assert sorted(outcomes) == ["refused", "stored"]
        assert len(read_mentions(tmp_path)) == 3


def test_existing_owner_oserror_returns_none(tmp_path: Path, monkeypatch):
    """Covers the except OSError in _existing_owner (core collision path)."""
    from distill.concepts.notes import _existing_owner

    base = tmp_path / "x.md"
    base.write_text("---\nnormalized_name: foo\n---\n", encoding="utf-8")
    monkeypatch.setattr(notes_mod, "_read_safe_note", lambda _path, _root: None)
    assert _existing_owner(base, tmp_path) is None


def test_safe_note_reader_detects_missing_and_changed_content(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    note = tmp_path / "note.md"
    identity: FileIdentity = (1, 2, 1, 10, 20, 30)
    changed: FileIdentity = (1, 2, 1, 11, 21, 31)
    monkeypatch.setattr(notes_mod, "confined_file_identity", lambda _path, _root: identity)
    monkeypatch.setattr(notes_mod, "read_confined_state_text", lambda *args, **kwargs: None)
    assert notes_mod._read_safe_note(note, tmp_path) is None

    identities = iter((identity, changed))
    monkeypatch.setattr(
        notes_mod,
        "confined_file_identity",
        lambda _path, _root: next(identities),
    )
    monkeypatch.setattr(notes_mod, "read_confined_state_text", lambda *args, **kwargs: "body")
    with pytest.raises(ValueError, match="changed while it was being read"):
        notes_mod._read_safe_note(note, tmp_path)


def test_collision_resolution_is_bounded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        notes_mod,
        "_collision_path_available",
        lambda *args, **kwargs: False,
    )

    with pytest.raises(ConfinedStateError, match="collision-safe note"):
        notes_mod._resolve_collision(
            tmp_path,
            tmp_path / "concepts",
            "collision",
            "distinct identity",
        )


def test_ownership_index_skips_unreadable_notes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent = concept_dir_for_topic(tmp_path)
    parent.mkdir()
    note = parent / "note.md"
    note.write_text("content", encoding="utf-8")
    occupied: set[Path] = set()
    monkeypatch.setattr(notes_mod, "_read_safe_note", lambda _path, _root: None)

    assert build_playbook_ownership_index(tmp_path, occupied_paths=occupied) == {}
    assert occupied == {note}


def test_snapshot_cleanup_reports_every_failed_removal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity: FileIdentity = (1, 2, 1, 10, 20, 30)
    snapshots = [(tmp_path / "one.md", identity), (tmp_path / "two.md", identity)]

    def refuse_unlink(*args, **kwargs):
        raise OSError("refused")

    monkeypatch.setattr(notes_mod, "unlink_confined_file", refuse_unlink)

    with pytest.raises(ExceptionGroup, match="Could not remove") as caught:
        notes_mod._remove_created_snapshots(tmp_path, snapshots)

    assert len(caught.value.exceptions) == 2


def test_migrated_note_cleanup_skips_unreadable_and_disappeared_notes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unreadable = tmp_path / "concepts" / "unreadable.md"
    disappeared = tmp_path / "entities" / "disappeared.md"
    identity: FileIdentity = (1, 2, 1, 10, 20, 30)
    content = "---\nnormalized_name: expected\n---\n"
    monkeypatch.setattr(
        notes_mod,
        "_read_safe_note",
        lambda path, _root: None if path == unreadable else (content, identity),
    )
    monkeypatch.setattr(
        notes_mod,
        "unlink_confined_file",
        lambda *args, **kwargs: (_ for _ in ()).throw(FileNotFoundError()),
    )

    assert not notes_mod._remove_migrated_notes(
        tmp_path,
        [unreadable, disappeared],
        tmp_path / "concepts" / "target.md",
        "expected",
    )


def test_playbook_target_refuses_note_owned_by_another_concept(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "note.md"
    identity: FileIdentity = (1, 2, 1, 10, 20, 30)
    content = "---\nnormalized_name: another identity\n---\n"
    monkeypatch.setattr(notes_mod, "_read_safe_note", lambda _path, _root: (content, identity))

    assert (
        notes_mod._update_playbook_target(
            tmp_path,
            _concept(),
            target,
            "replacement",
            "2026-07-18T12:00:00Z",
        )
        is None
    )


def test_playbook_target_reports_write_and_history_cleanup_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "note.md"
    snapshot = tmp_path / "snapshot.md"
    identity: FileIdentity = (1, 2, 1, 10, 20, 30)
    concept = _concept()
    content = f"---\nnormalized_name: {concept.normalized_name}\n---\nold"
    monkeypatch.setattr(notes_mod, "_read_safe_note", lambda _path, _root: (content, identity))
    monkeypatch.setattr(notes_mod, "write_history_snapshot", lambda *args, **kwargs: snapshot)
    monkeypatch.setattr(notes_mod, "confined_file_identity", lambda _path, _root: identity)
    monkeypatch.setattr(
        notes_mod,
        "atomic_write_confined_text",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("write failed")),
    )
    monkeypatch.setattr(
        notes_mod,
        "_remove_created_snapshots",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("cleanup failed")),
    )

    with pytest.raises(ExceptionGroup, match="publication and history cleanup") as caught:
        notes_mod._update_playbook_target(
            tmp_path,
            concept,
            target,
            "replacement",
            "2026-07-18T12:00:00Z",
        )

    assert len(caught.value.exceptions) == 2


def test_playbook_sources_section_is_empty_without_sources() -> None:
    assert notes_mod._sources_section(replace(_concept(), sources=())) == ""


def test_append_mentions_rejects_oversized_serialized_row(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(notes_mod, "_MAX_MENTION_ROW_BYTES", 1)

    with pytest.raises(JsonlIntegrityError, match="mention batch contains"):
        append_mentions(tmp_path, [_mention_row("source")])


def test_mentions_capacity_rejects_full_byte_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(notes_mod, "_MAX_MENTIONS_HISTORY_BYTES", 1)
    monkeypatch.setattr(notes_mod, "_read_mentions_history", lambda _topic_dir: [])
    monkeypatch.setattr(notes_mod, "read_confined_state_bytes", lambda *args, **kwargs: b"x")

    with pytest.raises(JsonlIntegrityError, match="1-byte limit"):
        notes_mod.ensure_mention_store_append_capacity(tmp_path)


def test_history_snapshot_allocation_is_bounded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(notes_mod, "range", lambda *args: range(1, 3), raising=False)
    monkeypatch.setattr(notes_mod, "exclusive_path_lock", lambda *args, **kwargs: nullcontext())
    monkeypatch.setattr(
        notes_mod,
        "atomic_write_confined_text",
        lambda *args, **kwargs: (_ for _ in ()).throw(FileExistsError()),
    )

    with pytest.raises(RuntimeError, match="unique history snapshot"):
        notes_mod.write_history_snapshot(tmp_path / "snapshot.md", "content", root=tmp_path)


def test_owned_note_snapshot_skips_unreadable_note(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    old = tmp_path / "concepts" / "old.md"
    target = tmp_path / "entities" / "target.md"
    monkeypatch.setattr(notes_mod, "_read_safe_note", lambda _path, _root: None)

    assert (
        notes_mod._snapshot_owned_notes(
            tmp_path,
            _concept(),
            [old],
            target,
            "2026-07-18T12:00:00Z",
        )
        == []
    )


def test_owned_note_snapshot_reports_publication_and_cleanup_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    old = tmp_path / "concepts" / "old.md"
    target = tmp_path / "entities" / "target.md"
    identity: FileIdentity = (1, 2, 1, 10, 20, 30)
    monkeypatch.setattr(
        notes_mod,
        "_read_safe_note",
        lambda _path, _root: ("content", identity),
    )
    monkeypatch.setattr(
        notes_mod,
        "write_history_snapshot",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("snapshot failed")),
    )
    monkeypatch.setattr(
        notes_mod,
        "_remove_created_snapshots",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("cleanup failed")),
    )

    with pytest.raises(ExceptionGroup, match="publication and cleanup") as caught:
        notes_mod._snapshot_owned_notes(
            tmp_path,
            _concept(),
            [old],
            target,
            "2026-07-18T12:00:00Z",
        )

    assert len(caught.value.exceptions) == 2

    monkeypatch.setattr(notes_mod, "_remove_created_snapshots", lambda *args, **kwargs: None)
    with pytest.raises(OSError, match="snapshot failed"):
        notes_mod._snapshot_owned_notes(
            tmp_path,
            _concept(),
            [old],
            target,
            "2026-07-18T12:00:00Z",
        )


def test_playbook_migration_reports_write_and_cleanup_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "concepts" / "target.md"
    monkeypatch.setattr(notes_mod, "render_playbook", lambda _concept: "content")
    monkeypatch.setattr(notes_mod, "_migration_target", lambda *args, **kwargs: target)
    monkeypatch.setattr(notes_mod, "_snapshot_owned_notes", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        notes_mod,
        "_update_playbook_target",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("write failed")),
    )
    monkeypatch.setattr(
        notes_mod,
        "_remove_created_snapshots",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("cleanup failed")),
    )

    with pytest.raises(ExceptionGroup, match="migration and history cleanup") as caught:
        notes_mod._write_playbook_transaction(
            tmp_path,
            _concept(),
            now_iso="2026-07-18T12:00:00Z",
            owned_paths=[],
            occupied_paths=set(),
        )

    assert len(caught.value.exceptions) == 2


def test_playbook_collision_retry_is_bounded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "concepts" / "target.md"
    monkeypatch.setattr(notes_mod, "range", lambda *args: range(2), raising=False)
    monkeypatch.setattr(notes_mod, "render_playbook", lambda _concept: "content")
    monkeypatch.setattr(notes_mod, "_owned_note_paths", lambda *args, **kwargs: [])
    monkeypatch.setattr(notes_mod, "_migration_target", lambda *args, **kwargs: target)
    monkeypatch.setattr(notes_mod, "_snapshot_owned_notes", lambda *args, **kwargs: [])
    monkeypatch.setattr(notes_mod, "_update_playbook_target", lambda *args, **kwargs: None)
    monkeypatch.setattr(notes_mod, "_remove_created_snapshots", lambda *args, **kwargs: None)
    occupied: set[Path] = set()

    with pytest.raises(RuntimeError, match="claim a collision-safe note path"):
        notes_mod._write_playbook_transaction(
            tmp_path,
            _concept(),
            now_iso="2026-07-18T12:00:00Z",
            owned_paths=[],
            occupied_paths=occupied,
        )

    assert occupied == {target}


class TestExtractedSourcesLedger:
    def test_read_missing_returns_empty(self, tmp_path: Path) -> None:
        assert read_extracted_sources(tmp_path) == set()

    def test_read_bad_json_raises_integrity_error(self, tmp_path: Path) -> None:
        path = _extracted_sources_path(tmp_path)
        path.parent.mkdir(parents=True)
        path.write_text("not json", encoding="utf-8")

        with pytest.raises(SourceLedgerIntegrityError) as caught:
            read_extracted_sources(tmp_path)

        assert str(path) in str(caught.value)

    def test_record_merges_and_idempotent(self, tmp_path: Path) -> None:
        record_extracted_sources(tmp_path, ["A", "B"])
        assert read_extracted_sources(tmp_path) == {"A", "B"}
        record_extracted_sources(tmp_path, ["B", "C"])
        assert read_extracted_sources(tmp_path) == {"A", "B", "C"}

    def test_record_empty_noop(self, tmp_path: Path) -> None:
        record_extracted_sources(tmp_path, [])
        assert not _extracted_sources_path(tmp_path).exists()

    def test_rejects_linked_state_directory(self, tmp_path: Path) -> None:
        external = tmp_path / "external"
        external.mkdir()
        external_ledger = external / "extracted_sources.json"
        external_ledger.write_text('["outside"]', encoding="utf-8")
        linked = tmp_path / ".concepts"
        try:
            linked.symlink_to(external, target_is_directory=True)
        except OSError as exc:
            pytest.skip(f"directory symlinks unavailable: {exc}")
        before = external_ledger.read_bytes()

        with pytest.raises(SourceLedgerIntegrityError, match="private directory"):
            read_extracted_sources(tmp_path)
        with pytest.raises(SourceLedgerIntegrityError, match="private directory"):
            record_extracted_sources(tmp_path, ["new"])

        assert external_ledger.read_bytes() == before

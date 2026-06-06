"""Unit tests for the concept-playbook recovery surface (0.8.2).

History snapshots are produced through the real ``write_playbook`` path
so these tests exercise the actual on-disk serialization, not a
hand-rolled approximation of it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from distill.concepts import recovery
from distill.concepts.exports import write_exports
from distill.concepts.notes import write_playbook
from distill.concepts.records import (
    ConceptKind,
    EvidenceInterval,
    MergedConcept,
    Polarity,
    SourceEvidence,
)


def _concept(
    *,
    name: str = "Rotational Embedding",
    normalized: str = "rotational embedding",
    kind: ConceptKind = ConceptKind.TECHNIQUE,
    sources: list[tuple[str, Polarity]],
    helpful: tuple[int, int],
    harmful: tuple[int, int],
    last_seen: str,
) -> MergedConcept:
    srcs = tuple(
        SourceEvidence(
            source_id=sid,
            artifact_path=f"papers/{sid}/{sid}_Insights.md",
            polarity=pol,
            claim_excerpt=f"excerpt {sid}",
        )
        for sid, pol in sources
    )
    return MergedConcept(
        name=name,
        normalized_name=normalized,
        kind=kind,
        topic="tkg",
        sources=srcs,
        helpful_evidence=EvidenceInterval(*helpful),
        harmful_evidence=EvidenceInterval(*harmful),
        first_seen="2026-05-01T00:00:00Z",
        last_seen=last_seen,
    )


def test_recovery_rejects_traversal_slug(tmp_path: Path) -> None:
    # slug reaches filesystem joins from untrusted MCP/CLI callers; a traversal
    # slug must not read or write outside the topic dir.
    td = tmp_path / "topics" / "tkg"
    td.mkdir(parents=True)
    bad = "../../../../etc/secret"
    assert recovery.note_path_for_slug(td, bad) is None
    assert recovery.list_snapshots(td, bad) == []
    with pytest.raises(ValueError, match=r"[Uu]nsafe"):
        recovery.rollback(td, bad, "2026-01-01T00-00-00Z", now_iso="2026-01-02T00:00:00Z")


def test_rollback_refuses_on_slug_collision(tmp_path: Path) -> None:
    # "gpt 4" and "gpt-4" are distinct concepts that both slugify to "gpt_4".
    # Rolling back the slug to the bumped concept's snapshot must NOT clobber
    # the base concept's note -- it must refuse on the identity mismatch.
    td = tmp_path / "topics" / "tkg"
    td.mkdir(parents=True)
    base = _concept(
        name="GPT 4",
        normalized="gpt 4",
        sources=[("A", Polarity.HELPFUL)],
        helpful=(1, 1),
        harmful=(0, 0),
        last_seen="2026-05-28T07:00:00Z",
    )
    write_playbook(td, base, now_iso="2026-05-28T07:00:00Z")
    bumped_v1 = _concept(
        name="GPT-4",
        normalized="gpt-4",
        sources=[("B", Polarity.HELPFUL)],
        helpful=(1, 1),
        harmful=(0, 0),
        last_seen="2026-05-28T07:30:00Z",
    )
    write_playbook(td, bumped_v1, now_iso="2026-05-28T07:30:00Z")
    bumped_v2 = _concept(
        name="GPT-4",
        normalized="gpt-4",
        sources=[("B", Polarity.HELPFUL), ("C", Polarity.HELPFUL)],
        helpful=(2, 2),
        harmful=(0, 0),
        last_seen="2026-05-29T09:00:00Z",
    )
    write_playbook(td, bumped_v2, now_iso="2026-05-29T09:00:00Z")

    with pytest.raises(ValueError, match="shared by multiple concepts"):
        recovery.rollback(td, "gpt_4", "2026-05-29T09:00:00Z", now_iso="2026-05-29T10:00:00Z")


@pytest.fixture
def history_topic(tmp_path: Path) -> Path:
    """Build a three-version history for ``rotational_embedding``.

    Snapshot files hold the *prior* content (write_playbook snapshots
    before overwriting), so after three writes there are two snapshots:
    one holding v1, one holding v2; the live note holds v3.
    """
    td = tmp_path / "topics" / "tkg"
    td.mkdir(parents=True)

    v1 = _concept(
        sources=[("A", Polarity.HELPFUL), ("B", Polarity.HELPFUL)],
        helpful=(2, 2),
        harmful=(0, 0),
        last_seen="2026-05-28T07:00:00Z",
    )
    write_playbook(td, v1, now_iso="2026-05-28T07:00:00Z")
    write_exports(td, [v1])

    v2 = _concept(
        sources=[("A", Polarity.HELPFUL), ("B", Polarity.HELPFUL), ("C", Polarity.HELPFUL)],
        helpful=(3, 3),
        harmful=(0, 0),
        last_seen="2026-05-29T08:10:31Z",
    )
    write_playbook(td, v2, now_iso="2026-05-29T08:10:31Z")
    write_exports(td, [v2])

    v3 = _concept(
        sources=[("A", Polarity.HELPFUL), ("B", Polarity.HARMFUL), ("C", Polarity.HELPFUL)],
        helpful=(2, 2),
        harmful=(1, 1),
        last_seen="2026-05-29T09:00:00Z",
    )
    write_playbook(td, v3, now_iso="2026-05-29T09:00:00Z")
    write_exports(td, [v3])

    return td


# ---- timestamp helpers -----------------------------------------------------


class TestTimestampHelpers:
    def test_iso_to_safe_swaps_colons(self) -> None:
        assert recovery.iso_to_safe_ts("2026-05-29T08:10:31Z") == "2026-05-29T08-10-31Z"

    def test_safe_to_iso_round_trips(self) -> None:
        iso = "2026-05-29T08:10:31Z"
        assert recovery.safe_ts_to_iso(recovery.iso_to_safe_ts(iso)) == iso

    def test_safe_to_iso_keeps_date_hyphens(self) -> None:
        # Only the time component should regain colons.
        assert recovery.safe_ts_to_iso("2026-05-29T08-10-31Z") == "2026-05-29T08:10:31Z"

    def test_safe_to_iso_without_t_is_unchanged(self) -> None:
        assert recovery.safe_ts_to_iso("nonsense") == "nonsense"


# ---- snapshot enumeration --------------------------------------------------


class TestListSnapshots:
    def test_orders_oldest_first(self, history_topic: Path) -> None:
        snaps = recovery.list_snapshots(history_topic, "rotational_embedding")
        assert [s.iso for s in snaps] == [
            "2026-05-29T08:10:31Z",
            "2026-05-29T09:00:00Z",
        ]

    def test_empty_when_no_history(self, tmp_path: Path) -> None:
        assert recovery.list_snapshots(tmp_path, "ghost") == []


class TestResolveSnapshot:
    def test_resolves_iso_form(self, history_topic: Path) -> None:
        snap = recovery.resolve_snapshot(
            history_topic, "rotational_embedding", "2026-05-29T08:10:31Z"
        )
        assert snap is not None and snap.iso == "2026-05-29T08:10:31Z"

    def test_resolves_safe_form(self, history_topic: Path) -> None:
        snap = recovery.resolve_snapshot(
            history_topic, "rotational_embedding", "2026-05-29T08-10-31Z"
        )
        assert snap is not None and snap.iso == "2026-05-29T08:10:31Z"

    def test_resolves_with_md_suffix(self, history_topic: Path) -> None:
        snap = recovery.resolve_snapshot(
            history_topic, "rotational_embedding", "2026-05-29T08:10:31Z.md"
        )
        assert snap is not None

    def test_returns_none_for_unknown(self, history_topic: Path) -> None:
        assert (
            recovery.resolve_snapshot(history_topic, "rotational_embedding", "1999-01-01") is None
        )


class TestNotePathForSlug:
    def test_finds_concept_note(self, history_topic: Path) -> None:
        path = recovery.note_path_for_slug(history_topic, "rotational_embedding")
        assert path is not None and path.parent.name == "concepts"

    def test_finds_entity_note(self, tmp_path: Path) -> None:
        td = tmp_path / "topics" / "tkg"
        td.mkdir(parents=True)
        ent = _concept(
            name="DeepMind",
            normalized="deepmind",
            kind=ConceptKind.ORGANIZATION,
            sources=[("A", Polarity.NEUTRAL)],
            helpful=(0, 1),
            harmful=(0, 0),
            last_seen="2026-05-29T09:00:00Z",
        )
        write_playbook(td, ent, now_iso="2026-05-29T09:00:00Z")
        path = recovery.note_path_for_slug(td, "deepmind")
        assert path is not None and path.parent.name == "entities"

    def test_returns_none_when_missing(self, tmp_path: Path) -> None:
        assert recovery.note_path_for_slug(tmp_path, "ghost") is None


# ---- frontmatter parsing ---------------------------------------------------


class TestParseNoteFields:
    def test_decodes_structured_fields(self, history_topic: Path) -> None:
        live = recovery.note_path_for_slug(history_topic, "rotational_embedding")
        assert live is not None
        fields = recovery.parse_note_fields(live.read_text(encoding="utf-8"))
        assert fields["source_count"] == 3
        assert fields["helpful_evidence"] == [2, 2]
        assert fields["harmful_evidence"] == [1, 1]
        assert fields["contested"] is True
        assert isinstance(fields["sources"], list)
        assert {s["source_id"] for s in fields["sources"]} == {"A", "B", "C"}

    def test_tolerates_no_frontmatter(self) -> None:
        assert recovery.parse_note_fields("just a body") == {}


# ---- diffing ---------------------------------------------------------------


class TestDiffNotes:
    def test_detects_repolarization_and_intervals(self, history_topic: Path) -> None:
        snaps = recovery.list_snapshots(history_topic, "rotational_embedding")
        live = recovery.note_path_for_slug(history_topic, "rotational_embedding")
        assert live is not None
        diff = recovery.diff_notes(
            snaps[-1].path.read_text(encoding="utf-8"),
            live.read_text(encoding="utf-8"),
        )
        assert diff.sources_added == []
        assert diff.sources_removed == []
        assert diff.sources_repolarized == [("B", "helpful", "harmful")]
        changed = {c.field for c in diff.field_changes}
        assert {"helpful_evidence", "harmful_evidence", "contested"} <= changed

    def test_detects_added_sources(self, history_topic: Path) -> None:
        snaps = recovery.list_snapshots(history_topic, "rotational_embedding")
        # oldest snapshot holds v1 (A,B); next holds v2 (A,B,C)
        diff = recovery.diff_notes(
            snaps[0].path.read_text(encoding="utf-8"),
            snaps[1].path.read_text(encoding="utf-8"),
        )
        assert diff.sources_added == ["C"]
        assert diff.sources_removed == []

    def test_identical_is_empty(self, history_topic: Path) -> None:
        live = recovery.note_path_for_slug(history_topic, "rotational_embedding")
        assert live is not None
        content = live.read_text(encoding="utf-8")
        diff = recovery.diff_notes(content, content)
        assert diff.is_empty
        assert not diff.has_frontmatter_changes


class TestSummarizeTransition:
    def test_source_and_interval_summary(self, history_topic: Path) -> None:
        snaps = recovery.list_snapshots(history_topic, "rotational_embedding")
        a = recovery.parse_note_fields(snaps[0].path.read_text(encoding="utf-8"))
        b = recovery.parse_note_fields(snaps[1].path.read_text(encoding="utf-8"))
        summary = recovery.summarize_transition(a, b)
        assert "+1 source" in summary
        assert "helpful [2,2]->[3,3]" in summary

    def test_contested_flip(self, history_topic: Path) -> None:
        snaps = recovery.list_snapshots(history_topic, "rotational_embedding")
        live = recovery.note_path_for_slug(history_topic, "rotational_embedding")
        assert live is not None
        b = recovery.parse_note_fields(snaps[-1].path.read_text(encoding="utf-8"))
        c = recovery.parse_note_fields(live.read_text(encoding="utf-8"))
        assert "became contested" in recovery.summarize_transition(b, c)

    def test_body_only_when_no_structural_change(self) -> None:
        fm = "---\nslug: x\nhelpful_evidence: [1, 1]\nharmful_evidence: [0, 0]\nsources: []\n---\nbody"
        assert (
            recovery.summarize_transition(
                recovery.parse_note_fields(fm), recovery.parse_note_fields(fm)
            )
            == "body/wording only"
        )


# ---- rollback --------------------------------------------------------------


class TestRollback:
    def test_restores_content_and_rollup(self, history_topic: Path) -> None:
        snaps = recovery.list_snapshots(history_topic, "rotational_embedding")
        oldest = snaps[0]  # holds v1: 2 sources, not contested
        result = recovery.rollback(
            history_topic, "rotational_embedding", oldest.iso, now_iso="2026-05-29T10:00:00Z"
        )
        assert result.changed is True
        assert result.restored_from == oldest.iso

        live = recovery.note_path_for_slug(history_topic, "rotational_embedding")
        assert live is not None
        assert live.read_text(encoding="utf-8") == oldest.path.read_text(encoding="utf-8")

        row = json.loads(
            (history_topic / "concepts.jsonl").read_text(encoding="utf-8").splitlines()[0]
        )
        assert row["source_count"] == 2
        assert row["contested"] is False
        assert row["helpful_evidence"] == [2, 2]

    def test_creates_reversible_backup(self, history_topic: Path) -> None:
        live = recovery.note_path_for_slug(history_topic, "rotational_embedding")
        assert live is not None
        pre_rollback = live.read_text(encoding="utf-8")
        snaps = recovery.list_snapshots(history_topic, "rotational_embedding")

        result = recovery.rollback(
            history_topic, "rotational_embedding", snaps[0].iso, now_iso="2026-05-29T10:00:00Z"
        )
        assert result.backup_path is not None
        assert result.backup_path.read_text(encoding="utf-8") == pre_rollback

    def test_noop_when_already_matches(self, history_topic: Path) -> None:
        # Snapshot the current live content, then "roll back" to it.
        live = recovery.note_path_for_slug(history_topic, "rotational_embedding")
        assert live is not None
        hist = recovery.history_dir_for_slug(history_topic, "rotational_embedding")
        snap_path = hist / "2026-05-29T11-00-00Z.md"
        snap_path.write_text(live.read_text(encoding="utf-8"), encoding="utf-8")

        result = recovery.rollback(
            history_topic,
            "rotational_embedding",
            "2026-05-29T11:00:00Z",
            now_iso="2026-05-29T12:00:00Z",
        )
        assert result.changed is False
        assert result.backup_path is None

    def test_unknown_snapshot_raises(self, history_topic: Path) -> None:
        with pytest.raises(FileNotFoundError):
            recovery.rollback(
                history_topic, "rotational_embedding", "1999-01-01", now_iso="2026-05-29T10:00:00Z"
            )

    def test_recreates_deleted_note(self, history_topic: Path) -> None:
        live = recovery.note_path_for_slug(history_topic, "rotational_embedding")
        assert live is not None
        live.unlink()
        snaps = recovery.list_snapshots(history_topic, "rotational_embedding")

        result = recovery.rollback(
            history_topic, "rotational_embedding", snaps[0].iso, now_iso="2026-05-29T10:00:00Z"
        )
        assert result.changed is True
        assert result.backup_path is None  # nothing live to back up
        restored = recovery.note_path_for_slug(history_topic, "rotational_embedding")
        assert restored is not None and restored.is_file()

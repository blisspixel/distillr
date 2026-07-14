"""Unit tests for the concept-playbook recovery surface (0.8.2).

History snapshots are produced through the real ``write_playbook`` path
so these tests exercise the actual on-disk serialization, not a
hand-rolled approximation of it.
"""

from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from distill.concepts import recovery
from distill.concepts.exports import write_exports
from distill.concepts.notes import render_playbook, write_playbook
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


def test_rollback_uses_collision_resolved_storage_slug(tmp_path: Path) -> None:
    # "gpt 4" and "gpt-4" are distinct concepts that both slugify to "gpt_4".
    # Each history follows its resolved live note stem, so rollback can select
    # the bumped concept without touching the base concept.
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
    base_path, _ = write_playbook(td, base, now_iso="2026-05-28T07:00:00Z")
    bumped_v1 = _concept(
        name="GPT-4",
        normalized="gpt-4",
        sources=[("B", Polarity.HELPFUL)],
        helpful=(1, 1),
        harmful=(0, 0),
        last_seen="2026-05-28T07:30:00Z",
    )
    bumped_path, _ = write_playbook(td, bumped_v1, now_iso="2026-05-28T07:30:00Z")
    write_exports(td, [base, bumped_v1])
    bumped_v2 = _concept(
        name="GPT-4",
        normalized="gpt-4",
        sources=[("B", Polarity.HELPFUL), ("C", Polarity.HELPFUL)],
        helpful=(2, 2),
        harmful=(0, 0),
        last_seen="2026-05-29T09:00:00Z",
    )
    write_playbook(td, bumped_v2, now_iso="2026-05-29T09:00:00Z")
    write_exports(td, [base, bumped_v2])

    base_content = base_path.read_text(encoding="utf-8")
    result = recovery.rollback(
        td,
        bumped_path.stem,
        "2026-05-29T09:00:00Z",
        now_iso="2026-05-29T10:00:00Z",
    )

    assert result.note_path == bumped_path
    assert base_path.read_text(encoding="utf-8") == base_content
    assert 'normalized_name: "gpt-4"' in bumped_path.read_text(encoding="utf-8")
    assert "source_count: 1" in bumped_path.read_text(encoding="utf-8")
    rollup_rows = [
        json.loads(line)
        for line in (td / "concepts.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert {row["normalized_name"] for row in rollup_rows} == {"gpt 4", "gpt-4"}
    assert (
        next(row for row in rollup_rows if row["normalized_name"] == "gpt 4")["source_count"] == 1
    )
    assert (
        next(row for row in rollup_rows if row["normalized_name"] == "gpt-4")["source_count"] == 1
    )


def test_rollback_preserves_legacy_same_slug_sibling(tmp_path: Path) -> None:
    topic_dir = tmp_path / "topics" / "tkg"
    topic_dir.mkdir(parents=True)
    legacy_sibling = _concept(
        name="GPT 4",
        normalized="gpt 4",
        sources=[("A", Polarity.HELPFUL)],
        helpful=(1, 1),
        harmful=(0, 0),
        last_seen="2026-05-28T07:00:00Z",
    )
    target_v1 = _concept(
        name="GPT-4",
        normalized="gpt-4",
        sources=[("B", Polarity.HELPFUL)],
        helpful=(1, 1),
        harmful=(0, 0),
        last_seen="2026-05-28T07:30:00Z",
    )
    write_playbook(topic_dir, legacy_sibling, now_iso="2026-05-28T07:00:00Z")
    target_path, _ = write_playbook(
        topic_dir,
        target_v1,
        now_iso="2026-05-28T07:30:00Z",
    )
    target_v2 = _concept(
        name="GPT-4",
        normalized="gpt-4",
        sources=[("B", Polarity.HELPFUL), ("C", Polarity.HELPFUL)],
        helpful=(2, 2),
        harmful=(0, 0),
        last_seen="2026-05-29T09:00:00Z",
    )
    write_playbook(topic_dir, target_v2, now_iso="2026-05-29T09:00:00Z")
    write_exports(topic_dir, [legacy_sibling, target_v2])
    rollup_path = topic_dir / "concepts.jsonl"
    rows = [json.loads(line) for line in rollup_path.read_text(encoding="utf-8").splitlines()]
    next(row for row in rows if row["normalized_name"] == "gpt 4").pop("normalized_name")
    rollup_path.write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )

    recovery.rollback(
        topic_dir,
        target_path.stem,
        "2026-05-29T09:00:00Z",
        now_iso="2026-05-29T10:00:00Z",
    )

    restored_rows = [
        json.loads(line) for line in rollup_path.read_text(encoding="utf-8").splitlines()
    ]
    assert len(restored_rows) == 2
    assert sum("normalized_name" not in row for row in restored_rows) == 1
    restored_target = next(row for row in restored_rows if row.get("normalized_name") == "gpt-4")
    assert restored_target["source_count"] == 1


def test_rollback_rejects_ambiguous_legacy_rows_before_mutating_note(tmp_path: Path) -> None:
    topic_dir = tmp_path / "topics" / "tkg"
    topic_dir.mkdir(parents=True)
    v1 = _concept(
        name="Alpha",
        normalized="alpha",
        sources=[("A", Polarity.HELPFUL)],
        helpful=(1, 1),
        harmful=(0, 0),
        last_seen="2026-05-28T07:00:00Z",
    )
    live_path, _ = write_playbook(topic_dir, v1, now_iso="2026-05-28T07:00:00Z")
    v2 = _concept(
        name="Alpha",
        normalized="alpha",
        sources=[("A", Polarity.HELPFUL), ("B", Polarity.HELPFUL)],
        helpful=(2, 2),
        harmful=(0, 0),
        last_seen="2026-05-29T09:00:00Z",
    )
    write_playbook(topic_dir, v2, now_iso="2026-05-29T09:00:00Z")
    snapshot = recovery.list_snapshots(topic_dir, "alpha")[0]
    snapshot.path.write_text(
        "\n".join(
            line
            for line in snapshot.path.read_text(encoding="utf-8").splitlines()
            if not line.startswith("normalized_name:")
        )
        + "\n",
        encoding="utf-8",
    )
    legacy_row = v2.to_jsonl_row()
    legacy_row.pop("normalized_name")
    duplicate = {**legacy_row, "name": "Ambiguous Alpha"}
    rollup_path = topic_dir / "concepts.jsonl"
    rollup_path.write_text(
        json.dumps(legacy_row) + "\n" + json.dumps(duplicate) + "\n",
        encoding="utf-8",
    )
    live_before = live_path.read_text(encoding="utf-8")
    rollup_before = rollup_path.read_text(encoding="utf-8")

    with pytest.raises(ValueError, match="multiple legacy rows"):
        recovery.rollback(
            topic_dir,
            "alpha",
            snapshot.iso,
            now_iso="2026-05-29T10:00:00Z",
        )

    assert live_path.read_text(encoding="utf-8") == live_before
    assert rollup_path.read_text(encoding="utf-8") == rollup_before


def test_rollback_rejects_identityless_snapshot_with_legacy_and_named_rows(
    tmp_path: Path,
) -> None:
    topic_dir = tmp_path / "topics" / "tkg"
    topic_dir.mkdir(parents=True)
    base = _concept(
        name="GPT 4",
        normalized="gpt 4",
        sources=[("A", Polarity.HELPFUL)],
        helpful=(1, 1),
        harmful=(0, 0),
        last_seen="2026-05-28T07:00:00Z",
    )
    target = _concept(
        name="GPT-4",
        normalized="gpt-4",
        sources=[("B", Polarity.HELPFUL)],
        helpful=(1, 1),
        harmful=(0, 0),
        last_seen="2026-05-28T07:30:00Z",
    )
    base_path, _ = write_playbook(topic_dir, base, now_iso="2026-05-28T07:00:00Z")
    target_path, _ = write_playbook(topic_dir, target, now_iso="2026-05-28T07:30:00Z")
    write_exports(topic_dir, [base, target])
    base_path.write_text(
        "\n".join(
            line
            for line in base_path.read_text(encoding="utf-8").splitlines()
            if not line.startswith("normalized_name:")
        )
        + "\n",
        encoding="utf-8",
    )
    rollup_path = topic_dir / "concepts.jsonl"
    rollup_rows = [
        json.loads(line) for line in rollup_path.read_text(encoding="utf-8").splitlines()
    ]
    next(row for row in rollup_rows if row["normalized_name"] == "gpt 4").pop("normalized_name")
    rollup_path.write_text(
        "".join(json.dumps(row) + "\n" for row in rollup_rows),
        encoding="utf-8",
    )
    legacy_content = (
        "\n".join(
            line
            for line in render_playbook(target).splitlines()
            if not line.startswith("normalized_name:")
        )
        + "\n"
    )
    legacy_snapshot = (
        recovery.history_dir_for_slug(topic_dir, base.slug) / "2026-05-29T09-00-00Z.md"
    )
    legacy_snapshot.parent.mkdir(parents=True)
    legacy_snapshot.write_text(legacy_content, encoding="utf-8")
    base_before = base_path.read_text(encoding="utf-8")
    target_before = target_path.read_text(encoding="utf-8")
    rollup_before = rollup_path.read_text(encoding="utf-8")
    history_before = {
        path.name: path.read_text(encoding="utf-8")
        for path in recovery.history_dir_for_slug(topic_dir, base.slug).glob("*.md")
    }

    with pytest.raises(ValueError, match="identity-less snapshot"):
        recovery.rollback(
            topic_dir,
            base.slug,
            "2026-05-29T09:00:00Z",
            now_iso="2026-05-29T10:00:00Z",
        )

    assert base_path.read_text(encoding="utf-8") == base_before
    assert target_path.read_text(encoding="utf-8") == target_before
    assert rollup_path.read_text(encoding="utf-8") == rollup_before
    assert {
        path.name: path.read_text(encoding="utf-8")
        for path in recovery.history_dir_for_slug(topic_dir, base.slug).glob("*.md")
    } == history_before


def test_concurrent_rollbacks_keep_live_notes_and_rollup_consistent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    topic_dir = tmp_path / "topics" / "tkg"
    topic_dir.mkdir(parents=True)
    alpha_v1 = _concept(
        name="Alpha",
        normalized="alpha",
        sources=[("A1", Polarity.HELPFUL)],
        helpful=(1, 1),
        harmful=(0, 0),
        last_seen="2026-05-28T07:00:00Z",
    )
    beta_v1 = _concept(
        name="Beta",
        normalized="beta",
        sources=[("B1", Polarity.HELPFUL)],
        helpful=(1, 1),
        harmful=(0, 0),
        last_seen="2026-05-28T07:00:00Z",
    )
    alpha_v2 = _concept(
        name="Alpha",
        normalized="alpha",
        sources=[("A1", Polarity.HELPFUL), ("A2", Polarity.HELPFUL)],
        helpful=(2, 2),
        harmful=(0, 0),
        last_seen="2026-05-29T09:00:00Z",
    )
    beta_v2 = _concept(
        name="Beta",
        normalized="beta",
        sources=[("B1", Polarity.HELPFUL), ("B2", Polarity.HELPFUL)],
        helpful=(2, 2),
        harmful=(0, 0),
        last_seen="2026-05-29T09:00:00Z",
    )
    write_playbook(topic_dir, alpha_v1, now_iso="2026-05-28T07:00:00Z")
    write_playbook(topic_dir, beta_v1, now_iso="2026-05-28T07:00:00Z")
    write_exports(topic_dir, [alpha_v1, beta_v1])
    write_playbook(topic_dir, alpha_v2, now_iso="2026-05-29T09:00:00Z")
    write_playbook(topic_dir, beta_v2, now_iso="2026-05-29T09:00:00Z")
    write_exports(topic_dir, [alpha_v2, beta_v2])

    real_read = recovery._read_rollup_rows
    first_read = threading.Event()
    second_read = threading.Event()
    read_count = 0
    read_count_lock = threading.Lock()

    def overlapping_read(path: Path):
        nonlocal read_count
        rows = real_read(path)
        with read_count_lock:
            read_count += 1
            current_read = read_count
        if current_read == 1:
            first_read.set()
            second_read.wait(timeout=0.25)
        elif current_read == 2:
            second_read.set()
        return rows

    monkeypatch.setattr(recovery, "_read_rollup_rows", overlapping_read)
    with ThreadPoolExecutor(max_workers=2) as executor:
        alpha_result = executor.submit(
            recovery.rollback,
            topic_dir,
            "alpha",
            "2026-05-29T09:00:00Z",
            now_iso="2026-05-29T10:00:00Z",
        )
        assert first_read.wait(timeout=5)
        beta_result = executor.submit(
            recovery.rollback,
            topic_dir,
            "beta",
            "2026-05-29T09:00:00Z",
            now_iso="2026-05-29T10:00:01Z",
        )
        alpha_result.result(timeout=5)
        beta_result.result(timeout=5)

    rollup_rows = {
        row["slug"]: row for row in recovery._read_rollup_rows(topic_dir / "concepts.jsonl")
    }
    for slug in ("alpha", "beta"):
        live_path = recovery.note_path_for_slug(topic_dir, slug)
        assert live_path is not None
        live_fields = recovery.parse_note_fields(live_path.read_text(encoding="utf-8"))
        assert rollup_rows[slug]["source_count"] == live_fields["source_count"] == 1


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

    def test_resolves_after_trimming_whitespace(self, history_topic: Path) -> None:
        snap = recovery.resolve_snapshot(
            history_topic, "rotational_embedding", " 2026-05-29T08:10:31Z.md \n"
        )
        assert snap is not None and snap.safe_ts == "2026-05-29T08-10-31Z"

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

    def test_scans_collision_bumped_note_by_frontmatter_slug(self, tmp_path: Path) -> None:
        td = tmp_path / "topics" / "tkg"
        note_dir = td / "concepts"
        note_dir.mkdir(parents=True)
        bumped = note_dir / "rotational_embedding__2.md"
        bumped.write_text(
            "---\n"
            "slug: rotational_embedding\n"
            "normalized_name: rotational embedding duplicate\n"
            "---\n"
            "body\n",
            encoding="utf-8",
        )

        path = recovery.note_path_for_slug(td, "rotational_embedding")
        assert path == bumped

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

    def test_malformed_structured_fields_fall_back_to_typed_defaults(self) -> None:
        content = """---
source_count: nope
helpful_evidence: not-json
harmful_evidence: [3, 1]
helpful_count: -4
harmful_count: 2
sources: {"not": "a list"}
contested: true
---
body
"""
        fields = recovery.parse_note_fields(content)
        assert fields["source_count"] == 0
        assert fields["helpful_evidence"] == [0, 0]
        assert fields["harmful_evidence"] == [0, 0]
        assert fields["helpful_count"] == 0
        assert fields["harmful_count"] == 2
        assert fields["sources"] == []
        assert fields["contested"] is True


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

    def test_detects_removed_sources_and_uses_labels_in_body_diff(self) -> None:
        old = """---
sources: [{"source_id": "A", "polarity": "helpful"}, {"source_id": "B", "polarity": "harmful"}]
---
old body
"""
        new = """---
sources: [{"source_id": "A", "polarity": "helpful"}]
---
new body
"""
        diff = recovery.diff_notes(old, new, old_label="before", new_label="after")
        assert diff.sources_added == []
        assert diff.sources_removed == ["B"]
        assert "--- before" in diff.body_diff
        assert "+++ after" in diff.body_diff

    def test_ignores_malformed_source_entries_when_diffing(self) -> None:
        old = """---
sources: [{"source_id": "A", "polarity": "helpful"}, {"artifact_path": "missing-id"}, "junk"]
---
body
"""
        new = """---
sources: [{"source_id": "A", "polarity": "harmful"}, {"source_id": "B", "polarity": "neutral"}]
---
body
"""
        diff = recovery.diff_notes(old, new)
        assert diff.sources_added == ["B"]
        assert diff.sources_removed == []
        assert diff.sources_repolarized == [("A", "helpful", "harmful")]

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

    def test_replaces_existing_rollup_row_without_duplicates(self, history_topic: Path) -> None:
        stale = {
            "name": "Rotational Embedding",
            "normalized_name": "rotational embedding",
            "slug": "rotational_embedding",
            "kind": "technique",
            "topic": "tkg",
            "source_count": 99,
            "helpful_evidence": [99, 99],
            "harmful_evidence": [0, 0],
            "helpful_count": 99,
            "harmful_count": 0,
            "contested": False,
            "first_seen": "2026-05-01T00:00:00Z",
            "last_seen": "2026-05-29T09:00:00Z",
        }
        unrelated = {
            "name": "Alpha Architecture",
            "normalized_name": "alpha architecture",
            "slug": "alpha_architecture",
            "kind": "architecture",
            "topic": "tkg",
            "source_count": 1,
            "helpful_evidence": [1, 1],
            "harmful_evidence": [0, 0],
            "helpful_count": 1,
            "harmful_count": 0,
            "contested": False,
            "first_seen": "2026-05-01T00:00:00Z",
            "last_seen": "2026-05-01T00:00:00Z",
        }
        rollup = history_topic / "concepts.jsonl"
        rollup.write_text(
            json.dumps(stale) + "\nnot-json\n" + json.dumps(unrelated) + "\n",
            encoding="utf-8",
        )

        oldest = recovery.list_snapshots(history_topic, "rotational_embedding")[0]
        recovery.rollback(
            history_topic, "rotational_embedding", oldest.iso, now_iso="2026-05-29T10:00:00Z"
        )

        rows = [json.loads(line) for line in rollup.read_text(encoding="utf-8").splitlines()]
        assert [row["slug"] for row in rows] == ["alpha_architecture", "rotational_embedding"]
        restored = [row for row in rows if row["slug"] == "rotational_embedding"]
        assert len(restored) == 1
        assert restored[0]["source_count"] == 2
        assert restored[0]["helpful_evidence"] == [2, 2]

    def test_entity_rollback_updates_entities_rollup(self, tmp_path: Path) -> None:
        td = tmp_path / "topics" / "tkg"
        td.mkdir(parents=True)
        v1 = _concept(
            name="DeepMind",
            normalized="deepmind",
            kind=ConceptKind.ORGANIZATION,
            sources=[("A", Polarity.HELPFUL)],
            helpful=(1, 1),
            harmful=(0, 0),
            last_seen="2026-05-29T08:00:00Z",
        )
        write_playbook(td, v1, now_iso="2026-05-29T08:00:00Z")
        write_exports(td, [v1])
        v2 = _concept(
            name="DeepMind",
            normalized="deepmind",
            kind=ConceptKind.ORGANIZATION,
            sources=[("A", Polarity.HELPFUL), ("B", Polarity.HELPFUL)],
            helpful=(2, 2),
            harmful=(0, 0),
            last_seen="2026-05-29T09:00:00Z",
        )
        write_playbook(td, v2, now_iso="2026-05-29T09:00:00Z")
        write_exports(td, [v2])

        snap = recovery.list_snapshots(td, "deepmind")[0]
        result = recovery.rollback(td, "deepmind", snap.iso, now_iso="2026-05-29T10:00:00Z")

        assert result.rollup_path == td / "entities.jsonl"
        entity_row = json.loads((td / "entities.jsonl").read_text(encoding="utf-8"))
        assert entity_row["slug"] == "deepmind"
        assert entity_row["source_count"] == 1
        assert (td / "concepts.jsonl").read_text(encoding="utf-8") == ""

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

    def test_repairs_stale_rollup_when_note_already_matches(self, history_topic: Path) -> None:
        oldest = recovery.list_snapshots(history_topic, "rotational_embedding")[0]
        live = recovery.note_path_for_slug(history_topic, "rotational_embedding")
        assert live is not None
        live.write_bytes(oldest.path.read_bytes())
        snapshots_before = recovery.list_snapshots(history_topic, "rotational_embedding")

        result = recovery.rollback(
            history_topic,
            "rotational_embedding",
            oldest.iso,
            now_iso="2026-05-29T12:00:00Z",
        )

        assert result.changed is True
        assert result.backup_path is None
        rollup_path = result.rollup_path
        assert rollup_path is not None
        assert rollup_path == history_topic / "concepts.jsonl"
        assert recovery.list_snapshots(history_topic, "rotational_embedding") == snapshots_before
        row = json.loads(rollup_path.read_text(encoding="utf-8").splitlines()[0])
        assert row["source_count"] == 2
        assert row["helpful_evidence"] == [2, 2]

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


def test_safe_ts_to_iso_no_t_returns_unchanged():
    assert recovery.safe_ts_to_iso("2026-05-29") == "2026-05-29"


def test_is_safe_slug_rejects_bad():
    assert not recovery._is_safe_slug("")
    assert not recovery._is_safe_slug("a/b")
    assert not recovery._is_safe_slug("a\\b")
    assert not recovery._is_safe_slug("C:secret")
    assert not recovery._is_safe_slug(".")
    assert not recovery._is_safe_slug("..")
    assert not recovery._is_safe_slug("a\x00b")
    assert recovery._is_safe_slug("rotational_embedding")

"""Unit tests for distill.concepts.notes: rendering, .history versioning, mentions.jsonl."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from distill.concepts.notes import (
    already_extracted_source_ids,
    append_mentions,
    concept_dir_for_topic,
    entity_dir_for_topic,
    history_path_for,
    mentions_jsonl_path,
    note_path_for,
    read_mentions,
    render_playbook,
    write_playbook,
)
from distill.concepts.records import (
    ConceptKind,
    EvidenceInterval,
    MergedConcept,
    Polarity,
    SourceEvidence,
)


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

    def test_idempotent_on_unchanged_content(self, tmp_path: Path) -> None:
        c = _concept()
        write_playbook(tmp_path, c, now_iso="2026-05-15T14:30:00Z")
        _, changed = write_playbook(tmp_path, c, now_iso="2026-05-15T15:00:00Z")
        assert changed is False
        # No history entry should have been created on the second call
        history_dir = tmp_path / ".history" / "rotational_embeddings"
        assert not history_dir.exists()

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

        history_files = list((tmp_path / ".history" / "rotational_embeddings").iterdir())
        assert len(history_files) == 1
        assert history_files[0].read_text(encoding="utf-8") == prior_content

        # New file should reflect the new content
        new_content = path.read_text(encoding="utf-8")
        assert new_content != prior_content
        assert "[[new_Insights]]" in new_content


class TestMentionsJsonl:
    def test_path_resolution(self, tmp_path: Path) -> None:
        assert mentions_jsonl_path(tmp_path) == tmp_path / ".concepts" / "mentions.jsonl"

    def test_append_creates_file_and_writes_rows(self, tmp_path: Path) -> None:
        rows = [
            {"source_id": "A", "normalized_name": "x", "polarity": "helpful"},
            {"source_id": "B", "normalized_name": "x", "polarity": "harmful"},
        ]
        path = append_mentions(tmp_path, rows)
        assert path.exists()
        lines = path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 2
        assert json.loads(lines[0])["source_id"] == "A"

    def test_append_appends_does_not_overwrite(self, tmp_path: Path) -> None:
        append_mentions(tmp_path, [{"source_id": "A"}])
        append_mentions(tmp_path, [{"source_id": "B"}])
        rows = read_mentions(tmp_path)
        assert [r["source_id"] for r in rows] == ["A", "B"]

    def test_read_empty_when_missing(self, tmp_path: Path) -> None:
        assert read_mentions(tmp_path) == []

    def test_already_extracted_source_ids(self, tmp_path: Path) -> None:
        append_mentions(
            tmp_path,
            [
                {"source_id": "A", "normalized_name": "x"},
                {"source_id": "A", "normalized_name": "y"},  # same source, different concept
                {"source_id": "B", "normalized_name": "x"},
            ],
        )
        assert already_extracted_source_ids(tmp_path) == {"A", "B"}

    def test_read_skips_blank_lines(self, tmp_path: Path) -> None:
        path = mentions_jsonl_path(tmp_path)
        path.parent.mkdir(parents=True)
        path.write_text('{"source_id":"A"}\n\n  \n{"source_id":"B"}\n', encoding="utf-8")
        assert [r["source_id"] for r in read_mentions(tmp_path)] == ["A", "B"]

    def test_append_invalid_json_raises_on_read(self, tmp_path: Path) -> None:
        path = mentions_jsonl_path(tmp_path)
        path.parent.mkdir(parents=True)
        path.write_text("not json\n", encoding="utf-8")
        with pytest.raises(json.JSONDecodeError):
            read_mentions(tmp_path)

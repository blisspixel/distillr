"""Unit tests for distill.concepts.exports."""

from __future__ import annotations

import json
from pathlib import Path

from distill.concepts.exports import (
    concepts_jsonl_path,
    entities_jsonl_path,
    write_exports,
)
from distill.concepts.records import (
    ConceptKind,
    EvidenceInterval,
    MergedConcept,
    Polarity,
    SourceEvidence,
)


def _concept(
    name: str,
    kind: ConceptKind,
    *,
    contested: bool = False,
) -> MergedConcept:
    sources = (
        SourceEvidence(
            source_id="A",
            artifact_path=f"papers/{name}/a.md",
            polarity=Polarity.HELPFUL,
        ),
    )
    helpful = EvidenceInterval(1, 1)
    harmful = EvidenceInterval(1, 1) if contested else EvidenceInterval(0, 0)
    return MergedConcept(
        name=name,
        normalized_name=name.lower(),
        kind=kind,
        topic="t",
        sources=sources,
        helpful_evidence=helpful,
        harmful_evidence=harmful,
        first_seen="2026-04-12T10:00:00Z",
        last_seen="2026-05-15T14:30:00Z",
    )


class TestWriteExports:
    def test_routes_concepts_and_entities_separately(self, tmp_path: Path) -> None:
        merged = [
            _concept("technique_a", ConceptKind.TECHNIQUE),
            _concept("DeepMind", ConceptKind.ORGANIZATION),
            _concept("dataset_z", ConceptKind.DATASET),
        ]
        c_path, e_path = write_exports(tmp_path, merged)

        c_rows = [json.loads(line) for line in c_path.read_text(encoding="utf-8").splitlines()]
        e_rows = [json.loads(line) for line in e_path.read_text(encoding="utf-8").splitlines()]
        assert [r["name"] for r in c_rows] == ["dataset_z", "technique_a"]  # sorted by (kind, slug)
        assert [r["name"] for r in e_rows] == ["DeepMind"]

    def test_jsonl_row_has_scalar_derived_fields(self, tmp_path: Path) -> None:
        merged = [_concept("x", ConceptKind.TECHNIQUE)]
        c_path, _ = write_exports(tmp_path, merged)
        row = json.loads(c_path.read_text(encoding="utf-8").splitlines()[0])
        assert "helpful_count" in row
        assert "harmful_count" in row
        assert "contested" in row
        assert "helpful_evidence" in row

    def test_empty_input_produces_empty_files(self, tmp_path: Path) -> None:
        c_path, e_path = write_exports(tmp_path, [])
        assert c_path.exists()
        assert e_path.exists()
        assert c_path.read_text(encoding="utf-8") == ""
        assert e_path.read_text(encoding="utf-8") == ""

    def test_path_resolution(self, tmp_path: Path) -> None:
        assert concepts_jsonl_path(tmp_path) == tmp_path / "concepts.jsonl"
        assert entities_jsonl_path(tmp_path) == tmp_path / "entities.jsonl"

    def test_deterministic_output_under_input_reordering(self, tmp_path: Path) -> None:
        forward = [
            _concept("zebra", ConceptKind.TECHNIQUE),
            _concept("alpha", ConceptKind.TECHNIQUE),
            _concept("mango", ConceptKind.TECHNIQUE),
        ]
        c_forward, _ = write_exports(tmp_path / "f", forward)

        # Same concepts, different order -- output must be identical
        backward = list(reversed(forward))
        c_backward, _ = write_exports(tmp_path / "b", backward)

        assert c_forward.read_text(encoding="utf-8") == c_backward.read_text(encoding="utf-8")

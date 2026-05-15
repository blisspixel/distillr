"""Tests for distill.concepts.contradictions."""

from __future__ import annotations

import json
from pathlib import Path

from distill.concepts.contradictions import ContestedConcept, find_contested


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def _row(name: str, *, contested: bool, kind: str = "technique", source_count: int = 5) -> dict:
    return {
        "name": name,
        "slug": name.lower().replace(" ", "_"),
        "kind": kind,
        "topic": "tkg",
        "source_count": source_count,
        "helpful_count": 3 if contested else 5,
        "harmful_count": 2 if contested else 0,
        "contested": contested,
    }


class TestFindContested:
    def test_returns_empty_when_no_exports(self, tmp_path: Path) -> None:
        assert find_contested(tmp_path) == []

    def test_filters_to_contested_only(self, tmp_path: Path) -> None:
        _write_jsonl(
            tmp_path / "concepts.jsonl",
            [
                _row("contested one", contested=True),
                _row("uncontested", contested=False),
            ],
        )
        result = find_contested(tmp_path)
        assert [c.name for c in result] == ["contested one"]

    def test_sorts_by_source_count_desc_then_slug(self, tmp_path: Path) -> None:
        _write_jsonl(
            tmp_path / "concepts.jsonl",
            [
                _row("low_evidence", contested=True, source_count=4),
                _row("high_evidence", contested=True, source_count=10),
                _row("mid_evidence", contested=True, source_count=7),
            ],
        )
        result = find_contested(tmp_path)
        assert [c.name for c in result] == ["high_evidence", "mid_evidence", "low_evidence"]

    def test_combines_concepts_and_entities(self, tmp_path: Path) -> None:
        _write_jsonl(
            tmp_path / "concepts.jsonl",
            [_row("technique_one", contested=True, kind="technique", source_count=5)],
        )
        _write_jsonl(
            tmp_path / "entities.jsonl",
            [_row("openai", contested=True, kind="vendor", source_count=8)],
        )
        result = find_contested(tmp_path)
        # Vendor (entity) has more sources, sorts first
        assert [c.name for c in result] == ["openai", "technique_one"]
        assert result[0].is_entity is True
        assert result[1].is_entity is False

    def test_tolerates_malformed_lines(self, tmp_path: Path) -> None:
        path = tmp_path / "concepts.jsonl"
        path.write_text(
            json.dumps(_row("good", contested=True)) + "\nnot json\n",
            encoding="utf-8",
        )
        result = find_contested(tmp_path)
        assert len(result) == 1


class TestContestedConcept:
    def test_is_entity_for_vendor(self) -> None:
        c = ContestedConcept(
            name="x",
            slug="x",
            kind="vendor",
            topic="t",
            source_count=5,
            helpful_count=2,
            harmful_count=2,
        )
        assert c.is_entity is True

    def test_is_entity_false_for_technique(self) -> None:
        c = ContestedConcept(
            name="x",
            slug="x",
            kind="technique",
            topic="t",
            source_count=5,
            helpful_count=2,
            harmful_count=2,
        )
        assert c.is_entity is False

    def test_to_dict_round_trip_friendly(self) -> None:
        c = ContestedConcept(
            name="X",
            slug="x",
            kind="technique",
            topic="t",
            source_count=5,
            helpful_count=2,
            harmful_count=2,
        )
        d = c.to_dict()
        assert d["name"] == "X"
        assert d["is_entity"] is False

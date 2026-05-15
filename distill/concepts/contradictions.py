"""Surface contested concepts for ``distill health``.

A contested concept is one where the corpus has at least one source on
each side -- both helpful and harmful evidence are present. The merge
layer sets ``MergedConcept.contested`` to True under this condition;
this module is the read path that finds them by walking a topic dir's
``concepts.jsonl`` and ``entities.jsonl`` exports.

We read from the JSONL exports rather than parsing every concept .md
file: the JSONL files are written by the merge step and are guaranteed
in sync with the per-concept notes. Reading JSONL is also cheaper and
gives us scalar fields directly.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from distill.concepts.exports import concepts_jsonl_path, entities_jsonl_path

__all__ = ["ContestedConcept", "find_contested"]


@dataclass(frozen=True, slots=True)
class ContestedConcept:
    """Lightweight view of a contested concept for surfacing in health output."""

    name: str
    slug: str
    kind: str
    topic: str
    source_count: int
    helpful_count: int
    harmful_count: int

    @property
    def is_entity(self) -> bool:
        return self.kind in {"person", "organization", "vendor"}

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "slug": self.slug,
            "kind": self.kind,
            "topic": self.topic,
            "source_count": self.source_count,
            "helpful_count": self.helpful_count,
            "harmful_count": self.harmful_count,
            "is_entity": self.is_entity,
        }


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def find_contested(topic_dir: Path) -> list[ContestedConcept]:
    """Return every contested concept and entity for the topic.

    Sort order: source_count descending (most-evidence-having concepts
    surface first), then alphabetically by slug for ties. Stable order
    means health output diffs cleanly across runs.
    """
    rows = _read_jsonl(concepts_jsonl_path(topic_dir)) + _read_jsonl(entities_jsonl_path(topic_dir))
    contested = [r for r in rows if r.get("contested")]
    contested.sort(key=lambda r: (-r.get("source_count", 0), r.get("slug", "")))
    return [
        ContestedConcept(
            name=r.get("name", ""),
            slug=r.get("slug", ""),
            kind=r.get("kind", ""),
            topic=r.get("topic", ""),
            source_count=r.get("source_count", 0),
            helpful_count=r.get("helpful_count", 0),
            harmful_count=r.get("harmful_count", 0),
        )
        for r in contested
    ]

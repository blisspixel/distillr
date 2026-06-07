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
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        # Keep only object rows. A hand-edited or corrupted export line that is
        # valid JSON but a list/scalar (``[]``, ``true``) would otherwise crash
        # find_contested's ``r.get(...)`` with AttributeError.
        if isinstance(obj, dict):
            rows.append(obj)
    return rows


def find_contested(topic_dir: Path) -> list[ContestedConcept]:
    """Return every contested concept and entity for the topic.

    Sort order: source_count descending (most-evidence-having concepts
    surface first), then alphabetically by slug for ties. Stable order
    means health output diffs cleanly across runs.
    """
    rows = _read_jsonl(concepts_jsonl_path(topic_dir)) + _read_jsonl(entities_jsonl_path(topic_dir))
    contested = [r for r in rows if r.get("contested")]
    # Sort defensively: a malformed row with a non-numeric ``source_count`` must
    # not raise a TypeError from the unary-negate sort key.
    contested.sort(key=lambda r: (-_as_int(r.get("source_count")), str(r.get("slug", ""))))
    return [
        ContestedConcept(
            name=str(r.get("name", "")),
            slug=str(r.get("slug", "")),
            kind=str(r.get("kind", "")),
            topic=str(r.get("topic", "")),
            source_count=_as_int(r.get("source_count")),
            helpful_count=_as_int(r.get("helpful_count")),
            harmful_count=_as_int(r.get("harmful_count")),
        )
        for r in contested
    ]


def _as_int(value: object) -> int:
    """Coerce a JSONL scalar to int, defaulting to 0 on anything non-numeric."""
    if isinstance(value, bool):
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    return 0

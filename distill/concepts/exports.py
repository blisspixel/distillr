"""Project merged concepts into JSONL rollups for downstream consumers.

Per-topic ``concepts.jsonl`` and ``entities.jsonl`` are the structured-row
view of the playbook layer: one row per concept, with scalar derived
fields. Graph databases, dashboards, and external agents read these
directly instead of parsing every ``.md`` file.

Determinism: rows are sorted by ``(kind, slug)`` so re-running with the
same input produces byte-identical files. This matters for git diffs
when users commit their library; an unstable order would produce noise.
"""

# pyright: strict

from __future__ import annotations

import json
from pathlib import Path

from distill.concepts.records import MergedConcept

__all__ = ["concepts_jsonl_path", "entities_jsonl_path", "write_exports"]


def concepts_jsonl_path(topic_dir: Path) -> Path:
    return topic_dir / "concepts.jsonl"


def entities_jsonl_path(topic_dir: Path) -> Path:
    return topic_dir / "entities.jsonl"


def _sort_key(c: MergedConcept) -> tuple[str, str]:
    return (c.kind.value, c.slug)


def write_exports(
    topic_dir: Path,
    merged: list[MergedConcept],
) -> tuple[Path, Path]:
    """Write both rollup files; return their paths.

    Empty rollups still produce empty files. That way a downstream
    consumer can tell "topic exists but has no concepts yet" apart from
    "topic doesn't exist."
    """
    concepts = sorted([c for c in merged if not c.kind.is_entity], key=_sort_key)
    entities = sorted([c for c in merged if c.kind.is_entity], key=_sort_key)

    concepts_path = concepts_jsonl_path(topic_dir)
    entities_path = entities_jsonl_path(topic_dir)
    topic_dir.mkdir(parents=True, exist_ok=True)

    concepts_path.write_text(
        "".join(json.dumps(c.to_jsonl_row(), ensure_ascii=False) + "\n" for c in concepts),
        encoding="utf-8",
    )
    entities_path.write_text(
        "".join(json.dumps(c.to_jsonl_row(), ensure_ascii=False) + "\n" for c in entities),
        encoding="utf-8",
    )
    return concepts_path, entities_path

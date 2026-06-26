"""Shared discovery of per-source ``_Insights.md`` files under a topic.

Both the concept playbook layer (``distill.concepts``) and the claim layer
(``distill.claims``) walk a topic directory to find every source insight,
derive a stable ``source_id`` for each, and compute a topic-relative
artifact path for backlinks. That walk lived in ``concepts.pipeline``; it is
lifted here so the two layers share one implementation instead of drifting.

This module is foundational: it imports only ``distill.library.paths`` and
the standard library, so both higher layers can depend on it without an
upward import (enforced by the import-linter foundational-layer contract).
"""

# pyright: strict

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

__all__ = ["InsightRef", "derive_source_id", "discover_insights"]


# Top-level subdirectories under a topic that hold derived artifacts rather
# than source insights. Any dot-prefixed directory (``.history``, ``.concepts``,
# ``.claims``) is also skipped generically.
_SKIP_TOP_DIRS = {"concepts", "entities"}


@dataclass(frozen=True)
class InsightRef:
    """One discovered ``_Insights.md`` ready to extract from.

    Holds enough to populate a downstream record without re-walking the
    filesystem: the on-disk path, the stable ``source_id``, and the
    topic-relative ``artifact_path`` used for wiki-link backlinks.
    """

    path: Path
    source_id: str
    artifact_path: str


def derive_source_id(insight_path: Path) -> str:
    """Derive a stable source_id from an insight path.

    Prefers a canonical id from frontmatter (``paper_id`` / ``video_id`` /
    ``page_id`` / ``source_id``); falls back to the slug of the directory
    containing the ``_Insights.md``, which always works without a YAML parse.
    """
    from distill.library.paths import extract_frontmatter

    try:
        fm = extract_frontmatter(insight_path.read_text(encoding="utf-8"))
    except OSError:
        fm = {}
    for key in ("paper_id", "video_id", "page_id", "source_id"):
        if fm.get(key):
            return str(fm[key])
    return insight_path.parent.name


def discover_insights(topic_dir: Path) -> list[InsightRef]:
    """Find every ``_Insights.md`` under a topic dir, sorted for determinism.

    Sort order is the topic-relative path. Sorting matters because the order
    insights are processed influences the order of append-only log entries,
    which influences git diffs; determinism keeps those stable across runs.

    Derived-artifact subtrees (``concepts/``, ``entities/``) and any
    dot-prefixed directory (``.history``, ``.concepts``, ``.claims``) are
    skipped so only true source insights are returned.
    """
    if not topic_dir.exists():
        return []
    refs: list[InsightRef] = []
    for path in sorted(topic_dir.rglob("*_Insights.md")):
        rel = path.relative_to(topic_dir)
        top = rel.parts[0]
        if top in _SKIP_TOP_DIRS or top.startswith("."):
            continue
        refs.append(
            InsightRef(
                path=path,
                source_id=derive_source_id(path),
                artifact_path=str(rel).replace("\\", "/"),
            )
        )
    return refs

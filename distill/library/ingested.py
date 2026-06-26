"""Already-ingested source identities for a topic.

Discovery flows (``discover``, ``papers``) drop candidates the topic already
contains so rerank slots and ingest spend go to new material, and so
gap-driven re-discovery converges instead of re-suggesting the corpus back at
the user (the documented dogfood failure: identical previews kept offering
already-ingested videos).

This module is foundational: it imports only ``distill.library.insights`` and
the standard library, per the import-linter foundational-layer contract.
"""

# pyright: strict

from __future__ import annotations

import re
from pathlib import Path

__all__ = ["ingested_source_ids", "normalize_arxiv_id"]

# arXiv identifiers with an optional version suffix: new-style ``2604.11544v2``
# and old-style ``cs/0123456v1``. Group 1 is the versionless id.
_ARXIV_ID_RE = re.compile(r"^((?:\d{4}\.\d{4,5})|(?:[a-z][a-z.\-]*/\d{7}))(v\d+)?$", re.IGNORECASE)


def normalize_arxiv_id(identifier: str) -> str:
    """Canonicalize an arXiv id for identity comparison.

    Strips the version suffix (``2604.11544v2`` -> ``2604.11544``) so a paper
    ingested at v1 still matches when a later search returns v2. Anything that
    is not arXiv-shaped passes through unchanged -- YouTube video ids are
    case-sensitive, so there is deliberately no blanket lowercasing.
    """
    match = _ARXIV_ID_RE.match(identifier.strip())
    return match.group(1) if match else identifier.strip()


def ingested_source_ids(topic_dir: Path) -> frozenset[str]:
    """Return every source identity already ingested under *topic_dir*.

    Identities come from each ``_Insights.md``'s frontmatter (``paper_id`` /
    ``video_id`` / ``page_id`` / ``source_id``, via ``derive_source_id``).
    arXiv-shaped ids are included both raw and version-stripped so candidate
    matching works with either form. Missing topic dirs yield an empty set.
    """
    from distill.library.insights import discover_insights

    ids: set[str] = set()
    for ref in discover_insights(topic_dir):
        ids.add(ref.source_id)
        normalized = normalize_arxiv_id(ref.source_id)
        if normalized != ref.source_id:
            ids.add(normalized)
    return frozenset(ids)

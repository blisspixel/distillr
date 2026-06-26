"""Near-duplicate insight detection (deterministic, embedding-free).

The same announcement covered by a video, a newsletter, and a vendor page
produces three insights that say largely the same thing; left invisible,
they triple-weight one event in synthesis. Detection is token-shingle
Jaccard -- deterministic, free, and explainable ("these two share 71% of
their 5-word phrases") -- in keeping with the no-database invariant: no
embeddings, no index, just a pairwise pass over the topic's insights at
audit time.

Artifact-preserving by design (per the roadmap note): nothing is deleted or
merged. The audit *surfaces* duplicate groups; the human (or the synthesis
prompt, which already attributes source origin) decides what they mean --
three outlets repeating one press release is itself a signal.
"""

# pyright: strict

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from distill.library.insights import discover_insights
from distill.library.paths import strip_frontmatter

__all__ = ["DuplicateGroup", "collect_near_duplicates", "shingle_similarity"]

_SHINGLE_SIZE = 5
_SIMILARITY_THRESHOLD = 0.55
_MIN_TOKENS = 40  # short stubs pair-match trivially; skip them
_WORD_RE = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class DuplicateGroup:
    """A set of insights whose bodies substantially overlap."""

    paths: list[str]  # artifact paths, sorted
    similarity: float  # the max pairwise Jaccard that formed the group
    members: int = field(init=False, default=0)

    def __post_init__(self):
        object.__setattr__(self, "members", len(self.paths))


def _shingles(text: str) -> frozenset[str]:
    """Lowercased ``_SHINGLE_SIZE``-token shingles of the body text."""
    tokens = _WORD_RE.findall(text.lower())
    if len(tokens) < _MIN_TOKENS:
        return frozenset()
    return frozenset(
        " ".join(tokens[i : i + _SHINGLE_SIZE]) for i in range(len(tokens) - _SHINGLE_SIZE + 1)
    )


def shingle_similarity(a: str, b: str) -> float:
    """Jaccard similarity of two texts' shingle sets (0.0 when either is a stub)."""
    sa, sb = _shingles(a), _shingles(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def _load_shingled_docs(topic_dir: Path) -> list[tuple[str, frozenset[str]]]:
    """Read each insight once and shingle it; stubs and unreadables drop out."""
    docs: list[tuple[str, frozenset[str]]] = []
    for ref in discover_insights(topic_dir):
        try:
            body = strip_frontmatter(ref.path.read_text(encoding="utf-8"))
        except OSError:
            continue
        shingles = _shingles(body)
        if shingles:
            docs.append((ref.artifact_path, shingles))
    return docs


def _cluster_similar(
    docs: list[tuple[str, frozenset[str]]], threshold: float
) -> tuple[list[int], dict[int, float]]:
    """Union-find over above-threshold pairs; returns per-doc root + best score per root."""
    parent = list(range(len(docs)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    pair_score: dict[int, float] = {}
    for i in range(len(docs)):
        for j in range(i + 1, len(docs)):
            sa, sb = docs[i][1], docs[j][1]
            score = len(sa & sb) / len(sa | sb)
            if score < threshold:
                continue
            ri, rj = find(i), find(j)
            if ri != rj:
                parent[rj] = ri
                # Carry the absorbed root's best score into the survivor.
                pair_score[ri] = max(pair_score.get(ri, 0.0), pair_score.pop(rj, 0.0), score)
            else:
                pair_score[ri] = max(pair_score.get(ri, 0.0), score)
    return [find(i) for i in range(len(docs))], pair_score


def collect_near_duplicates(
    topic_dir: Path, *, threshold: float = _SIMILARITY_THRESHOLD
) -> list[DuplicateGroup]:
    """Pairwise shingle comparison across a topic's insights, grouped.

    Quadratic in insight count, which is fine at topic scale (tens to low
    hundreds); shingle sets are computed once per document. Union-find
    grouping so A~B and B~C land in one group even when A~C alone misses
    the threshold.
    """
    docs = _load_shingled_docs(topic_dir)
    roots, pair_score = _cluster_similar(docs, threshold)

    clusters: dict[int, list[str]] = {}
    for i, (path, _) in enumerate(docs):
        clusters.setdefault(roots[i], []).append(path)

    return sorted(
        (
            DuplicateGroup(paths=sorted(paths), similarity=round(pair_score.get(root, 0.0), 3))
            for root, paths in clusters.items()
            if len(paths) > 1
        ),
        key=lambda g: -g.similarity,
    )

"""Near-duplicate insight detection (deterministic, embedding-free).

The same announcement covered by a video, a newsletter, and a vendor page
produces three insights that say largely the same thing; left invisible,
they triple-weight one event in synthesis. Detection is token-shingle
Jaccard -- deterministic, free, and explainable ("these two share 71% of
their 5-word phrases") -- in keeping with the no-database invariant. An
ephemeral in-memory rare-first prefix index removes impossible candidates at
audit time; no index is persisted, and exact Jaccard remains authoritative.

Artifact-preserving by design (per the roadmap note): nothing is deleted or
merged. The audit *surfaces* duplicate groups; the human (or the synthesis
prompt, which already attributes source origin) decides what they mean --
three outlets repeating one press release is itself a signal.
"""

# pyright: strict

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from collections.abc import Iterator
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


def _exhaustive_candidate_pairs(doc_count: int) -> Iterator[tuple[int, int]]:
    """Yield every document pair in the legacy ``i`` then ``j`` order."""
    for i in range(doc_count):
        for j in range(i + 1, doc_count):
            yield i, j


def _conservative_prefix_length(size: int, threshold: float) -> int:
    """Return an over-approximating Jaccard prefix length.

    The textbook length is ``size - ceil(threshold * size) + 1``. Moving the
    floating-point product one representable value downward and using ``floor``
    deliberately keeps the prefix at least one token longer. The extra
    candidates are harmless because exact Jaccard remains the arbiter; a prefix
    that is too short could hide a threshold-edge match through rounding.
    """
    conservative_product = math.nextafter(threshold * size, -math.inf)
    return min(size, size - math.floor(conservative_product) + 1)


def _indexed_candidate_pairs(
    docs: list[tuple[str, frozenset[str]]], threshold: float
) -> Iterator[tuple[int, int]]:
    """Yield a conservative exact-Jaccard candidate superset.

    All documents use the same global shingle order: rare shingles first, then
    lexical order for deterministic ties. For positive Jaccard thresholds, two
    qualifying sets must share a token in their threshold prefix. Prefix hits
    only nominate candidates; callers still calculate exact Jaccard.

    Candidate sets are built one left-hand document at a time and emitted in
    the legacy ``i`` then ``j`` traversal order. That order preserves even the
    private union-find root behavior without retaining all corpus pairs.
    """
    frequencies = Counter(shingle for _, shingles in docs for shingle in shingles)
    rank = {
        shingle: position
        for position, shingle in enumerate(
            sorted(frequencies, key=lambda item: (frequencies[item], item))
        )
    }
    prefixes: list[tuple[str, ...]] = []
    for _, shingles in docs:
        ordered = sorted(shingles, key=rank.__getitem__)
        prefix_length = _conservative_prefix_length(len(ordered), threshold)
        prefixes.append(tuple(ordered[:prefix_length]))

    postings: defaultdict[str, list[int]] = defaultdict(list)
    for index, prefix in enumerate(prefixes):
        for shingle in prefix:
            postings[shingle].append(index)

    for left, prefix in enumerate(prefixes):
        candidates: set[int] = set()
        for shingle in prefix:
            candidates.update(right for right in postings[shingle] if right > left)
        for right in sorted(candidates):
            yield left, right


def _candidate_pairs(
    docs: list[tuple[str, frozenset[str]]], threshold: float
) -> Iterator[tuple[int, int]]:
    """Choose the exact indexed path or a compatibility fallback."""
    if len(docs) < 2:
        return

    # The loaded corpus never contains empty shingle sets. Preserve the private
    # helper's legacy divide-by-zero behavior for synthetic/internal callers
    # instead of letting indexing silently skip an invalid empty/empty pair.
    if any(not shingles for _, shingles in docs):
        yield from _exhaustive_candidate_pairs(len(docs))
        return

    # Legacy comparison semantics make every pair qualify for non-positive or
    # NaN thresholds. Positive thresholds above one can match no Jaccard score.
    # These branches also keep the indexed prefix arithmetic inside (0, 1].
    if isinstance(threshold, float) and math.isnan(threshold):
        yield from _exhaustive_candidate_pairs(len(docs))
        return
    if threshold <= 0.0:
        yield from _exhaustive_candidate_pairs(len(docs))
        return
    if threshold > 1.0:
        return
    yield from _indexed_candidate_pairs(docs, threshold)


def _cluster_similar(
    docs: list[tuple[str, frozenset[str]]], threshold: float
) -> tuple[list[int], dict[int, float]]:
    """Union-find over exact above-threshold pairs.

    Positive thresholds use conservative prefix candidates. Exact Jaccard is
    still calculated here, so indexing cannot promote a false match.
    """
    parent = list(range(len(docs)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    pair_score: dict[int, float] = {}
    for i, j in _candidate_pairs(docs, threshold):
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
    """Exact shingle comparison across a topic's insights, grouped.

    A rare-first prefix index removes pairs that cannot clear the threshold;
    every candidate is still verified with exact Jaccard. Union-find grouping
    keeps A~B and B~C in one group even when A~C alone misses the threshold.
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

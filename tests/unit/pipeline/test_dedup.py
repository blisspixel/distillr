"""Tests for near-duplicate insight detection (shingle Jaccard, union-find groups)."""

from __future__ import annotations

import math
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from distill.pipeline import dedup as dedup_module
from distill.pipeline.dedup import collect_near_duplicates, shingle_similarity

_BASE = (
    "The vendor announced a new agent runtime with checkpoint support and a "
    "pricing change effective next quarter. Early benchmarks show a thirty "
    "percent latency reduction on long-context workloads, and the migration "
    "path requires no code changes for existing deployments according to the "
    "launch blog post and the accompanying technical documentation pages."
)


def _insight(topic_dir: Path, name: str, body: str) -> None:
    d = topic_dir / "sites" / name
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}_Insights.md").write_text(f"---\ntitle: {name}\n---\n\n{body}\n", encoding="utf-8")


def _oracle_cluster_similar(
    docs: list[tuple[str, frozenset[str]]], threshold: float
) -> tuple[list[int], dict[int, float]]:
    """The pre-index exhaustive implementation, retained only as a test oracle."""
    parent = list(range(len(docs)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    pair_score: dict[int, float] = {}
    for i in range(len(docs)):
        for j in range(i + 1, len(docs)):
            left, right = docs[i][1], docs[j][1]
            score = len(left & right) / len(left | right)
            if score < threshold:
                continue
            left_root, right_root = find(i), find(j)
            if left_root != right_root:
                parent[right_root] = left_root
                pair_score[left_root] = max(
                    pair_score.get(left_root, 0.0),
                    pair_score.pop(right_root, 0.0),
                    score,
                )
            else:
                pair_score[left_root] = max(pair_score.get(left_root, 0.0), score)
    return [find(i) for i in range(len(docs))], pair_score


_SHINGLE_SET = st.frozensets(
    st.integers(min_value=0, max_value=30).map(lambda value: f"token-{value}"),
    min_size=1,
    max_size=12,
)
_THRESHOLDS = st.one_of(
    st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    st.sampled_from(
        [
            -math.inf,
            -1.0,
            0.0,
            math.nextafter(0.0, 1.0),
            0.25,
            0.5,
            0.55,
            math.nextafter(0.55, 0.0),
            math.nextafter(0.55, 1.0),
            1.0,
            math.nextafter(1.0, math.inf),
            math.inf,
            math.nan,
        ]
    ),
)
_POSITIVE_THRESHOLDS = st.floats(
    min_value=math.nextafter(0.0, 1.0),
    max_value=1.0,
    allow_nan=False,
    allow_infinity=False,
)


class TestShingleSimilarity:
    def test_identical_is_one(self):
        assert shingle_similarity(_BASE, _BASE) == 1.0

    def test_unrelated_is_near_zero(self):
        other = (
            "Quarterly hurricane forecasts improved when ensemble members were "
            "weighted by sea-surface temperature anomalies, a meteorological "
            "result with no relation to software, runtimes, or pricing at all. "
            "The study covered four decades of Atlantic storm-track records and "
            "validated against reanalysis data from two independent archives."
        )
        assert shingle_similarity(_BASE, other) < 0.05

    def test_short_stubs_never_match(self):
        assert shingle_similarity("too short to mean anything", "too short to mean anything") == 0.0


class TestCollectNearDuplicates:
    def test_near_duplicates_grouped(self, tmp_path):
        topic = tmp_path / "t"
        # Same press release, lightly reworded tail -> high overlap.
        _insight(topic, "video-coverage", _BASE + " The host walked through the demo flow.")
        _insight(topic, "newsletter-coverage", _BASE + " The author added brief commentary.")
        _insight(
            topic,
            "unrelated",
            "Entirely different subject matter about marine biology and reef restoration "
            "methods using coral fragment seeding across twelve experimental sites with "
            "survival tracked over five years against a control lagoon, plus genetic "
            "diversity sampling from donor colonies and temperature-stress assays.",
        )

        groups = collect_near_duplicates(topic)

        assert len(groups) == 1
        assert groups[0].members == 2
        assert groups[0].similarity > 0.55
        assert all("coverage" in p for p in groups[0].paths)

    def test_transitive_grouping(self, tmp_path):
        topic = tmp_path / "t"
        _insight(topic, "a", _BASE + " extra alpha sentence one here now.")
        _insight(topic, "b", _BASE)
        _insight(topic, "c", _BASE + " different beta closing line entirely instead.")

        groups = collect_near_duplicates(topic)

        assert len(groups) == 1
        assert groups[0].members == 3

    def test_empty_and_distinct_topics(self, tmp_path):
        assert collect_near_duplicates(tmp_path / "none") == []


@settings(max_examples=250, deadline=None)
@given(shingle_sets=st.lists(_SHINGLE_SET, min_size=0, max_size=12), threshold=_THRESHOLDS)
def test_indexed_clustering_matches_exhaustive_oracle(
    shingle_sets: list[frozenset[str]], threshold: float
) -> None:
    docs = [(f"doc-{index}", shingles) for index, shingles in enumerate(shingle_sets)]

    assert dedup_module._cluster_similar(docs, threshold) == _oracle_cluster_similar(
        docs, threshold
    )


@settings(max_examples=300, deadline=None)
@given(
    shingle_sets=st.lists(_SHINGLE_SET, min_size=2, max_size=12),
    threshold=_POSITIVE_THRESHOLDS,
)
def test_prefix_candidates_include_every_qualifying_pair(
    shingle_sets: list[frozenset[str]], threshold: float
) -> None:
    docs = [(f"doc-{index}", shingles) for index, shingles in enumerate(shingle_sets)]
    candidates = set(dedup_module._indexed_candidate_pairs(docs, threshold))
    qualifying = {
        (left, right)
        for left in range(len(docs))
        for right in range(left + 1, len(docs))
        if len(docs[left][1] & docs[right][1]) / len(docs[left][1] | docs[right][1]) >= threshold
    }

    assert qualifying <= candidates


@pytest.mark.parametrize(
    ("threshold", "expected_roots", "expected_scores"),
    [
        (-math.inf, [0, 0, 0], {0: 0.5}),
        (-1.0, [0, 0, 0], {0: 0.5}),
        (0.0, [0, 0, 0], {0: 0.5}),
        (math.nan, [0, 0, 0], {0: 0.5}),
        (0.5, [0, 0, 2], {0: 0.5}),
        (math.nextafter(0.5, math.inf), [0, 1, 2], {}),
        (1.0, [0, 1, 2], {}),
        (math.nextafter(1.0, math.inf), [0, 1, 2], {}),
        (math.inf, [0, 1, 2], {}),
    ],
)
def test_threshold_edges_preserve_exhaustive_behavior(
    threshold: float,
    expected_roots: list[int],
    expected_scores: dict[int, float],
) -> None:
    docs = [
        ("a", frozenset({"a", "b"})),
        ("b", frozenset({"a", "b", "c", "d"})),
        ("c", frozenset({"x", "y"})),
    ]

    roots, scores = dedup_module._cluster_similar(docs, threshold)

    assert roots == expected_roots
    assert scores == expected_scores


def test_identical_sets_match_at_one() -> None:
    docs = [
        ("a", frozenset({"rare", "shared", "tokens"})),
        ("b", frozenset({"rare", "shared", "tokens"})),
        ("c", frozenset({"rare", "shared", "other"})),
    ]

    roots, scores = dedup_module._cluster_similar(docs, 1.0)

    assert roots == [0, 0, 2]
    assert scores == {0: 1.0}


def test_empty_internal_sets_retain_exhaustive_division_error() -> None:
    docs = [("a", frozenset()), ("b", frozenset())]

    with pytest.raises(ZeroDivisionError):
        dedup_module._cluster_similar(docs, 0.55)


def test_rare_prefix_index_reduces_structural_candidates() -> None:
    docs: list[tuple[str, frozenset[str]]] = []
    duplicate_pairs = 10
    for pair in range(duplicate_pairs):
        shingles = frozenset(f"duplicate-{pair}-token-{token}" for token in range(40))
        docs.extend(
            [
                (f"duplicate-{pair}-a", shingles),
                (f"duplicate-{pair}-b", shingles),
            ]
        )
    for index in range(180):
        docs.append(
            (
                f"unique-{index}",
                frozenset(f"unique-{index}-token-{token}" for token in range(40)),
            )
        )

    candidates = list(dedup_module._indexed_candidate_pairs(docs, 0.55))
    exhaustive_pairs = len(docs) * (len(docs) - 1) // 2

    assert len(docs) == 200
    assert candidates == [(pair * 2, pair * 2 + 1) for pair in range(duplicate_pairs)]
    assert len(candidates) == 10
    assert exhaustive_pairs == 19_900

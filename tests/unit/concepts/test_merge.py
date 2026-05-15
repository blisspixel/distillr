"""Unit + property tests for distill.concepts.merge.

The merge layer is the critical pure-Python core of the 0.8 release.
These tests enforce the invariants that make the playbook layer work:

1. Commutativity: same mentions in any order produce the same MergedConcept.
2. Idempotency: re-merging an already-merged set produces the same result.
3. Monotonic widening: adding a mention never narrows an evidence interval.
4. Polarity projection: helpful_lower == helpful_count, neutrals widen uppers.
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from distill.concepts.merge import build_all, build_merged_concept
from distill.concepts.normalize import group_mentions
from distill.concepts.records import (
    ConceptKind,
    ConceptMention,
    EvidenceInterval,
    MergedConcept,
    Polarity,
)

# ---- helpers ----------------------------------------------------------------


def _mention(
    *,
    source: str,
    name: str = "rotational embedding",
    polarity: Polarity = Polarity.HELPFUL,
    kind: ConceptKind = ConceptKind.TECHNIQUE,
    extracted_at: str = "2026-05-15T00:00:00Z",
    surface: str | None = None,
) -> ConceptMention:
    return ConceptMention(
        name=surface or name,
        normalized_name=name,
        kind=kind,
        polarity=polarity,
        source_id=source,
        artifact_path=f"papers/{source}/p.md",
        extracted_at=extracted_at,
    )


def _make_merge_input(mentions: list[ConceptMention]) -> tuple[str, list[ConceptMention]]:
    grouped = group_mentions(mentions)
    canonical = next(iter(grouped))
    return canonical, grouped[canonical]


# ---- unit -------------------------------------------------------------------


class TestBuildMergedConcept:
    def test_rejects_empty_mention_list(self) -> None:
        with pytest.raises(ValueError):
            build_merged_concept("x", [], topic="t")

    def test_all_helpful_no_neutral(self) -> None:
        mentions = [
            _mention(source="A", polarity=Polarity.HELPFUL),
            _mention(source="B", polarity=Polarity.HELPFUL),
            _mention(source="C", polarity=Polarity.HELPFUL),
        ]
        canonical, grouped = _make_merge_input(mentions)
        m = build_merged_concept(canonical, grouped, topic="tkg")
        assert m.helpful_evidence == EvidenceInterval(3, 3)
        assert m.harmful_evidence == EvidenceInterval(0, 0)
        assert m.contested is False

    def test_neutrals_widen_both_uppers(self) -> None:
        mentions = [
            _mention(source="A", polarity=Polarity.HELPFUL),
            _mention(source="B", polarity=Polarity.NEUTRAL),
            _mention(source="C", polarity=Polarity.NEUTRAL),
        ]
        canonical, grouped = _make_merge_input(mentions)
        m = build_merged_concept(canonical, grouped, topic="tkg")
        # helpful: 1 unambiguous + 2 neutrals widen upper to 3
        assert m.helpful_evidence == EvidenceInterval(1, 3)
        # harmful: 0 unambiguous + 2 neutrals widen upper to 2
        assert m.harmful_evidence == EvidenceInterval(0, 2)
        assert m.contested is True

    def test_mixed_polarity_is_contested(self) -> None:
        mentions = [
            _mention(source="A", polarity=Polarity.HELPFUL),
            _mention(source="B", polarity=Polarity.HARMFUL),
            _mention(source="C", polarity=Polarity.HELPFUL),
        ]
        canonical, grouped = _make_merge_input(mentions)
        m = build_merged_concept(canonical, grouped, topic="tkg")
        assert m.helpful_evidence == EvidenceInterval(2, 2)
        assert m.harmful_evidence == EvidenceInterval(1, 1)
        assert m.contested is True

    def test_display_name_picks_longest(self) -> None:
        mentions = [
            _mention(source="A", surface="rot", name="rotational embedding"),
            _mention(source="B", surface="Rotational Embeddings", name="rotational embedding"),
            _mention(source="C", surface="rot emb", name="rotational embedding"),
        ]
        canonical, grouped = _make_merge_input(mentions)
        m = build_merged_concept(canonical, grouped, topic="tkg")
        assert m.name == "Rotational Embeddings"

    def test_kind_is_majority_vote(self) -> None:
        mentions = [
            _mention(source="A", kind=ConceptKind.TECHNIQUE),
            _mention(source="B", kind=ConceptKind.TECHNIQUE),
            _mention(source="C", kind=ConceptKind.ARCHITECTURE),
        ]
        canonical, grouped = _make_merge_input(mentions)
        m = build_merged_concept(canonical, grouped, topic="tkg")
        assert m.kind == ConceptKind.TECHNIQUE

    def test_kind_tie_break_is_stable(self) -> None:
        mentions = [
            _mention(source="A", kind=ConceptKind.ARCHITECTURE),
            _mention(source="B", kind=ConceptKind.TECHNIQUE),
        ]
        canonical, grouped = _make_merge_input(mentions)
        m1 = build_merged_concept(canonical, grouped, topic="tkg")
        m2 = build_merged_concept(canonical, list(reversed(grouped)), topic="tkg")
        # Tie -> lex sort: "architecture" < "technique"
        assert m1.kind == m2.kind == ConceptKind.ARCHITECTURE

    def test_first_and_last_seen_from_extracted_at(self) -> None:
        mentions = [
            _mention(source="A", extracted_at="2026-04-12T00:00:00Z"),
            _mention(source="B", extracted_at="2026-05-15T00:00:00Z"),
            _mention(source="C", extracted_at="2026-04-30T00:00:00Z"),
        ]
        canonical, grouped = _make_merge_input(mentions)
        m = build_merged_concept(canonical, grouped, topic="tkg")
        assert m.first_seen == "2026-04-12T00:00:00Z"
        assert m.last_seen == "2026-05-15T00:00:00Z"

    def test_provenance_stored(self) -> None:
        mentions = [_mention(source="A")]
        canonical, grouped = _make_merge_input(mentions)
        m = build_merged_concept(
            canonical,
            grouped,
            topic="t",
            provenance={"model": "grok-4.3", "prompt_id": "concepts.extract.v1"},
        )
        assert m.provenance["model"] == "grok-4.3"
        assert m.provenance["prompt_id"] == "concepts.extract.v1"

    def test_topic_passed_through(self) -> None:
        mentions = [_mention(source="A")]
        canonical, grouped = _make_merge_input(mentions)
        m = build_merged_concept(canonical, grouped, topic="my-topic")
        assert m.topic == "my-topic"


class TestBuildAll:
    def test_preserves_grouping_order(self) -> None:
        mentions = [
            _mention(source="A", name="alpha"),
            _mention(source="B", name="zebra"),
            _mention(source="C", name="mango"),
            _mention(source="D", name="zebra"),
            _mention(source="E", name="alpha"),
            _mention(source="F", name="mango"),
        ]
        grouped = group_mentions(mentions)
        merged = build_all(grouped.items(), topic="t")
        names = [m.normalized_name for m in merged]
        # Alpha, mango, zebra (sorted by normalize) -- not in original order
        assert names == ["alpha", "mango", "zebra"]


# ---- property tests --------------------------------------------------------


polarities = st.sampled_from([Polarity.HELPFUL, Polarity.HARMFUL, Polarity.NEUTRAL])
source_ids = st.sampled_from(["A", "B", "C", "D", "E", "F", "G", "H"])
concept_names = st.sampled_from(["alpha concept", "beta concept", "gamma concept"])


def _mention_from_tuple(t: tuple[str, str, Polarity, int]) -> ConceptMention:
    source, name, polarity, day = t
    return ConceptMention(
        name=name,
        normalized_name=name,
        kind=ConceptKind.TECHNIQUE,
        polarity=polarity,
        source_id=source,
        artifact_path=f"papers/{source}/p.md",
        extracted_at=f"2026-05-{(day % 28) + 1:02d}T00:00:00Z",
    )


mention_tuples = st.tuples(
    source_ids,
    concept_names,
    polarities,
    st.integers(min_value=0, max_value=27),
)


def mention_set(min_size: int = 1, max_size: int = 12) -> st.SearchStrategy[list[ConceptMention]]:
    """Generate a list of mentions across a small fixed universe of sources + names."""
    return st.lists(mention_tuples, min_size=min_size, max_size=max_size).map(
        lambda ts: [_mention_from_tuple(t) for t in ts]
    )


def _merge_all(mentions: list[ConceptMention]) -> list[MergedConcept]:
    return build_all(group_mentions(mentions).items(), topic="t")


class TestMergeInvariants:
    @given(mentions=mention_set(1, 12))
    @settings(max_examples=200)
    def test_commutative_under_source_ordering(
        self,
        mentions: list[ConceptMention],
    ) -> None:
        forward = _merge_all(mentions)
        backward = _merge_all(list(reversed(mentions)))
        # By-canonical equality. Compare on the fields we promise to keep stable.
        a = {m.normalized_name: m for m in forward}
        b = {m.normalized_name: m for m in backward}
        assert set(a) == set(b)
        for k, m_a in a.items():
            m_b = b[k]
            assert m_a.helpful_evidence == m_b.helpful_evidence
            assert m_a.harmful_evidence == m_b.harmful_evidence
            assert m_a.source_count == m_b.source_count
            assert {s.source_id for s in m_a.sources} == {s.source_id for s in m_b.sources}
            assert m_a.kind == m_b.kind

    @given(mentions=mention_set(1, 12))
    @settings(max_examples=200)
    def test_idempotent_under_duplicate_mentions(
        self,
        mentions: list[ConceptMention],
    ) -> None:
        once = _merge_all(mentions)
        twice = _merge_all(mentions + mentions)
        # Dedup at normalize: same (source_id, canonical) collapses
        a = {m.normalized_name: m for m in once}
        b = {m.normalized_name: m for m in twice}
        assert set(a) == set(b)
        for k in a:
            assert a[k].helpful_evidence == b[k].helpful_evidence
            assert a[k].harmful_evidence == b[k].harmful_evidence
            assert a[k].source_count == b[k].source_count

    @given(
        base=mention_set(1, 8),
        extra=mention_set(1, 4),
    )
    @settings(max_examples=200)
    def test_monotonic_widening_for_new_sources(
        self,
        base: list[ConceptMention],
        extra: list[ConceptMention],
    ) -> None:
        """Adding mentions from *new* source ids never narrows an existing concept's intervals.

        The "only new sources" qualifier matters: when extra adds a
        conflicting polarity from an existing source, the per-source
        aggregation in normalize collapses that source to NEUTRAL,
        which can shift its contribution from the lower to the upper
        bound. That is the credal-interval-correct behavior (the source
        is now ambiguous), but it means strict monotonicity holds only
        when refresh introduces fresh sources -- which is the realistic
        refresh scenario in production. Conflict-on-the-same-source is
        a re-extraction artifact and is covered by the commutativity
        test instead.
        """
        base_sources = {m.source_id for m in base}
        extra_filtered = [m for m in extra if m.source_id not in base_sources]
        before = {m.normalized_name: m for m in _merge_all(base)}
        after = {m.normalized_name: m for m in _merge_all(base + extra_filtered)}
        for canonical, m_before in before.items():
            if canonical not in after:
                continue
            m_after = after[canonical]
            assert m_after.helpful_evidence.lower >= m_before.helpful_evidence.lower
            assert m_after.helpful_evidence.upper >= m_before.helpful_evidence.upper
            assert m_after.harmful_evidence.lower >= m_before.harmful_evidence.lower
            assert m_after.harmful_evidence.upper >= m_before.harmful_evidence.upper

    @given(mentions=mention_set(1, 12))
    @settings(max_examples=200)
    def test_evidence_bounds_invariant(
        self,
        mentions: list[ConceptMention],
    ) -> None:
        for m in _merge_all(mentions):
            assert m.helpful_evidence.lower <= m.helpful_evidence.upper
            assert m.harmful_evidence.lower <= m.harmful_evidence.upper
            # Lower bounds match unambiguous polarity counts
            helpful_lower = sum(1 for s in m.sources if s.polarity == Polarity.HELPFUL)
            harmful_lower = sum(1 for s in m.sources if s.polarity == Polarity.HARMFUL)
            assert m.helpful_evidence.lower == helpful_lower
            assert m.harmful_evidence.lower == harmful_lower
            # Upper bounds = lower + neutral count
            neutrals = sum(1 for s in m.sources if s.polarity == Polarity.NEUTRAL)
            assert m.helpful_evidence.upper == helpful_lower + neutrals
            assert m.harmful_evidence.upper == harmful_lower + neutrals

    @given(mentions=mention_set(1, 12))
    @settings(max_examples=200)
    def test_contested_iff_both_uppers_positive(
        self,
        mentions: list[ConceptMention],
    ) -> None:
        for m in _merge_all(mentions):
            expected = m.helpful_evidence.upper > 0 and m.harmful_evidence.upper > 0
            assert m.contested == expected

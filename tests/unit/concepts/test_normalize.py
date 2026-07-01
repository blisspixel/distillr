"""Unit + property tests for distill.concepts.normalize."""

from __future__ import annotations

from collections import OrderedDict

from hypothesis import example, given, settings
from hypothesis import strategies as st

from distill.concepts.normalize import (
    DEFAULT_SOURCE_THRESHOLD,
    canonicalize,
    filter_by_threshold,
    group_mentions,
)
from distill.concepts.records import ConceptKind, ConceptMention, Polarity


def _mention(
    *,
    source: str,
    name: str,
    polarity: Polarity = Polarity.HELPFUL,
    extracted_at: str = "2026-05-15T00:00:00Z",
) -> ConceptMention:
    return ConceptMention(
        name=name,
        normalized_name=name,
        kind=ConceptKind.TECHNIQUE,
        polarity=polarity,
        source_id=source,
        artifact_path=f"papers/{source}/p.md",
        extracted_at=extracted_at,
    )


class TestCanonicalize:
    def test_empty(self) -> None:
        assert canonicalize("") == ""

    def test_lowercases(self) -> None:
        assert canonicalize("ROTATIONAL EMBEDDINGS") == "rotational embedding"

    def test_strips_whitespace(self) -> None:
        assert canonicalize("   rotational embeddings   ") == "rotational embedding"

    def test_collapses_inner_whitespace(self) -> None:
        assert canonicalize("rotational    embeddings") == "rotational embedding"

    def test_strips_trailing_plural_s_on_long_words(self) -> None:
        assert canonicalize("embeddings") == "embedding"

    def test_preserves_short_words_ending_in_s(self) -> None:
        # 3-char words like "css", "ml" can't strip; pattern requires 3 chars + s
        # "css" has length 3 ending in s -- not stripped (need 3 char + s = 4 total to match)
        # Actually our regex is (\w{3})s -- so "csss" -> "css", but "css" stays
        assert canonicalize("css") == "css"
        assert canonicalize("ml") == "ml"

    def test_strips_possessive(self) -> None:
        assert canonicalize("OpenAI's") == "openai"

    def test_pure_punctuation_becomes_empty(self) -> None:
        assert canonicalize("!!!") == ""
        assert canonicalize("   ") == ""

    def test_strips_leading_punct(self) -> None:
        assert canonicalize("--rotation") == "rotation"

    def test_strips_trailing_punct(self) -> None:
        assert canonicalize("rotation!!") == "rotation"

    @given(s=st.text(min_size=0, max_size=200))
    @settings(max_examples=200)
    # Discovered failure (0.8.1 fix): "000ss" stripped to "000s" then "000",
    # because the plural regex was matching any 3-char prefix + trailing s,
    # which left the result still ending in -s. Pinned to keep the regression
    # in scope of every future run, not just the runs hypothesis happens to
    # generate it on.
    @example(s="000ss")
    @example(s="0:'S")
    def test_idempotent(self, s: str) -> None:
        once = canonicalize(s)
        twice = canonicalize(once)
        assert once == twice


class TestGroupMentions:
    def test_groups_by_canonical_name(self) -> None:
        a1 = _mention(source="A", name="Rotational Embeddings")
        a2 = _mention(
            source="A", name="rotational embedding"
        )  # same source, same canonical -> dedup
        b1 = _mention(source="B", name="ROTATIONAL EMBEDDINGS")
        groups = group_mentions([a1, a2, b1])
        assert list(groups) == ["rotational embedding"]
        assert len(groups["rotational embedding"]) == 2  # A and B, A's second mention deduped
        assert {m.source_id for m in groups["rotational embedding"]} == {"A", "B"}

    def test_distinct_canonical_names_grouped_separately(self) -> None:
        groups = group_mentions(
            [
                _mention(source="A", name="Rotational Embeddings"),
                _mention(source="A", name="Energy Barrier Gate"),
            ]
        )
        assert set(groups.keys()) == {"rotational embedding", "energy barrier gate"}

    def test_empty_input(self) -> None:
        assert group_mentions([]) == OrderedDict()

    def test_pure_punctuation_skipped(self) -> None:
        groups = group_mentions(
            [
                _mention(source="A", name="!!!"),
                _mention(source="A", name="real concept"),
            ]
        )
        assert list(groups) == ["real concept"]

    def test_iteration_order_is_sorted(self) -> None:
        groups = group_mentions(
            [
                _mention(source="X", name="zebra"),
                _mention(source="X", name="alpha"),
                _mention(source="X", name="mango"),
            ]
        )
        assert list(groups.keys()) == ["alpha", "mango", "zebra"]

    def test_within_group_sorted_by_source_then_time(self) -> None:
        groups = group_mentions(
            [
                _mention(source="C", name="x", extracted_at="2026-05-15T03:00:00Z"),
                _mention(source="A", name="x", extracted_at="2026-05-15T01:00:00Z"),
                _mention(source="B", name="x", extracted_at="2026-05-15T02:00:00Z"),
            ]
        )
        ordered_sources = [m.source_id for m in groups["x"]]
        assert ordered_sources == ["A", "B", "C"]

    @given(
        sources=st.lists(
            st.tuples(
                st.sampled_from(["A", "B", "C", "D", "E"]),
                st.sampled_from(["foo", "bar", "baz"]),
            ),
            min_size=0,
            max_size=20,
        )
    )
    @settings(max_examples=100)
    def test_grouping_is_commutative(
        self,
        sources: list[tuple[str, str]],
    ) -> None:
        """Grouping the same mentions in two different orders yields the same result."""
        mentions = [_mention(source=s, name=n) for s, n in sources]
        groups_a = group_mentions(mentions)
        groups_b = group_mentions(list(reversed(mentions)))
        assert list(groups_a.keys()) == list(groups_b.keys())
        # Each group must contain the same set of source_ids
        for key in groups_a:
            assert {m.source_id for m in groups_a[key]} == {m.source_id for m in groups_b[key]}


class TestFilterByThreshold:
    def test_below_threshold_dropped(self) -> None:
        grouped = group_mentions(
            [
                _mention(source="A", name="below"),
                _mention(source="B", name="below"),
                _mention(source="A", name="above"),
                _mention(source="B", name="above"),
                _mention(source="C", name="above"),
            ]
        )
        filtered = filter_by_threshold(grouped, min_sources=3)
        assert list(filtered) == ["above"]

    def test_threshold_of_one_no_filter(self) -> None:
        grouped = group_mentions([_mention(source="A", name="solo")])
        assert filter_by_threshold(grouped, min_sources=1) == grouped

    def test_default_threshold_is_three(self) -> None:
        assert DEFAULT_SOURCE_THRESHOLD == 3

    def test_distinct_sources_counted_not_mentions(self) -> None:
        # One source contributing N times still counts as 1 source
        grouped = group_mentions(
            [
                _mention(source="A", name="x", extracted_at="2026-01-01T00:00:00Z"),
            ]
        )
        # Manually inject a second mention from A into the group to simulate
        # what would happen if dedup weren't applied
        grouped["x"].append(_mention(source="A", name="x", extracted_at="2026-02-01T00:00:00Z"))
        filtered = filter_by_threshold(grouped, min_sources=2)
        assert filtered == OrderedDict()

"""Generated contract tests for deterministic concept helpers."""

from __future__ import annotations

import deal
from hypothesis import strategies as st

from distill.concepts.merge import build_merged_concept
from distill.concepts.normalize import canonicalize, filter_by_threshold, group_mentions
from distill.concepts.records import ConceptKind, ConceptMention, Polarity
from distill.concepts.recovery import parse_note_fields
from distill.library.paths import sanitize_path_component, sanitize_topic, slugify_title

_POLARITIES = st.sampled_from([Polarity.HELPFUL, Polarity.HARMFUL, Polarity.NEUTRAL])
_KINDS = st.sampled_from(
    [
        ConceptKind.TECHNIQUE,
        ConceptKind.ARCHITECTURE,
        ConceptKind.DATASET,
        ConceptKind.METRIC,
    ]
)
_SOURCE_IDS = st.sampled_from(["source-a", "source-b", "source-c", "source-d"])
_ARTIFACT_PATHS = st.sampled_from(
    [
        "papers/a/a_Insights.md",
        "papers/b/b_Insights.md",
        "videos/c/c_Insights.md",
        "sites/d/d_Insights.md",
    ]
)
_EXTRACTED_AT = st.sampled_from(
    [
        "",
        "2026-01-01T00:00:00Z",
        "2026-01-02T00:00:00Z",
        "2026-01-03T00:00:00Z",
    ]
)


def _mention_strategy(*, normalized_name: str | None = None) -> st.SearchStrategy[ConceptMention]:
    """Generate compact concept mentions for generated contract cases."""
    names = st.sampled_from(["Alpha", "Alpha Concept", "alpha concepts", "Beta Technique"])
    normalized_names = st.just(normalized_name) if normalized_name is not None else names
    return st.builds(
        ConceptMention,
        name=names,
        normalized_name=normalized_names,
        kind=_KINDS,
        polarity=_POLARITIES,
        source_id=_SOURCE_IDS,
        artifact_path=_ARTIFACT_PATHS,
        claim_excerpt=st.text(max_size=80),
        evidence_type=st.text(max_size=24),
        extracted_at=_EXTRACTED_AT,
    )


_MENTIONS = st.lists(_mention_strategy(), min_size=0, max_size=8)
_MERGE_MENTIONS = st.lists(
    _mention_strategy(normalized_name="alpha concept"),
    min_size=1,
    max_size=6,
)
_GROUPED_MENTIONS = _MENTIONS.map(group_mentions)


def test_parse_note_fields_generated_contract_cases() -> None:
    """Arbitrary note text must satisfy the parser's structural postcondition."""
    for case in deal.cases(parse_note_fields, count=50, check_types=False, seed=20260627):
        case()


def test_canonicalize_generated_contract_cases() -> None:
    """Arbitrary concept names must satisfy the canonical idempotence contract."""
    for case in deal.cases(canonicalize, count=100, check_types=False, seed=20260628):
        case()


def test_path_sanitizer_generated_contract_cases() -> None:
    """Arbitrary path labels must stay confined to one path component."""
    targets = (slugify_title, sanitize_path_component, sanitize_topic)
    for offset, target in enumerate(targets):
        for case in deal.cases(target, count=50, check_types=False, seed=20260628 + offset):
            case()


def test_group_mentions_generated_contract_cases() -> None:
    """Generated mention lists must satisfy the grouping postcondition."""
    for case in deal.cases(
        group_mentions,
        count=50,
        kwargs={"mentions": _MENTIONS},
        check_types=False,
        seed=20260631,
    ):
        case()


def test_filter_by_threshold_generated_contract_cases() -> None:
    """Generated grouped mentions must satisfy the threshold postcondition."""
    for case in deal.cases(
        filter_by_threshold,
        count=50,
        kwargs={"grouped": _GROUPED_MENTIONS, "min_sources": st.integers(min_value=0, max_value=5)},
        check_types=False,
        seed=20260632,
    ):
        case()


def test_build_merged_concept_generated_contract_cases() -> None:
    """Generated mention groups must satisfy merge postconditions."""
    for case in deal.cases(
        build_merged_concept,
        count=50,
        kwargs={
            "canonical_name": "alpha concept",
            "mentions": _MERGE_MENTIONS,
            "topic": "contract-generated-topic",
            "provenance": {},
        },
        check_types=False,
        seed=20260633,
    ):
        case()

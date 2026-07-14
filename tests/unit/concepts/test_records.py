"""Unit tests for distill.concepts.records dataclasses."""

from __future__ import annotations

from dataclasses import replace

import pytest

from distill.concepts.records import (
    ConceptKind,
    ConceptMention,
    EvidenceInterval,
    MergedConcept,
    Polarity,
    SourceEvidence,
    utcnow_iso,
)


def _make_mention(**overrides) -> ConceptMention:
    base = {
        "name": "Rotational Embeddings",
        "normalized_name": "rotational embeddings",
        "kind": ConceptKind.TECHNIQUE,
        "polarity": Polarity.HELPFUL,
        "source_id": "2604.11544",
        "artifact_path": "papers/romem/romem_Insights.md",
        "claim_excerpt": "Continuous rotation beats discrete timestamps.",
        "evidence_type": "empirical_result",
        "extracted_at": "2026-05-15T14:30:00Z",
    }
    base.update(overrides)
    return ConceptMention(**base)


class TestPolarity:
    def test_string_values(self) -> None:
        assert Polarity.HELPFUL.value == "helpful"
        assert Polarity.HARMFUL.value == "harmful"
        assert Polarity.NEUTRAL.value == "neutral"

    def test_round_trip_through_value(self) -> None:
        assert Polarity(Polarity.HELPFUL.value) is Polarity.HELPFUL


class TestConceptKind:
    @pytest.mark.parametrize(
        "kind,is_entity",
        [
            (ConceptKind.TECHNIQUE, False),
            (ConceptKind.ARCHITECTURE, False),
            (ConceptKind.DATASET, False),
            (ConceptKind.METRIC, False),
            (ConceptKind.PERSON, True),
            (ConceptKind.ORGANIZATION, True),
            (ConceptKind.VENDOR, True),
        ],
    )
    def test_is_entity_routes_correctly(self, kind: ConceptKind, is_entity: bool) -> None:
        assert kind.is_entity is is_entity


class TestEvidenceInterval:
    def test_valid_interval(self) -> None:
        iv = EvidenceInterval(lower=2, upper=5)
        assert iv.width == 3

    def test_zero_zero_is_valid(self) -> None:
        EvidenceInterval(lower=0, upper=0)

    def test_lower_equals_upper_is_valid(self) -> None:
        iv = EvidenceInterval(lower=3, upper=3)
        assert iv.width == 0

    def test_negative_lower_rejected(self) -> None:
        with pytest.raises(ValueError):
            EvidenceInterval(lower=-1, upper=2)

    def test_negative_upper_rejected(self) -> None:
        with pytest.raises(ValueError):
            EvidenceInterval(lower=0, upper=-1)

    def test_lower_above_upper_rejected(self) -> None:
        with pytest.raises(ValueError):
            EvidenceInterval(lower=5, upper=2)

    def test_to_list_yaml_friendly(self) -> None:
        assert EvidenceInterval(lower=2, upper=5).to_list() == [2, 5]


class TestConceptMentionRoundTrip:
    def test_jsonl_round_trip_preserves_all_fields(self) -> None:
        original = _make_mention()
        round_tripped = ConceptMention.from_jsonl_row(original.to_jsonl_row())
        assert round_tripped == original

    def test_optional_fields_default_empty(self) -> None:
        m = _make_mention(claim_excerpt="", evidence_type="", extracted_at="")
        row = m.to_jsonl_row()
        rebuilt = ConceptMention.from_jsonl_row(row)
        assert rebuilt == m

    def test_from_jsonl_tolerates_missing_optional_keys(self) -> None:
        # Older mentions.jsonl rows may not have evidence_type
        row = {
            "name": "X",
            "normalized_name": "x",
            "kind": "technique",
            "polarity": "helpful",
            "source_id": "S1",
            "artifact_path": "p.md",
        }
        m = ConceptMention.from_jsonl_row(row)
        assert m.claim_excerpt == ""
        assert m.evidence_type == ""

    def test_mention_is_hashable(self) -> None:
        s = {_make_mention(), _make_mention()}
        assert len(s) == 1


class TestMergedConcept:
    def _make_merged(
        self,
        *,
        helpful: tuple[int, int] = (3, 5),
        harmful: tuple[int, int] = (0, 1),
        kind: ConceptKind = ConceptKind.TECHNIQUE,
    ) -> MergedConcept:
        sources = (
            SourceEvidence(
                source_id="A",
                artifact_path="papers/a/a_Insights.md",
                polarity=Polarity.HELPFUL,
            ),
            SourceEvidence(
                source_id="B",
                artifact_path="papers/b/b_Insights.md",
                polarity=Polarity.HELPFUL,
            ),
            SourceEvidence(
                source_id="C",
                artifact_path="papers/c/c_Insights.md",
                polarity=Polarity.NEUTRAL,
            ),
        )
        return MergedConcept(
            name="Rotational Embeddings",
            normalized_name="rotational embeddings",
            kind=kind,
            topic="tkg",
            sources=sources,
            helpful_evidence=EvidenceInterval(*helpful),
            harmful_evidence=EvidenceInterval(*harmful),
            first_seen="2026-04-12T10:00:00Z",
            last_seen="2026-05-15T14:30:00Z",
        )

    def test_source_count(self) -> None:
        assert self._make_merged().source_count == 3

    def test_contested_when_both_polarities_present(self) -> None:
        assert self._make_merged(helpful=(2, 3), harmful=(1, 1)).contested is True

    def test_not_contested_when_only_helpful(self) -> None:
        assert self._make_merged(helpful=(3, 5), harmful=(0, 0)).contested is False

    def test_not_contested_when_only_harmful(self) -> None:
        assert self._make_merged(helpful=(0, 0), harmful=(2, 2)).contested is False

    def test_contested_uses_upper_bound(self) -> None:
        # Both upper > 0, both lower == 0 -- still contested under our looser threshold
        assert self._make_merged(helpful=(0, 1), harmful=(0, 1)).contested is True

    def test_slug_simple(self) -> None:
        m = self._make_merged()
        assert m.slug == "rotational_embeddings"

    def test_slug_strips_punctuation(self) -> None:
        sources = (SourceEvidence(source_id="S", artifact_path="p.md", polarity=Polarity.HELPFUL),)
        m = MergedConcept(
            name="GPT-4 (turbo)",
            normalized_name="gpt-4 (turbo)",
            kind=ConceptKind.ARCHITECTURE,
            topic="t",
            sources=sources,
            helpful_evidence=EvidenceInterval(1, 1),
            harmful_evidence=EvidenceInterval(0, 0),
            first_seen="x",
            last_seen="x",
        )
        # Non-alphanumerics collapse to single underscores, trailing trimmed
        assert m.slug == "gpt_4_turbo"

    def test_slug_empty_fallback(self) -> None:
        sources = (SourceEvidence(source_id="S", artifact_path="p.md", polarity=Polarity.HELPFUL),)
        m = MergedConcept(
            name="!!!",
            normalized_name="!!!",
            kind=ConceptKind.TECHNIQUE,
            topic="t",
            sources=sources,
            helpful_evidence=EvidenceInterval(1, 1),
            harmful_evidence=EvidenceInterval(0, 0),
            first_seen="x",
            last_seen="x",
        )
        assert m.slug == "unnamed"

    def test_slug_bounds_long_unicode_components_without_losing_identity(self) -> None:
        first = replace(
            self._make_merged(),
            normalized_name=("model architecture " * 40) + ("\u6a21\u578b" * 80) + " alpha",
        )
        second = replace(
            first, normalized_name=first.normalized_name.removesuffix("alpha") + "beta"
        )

        assert len(first.slug.encode("utf-8")) <= 120
        assert len(first.slug.encode("utf-16-le")) // 2 <= 120
        assert first.slug != second.slug
        assert first.slug.startswith("model_architecture")

    def test_slug_avoids_windows_reserved_device_names(self) -> None:
        reserved = replace(self._make_merged(), normalized_name="CON")

        assert reserved.slug.startswith("con__")
        assert reserved.slug != "con"

    def test_to_jsonl_row_includes_scalar_derived_views(self) -> None:
        row = self._make_merged(helpful=(3, 5), harmful=(0, 0)).to_jsonl_row()
        assert row["helpful_evidence"] == [3, 5]
        assert row["helpful_count"] == 5
        assert row["harmful_count"] == 0
        assert row["contested"] is False
        assert row["source_count"] == 3


class TestUtcnowIso:
    def test_ends_with_z(self) -> None:
        assert utcnow_iso().endswith("Z")

    def test_no_microseconds(self) -> None:
        # second precision -- no fractional seconds in the string
        ts = utcnow_iso()
        assert "." not in ts

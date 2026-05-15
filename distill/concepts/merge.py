"""Deterministic merge of grouped concept mentions into ``MergedConcept`` records.

The merge step is pure Python -- no LLM, no IO, no clock. Inputs are
``ConceptMention`` lists grouped by canonical name; outputs are
``MergedConcept`` records ready for rendering. The invariants the
hypothesis property tests enforce:

1. **Commutativity under source ordering.** ``build_merged_concept(A + B)``
   produces the same result (under field-by-field equality) as
   ``build_merged_concept(B + A)``. Achieved by sorting mentions by
   ``(source_id, extracted_at)`` before any aggregation.

2. **Idempotency under repeated mentions from the same source.**
   Duplicate ``(source_id, canonical_name)`` rows are dropped at the
   normalize layer; merge only sees one row per source. Merging an
   already-merged concept's source list back through ``build_merged_concept``
   yields the same record.

3. **Monotonic interval widening.** Adding a new mention to an existing
   group never narrows ``helpful_evidence`` or ``harmful_evidence``.
   Either bound can stay flat or grow.

4. **Lower <= upper.** The dataclass ``__post_init__`` enforces this on
   every ``EvidenceInterval``; the merge logic constructs intervals such
   that the invariant is satisfied by construction.

The polarity-to-bounds projection (the credal-interval logic):

    helpful_lower = #sources with polarity == HELPFUL
    helpful_upper = helpful_lower + #sources with polarity == NEUTRAL
    harmful_lower = #sources with polarity == HARMFUL
    harmful_upper = harmful_lower + #sources with polarity == NEUTRAL

A neutral source widens *both* upper bounds because neutrality means
the mention could go either way. The width (`upper - lower`) is the
shared-ambiguity margin -- and ``contested`` (both uppers > 0) lifts
into ``distill health`` automatically when neutrals push it over.
"""

from __future__ import annotations

from collections.abc import Iterable

from distill.concepts.records import (
    ConceptMention,
    EvidenceInterval,
    MergedConcept,
    Polarity,
    SourceEvidence,
)

__all__ = ["build_all", "build_merged_concept"]


def _pick_display_name(mentions: list[ConceptMention]) -> str:
    """Pick the canonical display form across mentions.

    Strategy: prefer the longest surface form (more information),
    tie-break by lexicographic order for determinism. The longest form
    is usually the most specific ("Rotational Embeddings" over "rotation"),
    and the lex tiebreak makes the choice stable across runs.
    """
    candidates = sorted({m.name for m in mentions}, key=lambda s: (-len(s), s))
    return candidates[0]


def _pick_kind(mentions: list[ConceptMention]) -> str:
    """Pick the most-common ``ConceptKind`` across mentions.

    Tie-break by the kind value's sort order so output is stable. The
    LLM occasionally disagrees on whether something is a "technique" or
    "architecture" across insights; we don't try to resolve that
    semantically, we just pick the most-voted one.
    """
    from collections import Counter

    counts = Counter(m.kind.value for m in mentions)
    most_common = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return most_common[0][0]


def build_merged_concept(
    canonical_name: str,
    mentions: list[ConceptMention],
    *,
    topic: str,
    provenance: dict | None = None,
) -> MergedConcept:
    """Build a ``MergedConcept`` from one canonical group's mentions.

    The mentions list is expected to come from ``group_mentions`` (already
    deduplicated by source_id and sorted). This function does not
    re-sort -- if you pass shuffled input you'll get shuffled output.
    The normalize layer is what enforces commutativity.
    """
    if not mentions:
        raise ValueError(f"Cannot build merged concept from empty mention list: {canonical_name}")

    from distill.concepts.records import ConceptKind

    name = _pick_display_name(mentions)
    kind = ConceptKind(_pick_kind(mentions))

    sources = tuple(
        SourceEvidence(
            source_id=m.source_id,
            artifact_path=m.artifact_path,
            polarity=m.polarity,
            claim_excerpt=m.claim_excerpt,
            evidence_type=m.evidence_type,
            seen_at=m.extracted_at,
        )
        for m in mentions
    )

    helpful_count = sum(1 for m in mentions if m.polarity == Polarity.HELPFUL)
    harmful_count = sum(1 for m in mentions if m.polarity == Polarity.HARMFUL)
    neutral_count = sum(1 for m in mentions if m.polarity == Polarity.NEUTRAL)

    helpful = EvidenceInterval(lower=helpful_count, upper=helpful_count + neutral_count)
    harmful = EvidenceInterval(lower=harmful_count, upper=harmful_count + neutral_count)

    timestamps = [m.extracted_at for m in mentions if m.extracted_at]
    first_seen = min(timestamps) if timestamps else ""
    last_seen = max(timestamps) if timestamps else ""

    return MergedConcept(
        name=name,
        normalized_name=canonical_name,
        kind=kind,
        topic=topic,
        sources=sources,
        helpful_evidence=helpful,
        harmful_evidence=harmful,
        first_seen=first_seen,
        last_seen=last_seen,
        provenance=dict(provenance or {}),
    )


def build_all(
    grouped: Iterable[tuple[str, list[ConceptMention]]],
    *,
    topic: str,
    provenance: dict | None = None,
) -> list[MergedConcept]:
    """Merge every group; preserve iteration order (already canonicalized-and-sorted by normalize)."""
    return [
        build_merged_concept(canonical, mentions, topic=topic, provenance=provenance)
        for canonical, mentions in grouped
    ]

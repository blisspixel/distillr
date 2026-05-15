"""Group concept mentions by normalized name and apply the threshold filter.

This step is between extraction (LLM, produces raw mentions) and merge
(produces the deterministic playbook). It is pure: no IO, no LLM, no
hidden state. The same input always produces the same grouping.

Two things happen here:

1. Mentions are grouped by ``normalized_name``. The LLM is asked to
   produce a normalized name in the extraction prompt, but the same
   surface concept may arrive with slightly different normalized forms
   from different insights ("rotational embeddings" vs "rotational
   embedding"). We post-process the LLM's normalization with a fold
   that's purely mechanical (lowercase, strip, collapse whitespace,
   strip trailing punctuation/plural-s) so the merge step receives
   already-canonical keys. Anything more clever (semantic alias
   resolution) is deliberately *not* here -- it would make merges
   non-deterministic across model changes.

2. The threshold filter drops concepts mentioned in fewer than
   ``min_sources`` *distinct* source ids. This is the noise filter
   the roadmap calls for ("mentioned across 3+ insights"). Default
   threshold lives in ``DEFAULT_SOURCE_THRESHOLD``; the CLI exposes
   ``--threshold`` for overrides.

A mention from the same source contributing twice to the same concept
(same ``source_id`` + same ``normalized_name``) is collapsed here.
Aggregation rule when the polarities disagree: collapse to NEUTRAL. This
is the credal-interval-faithful answer (the source is internally
ambiguous about this concept; we count it on the upper bounds of both
helpful and harmful), and it is order-independent, which makes the
downstream merge commutative even when extraction emits duplicates with
conflicting polarities. When polarities agree, that polarity wins.
"""

from __future__ import annotations

import re
from collections import OrderedDict
from collections.abc import Iterable

from distill.concepts.records import ConceptMention, Polarity

__all__ = [
    "DEFAULT_SOURCE_THRESHOLD",
    "canonicalize",
    "filter_by_threshold",
    "group_mentions",
]

DEFAULT_SOURCE_THRESHOLD = 3

# Trailing plural -s only when the word is at least 4 chars (preserve "css",
# "ml", "ai", etc.). Possessive "'s" also stripped. Trailing punctuation
# stripped fully.
_TRAILING_PLURAL = re.compile(r"(\w{3})s\b")
_TRAILING_PUNCT = re.compile(r"[\s\W_]+$")
_LEADING_PUNCT = re.compile(r"^[\s\W_]+")
_INNER_WS = re.compile(r"\s+")


def canonicalize(name: str) -> str:
    """Mechanical canonical form of a concept name.

    Lowercase, collapse whitespace, strip trailing/leading punctuation,
    drop trailing plural-s on words of length 4+. Idempotent:
    ``canonicalize(canonicalize(x)) == canonicalize(x)``. Property tested.

    Returns the empty string for inputs that canonicalize to nothing
    (pure punctuation, whitespace). Callers should treat empty as a
    skip signal.
    """
    if not name:
        return ""
    folded = name.lower()
    folded = _LEADING_PUNCT.sub("", folded)
    folded = _TRAILING_PUNCT.sub("", folded)
    folded = _INNER_WS.sub(" ", folded).strip()
    if not folded:
        return ""
    # Strip possessive apostrophe-s so "OpenAI's" matches "openai"
    if folded.endswith("'s"):
        folded = folded[:-2]
    folded = _TRAILING_PLURAL.sub(r"\1", folded)
    return folded


def group_mentions(
    mentions: Iterable[ConceptMention],
) -> OrderedDict[str, list[ConceptMention]]:
    """Group mentions by canonicalized name.

    Returns an ``OrderedDict`` so iteration order is deterministic and
    matches the sorted order of canonical names. Within each group,
    mentions are sorted by ``source_id`` to give the merge step stable
    input ordering regardless of the order extraction produced them.

    Per-source aggregation: when the same ``(source_id, canonical_name)``
    appears multiple times, the mentions are collapsed into one
    representative mention for that source. If all duplicate polarities
    agree, the agreed polarity wins; if they disagree, the polarity
    collapses to ``NEUTRAL`` (the source is internally ambiguous about
    the concept -- recording that as neutral matches the credal-interval
    semantics, where neutrals widen both upper bounds). The earliest
    ``extracted_at`` and the longest surface ``name`` are kept; other
    fields come from the first mention seen in sorted order.
    """
    by_source: dict[tuple[str, str], list[ConceptMention]] = {}
    for mention in mentions:
        canonical = canonicalize(mention.normalized_name)
        if not canonical:
            continue
        by_source.setdefault((mention.source_id, canonical), []).append(mention)

    grouped: dict[str, list[ConceptMention]] = {}
    for key, per_source in by_source.items():
        canonical = key[1]
        grouped.setdefault(canonical, []).append(_aggregate_per_source(per_source))

    ordered: OrderedDict[str, list[ConceptMention]] = OrderedDict()
    for canonical in sorted(grouped):
        ordered[canonical] = sorted(
            grouped[canonical],
            key=lambda m: m.source_id,
        )
    return ordered


def _aggregate_per_source(mentions: list[ConceptMention]) -> ConceptMention:
    """Collapse multiple mentions from one source into one representative.

    Polarity aggregation: unanimous polarity wins; disagreement -> NEUTRAL.
    Other fields: longest ``name`` (display form); earliest ``extracted_at``;
    first non-empty ``claim_excerpt`` and ``evidence_type``; ``kind`` from
    the lex-first by value (deterministic tie-break).
    """
    if len(mentions) == 1:
        return mentions[0]

    sorted_by_polarity = sorted(mentions, key=lambda m: m.polarity.value)
    polarities = {m.polarity for m in mentions}
    polarity = sorted_by_polarity[0].polarity if len(polarities) == 1 else Polarity.NEUTRAL

    name = max((m.name for m in mentions), key=lambda s: (len(s), s))
    kind = min((m.kind for m in mentions), key=lambda k: k.value)
    timestamps = sorted(m.extracted_at for m in mentions if m.extracted_at)
    extracted_at = timestamps[0] if timestamps else ""
    claim = next((m.claim_excerpt for m in mentions if m.claim_excerpt), "")
    evidence_type = next((m.evidence_type for m in mentions if m.evidence_type), "")

    head = mentions[0]
    return ConceptMention(
        name=name,
        normalized_name=head.normalized_name,
        kind=kind,
        polarity=polarity,
        source_id=head.source_id,
        artifact_path=head.artifact_path,
        claim_excerpt=claim,
        evidence_type=evidence_type,
        extracted_at=extracted_at,
    )


def filter_by_threshold(
    grouped: OrderedDict[str, list[ConceptMention]],
    min_sources: int = DEFAULT_SOURCE_THRESHOLD,
) -> OrderedDict[str, list[ConceptMention]]:
    """Drop groups with fewer than ``min_sources`` distinct source ids.

    A ``min_sources`` of 1 disables the filter (every grouped concept
    emits). The default of 3 matches the roadmap's "mentioned across 3+
    insights" threshold and filters single-paper hapax noise.
    """
    if min_sources <= 1:
        return grouped
    filtered: OrderedDict[str, list[ConceptMention]] = OrderedDict()
    for canonical, mentions in grouped.items():
        distinct_sources = {m.source_id for m in mentions}
        if len(distinct_sources) >= min_sources:
            filtered[canonical] = mentions
    return filtered

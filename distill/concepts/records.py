"""Core dataclasses and enums for the concept playbook layer.

These types are deliberately small and pure -- no IO, no LLM calls, no
dependencies on the rest of distillr beyond ``distill.library.paths`` (which
this module does not import). Keeping the data layer free of cross-package
imports lets the merge and normalize layers be tested in isolation with
hypothesis property tests.

Vocabulary:

- A **mention** (``ConceptMention``) is one source's reference to a concept.
  Extraction produces one mention per ``(insight, normalized_name)`` tuple.
- A **merged concept** (``MergedConcept``) is the deterministic projection
  of all mentions sharing a normalized name, with evidence intervals.
- **Polarity** captures whether a mention supports, contradicts, or merely
  references the concept. Neutral mentions widen the upper bound of the
  evidence interval without contributing to the lower bound -- the credal
  interval that lets ``distill health`` separate strong consensus from
  passing references.
"""

# pyright: strict

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

__all__ = [
    "ConceptKind",
    "ConceptMention",
    "EvidenceInterval",
    "MergedConcept",
    "Polarity",
    "SourceEvidence",
]

_MAX_SLUG_COMPONENT_UNITS = 120
_SLUG_DIGEST_LENGTH = 12
_WINDOWS_RESERVED_COMPONENTS = {
    "aux",
    "con",
    "nul",
    "prn",
    *(f"com{number}" for number in range(1, 10)),
    *(f"lpt{number}" for number in range(1, 10)),
}


def _bounded_slug(slug: str, *, identity: str) -> str:
    """Bound a filesystem component while preserving stable identity.

    The limit applies independently to UTF-8 bytes and UTF-16 code units so
    the same component remains safe on common POSIX filesystems and Windows.
    Short slugs remain unchanged for backward compatibility.
    """
    utf8_length = len(slug.encode("utf-8"))
    utf16_length = len(slug.encode("utf-16-le")) // 2
    if (
        max(utf8_length, utf16_length) <= _MAX_SLUG_COMPONENT_UNITS
        and slug.casefold() not in _WINDOWS_RESERVED_COMPONENTS
    ):
        return slug

    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:_SLUG_DIGEST_LENGTH]
    suffix = f"__{digest}"
    prefix_budget = _MAX_SLUG_COMPONENT_UNITS - len(suffix)
    prefix_chars: list[str] = []
    utf8_length = 0
    utf16_length = 0
    for character in slug:
        character_utf8 = len(character.encode("utf-8"))
        character_utf16 = len(character.encode("utf-16-le")) // 2
        next_units = max(
            utf8_length + character_utf8,
            utf16_length + character_utf16,
        )
        if next_units > prefix_budget:
            break
        prefix_chars.append(character)
        utf8_length += character_utf8
        utf16_length += character_utf16

    prefix = "".join(prefix_chars).rstrip("_")
    return f"{prefix}{suffix}"


class Polarity(StrEnum):
    """How a source treats a concept.

    String-valued enum so the records serialize cleanly to JSON without
    custom encoders; reading the JSONL back ``Polarity(value)`` round-trips.
    """

    HELPFUL = "helpful"
    HARMFUL = "harmful"
    NEUTRAL = "neutral"


class ConceptKind(StrEnum):
    """High-level category of a named thing.

    Concepts (techniques, architectures, datasets, metrics) live in
    ``library/topics/<topic>/concepts/``. Entities (people, organizations,
    vendors) live in ``entities/``. The split is conventional, not a hard
    architectural boundary -- both kinds share the same merge + render
    pipeline. Routing happens in ``notes.py`` based on this field.
    """

    TECHNIQUE = "technique"
    ARCHITECTURE = "architecture"
    DATASET = "dataset"
    METRIC = "metric"
    PERSON = "person"
    ORGANIZATION = "organization"
    VENDOR = "vendor"

    @property
    def is_entity(self) -> bool:
        """``True`` for kinds that route to ``entities/``, ``False`` for ``concepts/``."""
        return self in {ConceptKind.PERSON, ConceptKind.ORGANIZATION, ConceptKind.VENDOR}


@dataclass(frozen=True, slots=True)
class ConceptMention:
    """One source's reference to a concept.

    Produced by the extraction step (LLM); consumed by normalize + merge.
    Frozen so it can live in a ``set`` and so accidental mutation in the
    merge layer can't corrupt evidence counts.

    Fields:
        name: surface form as it appears in the source insight (e.g.
            "Rotational Embeddings" or "rotation embeddings"). Preserved
            verbatim for display; normalization happens separately so we
            don't lose the original phrasing.
        normalized_name: deterministic canonical form derived from the
            grounded surface name. Two mentions with the same normalized_name
            merge into one concept.
        kind: routing category (concept vs entity, technique vs dataset, ...).
        polarity: helpful / harmful / neutral.
        source_id: stable identifier for the source insight (arXiv ID,
            video ID, page slug). Used as the merge dedup key together
            with normalized_name.
        artifact_path: relative path from the topic dir to the source
            ``_Insights.md`` (e.g. ``papers/romem/romem_Insights.md``).
            Used by the notes layer to emit wiki-link backlinks.
        claim_excerpt: exact quote from the insight body containing the
            surface name and grounding the polarity.
        evidence_type: optional label for what kind of evidence the
            source provides (e.g. ``empirical_result``, ``methodology``,
            ``citation``). Free-form; not validated.
        extracted_at: ISO 8601 UTC timestamp of the extraction call.
    """

    name: str
    normalized_name: str
    kind: ConceptKind
    polarity: Polarity
    source_id: str
    artifact_path: str
    claim_excerpt: str = ""
    evidence_type: str = ""
    extracted_at: str = ""

    def to_jsonl_row(self) -> dict[str, Any]:
        """Serialize for the per-topic ``mentions.jsonl`` append-only log."""
        return {
            "name": self.name,
            "normalized_name": self.normalized_name,
            "kind": self.kind.value,
            "polarity": self.polarity.value,
            "source_id": self.source_id,
            "artifact_path": self.artifact_path,
            "claim_excerpt": self.claim_excerpt,
            "evidence_type": self.evidence_type,
            "extracted_at": self.extracted_at,
        }

    @classmethod
    def from_jsonl_row(cls, row: dict[str, Any]) -> ConceptMention:
        """Round-trip from a row written by ``to_jsonl_row``."""
        return cls(
            name=row["name"],
            normalized_name=row["normalized_name"],
            kind=ConceptKind(row["kind"]),
            polarity=Polarity(row["polarity"]),
            source_id=row["source_id"],
            artifact_path=row["artifact_path"],
            claim_excerpt=row.get("claim_excerpt", ""),
            evidence_type=row.get("evidence_type", ""),
            extracted_at=row.get("extracted_at", ""),
        )


@dataclass(frozen=True, slots=True)
class EvidenceInterval:
    """Credal-style interval over evidence counts for one polarity.

    ``lower`` counts sources whose polarity is unambiguously this one.
    ``upper`` additionally counts sources whose polarity is neutral, since
    a neutral mention *could* be evidence either way. The width
    ``upper - lower`` is the ambiguity margin.

    Invariant: ``0 <= lower <= upper``. Enforced in ``__post_init__``.
    """

    lower: int
    upper: int

    def __post_init__(self) -> None:
        if self.lower < 0 or self.upper < 0:
            raise ValueError(f"EvidenceInterval bounds must be non-negative: {self}")
        if self.lower > self.upper:
            raise ValueError(f"EvidenceInterval lower > upper: {self}")

    @property
    def width(self) -> int:
        """Ambiguity margin: how many sources are merely possibly-supporting."""
        return self.upper - self.lower

    def to_list(self) -> list[int]:
        """YAML-friendly two-element list."""
        return [self.lower, self.upper]


@dataclass(frozen=True, slots=True)
class SourceEvidence:
    """One source's contribution to a merged concept, as stored in the note.

    Frontmatter ``sources`` field is a list of these. Distinct from
    ``ConceptMention`` because the merge step deduplicates and may drop
    fields that are irrelevant after merging (e.g. ``evidence_type`` is
    kept; ``normalized_name`` is redundant once grouped).
    """

    source_id: str
    artifact_path: str
    polarity: Polarity
    claim_excerpt: str = ""
    evidence_type: str = ""
    seen_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "artifact_path": self.artifact_path,
            "polarity": self.polarity.value,
            "claim_excerpt": self.claim_excerpt,
            "evidence_type": self.evidence_type,
            "seen_at": self.seen_at,
        }


@dataclass(frozen=True, slots=True)
class MergedConcept:
    """Deterministic projection of all mentions for one normalized name.

    Produced by ``merge.build_merged_concept`` from a list of mentions
    sharing a ``normalized_name``. The notes layer renders the playbook
    ``.md`` from this; the exports layer projects scalar rows from this.
    """

    name: str  # display form -- the longest distinct surface form across mentions
    normalized_name: str
    kind: ConceptKind
    topic: str
    sources: tuple[SourceEvidence, ...]  # ordered by source_id for stable diffs
    helpful_evidence: EvidenceInterval
    harmful_evidence: EvidenceInterval
    first_seen: str
    last_seen: str
    provenance: dict[str, Any] = field(default_factory=dict)  # pyright: ignore[reportUnknownVariableType] dataclass default_factory appears as dict[Unknown, Unknown] under strict; usage confirms dict[str, Any]

    @property
    def source_count(self) -> int:
        return len(self.sources)

    @property
    def contested(self) -> bool:
        """A concept is contested when both polarities have at least one possibly-supporting source.

        ``upper > 0`` is the looser threshold (count neutrals); we use it
        here so that a concept where one source strongly supports and one
        is ambiguous-but-leaning-against still flags as contested. The
        scalar ``helpful_count`` / ``harmful_count`` derived views match
        ``upper`` for the same reason.
        """
        return self.helpful_evidence.upper > 0 and self.harmful_evidence.upper > 0

    @property
    def slug(self) -> str:
        """Stable filesystem slug derived from normalized_name.

        Deliberately simple: lowercase, replace non-alphanumerics with
        underscores, and collapse runs. Long components receive a stable
        digest suffix so model-produced names cannot exceed filesystem
        component limits. The notes layer handles remaining lossy collisions
        against existing files in ``concepts/`` and ``entities/``.
        """
        out_chars: list[str] = []
        prev_underscore = False
        for ch in self.normalized_name.lower():
            if ch.isalnum():
                out_chars.append(ch)
                prev_underscore = False
            elif not prev_underscore:
                out_chars.append("_")
                prev_underscore = True
        slug = "".join(out_chars).strip("_") or "unnamed"
        return _bounded_slug(slug, identity=self.normalized_name)

    def to_jsonl_row(self) -> dict[str, Any]:
        """Project into a scalar-friendly row for ``concepts.jsonl`` / ``entities.jsonl``.

        ``helpful_count`` and ``harmful_count`` are derived views matching
        the upper bounds -- the "generous read" -- so a downstream agent
        that wants a single number gets the more inclusive count. The
        interval pair is also preserved so consumers can inspect the
        ambiguity margin.
        """
        return {
            "name": self.name,
            "normalized_name": self.normalized_name,
            "slug": self.slug,
            "kind": self.kind.value,
            "topic": self.topic,
            "source_count": self.source_count,
            "helpful_evidence": self.helpful_evidence.to_list(),
            "harmful_evidence": self.harmful_evidence.to_list(),
            "helpful_count": self.helpful_evidence.upper,
            "harmful_count": self.harmful_evidence.upper,
            "contested": self.contested,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
        }


def utcnow_iso() -> str:
    """Return current UTC time as an ISO 8601 string with second precision.

    Centralized so tests can monkeypatch this single function when they
    need stable timestamps in fixtures.
    """
    return datetime.now(UTC).replace(microsecond=0, tzinfo=None).isoformat() + "Z"

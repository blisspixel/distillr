"""Core dataclasses and enums for the claim layer (0.9 two-pass synthesis).

A **claim** is one assertion a single source makes -- the atomic unit the
second synthesis pass clusters, compares, and cites. This mirrors the 0.8
concept layer's data design (frozen records, ``StrEnum``, injected timestamps,
JSONL round-trip) so the same append-only-log + pure-Python-merge discipline
applies: the LLM produces rows, Python parses and stores them, and the merge
is deterministic under source ordering.

Unlike a ``ConceptMention`` (one source's stance toward a *named thing*), a
``Claim`` is a free-standing assertion with a *rhetorical role* -- whether the
source is stating background, describing a method, reporting a result, noting
a limitation, or drawing a conclusion. The role is load-bearing for the
synthesis pass: claims about methods compose differently than claims about
results, so clustering without the role is noisier than it needs to be.

The schema is grounded in the argument-mining / scientific-claim-extraction
literature. ``subject``/``predicate``/``object`` is an optional triple for
claims with a clean agent-action-object structure; ``claim_text`` is the
free-form fallback for narrative claims that do not decompose cleanly. The
extractor chooses granularity per claim (clause / sentence / span); forcing
one global granularity is the documented failure mode in reference systems.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

__all__ = [
    "Claim",
    "ClaimRole",
    "utcnow_iso",
]


class ClaimRole(StrEnum):
    """Rhetorical role of a claim within its source.

    A precursor segmentation that both shipped scientific-claim systems treat
    as load-bearing: clustering on the synthesis side groups method claims
    with method claims and result claims with result claims. String-valued so
    records serialize to JSON without custom encoders and ``ClaimRole(value)``
    round-trips on read.
    """

    BACKGROUND = "background"
    METHOD = "method"
    RESULT = "result"
    LIMITATION = "limitation"
    CONCLUSION = "conclusion"


@dataclass(frozen=True, slots=True)
class Claim:
    """One source's assertion, ready to append to ``claims.jsonl``.

    Produced by the extraction step (LLM); consumed by the claim-aware
    synthesis pass. Frozen so it can live in a ``set`` and so accidental
    mutation downstream cannot corrupt the claim set.

    Fields:
        claim_id: stable per-claim identifier, derived deterministically from
            ``source_id`` + a content hash of ``claim_text`` so re-extraction
            of the same assertion yields the same id (lets downstream scoring
            cache by ``claim_id``).
        source_id: stable identifier for the source insight (arXiv ID, video
            ID, page slug). Ties the claim back to its origin.
        artifact_path: topic-relative path to the source ``_Insights.md`` used
            for per-claim citation backlinks.
        claim_text: the assertion in the source's terms, 1-2 sentences. The
            free-form fallback that always works; the triple below is optional.
        rhetorical_role: background / method / result / limitation / conclusion.
        subject, predicate, object: optional agent-action-object triple for
            claims that decompose cleanly (drawn from argument-role designs).
            Empty strings when the claim is narrative.
        dataset, metric: optional named dataset / evaluation metric the claim
            is about, when it reports an empirical result. Empty otherwise.
        evidence_type: free-form label (e.g. ``empirical_result``,
            ``methodology``, ``citation``, ``comparison``).
        role_confidence: 0.0-1.0 self-rated confidence in the role assignment.
            Imperfect role tagging propagates into wrong clusters downstream;
            surfacing low confidence (rather than dropping it) is the designed
            mitigation, and ``--rigor strict`` can require a minimum.
        extracted_at: ISO 8601 UTC timestamp of the extraction call.
    """

    claim_id: str
    source_id: str
    artifact_path: str
    claim_text: str
    rhetorical_role: ClaimRole
    subject: str = ""
    predicate: str = ""
    object: str = ""
    dataset: str = ""
    metric: str = ""
    evidence_type: str = ""
    role_confidence: float = 0.0
    extracted_at: str = ""

    def to_jsonl_row(self) -> dict[str, Any]:
        """Serialize for the per-topic ``claims.jsonl`` append-only log."""
        return {
            "claim_id": self.claim_id,
            "source_id": self.source_id,
            "artifact_path": self.artifact_path,
            "claim_text": self.claim_text,
            "rhetorical_role": self.rhetorical_role.value,
            "subject": self.subject,
            "predicate": self.predicate,
            "object": self.object,
            "dataset": self.dataset,
            "metric": self.metric,
            "evidence_type": self.evidence_type,
            "role_confidence": self.role_confidence,
            "extracted_at": self.extracted_at,
        }

    @classmethod
    def from_jsonl_row(cls, row: dict[str, Any]) -> Claim:
        """Round-trip from a row written by ``to_jsonl_row``."""
        return cls(
            claim_id=row["claim_id"],
            source_id=row["source_id"],
            artifact_path=row["artifact_path"],
            claim_text=row["claim_text"],
            rhetorical_role=ClaimRole(row["rhetorical_role"]),
            subject=row.get("subject", ""),
            predicate=row.get("predicate", ""),
            object=row.get("object", ""),
            dataset=row.get("dataset", ""),
            metric=row.get("metric", ""),
            evidence_type=row.get("evidence_type", ""),
            role_confidence=float(row.get("role_confidence", 0.0)),
            extracted_at=row.get("extracted_at", ""),
        )


def utcnow_iso() -> str:
    """Return current UTC time as an ISO 8601 string with second precision.

    Centralized so tests can monkeypatch this single function when they need
    stable timestamps in fixtures. Mirrors ``concepts.records.utcnow_iso``.
    """
    return datetime.now(UTC).replace(microsecond=0, tzinfo=None).isoformat() + "Z"

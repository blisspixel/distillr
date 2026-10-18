# pyright: strict
"""Complete extraction generations in the canonical append-only claim log."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import cast

from distill.claims.records import Claim
from distill.library.source_ledger import validate_source_id


@dataclass(frozen=True)
class ClaimGeneration:
    source_id: str
    artifact_path: str
    content_sha256: str
    claims: tuple[Claim, ...]

    def to_row(self) -> dict[str, object]:
        return {
            "event": "claim-generation.v1",
            "source_id": self.source_id,
            "artifact_path": self.artifact_path,
            "content_sha256": self.content_sha256,
            "claims": [claim.to_jsonl_row() for claim in self.claims],
        }

    @classmethod
    def from_row(cls, row: dict[str, object]) -> ClaimGeneration:
        source, artifact, digest = (
            row.get("source_id"),
            row.get("artifact_path"),
            row.get("content_sha256"),
        )
        if not isinstance(source, str) or not isinstance(artifact, str) or not artifact:
            raise ValueError("Generation source and artifact identity are required")
        validate_source_id(source)
        if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise ValueError("Generation requires an exact artifact digest")
        raw_claims = row.get("claims")
        if not isinstance(raw_claims, list):
            raise ValueError("Generation claims must be an array")
        claims: list[Claim] = []
        seen: set[str] = set()
        for raw in cast(list[object], raw_claims):
            if not isinstance(raw, dict):
                raise ValueError("Generation claim must be an object")
            claim = Claim.from_jsonl_row(cast(dict[str, object], raw))
            if (
                claim.source_id != source
                or claim.artifact_path != artifact
                or claim.claim_id in seen
            ):
                raise ValueError("Generation crosses source/artifact identity or repeats a claim")
            seen.add(claim.claim_id)
            claims.append(claim)
        return cls(source, artifact, digest, tuple(claims))


def active_generation_claims(rows: list[dict[str, object]]) -> list[Claim]:
    active: dict[tuple[str, str], dict[str, Claim]] = {}
    for row in rows:
        if "event" in row:
            if row.get("event") != "claim-generation.v1":
                raise ValueError("Unsupported claim history event")
            generation = ClaimGeneration.from_row(row)
            key = (generation.source_id, generation.artifact_path)
            active[key] = {claim.claim_id: claim for claim in generation.claims}
        else:
            claim = Claim.from_jsonl_row(row)
            active.setdefault((claim.source_id, claim.artifact_path), {})[claim.claim_id] = claim
    return [claim for claims in active.values() for claim in claims.values()]

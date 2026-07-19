"""Unit tests for distill.claims.records: Claim round-trip and ClaimRole."""

from __future__ import annotations

import math

import pytest

from distill.claims.records import Claim, ClaimRole, utcnow_iso


def _sample_claim(**overrides) -> Claim:
    base = {
        "claim_id": "src1:abc123def456",
        "source_id": "src1",
        "artifact_path": "papers/x/x_Insights.md",
        "claim_text": "Rotary embeddings improve length generalization on ICEWS.",
        "rhetorical_role": ClaimRole.RESULT,
        "subject": "rotary embeddings",
        "predicate": "improve",
        "object": "length generalization",
        "dataset": "ICEWS05-15",
        "metric": "MRR",
        "evidence_type": "empirical_result",
        "role_confidence": 0.82,
        "extracted_at": "2026-05-30T00:00:00Z",
    }
    base.update(overrides)
    return Claim(**base)


def test_claim_round_trip():
    claim = _sample_claim()
    row = claim.to_jsonl_row()
    restored = Claim.from_jsonl_row(row)
    assert restored == claim


def test_claim_round_trip_minimal_optional_fields():
    # Only required fields set; optionals default. Round-trip must still hold,
    # and from_jsonl_row must tolerate a row missing the optional keys.
    claim = Claim(
        claim_id="s:deadbeef0000",
        source_id="s",
        artifact_path="sites/y/y_Insights.md",
        claim_text="The method has not been tested beyond English.",
        rhetorical_role=ClaimRole.LIMITATION,
    )
    row = claim.to_jsonl_row()
    assert Claim.from_jsonl_row(row) == claim
    # A legacy/partial row without optional keys hydrates with defaults.
    sparse = {
        "claim_id": claim.claim_id,
        "source_id": claim.source_id,
        "artifact_path": claim.artifact_path,
        "claim_text": claim.claim_text,
        "rhetorical_role": "limitation",
    }
    hydrated = Claim.from_jsonl_row(sparse)
    assert hydrated.subject == ""
    assert hydrated.role_confidence == 0.0


def test_claim_role_values_serialize_as_strings():
    assert ClaimRole.RESULT.value == "result"
    assert {r.value for r in ClaimRole} == {
        "background",
        "method",
        "result",
        "limitation",
        "conclusion",
    }
    # Round-trips through the string value.
    assert ClaimRole("conclusion") is ClaimRole.CONCLUSION


def test_claim_is_frozen_and_hashable():
    claim = _sample_claim()
    # frozen + slots -> hashable, usable in a set
    assert claim in {claim}


def test_utcnow_iso_format():
    stamp = utcnow_iso()
    assert stamp.endswith("Z")
    # No microseconds in the centralized helper.
    assert "." not in stamp


@pytest.mark.parametrize(
    "field",
    ["claim_id", "source_id", "artifact_path", "claim_text", "rhetorical_role"],
)
@pytest.mark.parametrize("invalid", [None, 3, True, [], ""])
def test_claim_from_jsonl_rejects_invalid_required_fields(field: str, invalid: object) -> None:
    row = _sample_claim().to_jsonl_row()
    row[field] = invalid

    with pytest.raises(ValueError, match=field):
        Claim.from_jsonl_row(row)


@pytest.mark.parametrize(
    "field",
    ["subject", "predicate", "object", "dataset", "metric", "evidence_type", "extracted_at"],
)
def test_claim_from_jsonl_rejects_wrong_optional_field_type(field: str) -> None:
    row = _sample_claim().to_jsonl_row()
    row[field] = 3

    with pytest.raises(ValueError, match=field):
        Claim.from_jsonl_row(row)


@pytest.mark.parametrize("invalid", [True, "0.5", -0.1, 1.1, math.nan, math.inf, -math.inf])
def test_claim_from_jsonl_rejects_invalid_role_confidence(invalid: object) -> None:
    row = _sample_claim().to_jsonl_row()
    row["role_confidence"] = invalid

    with pytest.raises(ValueError, match="finite number from 0 to 1"):
        Claim.from_jsonl_row(row)

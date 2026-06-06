"""Unit tests for distill.claims.exports: the claims.jsonl append-only store."""

from __future__ import annotations

from pathlib import Path

from distill.claims.exports import (
    already_extracted_source_ids,
    append_claims,
    claims_jsonl_path,
    read_claims,
)
from distill.claims.records import Claim, ClaimRole


def _claim(source_id: str, text: str, role: ClaimRole = ClaimRole.RESULT) -> Claim:
    from distill.claims.extract import claim_id_for

    return Claim(
        claim_id=claim_id_for(source_id, text),
        source_id=source_id,
        artifact_path=f"papers/{source_id}/{source_id}_Insights.md",
        claim_text=text,
        rhetorical_role=role,
        role_confidence=0.7,
        extracted_at="2026-05-30T00:00:00Z",
    )


def test_read_claims_skips_non_object_lines(tmp_path: Path) -> None:
    # A line that is valid JSON but not an object (42, [1,2]) must be skipped,
    # not crash read_claims/already_extracted_source_ids with a TypeError.
    import json

    path = claims_jsonl_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    good = _claim("S1", "A real claim about RoPE.")
    lines = [
        '{"not": "a claim"}',  # dict missing required keys -> KeyError, skipped
        "42",  # scalar -> TypeError, skipped
        "[1, 2, 3]",  # array -> TypeError, skipped
        "{ broken json",  # JSONDecodeError, skipped
        json.dumps(good.to_jsonl_row(), ensure_ascii=False),
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    assert [c.source_id for c in read_claims(tmp_path)] == ["S1"]
    assert already_extracted_source_ids(tmp_path) == {"S1"}


def test_path_is_under_dot_claims(tmp_path: Path) -> None:
    p = claims_jsonl_path(tmp_path)
    assert p.parent.name == ".claims"
    assert p.name == "claims.jsonl"


def test_append_then_read_round_trips(tmp_path: Path) -> None:
    claims = [_claim("a", "First claim."), _claim("b", "Second claim.")]
    append_claims(tmp_path, claims)
    read_back = read_claims(tmp_path)
    assert read_back == claims


def test_append_is_additive(tmp_path: Path) -> None:
    append_claims(tmp_path, [_claim("a", "First.")])
    append_claims(tmp_path, [_claim("b", "Second.")])
    assert len(read_claims(tmp_path)) == 2


def test_read_missing_is_empty(tmp_path: Path) -> None:
    assert read_claims(tmp_path) == []
    assert already_extracted_source_ids(tmp_path) == set()


def test_read_skips_malformed_lines(tmp_path: Path) -> None:
    append_claims(tmp_path, [_claim("a", "Good.")])
    path = claims_jsonl_path(tmp_path)
    with path.open("a", encoding="utf-8") as f:
        f.write("not json\n")
        f.write('{"missing": "required fields"}\n')
        f.write("\n")  # blank line tolerated
    # The one good claim survives; the junk is skipped.
    assert len(read_claims(tmp_path)) == 1


def test_already_extracted_source_ids(tmp_path: Path) -> None:
    append_claims(tmp_path, [_claim("a", "One."), _claim("a", "Two."), _claim("b", "Three.")])
    assert already_extracted_source_ids(tmp_path) == {"a", "b"}

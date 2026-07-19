"""Unit tests for distill.claims.exports: the claims.jsonl append-only store."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

import distill.claims.exports as exports_mod
from distill.claims.exports import (
    already_extracted_source_ids,
    append_claims,
    claims_jsonl_path,
    read_claims,
    read_extracted_sources,
    record_extracted_sources,
)
from distill.claims.records import Claim, ClaimRole
from distill.jsonl import JsonlIntegrityError
from distill.library.source_ledger import SourceLedgerIntegrityError


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


def test_read_claims_fails_closed_on_non_object_or_malformed_rows(tmp_path: Path) -> None:
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

    with pytest.raises(JsonlIntegrityError) as caught:
        read_claims(tmp_path)
    assert str(path) in str(caught.value)

    with pytest.raises(JsonlIntegrityError):
        already_extracted_source_ids(tmp_path)


def test_path_is_under_dot_claims(tmp_path: Path) -> None:
    p = claims_jsonl_path(tmp_path)
    assert p.parent.name == ".claims"
    assert p.name == "claims.jsonl"


def test_append_then_read_round_trips(tmp_path: Path) -> None:
    claims = [_claim("a", "First claim."), _claim("b", "Second claim.")]
    append_claims(tmp_path, claims)
    read_back = read_claims(tmp_path)
    assert read_back == claims


def test_append_rejects_oversized_source_id_but_reads_legacy_row(tmp_path: Path) -> None:
    from distill.library.source_ledger import MAX_SOURCE_ID_BYTES

    oversized = "x" * (MAX_SOURCE_ID_BYTES + 1)
    claim = _claim(oversized, "Legacy claim.")

    with pytest.raises(JsonlIntegrityError, match="source-id limit"):
        append_claims(tmp_path, [claim])
    assert not claims_jsonl_path(tmp_path).exists()

    path = claims_jsonl_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(claim.to_jsonl_row()) + "\n", encoding="utf-8")
    assert read_claims(tmp_path) == [claim]


@pytest.mark.parametrize(
    "claim",
    [
        Claim("id", "", "p.md", "Claim.", ClaimRole.RESULT),
        Claim("id", "s", "p.md", "Claim.", ClaimRole.RESULT, role_confidence=float("nan")),
    ],
)
def test_append_rejects_invalid_runtime_claim_before_touching_store(
    tmp_path: Path, claim: Claim
) -> None:
    with pytest.raises(JsonlIntegrityError, match="Claim schema"):
        append_claims(tmp_path, [claim])

    assert not claims_jsonl_path(tmp_path).exists()


def test_append_is_additive(tmp_path: Path) -> None:
    append_claims(tmp_path, [_claim("a", "First.")])
    append_claims(tmp_path, [_claim("b", "Second.")])
    assert len(read_claims(tmp_path)) == 2


def test_read_missing_is_empty(tmp_path: Path) -> None:
    assert read_claims(tmp_path) == []
    assert already_extracted_source_ids(tmp_path) == set()


def test_read_rejects_malformed_canonical_evidence(tmp_path: Path) -> None:
    append_claims(tmp_path, [_claim("a", "Good.")])
    path = claims_jsonl_path(tmp_path)
    with path.open("a", encoding="utf-8") as f:
        f.write("not json\n")
        f.write('{"missing": "required fields"}\n')
        f.write("\n")  # blank line tolerated
    with pytest.raises(JsonlIntegrityError) as caught:
        read_claims(tmp_path)
    assert str(path) in str(caught.value)


def test_read_rejects_semantically_invalid_claim_with_exact_path(tmp_path: Path) -> None:
    path = claims_jsonl_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text('{"claim_id":"only-one-field"}\n', encoding="utf-8")

    with pytest.raises(JsonlIntegrityError) as caught:
        read_claims(tmp_path)

    assert str(path) in str(caught.value)
    assert "Claim schema" in str(caught.value)


def test_already_extracted_source_ids(tmp_path: Path) -> None:
    append_claims(tmp_path, [_claim("a", "One."), _claim("a", "Two."), _claim("b", "Three.")])
    assert already_extracted_source_ids(tmp_path) == {"a", "b"}


def test_append_claims_refuses_row_capacity_overflow_without_touching_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(exports_mod, "_MAX_CLAIMS_HISTORY_ROWS", 2)
    append_claims(tmp_path, [_claim("a", "First."), _claim("b", "Second.")])
    path = claims_jsonl_path(tmp_path)
    before = path.read_bytes()

    with pytest.raises(JsonlIntegrityError, match="append would exceed the 2-row limit"):
        append_claims(tmp_path, [_claim("c", "Third.")])

    assert path.read_bytes() == before


def test_append_claims_refuses_byte_capacity_overflow_without_touching_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    append_claims(tmp_path, [_claim("a", "First.")])
    path = claims_jsonl_path(tmp_path)
    before = path.read_bytes()
    monkeypatch.setattr(exports_mod, "_MAX_CLAIMS_HISTORY_BYTES", len(before) + 10)

    with pytest.raises(JsonlIntegrityError, match="append would exceed"):
        append_claims(tmp_path, [_claim("b", "Second claim is larger than ten bytes.")])

    assert path.read_bytes() == before


@pytest.mark.parametrize("damage", ["torn", "corrupt"])
def test_append_claims_refuses_damaged_history_without_touching_store(
    tmp_path: Path,
    damage: str,
) -> None:
    append_claims(tmp_path, [_claim("a", "First.")])
    path = claims_jsonl_path(tmp_path)
    content = path.read_bytes()
    damaged = content[:-1] if damage == "torn" else content + b"not-json\n"
    path.write_bytes(damaged)

    with pytest.raises(JsonlIntegrityError):
        append_claims(tmp_path, [_claim("b", "Second.")])

    assert path.read_bytes() == damaged


def test_concurrent_claim_batches_cannot_exceed_projected_capacity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(exports_mod, "_MAX_CLAIMS_HISTORY_ROWS", 3)
    append_claims(tmp_path, [_claim("seed", "Seed.")])
    batches = [
        [_claim("a1", "A one."), _claim("a2", "A two.")],
        [_claim("b1", "B one."), _claim("b2", "B two.")],
    ]

    def append_batch(batch: list[Claim]) -> str:
        try:
            append_claims(tmp_path, batch)
        except JsonlIntegrityError:
            return "refused"
        return "stored"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(append_batch, batches))

    assert sorted(outcomes) == ["refused", "stored"]
    assert len(read_claims(tmp_path)) == 3


def test_claim_ledger_rejects_linked_state_directory(tmp_path: Path) -> None:
    external = tmp_path / "external"
    external.mkdir()
    external_ledger = external / "extracted_sources.json"
    external_ledger.write_text('["outside"]', encoding="utf-8")
    linked = tmp_path / ".claims"
    try:
        linked.symlink_to(external, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlinks unavailable: {exc}")
    before = external_ledger.read_bytes()

    with pytest.raises(SourceLedgerIntegrityError, match="private directory"):
        read_extracted_sources(tmp_path)
    with pytest.raises(SourceLedgerIntegrityError, match="private directory"):
        record_extracted_sources(tmp_path, ["new"])

    assert external_ledger.read_bytes() == before

"""Unit tests for distill.claims.extract: row parsing, dedup, mocked LLM call."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from distill.claims.extract import (
    ClaimExtractionResult,
    claim_id_for,
    extract_claims_from_insight,
)
from distill.claims.records import ClaimRole
from distill.llm import RouterConfig


class _StubResponse:
    def __init__(self, text: str, model: str = "stub-model") -> None:
        self.text = text
        self.model = model
        self.input_tokens = 10
        self.output_tokens = 5


@pytest.fixture
def rc() -> RouterConfig:
    return RouterConfig()


def _write_insight(tmp_path: Path) -> Path:
    path = tmp_path / "papers" / "x" / "x_Insights.md"
    path.parent.mkdir(parents=True)
    path.write_text("---\npaper_id: x1\n---\n\nBody.\n", encoding="utf-8")
    return path


def test_claim_id_is_stable_under_whitespace_and_case():
    a = claim_id_for("src", "Rotary embeddings help.")
    b = claim_id_for("src", "rotary   EMBEDDINGS help.")
    assert a == b
    # Different source -> different id even with identical text.
    assert claim_id_for("other", "Rotary embeddings help.") != a
    assert a.startswith("src:")


def test_extract_parses_valid_rows(tmp_path: Path, rc: RouterConfig) -> None:
    insight = _write_insight(tmp_path)
    rows = [
        {
            "claim_text": "Rotary embeddings improve length generalization.",
            "rhetorical_role": "result",
            "dataset": "ICEWS",
            "metric": "MRR",
            "role_confidence": 0.9,
        },
        {
            "claim_text": "The approach was not tested beyond English.",
            "rhetorical_role": "limitation",
            "role_confidence": 0.4,
        },
    ]
    with patch("distill.claims.extract.llm_call", return_value=_StubResponse(json.dumps(rows))):
        result = extract_claims_from_insight(
            insight,
            topic="ai",
            source_id="x1",
            artifact_path="papers/x/x_Insights.md",
            rc=rc,
            now_iso="2026-05-30T00:00:00Z",
        )
    assert isinstance(result, ClaimExtractionResult)
    assert len(result.claims) == 2
    first = result.claims[0]
    assert first.rhetorical_role is ClaimRole.RESULT
    assert first.source_id == "x1"
    assert first.dataset == "ICEWS"
    assert first.extracted_at == "2026-05-30T00:00:00Z"
    assert result.claims[1].rhetorical_role is ClaimRole.LIMITATION


def test_extract_skips_malformed_rows(tmp_path: Path, rc: RouterConfig) -> None:
    insight = _write_insight(tmp_path)
    rows = [
        {"claim_text": "Valid result.", "rhetorical_role": "result"},
        {"claim_text": "", "rhetorical_role": "result"},  # empty text -> dropped
        {"claim_text": "Bad role.", "rhetorical_role": "speculation"},  # invalid role -> dropped
        {"rhetorical_role": "method"},  # missing text -> dropped
        "not a dict",  # non-dict -> dropped
    ]
    with patch("distill.claims.extract.llm_call", return_value=_StubResponse(json.dumps(rows))):
        result = extract_claims_from_insight(
            insight,
            topic="ai",
            source_id="x1",
            artifact_path="papers/x/x_Insights.md",
            rc=rc,
        )
    assert len(result.claims) == 1
    assert result.claims[0].claim_text == "Valid result."
    assert len(result.skipped_rows) == 4


def test_extract_dedups_within_one_call(tmp_path: Path, rc: RouterConfig) -> None:
    insight = _write_insight(tmp_path)
    rows = [
        {"claim_text": "Same claim here.", "rhetorical_role": "result"},
        {"claim_text": "same   CLAIM here.", "rhetorical_role": "result"},  # same id after norm
    ]
    with patch("distill.claims.extract.llm_call", return_value=_StubResponse(json.dumps(rows))):
        result = extract_claims_from_insight(
            insight,
            topic="ai",
            source_id="x1",
            artifact_path="papers/x/x_Insights.md",
            rc=rc,
        )
    assert len(result.claims) == 1


def test_extract_non_list_response_is_safe(tmp_path: Path, rc: RouterConfig) -> None:
    insight = _write_insight(tmp_path)
    with patch(
        "distill.claims.extract.llm_call",
        return_value=_StubResponse(json.dumps({"oops": "object not array"})),
    ):
        result = extract_claims_from_insight(
            insight,
            topic="ai",
            source_id="x1",
            artifact_path="papers/x/x_Insights.md",
            rc=rc,
        )
    assert result.claims == []
    assert result.parsed is False


def test_extract_clamps_out_of_range_confidence(tmp_path: Path, rc: RouterConfig) -> None:
    insight = _write_insight(tmp_path)
    rows = [
        {"claim_text": "High.", "rhetorical_role": "result", "role_confidence": 5},
        {"claim_text": "Low.", "rhetorical_role": "result", "role_confidence": -2},
        {"claim_text": "Junk.", "rhetorical_role": "result", "role_confidence": "abc"},
        {"claim_text": "Nan.", "rhetorical_role": "result", "role_confidence": "nan"},
    ]
    with patch("distill.claims.extract.llm_call", return_value=_StubResponse(json.dumps(rows))):
        result = extract_claims_from_insight(
            insight,
            topic="ai",
            source_id="x1",
            artifact_path="papers/x/x_Insights.md",
            rc=rc,
        )
    confs = [c.role_confidence for c in result.claims]
    assert confs == [1.0, 0.0, 0.5, 0.5]


def test_extract_missing_file_raises(tmp_path: Path, rc: RouterConfig) -> None:
    with pytest.raises(FileNotFoundError):
        extract_claims_from_insight(
            tmp_path / "nope_Insights.md",
            topic="ai",
            source_id="x1",
            artifact_path="papers/x/x_Insights.md",
            rc=rc,
        )

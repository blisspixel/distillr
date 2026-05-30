"""End-to-end tests for distill.claims.pipeline.run_claims (mocked LLM)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from distill.claims.exports import read_claims
from distill.claims.pipeline import ClaimsSummary, run_claims
from distill.llm import RouterConfig


class _StubResponse:
    def __init__(self, text: str, model: str = "stub-model") -> None:
        self.text = text
        self.model = model
        self.input_tokens = 10
        self.output_tokens = 5


def _make_insight(topic_dir: Path, *, source_type: str, slug: str, source_id: str) -> Path:
    path = topic_dir / source_type / slug / f"{slug}_Insights.md"
    path.parent.mkdir(parents=True)
    path.write_text(f"---\npaper_id: {source_id}\ntitle: {slug}\n---\n\nBody.\n", encoding="utf-8")
    return path


def _responses(*payloads):
    """side_effect that yields each payload (a list of rows) as JSON in order."""
    queue = [json.dumps(p) for p in payloads]

    def _side_effect(*_args, **_kwargs):
        return _StubResponse(queue.pop(0) if queue else "[]")

    return _side_effect


@pytest.fixture
def rc() -> RouterConfig:
    return RouterConfig()


def test_run_claims_extracts_and_appends(tmp_path: Path, rc: RouterConfig) -> None:
    _make_insight(tmp_path, source_type="papers", slug="pa", source_id="p1")
    _make_insight(tmp_path, source_type="papers", slug="pb", source_id="p2")
    side = _responses(
        [{"claim_text": "Claim one.", "rhetorical_role": "result"}],
        [
            {"claim_text": "Claim two.", "rhetorical_role": "method"},
            {"claim_text": "Claim three.", "rhetorical_role": "conclusion"},
        ],
    )
    with patch("distill.claims.extract.llm_call", side_effect=side):
        summary = run_claims(tmp_path, tmp_path, rc=rc, now_iso="2026-05-30T00:00:00Z")
    assert isinstance(summary, ClaimsSummary)
    assert summary.insights_scanned == 2
    assert summary.insights_extracted == 2
    assert summary.claims_added == 3
    assert summary.total_claims == 3
    assert len(read_claims(tmp_path)) == 3


def test_run_claims_skips_already_extracted(tmp_path: Path, rc: RouterConfig) -> None:
    _make_insight(tmp_path, source_type="papers", slug="pa", source_id="p1")
    side = _responses([{"claim_text": "Only claim.", "rhetorical_role": "result"}])
    with patch("distill.claims.extract.llm_call", side_effect=side) as mock_llm:
        run_claims(tmp_path, tmp_path, rc=rc, now_iso="2026-05-30T00:00:00Z")
        assert mock_llm.call_count == 1
        # Second run: source already in claims.jsonl -> no LLM call.
        summary2 = run_claims(tmp_path, tmp_path, rc=rc, now_iso="2026-05-30T00:00:00Z")
        assert mock_llm.call_count == 1
    assert summary2.insights_extracted == 0
    assert summary2.claims_added == 0
    assert summary2.total_claims == 1


def test_run_claims_refresh_reextracts(tmp_path: Path, rc: RouterConfig) -> None:
    _make_insight(tmp_path, source_type="papers", slug="pa", source_id="p1")
    side = _responses(
        [{"claim_text": "Only claim.", "rhetorical_role": "result"}],
        [{"claim_text": "Only claim.", "rhetorical_role": "result"}],
    )
    with patch("distill.claims.extract.llm_call", side_effect=side) as mock_llm:
        run_claims(tmp_path, tmp_path, rc=rc, now_iso="2026-05-30T00:00:00Z")
        run_claims(tmp_path, tmp_path, rc=rc, refresh=True, now_iso="2026-05-30T00:00:00Z")
        assert mock_llm.call_count == 2


def test_run_claims_no_insights(tmp_path: Path, rc: RouterConfig) -> None:
    summary = run_claims(tmp_path, tmp_path, rc=rc)
    assert summary.insights_scanned == 0
    assert summary.claims_added == 0


def test_run_claims_tolerates_extraction_failure(tmp_path: Path, rc: RouterConfig) -> None:
    _make_insight(tmp_path, source_type="papers", slug="pa", source_id="p1")
    _make_insight(tmp_path, source_type="papers", slug="pb", source_id="p2")

    calls = {"n": 0}

    def _side(*_args, **_kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("transient LLM error")
        return _StubResponse(json.dumps([{"claim_text": "Survivor.", "rhetorical_role": "result"}]))

    with patch("distill.claims.extract.llm_call", side_effect=_side):
        summary = run_claims(tmp_path, tmp_path, rc=rc, now_iso="2026-05-30T00:00:00Z")
    # One source failed, one succeeded -> one claim, no crash.
    assert summary.claims_added == 1
    assert summary.total_claims == 1

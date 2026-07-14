"""End-to-end tests for distill.claims.pipeline.run_claims (mocked LLM)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from distill.claims import pipeline as pipeline_mod
from distill.claims.exports import read_claims, record_extracted_sources
from distill.claims.pipeline import ClaimsSummary, pending_claim_extraction_count, run_claims
from distill.llm import RouterConfig
from distill.pipeline.costs import BudgetExceededError, CostTracker


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


def test_run_claims_rejects_insight_changed_after_discovery(
    tmp_path: Path, rc: RouterConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    insight = _make_insight(tmp_path, source_type="papers", slug="pa", source_id="p1")
    refs = pipeline_mod.discover_insights(tmp_path)
    insight.write_text("tampered claim content", encoding="utf-8")
    monkeypatch.setattr(
        pipeline_mod,
        "discover_insights",
        lambda *_args, **_kwargs: refs,
    )

    with patch("distill.claims.extract.llm_call") as mock_llm:
        summary = run_claims(tmp_path, tmp_path, rc=rc)

    mock_llm.assert_not_called()
    assert summary.claims_added == 0


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


def test_run_claims_does_not_reextract_zero_claim_source(tmp_path: Path, rc: RouterConfig) -> None:
    # A source that yields zero claims has no claims.jsonl row, but the
    # extracted-sources ledger records it, so the next run does not re-issue a
    # (wasted) LLM call for it.
    _make_insight(tmp_path, source_type="papers", slug="pa", source_id="p1")
    side = _responses([])  # extraction returns zero claims
    with patch("distill.claims.extract.llm_call", side_effect=side) as mock_llm:
        s1 = run_claims(tmp_path, tmp_path, rc=rc, now_iso="2026-05-30T00:00:00Z")
        assert mock_llm.call_count == 1
        assert s1.claims_added == 0
        s2 = run_claims(tmp_path, tmp_path, rc=rc, now_iso="2026-05-30T00:00:00Z")
        assert mock_llm.call_count == 1  # not re-extracted
    assert s2.insights_extracted == 0


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


def test_pending_claim_extraction_count_respects_ledger_and_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _make_insight(tmp_path, source_type="papers", slug="pa", source_id="p1")
    _make_insight(tmp_path, source_type="papers", slug="pb", source_id="p2")
    _make_insight(tmp_path, source_type="papers", slug="pc", source_id="p3")
    record_extracted_sources(tmp_path, ["p1"])

    monkeypatch.setenv("DISTILL_CLAIMS_MAX_INSIGHTS", "1")
    assert pending_claim_extraction_count(tmp_path) == 1

    monkeypatch.setenv("DISTILL_CLAIMS_MAX_INSIGHTS", "0")
    assert pending_claim_extraction_count(tmp_path) == 2

    monkeypatch.setenv("DISTILL_CLAIMS_MAX_INSIGHTS", "9" * 100)
    assert pending_claim_extraction_count(tmp_path) == 2


@pytest.mark.parametrize("raw", ["\u00b2", "\u0661\u0662", "9" * 5000])
def test_claim_limit_rejects_non_ascii_or_oversized_integer(
    monkeypatch: pytest.MonkeyPatch, raw: str
) -> None:
    monkeypatch.setenv("DISTILL_CLAIMS_MAX_INSIGHTS", raw)

    assert pipeline_mod._max_insights_per_run() == 250


def test_run_claims_caps_pending_insights(
    tmp_path: Path, rc: RouterConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    _make_insight(tmp_path, source_type="papers", slug="pa", source_id="p1")
    _make_insight(tmp_path, source_type="papers", slug="pb", source_id="p2")
    monkeypatch.setenv("DISTILL_CLAIMS_MAX_INSIGHTS", "1")

    with patch("distill.claims.extract.llm_call", side_effect=_responses([])) as mock_llm:
        summary = run_claims(tmp_path, tmp_path, rc=rc, now_iso="2026-05-30T00:00:00Z")

    assert summary.insights_scanned == 2
    assert summary.insights_extracted == 1
    assert mock_llm.call_count == 1


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


def test_run_claims_budget_crossing_stops_before_later_insights(
    tmp_path: Path, rc: RouterConfig
) -> None:
    _make_insight(tmp_path, source_type="papers", slug="pa", source_id="p1")
    _make_insight(tmp_path, source_type="papers", slug="pb", source_id="p2")
    tracker = CostTracker(budget=0.0)

    with (
        patch(
            "distill.claims.extract.llm_call",
            return_value=_StubResponse("[]", model="grok-4.3"),
        ) as mock_llm,
        pytest.raises(BudgetExceededError),
    ):
        run_claims(
            "topic",
            tmp_path,
            rc=rc,
            tracker=tracker,
            now_iso="2026-05-30T00:00:00Z",
        )

    assert mock_llm.call_count == 1
    assert len(tracker.entries) == 1
    assert not (tmp_path / ".claims" / "extracted_sources.json").exists()

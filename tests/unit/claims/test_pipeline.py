"""End-to-end tests for distill.claims.pipeline.run_claims (mocked LLM)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from distill.claims import pipeline as pipeline_mod
from distill.claims.exports import read_claims, read_extracted_sources, record_extracted_sources
from distill.claims.extract import ClaimExtractionResult
from distill.claims.pipeline import ClaimsSummary, pending_claim_extraction_count, run_claims
from distill.claims.records import Claim, ClaimRole
from distill.jsonl import JsonlIntegrityError
from distill.library.source_ledger import MAX_SOURCE_ID_BYTES, SourceLedgerIntegrityError
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


def test_run_claims_does_not_complete_unparsed_response(tmp_path: Path, rc: RouterConfig) -> None:
    _make_insight(tmp_path, source_type="papers", slug="pa", source_id="p1")
    side = _responses("sorry, here is prose instead of claims")
    with patch("distill.claims.extract.llm_call", side_effect=side) as mock_llm:
        first = run_claims(tmp_path, tmp_path, rc=rc, now_iso="2026-05-30T00:00:00Z")
        assert mock_llm.call_count == 1
        assert first.claims_added == 0
        second = run_claims(tmp_path, tmp_path, rc=rc, now_iso="2026-05-30T00:00:00Z")
        assert mock_llm.call_count == 2
    assert second.insights_extracted == 1


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


def test_full_claim_store_fails_before_provider_work(
    tmp_path: Path,
    rc: RouterConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import distill.claims.exports as exports_mod

    pipeline_mod.append_claims(tmp_path, [_checkpoint_claim("p1")])
    _make_insight(tmp_path, source_type="papers", slug="pb", source_id="p2")
    monkeypatch.setattr(exports_mod, "_MAX_CLAIMS_HISTORY_ROWS", 1)
    provider_called = False

    def unexpected_provider(*_args, **_kwargs) -> ClaimExtractionResult:
        nonlocal provider_called
        provider_called = True
        return ClaimExtractionResult([], "stub", "claims.extract.v1", [])

    monkeypatch.setattr(pipeline_mod, "extract_claims_from_insight", unexpected_provider)

    with pytest.raises(JsonlIntegrityError, match="history reached the 1-row limit"):
        run_claims(tmp_path, tmp_path, rc=rc)

    assert provider_called is False


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


def _checkpoint_claim(source_id: str) -> Claim:
    number = int(source_id.removeprefix("p"))
    slug = f"p{chr(ord('a') + number - 1)}"
    return Claim(
        claim_id=f"{source_id}:checkpoint",
        source_id=source_id,
        artifact_path=f"papers/{slug}/{slug}_Insights.md",
        claim_text=f"Claim from {source_id}.",
        rhetorical_role=ClaimRole.RESULT,
        role_confidence=0.8,
        extracted_at="2026-05-30T00:00:00Z",
    )


def test_budget_stop_preserves_prior_claim_and_completion_checkpoint(
    tmp_path: Path, rc: RouterConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    _make_insight(tmp_path, source_type="papers", slug="pa", source_id="p1")
    _make_insight(tmp_path, source_type="papers", slug="pb", source_id="p2")
    calls: list[str] = []

    def extract(*_args, source_id: str, **_kwargs) -> ClaimExtractionResult:
        calls.append(source_id)
        if source_id == "p2":
            raise BudgetExceededError(2.0, 1.0)
        return ClaimExtractionResult(
            [_checkpoint_claim(source_id)],
            "stub-model",
            "claims.extract.v1",
            [],
        )

    monkeypatch.setattr(pipeline_mod, "extract_claims_from_insight", extract)

    with pytest.raises(BudgetExceededError):
        run_claims("topic", tmp_path, rc=rc)

    assert calls == ["p1", "p2"]
    assert [claim.source_id for claim in read_claims(tmp_path)] == ["p1"]
    assert read_extracted_sources(tmp_path) == {"p1"}
    assert pending_claim_extraction_count(tmp_path) == 1


def test_budget_stop_preserves_prior_zero_claim_checkpoint(
    tmp_path: Path, rc: RouterConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    _make_insight(tmp_path, source_type="papers", slug="pa", source_id="p1")
    _make_insight(tmp_path, source_type="papers", slug="pb", source_id="p2")

    def extract(*_args, source_id: str, **_kwargs) -> ClaimExtractionResult:
        if source_id == "p2":
            raise BudgetExceededError(2.0, 1.0)
        return ClaimExtractionResult([], "stub-model", "claims.extract.v1", [])

    monkeypatch.setattr(pipeline_mod, "extract_claims_from_insight", extract)

    with pytest.raises(BudgetExceededError):
        run_claims("topic", tmp_path, rc=rc)

    assert read_claims(tmp_path) == []
    assert read_extracted_sources(tmp_path) == {"p1"}
    assert pending_claim_extraction_count(tmp_path) == 1


def test_claim_append_failure_never_publishes_completion(
    tmp_path: Path, rc: RouterConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    _make_insight(tmp_path, source_type="papers", slug="pa", source_id="p1")
    monkeypatch.setattr(
        pipeline_mod,
        "extract_claims_from_insight",
        lambda *_args, **_kwargs: ClaimExtractionResult(
            [_checkpoint_claim("p1")], "stub-model", "claims.extract.v1", []
        ),
    )

    def fail_append(*_args, **_kwargs) -> None:
        raise OSError("simulated durable append failure")

    monkeypatch.setattr(pipeline_mod, "append_claims", fail_append)

    with pytest.raises(OSError, match="durable append failure"):
        run_claims("topic", tmp_path, rc=rc)

    assert read_extracted_sources(tmp_path) == set()


def test_next_run_repairs_completion_after_ledger_publish_failure(
    tmp_path: Path, rc: RouterConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    _make_insight(tmp_path, source_type="papers", slug="pa", source_id="p1")
    monkeypatch.setattr(
        pipeline_mod,
        "extract_claims_from_insight",
        lambda *_args, **_kwargs: ClaimExtractionResult(
            [_checkpoint_claim("p1")], "stub-model", "claims.extract.v1", []
        ),
    )
    real_record = pipeline_mod.record_extracted_sources
    provider_calls = 0

    def count_provider(*_args, **_kwargs) -> ClaimExtractionResult:
        nonlocal provider_calls
        provider_calls += 1
        return ClaimExtractionResult(
            [_checkpoint_claim("p1")], "stub-model", "claims.extract.v1", []
        )

    monkeypatch.setattr(pipeline_mod, "extract_claims_from_insight", count_provider)
    monkeypatch.setattr(
        pipeline_mod,
        "record_extracted_sources",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("ledger publish failed")),
    )

    with pytest.raises(OSError, match="ledger publish failed"):
        run_claims("topic", tmp_path, rc=rc)

    assert provider_calls == 1
    assert [claim.source_id for claim in read_claims(tmp_path)] == ["p1"]
    assert read_extracted_sources(tmp_path) == set()

    monkeypatch.setattr(pipeline_mod, "record_extracted_sources", real_record)
    summary = run_claims("topic", tmp_path, rc=rc)

    assert provider_calls == 1
    assert summary.insights_extracted == 0
    assert read_extracted_sources(tmp_path) == {"p1"}


def test_zero_claim_ledger_failure_aborts_before_later_provider_work(
    tmp_path: Path, rc: RouterConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    _make_insight(tmp_path, source_type="papers", slug="pa", source_id="p1")
    _make_insight(tmp_path, source_type="papers", slug="pb", source_id="p2")
    calls: list[str] = []

    def extract(*_args, source_id: str, **_kwargs) -> ClaimExtractionResult:
        calls.append(source_id)
        return ClaimExtractionResult([], "stub", "claims.extract.v1", [])

    def fail_ledger(*_args, **_kwargs) -> None:
        raise OSError("ledger publish failed")

    monkeypatch.setattr(pipeline_mod, "extract_claims_from_insight", extract)
    monkeypatch.setattr(pipeline_mod, "record_extracted_sources", fail_ledger)

    with pytest.raises(OSError, match="ledger publish failed"):
        run_claims("topic", tmp_path, rc=rc)

    assert calls == ["p1"]
    assert read_claims(tmp_path) == []
    assert read_extracted_sources(tmp_path) == set()


@pytest.mark.parametrize("mismatch", ["source", "artifact", "duplicate"])
def test_invalid_per_source_claim_batch_never_reaches_storage(
    tmp_path: Path,
    rc: RouterConfig,
    monkeypatch: pytest.MonkeyPatch,
    mismatch: str,
) -> None:
    _make_insight(tmp_path, source_type="papers", slug="pa", source_id="p1")
    claim = _checkpoint_claim("p1")
    if mismatch == "source":
        claim = Claim(
            claim.claim_id,
            "other",
            claim.artifact_path,
            claim.claim_text,
            claim.rhetorical_role,
        )
    elif mismatch == "artifact":
        claim = Claim(
            claim.claim_id,
            claim.source_id,
            "papers/other/other_Insights.md",
            claim.claim_text,
            claim.rhetorical_role,
        )
    claims = [claim, claim] if mismatch == "duplicate" else [claim]
    monkeypatch.setattr(
        pipeline_mod,
        "extract_claims_from_insight",
        lambda *_args, **_kwargs: ClaimExtractionResult(claims, "stub", "claims.extract.v1", []),
    )

    with pytest.raises(ValueError):
        run_claims("topic", tmp_path, rc=rc)

    assert read_claims(tmp_path) == []
    assert read_extracted_sources(tmp_path) == set()


@pytest.mark.parametrize("refresh", [False, True])
def test_invalid_completion_ledger_fails_before_provider_work(
    tmp_path: Path,
    rc: RouterConfig,
    monkeypatch: pytest.MonkeyPatch,
    refresh: bool,
) -> None:
    _make_insight(tmp_path, source_type="papers", slug="pa", source_id="p1")
    ledger = tmp_path / ".claims" / "extracted_sources.json"
    ledger.parent.mkdir(parents=True)
    ledger.write_text("not-json", encoding="utf-8")
    provider_called = False

    def unexpected_provider(*_args, **_kwargs) -> ClaimExtractionResult:
        nonlocal provider_called
        provider_called = True
        return ClaimExtractionResult([], "stub", "claims.extract.v1", [])

    monkeypatch.setattr(pipeline_mod, "extract_claims_from_insight", unexpected_provider)

    with pytest.raises(SourceLedgerIntegrityError) as caught:
        run_claims("topic", tmp_path, rc=rc, refresh=refresh)

    assert str(ledger) in str(caught.value)
    assert provider_called is False


def test_oversized_source_id_is_refused_before_provider_or_claim_state(
    tmp_path: Path,
    rc: RouterConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    oversized = "\U0001f600" * (MAX_SOURCE_ID_BYTES // 4 + 1)
    _make_insight(tmp_path, source_type="papers", slug="pa", source_id=oversized)
    provider_calls = 0

    def unexpected_provider(*_args, **_kwargs) -> ClaimExtractionResult:
        nonlocal provider_calls
        provider_calls += 1
        return ClaimExtractionResult([], "stub", "claims.extract.v1", [])

    monkeypatch.setattr(pipeline_mod, "extract_claims_from_insight", unexpected_provider)

    for _ in range(2):
        with pytest.raises(SourceLedgerIntegrityError, match="source-id limit"):
            run_claims("topic", tmp_path, rc=rc)

    assert provider_calls == 0
    assert read_claims(tmp_path) == []
    assert not (tmp_path / ".claims" / "extracted_sources.json").exists()


def test_projected_claim_ledger_overflow_is_refused_before_provider(
    tmp_path: Path,
    rc: RouterConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import distill.library.source_ledger as source_ledger_mod

    record_extracted_sources(tmp_path, ["safe"])
    ledger = tmp_path / ".claims" / "extracted_sources.json"
    before = ledger.read_bytes()
    monkeypatch.setattr(source_ledger_mod, "MAX_SOURCE_LEDGER_BYTES", len(before) + 8)
    _make_insight(
        tmp_path,
        source_type="papers",
        slug="pa",
        source_id="a-new-source-id",
    )
    provider_called = False

    def unexpected_provider(*_args, **_kwargs) -> ClaimExtractionResult:
        nonlocal provider_called
        provider_called = True
        return ClaimExtractionResult([], "stub", "claims.extract.v1", [])

    monkeypatch.setattr(pipeline_mod, "extract_claims_from_insight", unexpected_provider)

    with pytest.raises(SourceLedgerIntegrityError, match="serialized ledger"):
        run_claims("topic", tmp_path, rc=rc)

    assert provider_called is False
    assert ledger.read_bytes() == before
    assert read_claims(tmp_path) == []


def test_claim_transaction_serializes_real_process_extraction(tmp_path: Path) -> None:
    topic_dir = tmp_path / "topic"
    _make_insight(topic_dir, source_type="papers", slug="pa", source_id="p1")
    call_log = tmp_path / "calls.jsonl"
    script = "\n".join(
        [
            "import sys, time",
            "from pathlib import Path",
            "from unittest.mock import patch",
            "from distill.claims.extract import ClaimExtractionResult",
            "from distill.claims.pipeline import run_claims",
            "from distill.claims.records import Claim, ClaimRole",
            "from distill.jsonl import append_jsonl_line",
            "from distill.llm import RouterConfig",
            "topic_dir, call_log = Path(sys.argv[1]), Path(sys.argv[2])",
            "def extract(*args, source_id, artifact_path, **kwargs):",
            "    append_jsonl_line(call_log, '{\"source_id\":\"' + source_id + '\"}')",
            "    time.sleep(0.3)",
            "    claim = Claim(source_id + ':id', source_id, artifact_path, 'Claim.', ClaimRole.RESULT)",
            "    return ClaimExtractionResult([claim], 'stub', 'claims.extract.v1', [])",
            "with patch('distill.claims.pipeline.extract_claims_from_insight', extract):",
            "    run_claims('topic', topic_dir, rc=RouterConfig())",
        ]
    )
    processes = [
        subprocess.Popen(
            [sys.executable, "-c", script, str(topic_dir), str(call_log)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(2)
    ]

    failures: list[str] = []
    for process in processes:
        stdout, stderr = process.communicate(timeout=30)
        if process.returncode:
            failures.append(f"exit={process.returncode} stdout={stdout!r} stderr={stderr!r}")

    assert failures == []
    assert len(call_log.read_text(encoding="utf-8").splitlines()) == 1
    assert [claim.source_id for claim in read_claims(topic_dir)] == ["p1"]

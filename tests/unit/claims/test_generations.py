from __future__ import annotations

import pytest

from distill.claims import pipeline
from distill.claims.exports import append_claims, read_active_claims, read_claims
from distill.claims.extract import ClaimExtractionResult
from distill.claims.generations import ClaimGeneration, active_generation_claims
from distill.claims.records import Claim, ClaimRole, parse_claim_origin
from distill.llm import RouterConfig


def _claim(text="old"):
    return Claim(text, "p1", "papers/p/p_Insights.md", text, ClaimRole.RESULT)


@pytest.fixture
def source(tmp_path, monkeypatch):
    topic = tmp_path / "library" / "topics" / "t"
    insight = topic / "papers" / "p" / "p_Insights.md"
    insight.parent.mkdir(parents=True)
    insight.write_text("---\npaper_id: p1\nsource: arxiv\n---\nold", encoding="utf-8")
    results = [ClaimExtractionResult([_claim()], "test", "test", [])]
    monkeypatch.setattr(pipeline, "extract_claims_from_insight", lambda *a, **k: results.pop(0))
    return topic, insight, results


def _run(topic, **kwargs):
    return pipeline.run_claims("t", topic, rc=RouterConfig(), **kwargs)


def test_refresh_replaces_generation_and_zero_claims_retire_previous(source):
    topic, _insight, results = source
    _run(topic)
    results.append(ClaimExtractionResult([_claim("new")], "test", "test", []))
    _run(topic, refresh=True)
    assert [c.claim_text for c in read_active_claims(topic)] == ["new"]
    assert [c.claim_text for c in read_claims(topic)] == ["old", "new"]
    results.append(ClaimExtractionResult([], "test", "test", []))
    _run(topic, refresh=True)
    assert read_active_claims(topic) == []
    assert len(read_claims(topic)) == 2
    assert _run(topic).insights_extracted == 0


@pytest.mark.parametrize("parsed,skipped", [(False, []), (True, ["invalid row"])])
def test_incomplete_extraction_cannot_replace_previous(source, parsed, skipped):
    topic, insight, results = source
    _run(topic)
    insight.write_text(insight.read_text(encoding="utf-8") + " changed", encoding="utf-8")
    results.append(
        ClaimExtractionResult([_claim("partial")], "test", "test", skipped, parsed=parsed)
    )
    summary = _run(topic)
    assert summary.incomplete == 1
    assert [c.claim_text for c in read_active_claims(topic)] == ["old"]
    assert len(read_claims(topic)) == 1


def test_changed_artifact_is_reextracted_without_force(source):
    topic, insight, results = source
    _run(topic)
    insight.write_text(insight.read_text(encoding="utf-8") + " changed", encoding="utf-8")
    results.append(ClaimExtractionResult([_claim("changed")], "test", "test", []))
    assert _run(topic).insights_extracted == 1
    assert [c.claim_text for c in read_active_claims(topic)] == ["changed"]


@pytest.mark.parametrize("legacy", [False, True])
def test_failed_explicit_refresh_stays_incomplete_even_when_content_is_unchanged(source, legacy):
    topic, _insight, results = source
    if legacy:
        append_claims(topic, [_claim()])
        results.clear()
    else:
        _run(topic)
    results.append(ClaimExtractionResult([], "test", "test", ["invalid row"]))
    summary = _run(topic, refresh=True)
    assert summary.incomplete == 1
    assert [c.claim_text for c in read_active_claims(topic)] == ["old"]


def test_derived_origin_survives_extraction_and_persistence(source):
    topic, insight, _results = source
    insight.write_text(
        insight.read_text(encoding="utf-8").replace("source: arxiv", "source: distill-answer"),
        encoding="utf-8",
    )
    _run(topic)
    assert read_active_claims(topic)[0].origin == "derived"


def test_legacy_history_remains_readable_but_successful_generation_replaces_it(source):
    topic, _insight, _results = source
    append_claims(topic, [_claim("legacy")])
    assert read_active_claims(topic)[0].origin == "unknown"
    _run(topic, refresh=True)
    assert [c.claim_text for c in read_active_claims(topic)] == ["old"]
    assert len(read_claims(topic)) == 2


def test_failed_generation_append_keeps_previous_active(source, monkeypatch):
    topic, _insight, results = source
    _run(topic)
    results.append(ClaimExtractionResult([_claim("new")], "test", "test", []))

    def fail(*args, **kwargs):
        raise OSError("publication failed")

    monkeypatch.setattr(pipeline, "append_claims", fail)
    with pytest.raises(OSError, match="publication failed"):
        _run(topic, refresh=True)
    assert [c.claim_text for c in read_active_claims(topic)] == ["old"]


def test_generation_rejects_cross_artifact_claim():
    row = ClaimGeneration("other", "papers/p/p_Insights.md", "0" * 64, (_claim(),)).to_row()
    with pytest.raises(ValueError, match="identity"):
        ClaimGeneration.from_row(row)
    with pytest.raises(ValueError, match="Unsupported"):
        active_generation_claims([{"event": "unknown"}])
    with pytest.raises(ValueError, match="origin"):
        parse_claim_origin("independent")


@pytest.mark.parametrize(
    "replacement",
    [
        {"source_id": None},
        {"artifact_path": ""},
        {"content_sha256": "invalid"},
        {"claims": {}},
        {"claims": ["invalid"]},
        {"claims": [_claim().to_jsonl_row(), _claim().to_jsonl_row()]},
    ],
)
def test_generation_rejects_malformed_or_duplicate_payload(replacement):
    row = ClaimGeneration("p1", "papers/p/p_Insights.md", "0" * 64, (_claim(),)).to_row()
    with pytest.raises(ValueError):
        ClaimGeneration.from_row({**row, **replacement})


def test_active_and_completion_readers_enforce_full_history_limits(tmp_path, monkeypatch):
    import json

    from distill.claims import exports
    from distill.jsonl import JsonlIntegrityError

    claims = tuple(_claim(str(index)) for index in range(3))
    generation = ClaimGeneration("p1", "papers/p/p_Insights.md", "0" * 64, claims)
    path = exports.claims_jsonl_path(tmp_path)
    path.parent.mkdir()
    path.write_text(json.dumps(generation.to_row()) + "\n", encoding="utf-8")
    monkeypatch.setattr(exports, "_MAX_CLAIMS_HISTORY_ROWS", 2)
    for reader in (exports.read_claims, exports.read_active_claims, exports.completed_generations):
        with pytest.raises(JsonlIntegrityError, match="Flattened claim history"):
            reader(tmp_path)


def test_append_rejects_a_generation_with_a_different_claim_batch(tmp_path):
    from distill.jsonl import JsonlIntegrityError

    generation = ClaimGeneration("p1", "papers/p/p_Insights.md", "0" * 64, (_claim(),))
    with pytest.raises(JsonlIntegrityError, match="does not match"):
        append_claims(tmp_path, [], generation=generation)
    assert read_claims(tmp_path) == []

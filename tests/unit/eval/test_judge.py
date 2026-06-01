"""Tests for distill.eval.judge (advisory LLM-judge, mocked LLM)."""

from types import SimpleNamespace

from distill.eval import judge as judge_mod
from distill.eval.judge import judge_output
from distill.pipeline.costs import CostTracker


def _fake_response(text: str):
    return SimpleNamespace(text=text, input_tokens=120, output_tokens=40, model="grok-4.3")


def test_judge_parses_and_records_cost(monkeypatch):
    monkeypatch.setattr(
        judge_mod,
        "llm_call",
        lambda *a, **k: _fake_response(
            '{"faithfulness": 0.9, "depth": 0.6, "coverage": 0.75, "rationale": "solid"}'
        ),
    )
    tracker = CostTracker()
    score = judge_output(
        "source", "analysis", candidate_model="qwen3.5:27b", judge_model="grok-4.3", tracker=tracker
    )
    assert score is not None
    assert score.faithfulness == 0.9
    assert round(score.overall, 4) == round((0.9 + 0.6 + 0.75) / 3, 4)
    assert score.rationale == "solid"
    assert len(tracker.entries) == 1
    assert tracker.entries[0].call_type == "eval_judge"


def test_judge_refuses_to_grade_its_own_model(monkeypatch):
    called = {"n": 0}

    def _fail(*a, **k):
        called["n"] += 1
        raise AssertionError("should not call the LLM for self-judging")

    monkeypatch.setattr(judge_mod, "llm_call", _fail)
    score = judge_output("s", "o", candidate_model="grok-4.3", judge_model="grok-4.3")
    assert score is None
    assert called["n"] == 0


def test_judge_tolerates_unparseable_response(monkeypatch):
    monkeypatch.setattr(judge_mod, "llm_call", lambda *a, **k: _fake_response("not json at all"))
    score = judge_output("s", "o", candidate_model="x", judge_model="grok-4.3")
    assert score is None  # deterministic-only fallback, no crash

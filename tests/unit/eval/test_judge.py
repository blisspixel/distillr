"""Tests for distill.eval.judge (advisory pairwise judge, mocked LLM)."""

from types import SimpleNamespace

from distill.eval import judge as judge_mod
from distill.eval.judge import judge_pairwise, judge_shares_family
from distill.pipeline.costs import CostTracker


def _resp(text: str):
    return SimpleNamespace(text=text, input_tokens=200, output_tokens=30, model="grok-4.3")


def test_pairwise_candidate_always_wins_both_orderings(monkeypatch):
    # Judge always picks the candidate, whichever slot it's in:
    # ordering 1 candidate=A -> winner A; ordering 2 candidate=B -> winner B.
    seq = iter(
        [
            '{"winner": "A", "rationale": "cand better"}',
            '{"winner": "B", "rationale": "cand better"}',
        ]
    )
    monkeypatch.setattr(judge_mod, "llm_call", lambda *a, **k: _resp(next(seq)))
    tracker = CostTracker()
    res = judge_pairwise("src", "cand", "anchor", judge_model="grok-4.3", tracker=tracker)
    assert res is not None
    assert res.win_rate == 1.0
    assert res.comparisons == 2
    assert len(tracker.entries) == 2  # both orderings priced


def test_pairwise_position_bias_cancels(monkeypatch):
    # A judge that ALWAYS prefers slot A regardless of content: ordering1 (cand=A)
    # -> cand wins; ordering2 (anchor=A) -> anchor wins. Averages to a 0.5 tie,
    # i.e. the position bias cancels rather than crowning the candidate.
    monkeypatch.setattr(
        judge_mod, "llm_call", lambda *a, **k: _resp('{"winner": "A", "rationale": "slot A"}')
    )
    res = judge_pairwise("src", "cand", "anchor", judge_model="grok-4.3")
    assert res is not None
    assert res.win_rate == 0.5


def test_pairwise_returns_none_when_unparseable(monkeypatch):
    monkeypatch.setattr(judge_mod, "llm_call", lambda *a, **k: _resp("no json here"))
    assert judge_pairwise("s", "c", "a", judge_model="grok-4.3") is None


def test_judge_shares_family():
    assert judge_shares_family("grok-4.3", "grok-4.20") is True
    assert judge_shares_family("grok-4.3", "qwen3.5:27b") is False
    assert judge_shares_family("gemini-3.1-pro", "grok-4.3") is False

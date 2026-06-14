"""Tests for distill.eval.judge (pairwise + faithfulness model judges, mocked LLM)."""

from types import SimpleNamespace

from distill.eval import judge as judge_mod
from distill.eval.judge import (
    FAITHFULNESS_ORDINAL,
    _faithfulness_prompt,
    _pairwise_prompt,
    judge_faithfulness,
    judge_pairwise,
    judge_shares_family,
)
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


def test_pairwise_returns_none_when_only_one_ordering_parses(monkeypatch):
    # A single parseable ordering is position-biased; without both there is no
    # debiased verdict, so the result is None (deterministic-only) rather than a
    # biased win-rate reported as if it were debiased.
    seq = iter(
        [
            '{"winner": "A", "rationale": "cand better"}',  # ordering 1 parses
            "garbage, no json",  # ordering 2 fails
        ]
    )
    monkeypatch.setattr(judge_mod, "llm_call", lambda *a, **k: _resp(next(seq)))
    assert judge_pairwise("s", "c", "a", judge_model="grok-4.3") is None


def test_judge_routes_to_its_own_provider(monkeypatch):
    # A gemini judge must hit the gemini endpoint, not the default xAI one
    # (the bug that returned "Model not found: gemini-3.1-pro" from grok).
    captured: dict = {}

    def fake_call(config, **kwargs):
        captured["provider"] = config.provider
        captured["model"] = config.model
        return _resp('{"winner": "A", "rationale": "x"}')

    monkeypatch.setattr(judge_mod, "llm_call", fake_call)
    judge_pairwise("s", "cand", "anchor", judge_model="gemini-3.1-pro")
    assert captured["provider"] == "gemini"
    assert captured["model"] == "gemini-3.1-pro"


def test_judge_shares_family():
    assert judge_shares_family("grok-4.3", "grok-4.20") is True
    assert judge_shares_family("grok-4.3", "qwen3.5:27b") is False
    assert judge_shares_family("gemini-3.1-pro", "grok-4.3") is False


def test_prompt_is_rubric_structured_with_bias_guards():
    # The rubric criteria and the explicit anti-verbosity / anti-position guards
    # are the whole point of the rewrite — assert they survive in the prompt.
    prompt = _pairwise_prompt("SRC", "A out", "B out")
    for marker in ("Faithfulness", "Substance", "Coverage", "Conciseness"):
        assert marker in prompt
    assert "Length is NOT quality" in prompt
    assert "ignore which analysis is shown first" in prompt
    # No heuristics supplied -> no advisory block.
    assert "ADVISORY HEURISTIC SIGNALS" not in prompt


def test_prompt_includes_heuristics_block_when_supplied():
    prompt = _pairwise_prompt("SRC", "A out", "B out", "depth 0.90", "depth 0.20")
    assert "ADVISORY HEURISTIC SIGNALS" in prompt
    assert "weak prior" in prompt  # framed as noisy, not a verdict
    assert "A: depth 0.90" in prompt
    assert "B: depth 0.20" in prompt


def test_faithfulness_parses_faithful_verdict(monkeypatch):
    monkeypatch.setattr(
        judge_mod,
        "llm_call",
        lambda *a, **k: _resp(
            '{"verdict": "faithful", "unsupported": [], "rationale": "all good"}'
        ),
    )
    tracker = CostTracker()
    v = judge_faithfulness("SRC", "analysis", judge_model="grok-4.3", tracker=tracker)
    assert v is not None
    assert v.label == "faithful"
    assert v.ordinal == FAITHFULNESS_ORDINAL["faithful"] == 2
    assert v.unsupported == ()
    assert len(tracker.entries) == 1  # single absolute call (no A/B debias needed)


def test_faithfulness_parses_unfaithful_with_unsupported_claims(monkeypatch):
    monkeypatch.setattr(
        judge_mod,
        "llm_call",
        lambda *a, **k: _resp(
            '{"verdict": "unfaithful", "unsupported": ["MRR of 99.9", "invented dataset XYZ"], '
            '"rationale": "two numbers absent from the source"}'
        ),
    )
    v = judge_faithfulness("SRC", "analysis", judge_model="grok-4.3")
    assert v is not None
    assert v.label == "unfaithful"
    assert v.ordinal == 0
    assert v.unsupported == ("MRR of 99.9", "invented dataset XYZ")


def test_faithfulness_returns_none_on_unparseable(monkeypatch):
    monkeypatch.setattr(judge_mod, "llm_call", lambda *a, **k: _resp("no json at all"))
    assert judge_faithfulness("s", "o", judge_model="grok-4.3") is None


def test_faithfulness_returns_none_on_unknown_label(monkeypatch):
    # A verdict outside the fixed scale is no signal, not a silently-coerced one.
    monkeypatch.setattr(
        judge_mod, "llm_call", lambda *a, **k: _resp('{"verdict": "mostly ok", "rationale": "x"}')
    )
    assert judge_faithfulness("s", "o", judge_model="grok-4.3") is None


def test_faithfulness_routes_to_its_own_provider(monkeypatch):
    captured: dict = {}

    def fake_call(config, **kwargs):
        captured["provider"] = config.provider
        captured["model"] = config.model
        return _resp('{"verdict": "faithful", "rationale": "x"}')

    monkeypatch.setattr(judge_mod, "llm_call", fake_call)
    judge_faithfulness("s", "o", judge_model="gemini-3.1-pro")
    assert captured["provider"] == "gemini"
    assert captured["model"] == "gemini-3.1-pro"


def test_faithfulness_prompt_is_source_anchored_and_categorical():
    # The whole point: graded against the SOURCE, coarse 3-way verdict, no
    # fine-grained score, no anchor/pairwise comparison.
    prompt = _faithfulness_prompt("SRC-TEXT", "ANALYSIS-TEXT")
    assert "SOURCE is the ground truth" in prompt
    for label in ("faithful", "minor", "unfaithful"):
        assert f'"{label}"' in prompt
    assert "fluency is not faithfulness" in prompt
    assert "SRC-TEXT" in prompt and "ANALYSIS-TEXT" in prompt


def test_heuristics_follow_the_output_not_the_slot(monkeypatch):
    # The prior must swap with its output in ordering 2, or it would leak the
    # candidate's heuristic onto the anchor's slot and defeat the debias.
    seen: list[str] = []

    def capture(config, **kwargs):
        seen.append(kwargs["prompt"])
        return _resp('{"winner": "A", "rationale": "x"}')

    monkeypatch.setattr(judge_mod, "llm_call", capture)
    judge_pairwise(
        "src",
        "cand",
        "anchor",
        judge_model="grok-4.3",
        candidate_heuristics="CAND-HEUR",
        anchor_heuristics="ANCHOR-HEUR",
    )
    assert len(seen) == 2
    # Ordering 1: A = candidate, so A carries the candidate heuristic.
    assert "A: CAND-HEUR" in seen[0] and "B: ANCHOR-HEUR" in seen[0]
    # Ordering 2: A = anchor, so the priors swap in lockstep with the outputs.
    assert "A: ANCHOR-HEUR" in seen[1] and "B: CAND-HEUR" in seen[1]

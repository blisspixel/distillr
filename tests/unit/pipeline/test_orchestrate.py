"""Tests for the route-orchestration selection core.

The judges are mocked, so these run offline with zero spend and pin the
charter-correct behavior: a coarse faithfulness veto floor, pairwise ranking
among the faithful (never an absolute quality score), fail-closed on an
unparseable verdict, and honest degradation / bias labels.
"""

from __future__ import annotations

import pytest

from distill.eval.judge import FaithfulnessVerdict, PairwiseResult
from distill.llm.router import LLM_Response
from distill.pipeline.costs import CostTracker
from distill.pipeline.orchestrate import Candidate, LlmRoute, maker_checker, select_best


class _FakeRoute:
    def __init__(self, model: str, output: str) -> None:
        self.model = model
        self.output = output
        self.calls: list[str] = []

    def run(self, prompt: str, *, tracker=None) -> str:
        self.calls.append(prompt)
        return self.output


@pytest.fixture(autouse=True)
def _judge_model_available(monkeypatch):
    # select_best gates on a judge model being available; default it True so the
    # mocked judges run. The no-judge-model test overrides this to False.
    monkeypatch.setattr("distill.pipeline.orchestrate.model_available", lambda workload: True)


def _faith(label: str) -> FaithfulnessVerdict:
    return FaithfulnessVerdict(label=label, unsupported=(), rationale="")


def _patch_faithfulness(monkeypatch, fn) -> None:
    monkeypatch.setattr("distill.pipeline.orchestrate.judge_faithfulness", fn)


def _patch_pairwise(monkeypatch, fn) -> None:
    monkeypatch.setattr("distill.pipeline.orchestrate.judge_pairwise", fn)


def test_vetoes_unfaithful_keeps_single_faithful(monkeypatch) -> None:
    candidates = [Candidate("good one", "grok-4.3"), Candidate("BAD invented", "gemini-3")]
    _patch_faithfulness(
        monkeypatch,
        lambda src, out, **kw: _faith("unfaithful" if "BAD" in out else "faithful"),
    )

    selection = select_best("SRC", candidates, judge_model="qwen3")

    assert selection.method == "single-faithful"
    assert selection.winner is not None
    assert selection.winner.output == "good one"
    assert [c.output for c in selection.vetoed] == ["BAD invented"]
    assert selection.notice == ""


def test_pairwise_picks_the_winner(monkeypatch) -> None:
    candidates = [
        Candidate("draft A", "grok-4.3"),
        Candidate("draft B WIN", "gemini-3"),
        Candidate("draft C", "ollama"),
    ]
    _patch_faithfulness(monkeypatch, lambda src, out, **kw: _faith("faithful"))
    # The challenger wins iff its output carries WIN (win-rate 1.0), else loses.
    _patch_pairwise(
        monkeypatch,
        lambda src, challenger, anchor, **kw: PairwiseResult(
            win_rate=1.0 if "WIN" in challenger else 0.0, comparisons=2, rationale=""
        ),
    )

    selection = select_best("SRC", candidates, judge_model="qwen3")

    assert selection.method == "pairwise"
    assert selection.winner is not None
    assert selection.winner.output == "draft B WIN"
    assert len(selection.faithful) == 3
    assert selection.notice == ""


def test_zero_faithful_returns_no_winner(monkeypatch) -> None:
    candidates = [Candidate("BAD1", "grok-4.3"), Candidate("BAD2", "gemini-3")]
    _patch_faithfulness(monkeypatch, lambda src, out, **kw: _faith("unfaithful"))

    selection = select_best("SRC", candidates, judge_model="qwen3")

    assert selection.winner is None
    assert selection.method == "no-faithful-candidate"
    assert selection.faithful == ()
    assert len(selection.vetoed) == 2


def test_unparseable_verdict_fails_closed(monkeypatch) -> None:
    candidates = [Candidate("ok", "grok-4.3"), Candidate("unparseable", "gemini-3")]
    _patch_faithfulness(
        monkeypatch,
        lambda src, out, **kw: None if out == "unparseable" else _faith("faithful"),
    )

    selection = select_best("SRC", candidates, judge_model="qwen3")

    assert selection.winner is not None
    assert selection.winner.output == "ok"
    assert [c.output for c in selection.vetoed] == ["unparseable"]
    assert selection.method == "single-faithful"


def test_minor_counts_as_faithful(monkeypatch) -> None:
    candidates = [Candidate("a", "grok-4.3"), Candidate("b", "gemini-3")]
    _patch_faithfulness(monkeypatch, lambda src, out, **kw: _faith("minor"))
    _patch_pairwise(
        monkeypatch,
        lambda src, challenger, anchor, **kw: PairwiseResult(
            win_rate=0.0, comparisons=2, rationale=""
        ),
    )

    selection = select_best("SRC", candidates, judge_model="qwen3")

    assert selection.method == "pairwise"
    assert {c.output for c in selection.faithful} == {"a", "b"}
    assert selection.winner is not None
    assert selection.winner.output == "a"  # challenger b lost the comparison


def test_no_pairwise_signal_degrades_honestly(monkeypatch) -> None:
    candidates = [Candidate("a", "grok-4.3"), Candidate("b", "gemini-3")]
    _patch_faithfulness(monkeypatch, lambda src, out, **kw: _faith("faithful"))
    _patch_pairwise(monkeypatch, lambda src, challenger, anchor, **kw: None)

    selection = select_best("SRC", candidates, judge_model="qwen3")

    assert selection.method == "faithful-no-pairwise-signal"
    assert selection.winner is not None
    assert selection.winner.output == "a"
    assert "no pairwise signal" in selection.notice


def test_same_family_judge_bias_is_surfaced(monkeypatch) -> None:
    candidates = [Candidate("a", "grok-4.3"), Candidate("b", "gemini-3")]
    _patch_faithfulness(monkeypatch, lambda src, out, **kw: _faith("faithful"))
    _patch_pairwise(
        monkeypatch,
        lambda src, challenger, anchor, **kw: PairwiseResult(
            win_rate=0.0, comparisons=2, rationale=""
        ),
    )

    # The judge shares candidate a's family (grok), so the comparison is biased.
    selection = select_best("SRC", candidates, judge_model="grok-4.3")

    assert selection.method == "pairwise"
    assert "conservatively biased" in selection.notice


def test_no_judge_model_degrades_honestly(monkeypatch) -> None:
    # No model route to judge: degrade to a labeled no-judge-model result, never
    # a faked pick or a "no-faithful-candidate" that masquerades as a verdict.
    monkeypatch.setattr("distill.pipeline.orchestrate.model_available", lambda workload: False)
    candidates = [Candidate("a", "grok-4.3"), Candidate("b", "gemini-3")]

    selection = select_best("SRC", candidates, judge_model="qwen3")

    assert selection.winner is None
    assert selection.method == "no-judge-model"
    assert "no model route" in selection.notice
    assert selection.faithful == ()
    assert selection.vetoed == ()


# ---------------------------------------------------------------------------
# LlmRoute + maker_checker
# ---------------------------------------------------------------------------


def test_llm_route_forces_model_and_records_usage(monkeypatch) -> None:
    seen = {}

    def _fake_call(rc, *, workload_tag, prompt, **kwargs):
        seen["workload_tag"] = workload_tag
        seen["prompt"] = prompt
        return LLM_Response(text="ROUTED", input_tokens=5, output_tokens=7, model="grok-4.3")

    monkeypatch.setattr("distill.pipeline.orchestrate.llm_call", _fake_call)
    tracker = CostTracker()

    out = LlmRoute("grok-4.3").run("hello", tracker=tracker)

    assert out == "ROUTED"
    assert seen["workload_tag"] == "qa"
    assert seen["prompt"] == "hello"
    assert len(tracker.entries) == 1
    # Also works without a tracker (the usage-record branch is skipped).
    assert LlmRoute("grok-4.3").run("x") == "ROUTED"


def test_maker_checker_keeps_faithful_refinement(monkeypatch) -> None:
    # The cross-family correction is the deliverable; verify it is grounded and ship it.
    _patch_faithfulness(monkeypatch, lambda src, out, **kw: _faith("faithful"))
    maker = _FakeRoute("grok-4.3", "DRAFT")
    checker = _FakeRoute("gemini-3", "REFINED")

    result = maker_checker("SRC", "do the task", maker=maker, checker=checker, judge_model="qwen3")

    assert result.method == "maker-checker"
    assert result.output == "REFINED"
    assert result.draft == "DRAFT"
    assert result.refined == "REFINED"
    assert len(maker.calls) == 1
    assert len(checker.calls) == 1


def test_maker_checker_falls_back_to_draft_when_refinement_unfaithful(monkeypatch) -> None:
    _patch_faithfulness(
        monkeypatch,
        lambda src, out, **kw: _faith("unfaithful" if out == "REFINED" else "faithful"),
    )
    maker = _FakeRoute("grok-4.3", "DRAFT")
    checker = _FakeRoute("gemini-3", "REFINED")

    result = maker_checker("SRC", "task", maker=maker, checker=checker, judge_model="qwen3")

    assert result.method == "refinement-unfaithful-kept-draft"
    assert result.output == "DRAFT"
    assert result.refined == "REFINED"  # produced but rejected as unfaithful


def test_maker_checker_none_faithful_returns_no_output(monkeypatch) -> None:
    _patch_faithfulness(monkeypatch, lambda src, out, **kw: _faith("unfaithful"))
    maker = _FakeRoute("grok-4.3", "DRAFT")
    checker = _FakeRoute("gemini-3", "REFINED")

    result = maker_checker("SRC", "task", maker=maker, checker=checker, judge_model="qwen3")

    assert result.method == "none-faithful"
    assert result.output is None


def test_maker_checker_same_family_skips_refinement(monkeypatch) -> None:
    _patch_faithfulness(monkeypatch, lambda src, out, **kw: _faith("faithful"))
    maker = _FakeRoute("grok-4.3", "DRAFT")
    checker = _FakeRoute("grok-4.1-fast", "REFINED")  # same grok family as the maker

    result = maker_checker("SRC", "task", maker=maker, checker=checker, judge_model="qwen3")

    assert result.method == "single-route-same-family"
    assert result.refined is None
    assert result.output == "DRAFT"
    assert checker.calls == []  # the checker never ran


def test_maker_checker_same_family_unfaithful_draft_returns_none(monkeypatch) -> None:
    _patch_faithfulness(monkeypatch, lambda src, out, **kw: _faith("unfaithful"))
    maker = _FakeRoute("grok-4.3", "DRAFT")
    checker = _FakeRoute("grok-4.1-fast", "REFINED")

    result = maker_checker("SRC", "task", maker=maker, checker=checker, judge_model="qwen3")

    assert result.method == "single-route-same-family"
    assert result.output is None


def test_maker_checker_no_model_degrades(monkeypatch) -> None:
    monkeypatch.setattr("distill.pipeline.orchestrate.model_available", lambda workload: False)
    maker = _FakeRoute("grok-4.3", "DRAFT")
    checker = _FakeRoute("gemini-3", "REFINED")

    result = maker_checker("SRC", "task", maker=maker, checker=checker)

    assert result.method == "no-judge-model"
    assert result.output is None
    assert maker.calls == []  # nothing ran without a judge

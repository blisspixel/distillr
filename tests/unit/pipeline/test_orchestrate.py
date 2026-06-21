"""Tests for the route-orchestration selection core.

The judges are mocked, so these run offline with zero spend and pin the
charter-correct behavior: a coarse faithfulness veto floor, pairwise ranking
among the faithful (never an absolute quality score), fail-closed on an
unparseable verdict, and honest degradation / bias labels.
"""

from __future__ import annotations

from distill.eval.judge import FaithfulnessVerdict, PairwiseResult
from distill.pipeline.orchestrate import Candidate, select_best


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

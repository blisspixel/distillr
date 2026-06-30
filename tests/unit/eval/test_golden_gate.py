"""The golden-corpus eval gate (blocking).

Runs in the normal (already-blocking) test suite, fully offline. It freezes two
contracts so a regression in either fails CI:

1. **Scoring + fixtures**: every hand-checked golden output scores at/above a
   high per-dimension floor. A regression in ``scoring.py``, or a fixture whose
   golden concepts/sections drift out of sync with its golden output, breaks the
   floor.
2. **Discrimination**: a deliberately degraded output scores far below the floor,
   so a gate that rubber-stamps everything is itself caught.

Plus an end-to-end wiring check (the real per-workload prompt assembly runs with
a mock LLM) so a prompt-builder signature break is caught here, not in production.

This is the test-time complement to the run-time verify hook: verify grounds
*production* output against receipts; this gate freezes what *good* extraction
looks like and proves the scorer can still tell good from bad.

**This is a STRUCTURAL gate, not a live-quality gate.** It scores fixed,
hand-written goldens we control (discrimination + fixture sync + prompt wiring)
and never scores live model output. The deterministic composite is fine here for
exactly that reason. Judging the quality of *live* model output is `distill eval`'s
model judges (faithfulness/coverage vs the source), run on-demand with a real
model -- never a deterministic score, and never extend this offline gate to do it
(scoring live output against composite floors would punish paraphrase; see
docs/design/agentic-balance.md).
"""

from __future__ import annotations

import re

import pytest

from distill.eval.fixtures import HALLUCINATION_PATTERNS, load_fixtures
from distill.eval.golden import GOLDEN_OUTPUTS, degraded_output
from distill.eval.harness import _run_analysis, run_model_eval
from distill.eval.scoring import score_output
from distill.llm.router import LLM_Response

# Floors chosen from the measured golden scores (min composite 0.953, min depth
# 0.81) with margin: the gate catches material degradation, not scoring noise.
COMPOSITE_FLOOR = 0.90
DEPTH_FLOOR = 0.75
DEGRADED_CEILING = 0.30

_ALL = load_fixtures("all")


def test_fixtures_and_goldens_are_in_sync():
    fixture_ids = {fx.id for fx in _ALL}
    golden_ids = set(GOLDEN_OUTPUTS)
    assert fixture_ids == golden_ids, (
        f"fixtures without goldens: {fixture_ids - golden_ids}; "
        f"goldens without fixtures: {golden_ids - fixture_ids}"
    )


def test_hallucination_pattern_fixtures_cover_required_cases():
    ask_fixtures = load_fixtures("ask")
    assert ask_fixtures
    covered = {pattern for fx in ask_fixtures for pattern in fx.risk_patterns}
    assert set(HALLUCINATION_PATTERNS) <= covered
    for fx in ask_fixtures:
        assert fx.question
        assert fx.source_stems
        assert fx.risk_patterns


def test_ask_goldens_cite_only_declared_sources():
    for fx in load_fixtures("ask"):
        declared = set(fx.source_stems)
        cited = set(re.findall(r"\[([A-Za-z0-9][A-Za-z0-9_.-]*)\]", GOLDEN_OUTPUTS[fx.id]))
        assert cited
        assert cited <= declared, f"{fx.id}: unexpected citation(s) {cited - declared}"


@pytest.mark.parametrize("fx", _ALL, ids=lambda fx: fx.id)
def test_golden_output_clears_the_floor(fx):
    q = score_output(
        GOLDEN_OUTPUTS[fx.id],
        expected_sections=fx.expected_sections,
        golden_concepts=fx.golden_concepts,
        min_words=fx.min_words,
    )
    dims = {d.name: d.score for d in q.dimensions}
    assert q.composite >= COMPOSITE_FLOOR, f"{fx.id}: composite {q.composite:.3f}"
    # Every expected section present and every golden concept named -- exact, so a
    # dropped section/concept (golden drift) fails rather than silently eroding.
    assert dims["Structure"] == 1.0, f"{fx.id}: missing expected section(s)"
    assert dims["Concept coverage"] == 1.0, f"{fx.id}: missing golden concept(s)"
    assert dims["Formatting"] == 1.0, f"{fx.id}: golden lost headings/bullets"
    assert dims["Depth"] >= DEPTH_FLOOR, f"{fx.id}: depth {dims['Depth']:.3f}"


@pytest.mark.parametrize("fx", _ALL, ids=lambda fx: fx.id)
def test_degraded_output_fails_the_gate(fx):
    q = score_output(
        degraded_output(fx.golden_concepts[0]),
        expected_sections=fx.expected_sections,
        golden_concepts=fx.golden_concepts,
        min_words=fx.min_words,
    )
    assert q.composite < DEGRADED_CEILING, (
        f"{fx.id}: degraded scored {q.composite:.3f} (gate blind)"
    )


def test_end_to_end_harness_scores_goldens_high(monkeypatch):
    """run_model_eval over every workload with a mock analyzer returning the
    golden for each fixture: no workload crashes and every row clears the floor."""
    import distill.eval.harness as harness_mod

    monkeypatch.setattr(harness_mod, "judge_pairwise", lambda *a, **k: None)

    def mock_analyze(fixture, rc, tracker):
        return GOLDEN_OUTPUTS[fixture.id]

    rows = run_model_eval("all", ["golden-model"], anchor="golden-model", analyze=mock_analyze)
    assert len(rows) == len(_ALL)
    for r in rows:
        assert not r.error
        assert r.quality.composite >= COMPOSITE_FLOOR, f"{r.fixture_id}: {r.quality.composite:.3f}"


@pytest.mark.parametrize(
    "workload", ["paper", "video", "site", "ask"], ids=["paper", "video", "site", "ask"]
)
def test_real_prompt_assembly_runs_for_each_workload(workload, monkeypatch):
    """Exercise the real per-workload prompt builders with a mock LLM, so a
    prompt-builder signature break surfaces here instead of in production."""
    import distill.eval.harness as harness_mod
    from distill.llm.router import RouterConfig
    from distill.pipeline.costs import CostTracker

    fx = load_fixtures(workload)[0]

    def fake_llm_call(rc, *, workload_tag, prompt, call_type, **kwargs):
        # The prompt must be a non-empty string built from the fixture fields.
        assert isinstance(prompt, str) and (fx.title in prompt or fx.question in prompt)
        return LLM_Response(
            text=GOLDEN_OUTPUTS[fx.id], input_tokens=500, output_tokens=300, model="mock"
        )

    monkeypatch.setattr(harness_mod, "llm_call", fake_llm_call)
    out = _run_analysis(fx, RouterConfig(provider="xai", model="mock"), CostTracker())
    assert out == GOLDEN_OUTPUTS[fx.id]

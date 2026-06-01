"""Tests for distill.eval.harness (two-phase run + score + cost + cache + estimate)."""

from distill.eval import harness as harness_mod
from distill.eval.fixtures import load_fixtures
from distill.eval.harness import estimate_eval_cost, run_model_eval
from distill.eval.judge import PairwiseResult
from distill.pipeline.costs import TokenUsage

_OUTPUT = (
    "## Core Contribution\n- ICEWS MRR ChronoR GDELT Semantic Speed Gate.\n"
    "## Methods and Evidence\n- evidence.\n## Limits\n- limits.\n" + "word " * 200
)


def _fake_analyze_factory(calls):
    def _fake(fixture, rc, tracker):
        calls.append((fixture.id, rc.model))
        tracker.record(
            TokenUsage(prompt_tokens=2000, completion_tokens=600, model=rc.model, call_type="x")
        )
        return _OUTPUT

    return _fake


def test_run_model_eval_scores_costs_and_judges(monkeypatch):
    judged: list = []

    def fake_pairwise(src, cand, anchor, **k):
        judged.append((cand[:5], anchor[:5]))
        return PairwiseResult(win_rate=0.6, comparisons=2, rationale="ok")

    monkeypatch.setattr(harness_mod, "judge_pairwise", fake_pairwise)
    calls: list = []
    rows = run_model_eval(
        "paper",
        ["grok-4.3", "qwen3.5:27b"],
        anchor="grok-4.3",
        judge_model="grok-4.3",
        analyze=_fake_analyze_factory(calls),
    )
    # 3 paper fixtures x 2 models = 6 rows; analysis ran for each.
    assert len(rows) == 6
    assert len(calls) == 6
    anchor_rows = [r for r in rows if r.model == "grok-4.3"]
    cand_rows = [r for r in rows if r.model == "qwen3.5:27b"]
    assert all(r.pairwise_winrate is None for r in anchor_rows)  # anchor not judged vs itself
    assert all(r.pairwise_winrate == 0.6 for r in cand_rows)
    assert len(judged) == 3  # one pairwise per candidate fixture
    assert all(r.cost > 0 for r in rows)


def test_cache_hit_skips_reanalysis(tmp_path, monkeypatch):
    monkeypatch.setattr(
        harness_mod,
        "judge_pairwise",
        lambda *a, **k: PairwiseResult(win_rate=0.5, comparisons=2, rationale=""),
    )
    calls: list = []
    fake = _fake_analyze_factory(calls)
    run_model_eval("paper", ["grok-4.3"], anchor="grok-4.3", cache_dir=tmp_path, analyze=fake)
    assert len(calls) == 3
    calls.clear()
    second = run_model_eval(
        "paper", ["grok-4.3"], anchor="grok-4.3", cache_dir=tmp_path, analyze=fake
    )
    assert calls == []  # analysis served from cache
    assert all(r.cached for r in second)


def test_estimate_is_fixture_aware_and_modest():
    fixtures = load_fixtures("paper")
    est = estimate_eval_cost(
        fixtures, ["grok-4.3", "qwen3.5:27b"], anchor="grok-4.3", judge_model="grok-4.3"
    )
    # Small fixtures -> a few cents, not the multi-dollar production-stage figure.
    assert 0.0 < est < 0.50


def test_provider_inference():
    assert harness_mod.provider_for_model("grok-4.3") == "xai"
    assert harness_mod.provider_for_model("qwen3.5:27b") == "ollama"

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
    assert all(r.cost > 0 for r in anchor_rows)  # grok priced from the registry
    assert all(r.cost == 0.0 for r in cand_rows)  # qwen is local -> free


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


def test_malformed_cache_entry_recomputes(tmp_path, monkeypatch):
    # A corrupt-but-valid-JSON cache row (wrong shape) must be ignored and the
    # row recomputed, not crash the sweep with KeyError/TypeError.
    monkeypatch.setattr(
        harness_mod,
        "judge_pairwise",
        lambda *a, **k: PairwiseResult(win_rate=0.5, comparisons=2, rationale=""),
    )
    calls: list = []
    fake = _fake_analyze_factory(calls)
    run_model_eval("paper", ["grok-4.3"], anchor="grok-4.3", cache_dir=tmp_path, analyze=fake)
    assert len(calls) == 3
    # Poison every cached analysis row: valid JSON, missing the "output" field.
    for p in tmp_path.glob("*.json"):
        p.write_text('{"unexpected": "shape"}', encoding="utf-8")
    calls.clear()
    rows = run_model_eval(
        "paper", ["grok-4.3"], anchor="grok-4.3", cache_dir=tmp_path, analyze=fake
    )
    assert len(calls) == 3  # recomputed, did not serve the poisoned cache
    assert all(not r.cached for r in rows)


def test_estimate_is_fixture_aware_and_modest():
    fixtures = load_fixtures("paper")
    est = estimate_eval_cost(
        fixtures, ["grok-4.3", "qwen3.5:27b"], anchor="grok-4.3", judge_model="grok-4.3"
    )
    # Small fixtures -> a few cents, not the multi-dollar production-stage figure.
    assert 0.0 < est < 0.50


def test_analysis_failure_degrades_gracefully(monkeypatch):
    # One model times out on every fixture; the sweep must NOT crash — that model's
    # rows are flagged errored and the other model still produces real rows.
    monkeypatch.setattr(harness_mod, "judge_pairwise", lambda *a, **k: None)

    def flaky(fixture, rc, tracker):
        if rc.model == "bad-model":
            raise TimeoutError("read timeout")
        tracker.record(
            TokenUsage(prompt_tokens=1000, completion_tokens=500, model=rc.model, call_type="x")
        )
        return _OUTPUT

    rows = run_model_eval("paper", ["grok-4.3", "bad-model"], anchor="grok-4.3", analyze=flaky)
    assert len(rows) == 6  # 3 fixtures x 2 models, no crash
    bad = [r for r in rows if r.model == "bad-model"]
    good = [r for r in rows if r.model == "grok-4.3"]
    assert all(r.error for r in bad)
    assert all(not r.error for r in good)


def test_local_model_priced_at_zero(monkeypatch):
    # Local inference is free: a local model's rows must cost $0 even though it
    # burns tokens (the registry would otherwise price it at the cloud fallback).
    monkeypatch.setattr(harness_mod, "judge_pairwise", lambda *a, **k: PairwiseResult(0.5, 2, ""))

    def fake(fixture, rc, tracker):
        tracker.record(
            TokenUsage(prompt_tokens=5000, completion_tokens=3000, model=rc.model, call_type="x")
        )
        return _OUTPUT

    rows = run_model_eval("paper", ["grok-4.3", "qwen3.5:27b"], anchor="grok-4.3", analyze=fake)
    assert all(r.cost == 0.0 for r in rows if r.model == "qwen3.5:27b")
    assert all(r.cost > 0 for r in rows if r.model == "grok-4.3")


def test_estimate_local_only_is_free():
    fixtures = load_fixtures("paper")
    est = estimate_eval_cost(
        fixtures, ["qwen3.5:27b"], anchor="qwen3.5:27b", judge_model="qwen3.5:27b"
    )
    assert est == 0.0


def test_phase1_is_model_outer_to_avoid_vram_thrash(monkeypatch):
    # Analysis must process all of one model's fixtures before the next model, so
    # a local model stays loaded in VRAM instead of being swapped every fixture.
    monkeypatch.setattr(harness_mod, "judge_pairwise", lambda *a, **k: None)
    calls: list = []
    run_model_eval("paper", ["m1", "m2"], anchor="m1", analyze=_fake_analyze_factory(calls))
    models_in_call_order = [model for (_fid, model) in calls]
    assert models_in_call_order == ["m1", "m1", "m1", "m2", "m2", "m2"]


def test_failed_judge_verdict_is_not_cached(tmp_path, monkeypatch):
    # A transient judge failure (None) must not be cached — otherwise every rerun
    # reuses the failure instead of re-judging. First run fails; second succeeds.
    state = {"n": 0}

    def judge(src, cand, anchor, **k):
        state["n"] += 1
        if state["n"] <= 3:  # first run's 3 fixtures all fail
            return None
        return PairwiseResult(win_rate=0.7, comparisons=2, rationale="ok")

    monkeypatch.setattr(harness_mod, "judge_pairwise", judge)
    fake = _fake_analyze_factory([])
    r1 = run_model_eval(
        "paper", ["grok-4.3", "qwen3.5:27b"], anchor="grok-4.3", cache_dir=tmp_path, analyze=fake
    )
    assert all(row.pairwise_winrate is None for row in r1 if row.model == "qwen3.5:27b")
    r2 = run_model_eval(
        "paper", ["grok-4.3", "qwen3.5:27b"], anchor="grok-4.3", cache_dir=tmp_path, analyze=fake
    )
    # Analyses are cached, but the failed verdict re-ran and now succeeds.
    assert all(row.pairwise_winrate == 0.7 for row in r2 if row.model == "qwen3.5:27b")


def test_provider_inference():
    assert harness_mod.provider_for_model("grok-4.3") == "xai"
    assert harness_mod.provider_for_model("qwen3.5:27b") == "ollama"

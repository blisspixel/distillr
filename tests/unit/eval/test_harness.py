"""Tests for distill.eval.harness (run + score + cost + cache wiring)."""

from distill.eval import harness as harness_mod
from distill.eval.harness import run_model_eval
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


def test_run_model_eval_scores_and_costs(monkeypatch):
    monkeypatch.setattr(harness_mod, "judge_output", lambda *a, **k: None)
    calls: list = []
    rows = run_model_eval(
        "paper", ["grok-4.3"], judge_model="grok-4.3", analyze=_fake_analyze_factory(calls)
    )
    assert len(rows) == 1
    assert calls == [("paper-tkg", "grok-4.3")]
    assert rows[0].cost > 0  # grok-4.3 priced from the registry
    assert rows[0].quality.deterministic > 0.7
    assert rows[0].cached is False


def test_cache_hit_skips_reanalysis(tmp_path, monkeypatch):
    monkeypatch.setattr(harness_mod, "judge_output", lambda *a, **k: None)
    calls: list = []
    fake = _fake_analyze_factory(calls)

    first = run_model_eval(
        "paper", ["grok-4.3"], judge_model="grok-4.3", cache_dir=tmp_path, analyze=fake
    )
    assert calls == [("paper-tkg", "grok-4.3")]
    assert first[0].cached is False

    calls.clear()
    second = run_model_eval(
        "paper", ["grok-4.3"], judge_model="grok-4.3", cache_dir=tmp_path, analyze=fake
    )
    assert calls == []  # served from cache, no re-analysis
    assert second[0].cached is True
    assert round(second[0].cost, 6) == round(first[0].cost, 6)


def test_provider_inference():
    assert harness_mod.provider_for_model("grok-4.3") == "xai"
    assert harness_mod.provider_for_model("gemini-3.1-pro") == "gemini"
    assert harness_mod.provider_for_model("qwen3.5:27b") == "ollama"

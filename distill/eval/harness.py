"""Eval harness — run candidate models over fixtures, score quality + cost.

Two phases per run: (1) analyze every (model, fixture) with the *real* production
prompts under a forced model at ``temperature=0``; (2) judge each candidate
pairwise against the **anchor** (incumbent/reference) model's output for the same
fixture. The deterministic score is the decision signal; the pairwise win-rate is
advisory (feeds confidence only). Analysis outputs and pairwise verdicts cache
independently so re-running after a new model launches only runs the new work.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from distill.eval._models import is_local as _is_local
from distill.eval._models import provider_for_model
from distill.eval.fixtures import Fixture, load_fixtures
from distill.eval.judge import DEFAULT_JUDGE_MODEL, judge_pairwise
from distill.eval.scoring import QualityScore, score_output
from distill.llm import call as llm_call
from distill.llm.router import RouterConfig
from distill.pipeline.costs import CostTracker, TokenUsage
from distill.prompts.analysis import pass1_extraction_prompt, pass2_synthesis_prompt
from distill.prompts.synthesis import paper_insight_prompt, site_page_insight_prompt

logger = logging.getLogger(__name__)

__all__ = ["EvalRow", "estimate_eval_cost", "provider_for_model", "run_model_eval"]

# Analysis LLM calls per workload (video is 2-pass).
_CALLS_PER_WORKLOAD: dict[str, int] = {"paper": 1, "video": 2, "site": 1}


def estimate_eval_cost(
    fixtures: list[Fixture], models: list[str], *, anchor: str, judge_model: str
) -> float:
    """Fixture-aware pre-run estimate (USD), priced from each fixture's real size.

    Unlike a per-stage constant, this scales with the actual (small) fixture
    source, so it doesn't overshoot — analysis is priced per candidate model and
    the pairwise judge adds two calls per non-anchor model.
    """
    from distill.llm.cost import compute_cost

    total = 0.0
    judge_local = _is_local(judge_model)
    for fixture in fixtures:
        in_tok = len(fixture.source_text) // 4 + 600  # source + prompt template overhead
        out_tok = 800
        calls = _CALLS_PER_WORKLOAD.get(fixture.workload, 1)
        for model in models:
            if not _is_local(model):  # local analysis is free
                total += calls * compute_cost(model, in_tok, out_tok)
            if model != anchor and not judge_local:  # pairwise judge: 2 order-randomized calls
                total += 2 * compute_cost(judge_model, in_tok + 2 * out_tok, 120)
    return total


@dataclass(frozen=True)
class EvalRow:
    workload: str
    fixture_id: str
    model: str
    quality: QualityScore
    cost: float
    input_tokens: int
    output_tokens: int
    pairwise_winrate: float | None = None  # vs anchor; None for the anchor itself
    judge_rationale: str = ""
    cached: bool = False
    error: str = ""  # non-empty when analysis failed (timeout / provider error)


def _call(
    rc: RouterConfig, workload_tag: str, prompt: str, call_type: str, tracker: CostTracker
) -> str:
    # temperature=0 so a model's output is reproducible across runs and the only
    # variable between rows is the model itself. Generous timeout because a local
    # model's first call includes a cold load into VRAM.
    response = llm_call(
        rc,
        workload_tag=workload_tag,
        prompt=prompt,
        call_type=call_type,
        temperature=0.0,
        timeout=600,
    )
    tracker.record(
        TokenUsage(
            prompt_tokens=response.input_tokens,
            completion_tokens=response.output_tokens,
            model=response.model,
            call_type=call_type,
        )
    )
    return response.text


def _run_analysis(fixture: Fixture, rc: RouterConfig, tracker: CostTracker) -> str:
    """Build the real per-workload prompt and run it under ``rc``; return output text."""
    if fixture.workload == "paper":
        prompt = paper_insight_prompt(fixture.title, fixture.paper_id, fixture.source_text)
        return _call(rc, "site", prompt, "eval_paper", tracker)
    if fixture.workload == "video":
        p1 = pass1_extraction_prompt(
            fixture.title, "20260101", fixture.channel, fixture.source_text
        )
        pass1 = _call(rc, "analysis", p1, "eval_video_pass1", tracker)
        p2 = pass2_synthesis_prompt(fixture.title, "20260101", fixture.channel, pass1)
        return _call(rc, "analysis", p2, "eval_video_pass2", tracker)
    if fixture.workload == "site":
        prompt = site_page_insight_prompt(
            fixture.title, fixture.url, fixture.site_name, "documentation", fixture.source_text
        )
        return _call(rc, "site", prompt, "eval_site", tracker)
    raise ValueError(f"unknown workload: {fixture.workload}")


def _hash(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:16]


def _src_hash(fixture: Fixture) -> str:
    return hashlib.sha256(fixture.source_text.encode("utf-8")).hexdigest()[:8]


@dataclass(frozen=True)
class _Analysis:
    output: str
    cost: float
    input_tokens: int
    output_tokens: int
    cached: bool
    error: str = ""


def _analyze(
    model: str,
    fixture: Fixture,
    runner: Callable[[Fixture, RouterConfig, CostTracker], str],
    run_tracker: CostTracker,
    cache_dir: Path | None,
) -> _Analysis:
    key = _hash("analysis", model, fixture.id, _src_hash(fixture))
    cached = _load_json(cache_dir, key)
    if cached is not None:
        return _Analysis(
            output=cached["output"],
            cost=float(cached.get("cost", 0.0)),
            input_tokens=int(cached.get("input_tokens", 0)),
            output_tokens=int(cached.get("output_tokens", 0)),
            cached=True,
        )
    row_tracker = CostTracker()
    rc = RouterConfig(provider=provider_for_model(model), model=model)
    local = _is_local(model)  # local inference is free; keep it off the cost ledger
    # A single model failing (timeout, provider error, OOM on a local model) must
    # not abort the whole sweep — record the partial cost, mark the row errored,
    # and let the run continue. Errored results are NOT cached (so a retry runs).
    try:
        output = runner(fixture, rc, row_tracker)
    except Exception as exc:
        if not local:
            run_tracker.entries.extend(row_tracker.entries)
        logger.warning("eval analysis failed for %s on %s: %s", model, fixture.id, exc)
        return _Analysis(
            output="",
            cost=0.0 if local else row_tracker.total_cost,
            input_tokens=row_tracker.total_input_tokens,
            output_tokens=row_tracker.total_output_tokens,
            cached=False,
            error=f"{type(exc).__name__}: {exc}"[:200],
        )
    if not local:
        run_tracker.entries.extend(row_tracker.entries)
    analysis = _Analysis(
        output=output,
        cost=0.0 if local else row_tracker.total_cost,
        input_tokens=row_tracker.total_input_tokens,
        output_tokens=row_tracker.total_output_tokens,
        cached=False,
    )
    _save_json(
        cache_dir,
        key,
        {
            "model": model,
            "fixture_id": fixture.id,
            "output": analysis.output,
            "cost": analysis.cost,
            "input_tokens": analysis.input_tokens,
            "output_tokens": analysis.output_tokens,
        },
    )
    return analysis


def _pairwise(
    model: str,
    fixture: Fixture,
    candidate_output: str,
    anchor_output: str,
    anchor: str,
    judge_model: str,
    run_tracker: CostTracker,
    cache_dir: Path | None,
) -> tuple[float | None, str]:
    key = _hash("pairwise", model, fixture.id, _src_hash(fixture), anchor, judge_model)
    cached = _load_json(cache_dir, key)
    if cached is not None:
        wr = cached.get("win_rate")
        return (float(wr) if wr is not None else None), cached.get("rationale", "")
    try:
        result = judge_pairwise(
            fixture.source_text,
            candidate_output,
            anchor_output,
            judge_model=judge_model,
            tracker=run_tracker,
        )
    except Exception as exc:
        logger.warning("eval pairwise judge failed for %s on %s: %s", model, fixture.id, exc)
        return None, ""
    win_rate = result.win_rate if result else None
    rationale = result.rationale if result else ""
    # Don't cache a failed verdict (None) — otherwise a transient judge failure is
    # frozen in and every rerun reuses it instead of re-judging.
    if win_rate is not None:
        _save_json(cache_dir, key, {"win_rate": win_rate, "rationale": rationale})
    return win_rate, rationale


def run_model_eval(
    workload: str,
    models: list[str],
    *,
    anchor: str = DEFAULT_JUDGE_MODEL,
    judge_model: str = DEFAULT_JUDGE_MODEL,
    tracker: CostTracker | None = None,
    cache_dir: Path | None = None,
    analyze: Callable[[Fixture, RouterConfig, CostTracker], str] | None = None,
) -> list[EvalRow]:
    """Sweep ``models`` over the workload's fixtures; return scored rows.

    Phase 1 analyzes every (model, fixture); phase 2 judges each non-anchor model
    pairwise against the anchor's output for that fixture. ``analyze`` is
    injectable for testing.
    """
    run_tracker = tracker if tracker is not None else CostTracker()
    runner = analyze or _run_analysis
    fixtures = load_fixtures(workload)

    # Phase 1: analysis for every (model, fixture). Model-outer on purpose — a
    # local model then stays loaded in VRAM across its fixtures instead of being
    # swapped in/out every fixture (which thrashes a single-GPU box).
    analyses: dict[tuple[str, str], _Analysis] = {}
    for model in models:
        for fixture in fixtures:
            analyses[(model, fixture.id)] = _analyze(model, fixture, runner, run_tracker, cache_dir)

    # Phase 2: pairwise judge each candidate vs the anchor's output, then score.
    rows: list[EvalRow] = []
    for fixture in fixtures:
        anchor_a = analyses.get((anchor, fixture.id))
        for model in models:
            a = analyses[(model, fixture.id)]
            win_rate: float | None = None
            rationale = ""
            # Judge only when both this model and the anchor produced real output.
            if (
                model != anchor
                and not a.error
                and anchor_a is not None
                and not anchor_a.error
                and anchor_a.output
            ):
                win_rate, rationale = _pairwise(
                    model,
                    fixture,
                    a.output,
                    anchor_a.output,
                    anchor,
                    judge_model,
                    run_tracker,
                    cache_dir,
                )
            quality = score_output(
                a.output,
                expected_sections=fixture.expected_sections,
                golden_concepts=fixture.golden_concepts,
                min_words=fixture.min_words,
            )
            rows.append(
                EvalRow(
                    workload=fixture.workload,
                    fixture_id=fixture.id,
                    model=model,
                    quality=quality,
                    cost=a.cost,
                    input_tokens=a.input_tokens,
                    output_tokens=a.output_tokens,
                    pairwise_winrate=win_rate,
                    judge_rationale=rationale,
                    cached=a.cached,
                    error=a.error,
                )
            )
    return rows


def _load_json(cache_dir: Path | None, key: str) -> dict | None:
    if cache_dir is None:
        return None
    path = cache_dir / f"{key}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _save_json(cache_dir: Path | None, key: str, payload: dict) -> None:
    if cache_dir is None:
        return
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / f"{key}.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

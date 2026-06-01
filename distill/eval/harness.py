"""Eval harness — run candidate models over fixtures, score quality + cost.

For each (model, fixture) the harness builds the *real* analysis prompt (the same
builders the production pipeline uses), runs it under a forced model/provider,
scores the output (deterministic dimensions + advisory judge), and records the
candidate model's analysis cost. Results are cached by (model, fixture, judge) so
re-running after a new model launches only runs the new rows.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from distill.eval.fixtures import Fixture, load_fixtures
from distill.eval.judge import DEFAULT_JUDGE_MODEL, judge_output
from distill.eval.scoring import QualityScore, score_output
from distill.llm import call as llm_call
from distill.llm.router import RouterConfig
from distill.pipeline.costs import CostTracker, TokenUsage
from distill.prompts.analysis import pass1_extraction_prompt, pass2_synthesis_prompt
from distill.prompts.synthesis import paper_insight_prompt, site_page_insight_prompt

logger = logging.getLogger(__name__)

__all__ = ["EvalRow", "provider_for_model", "run_model_eval"]


@dataclass(frozen=True)
class EvalRow:
    workload: str
    fixture_id: str
    model: str
    quality: QualityScore
    cost: float
    input_tokens: int
    output_tokens: int
    judge_rationale: str = ""
    cached: bool = False


def provider_for_model(model: str) -> str:
    """Infer the provider from a model id (anything unrecognized is treated local)."""
    m = model.lower()
    if m.startswith("grok"):
        return "xai"
    if m.startswith(("gemini", "deep-research")):
        return "gemini"
    if m.startswith("claude"):
        return "anthropic"
    if m.startswith(("gpt", "o1", "o3")):
        return "openai"
    return "ollama"


def _call(
    rc: RouterConfig, workload_tag: str, prompt: str, call_type: str, tracker: CostTracker
) -> str:
    response = llm_call(rc, workload_tag=workload_tag, prompt=prompt, call_type=call_type)
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


def _cache_key(model: str, fixture: Fixture, judge_model: str) -> str:
    src = hashlib.sha256(fixture.source_text.encode("utf-8")).hexdigest()[:8]
    payload = f"{model}|{fixture.id}|{src}|{judge_model}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def run_model_eval(
    workload: str,
    models: list[str],
    *,
    judge_model: str = DEFAULT_JUDGE_MODEL,
    tracker: CostTracker | None = None,
    cache_dir: Path | None = None,
    analyze: Callable[[Fixture, RouterConfig, CostTracker], str] | None = None,
) -> list[EvalRow]:
    """Sweep ``models`` over the workload's fixtures and return scored rows.

    ``analyze`` is injectable for testing (defaults to the real prompt+LLM path).
    Each row's ``cost`` is the candidate model's analysis spend only; judge spend
    is eval overhead and lands in the shared ``tracker`` for run accounting.
    """
    run_tracker = tracker if tracker is not None else CostTracker()
    runner = analyze or _run_analysis
    fixtures = load_fixtures(workload)
    rows: list[EvalRow] = []

    for fixture in fixtures:
        for model in models:
            cached = _load_cached(cache_dir, model, fixture, judge_model) if cache_dir else None
            if cached is not None:
                output, judge_overall, judge_rationale, cost, tin, tout = cached
                was_cached = True
            else:
                row_tracker = CostTracker()
                rc = RouterConfig(provider=provider_for_model(model), model=model)
                output = runner(fixture, rc, row_tracker)
                cost = row_tracker.total_cost
                tin, tout = row_tracker.total_input_tokens, row_tracker.total_output_tokens
                run_tracker.entries.extend(row_tracker.entries)
                judge = judge_output(
                    fixture.source_text,
                    output,
                    candidate_model=model,
                    judge_model=judge_model,
                    tracker=run_tracker,
                )
                judge_overall = judge.overall if judge else None
                judge_rationale = judge.rationale if judge else ""
                was_cached = False
                _save_cached(
                    cache_dir,
                    model,
                    fixture,
                    judge_model,
                    output,
                    judge_overall,
                    judge_rationale,
                    cost,
                    tin,
                    tout,
                )

            quality = score_output(
                output,
                expected_sections=fixture.expected_sections,
                golden_concepts=fixture.golden_concepts,
                min_words=fixture.min_words,
                judge=judge_overall,
            )
            rows.append(
                EvalRow(
                    workload=fixture.workload,
                    fixture_id=fixture.id,
                    model=model,
                    quality=quality,
                    cost=cost,
                    input_tokens=tin,
                    output_tokens=tout,
                    judge_rationale=judge_rationale,
                    cached=was_cached,
                )
            )
    return rows


def _load_cached(
    cache_dir: Path, model: str, fixture: Fixture, judge_model: str
) -> tuple[str, float | None, str, float, int, int] | None:
    path = cache_dir / f"{_cache_key(model, fixture, judge_model)}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return (
            data["output"],
            data.get("judge_overall"),
            data.get("judge_rationale", ""),
            float(data.get("cost", 0.0)),
            int(data.get("input_tokens", 0)),
            int(data.get("output_tokens", 0)),
        )
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None


def _save_cached(
    cache_dir: Path | None,
    model: str,
    fixture: Fixture,
    judge_model: str,
    output: str,
    judge_overall: float | None,
    judge_rationale: str,
    cost: float,
    tin: int,
    tout: int,
) -> None:
    if cache_dir is None:
        return
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{_cache_key(model, fixture, judge_model)}.json"
    payload = {
        "model": model,
        "fixture_id": fixture.id,
        "output": output,
        "judge_overall": judge_overall,
        "judge_rationale": judge_rationale,
        "cost": cost,
        "input_tokens": tin,
        "output_tokens": tout,
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

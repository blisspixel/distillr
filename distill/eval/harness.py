"""Eval harness — run candidate models over fixtures, score quality + cost.

Two phases per run: (1) analyze every (model, fixture) with the *real* production
prompts under a forced model at ``temperature=0``; (2) judge each output — an
absolute source-anchored faithfulness verdict for every model, plus a pairwise
candidate-vs-**anchor** win-rate for non-anchor models. ``report`` gates a
migration on the model judges (faithfulness vetoes, pairwise ranks); the
deterministic composite is only a guardrail floor. Analysis, pairwise, and
faithfulness results cache independently so re-running after a new model launches
only runs the new work.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

from distill.eval._models import LOCAL_PROVIDERS, provider_for_model
from distill.eval.fixtures import Fixture, load_fixtures
from distill.eval.judge import (
    DEFAULT_JUDGE_MODEL,
    FAITHFULNESS_ORDINAL,
    judge_faithfulness,
    judge_pairwise,
)
from distill.eval.scoring import QualityScore, score_output
from distill.llm import call as llm_call
from distill.llm.cost_policy import classify_provider, local_provider_endpoint
from distill.llm.router import RouterConfig
from distill.pipeline.costs import CostTracker, TokenUsage
from distill.prompts.analysis import pass1_extraction_prompt, pass2_synthesis_prompt
from distill.prompts.ask import ask_prompt
from distill.prompts.synthesis import paper_insight_prompt, site_page_insight_prompt

logger = logging.getLogger(__name__)

__all__ = [
    "EvalRow",
    "UnpricedEvalRouteError",
    "estimate_eval_cost",
    "provider_for_model",
    "run_model_eval",
]

# Analysis LLM calls per workload (video is 2-pass).
_CALLS_PER_WORKLOAD: dict[str, int] = {"paper": 1, "video": 2, "site": 1}


class UnpricedEvalRouteError(ValueError):
    """An eval route has usage evidence but no trustworthy price contract."""


def _eval_provider_type(provider: str) -> str:
    if provider in LOCAL_PROVIDERS:
        return "local" if classify_provider(provider) == "local" else "unknown"
    if provider == "adapter":
        return "included-plan"
    return "cloud"


def _eval_model_is_no_metered(model: str) -> bool:
    return _eval_provider_type(provider_for_model(model)) in {"local", "included-plan"}


def _require_known_eval_cost(model: str) -> None:
    provider = provider_for_model(model)
    if provider in LOCAL_PROVIDERS and _eval_provider_type(provider) == "unknown":
        raise UnpricedEvalRouteError(
            f"Cannot evaluate cost for model '{model}' through a non-loopback {provider} "
            "endpoint because its external price is unknown. Use a loopback endpoint "
            "or a provider with a configured price contract."
        )


def estimate_eval_cost(
    fixtures: list[Fixture], models: list[str], *, anchor: str, judge_model: str
) -> float:
    """Fixture-aware pre-run estimate (USD), priced from each fixture's real size.

    Unlike a per-stage constant, this scales with the actual (small) fixture
    source, so it doesn't overshoot — analysis is priced per candidate model, the
    faithfulness judge adds one call per (model, fixture) (anchor included), and
    the pairwise judge adds two order-randomized calls per non-anchor model.
    """
    from distill.llm.cost import compute_cost

    for model in {*models, judge_model}:
        if model:
            _require_known_eval_cost(model)

    total = 0.0
    judge_no_metered = not judge_model or _eval_model_is_no_metered(judge_model)
    for fixture in fixtures:
        in_tok = len(fixture.source_text) // 4 + 600  # source + prompt template overhead
        out_tok = 800
        calls = _CALLS_PER_WORKLOAD.get(fixture.workload, 1)
        for model in models:
            if not _eval_model_is_no_metered(model):
                total += calls * compute_cost(model, in_tok, out_tok)
            if not judge_no_metered:
                # Faithfulness judge: 1 absolute call per (model, fixture), anchor included.
                total += compute_cost(judge_model, in_tok + out_tok, 120)
                if model != anchor:  # pairwise judge: 2 order-randomized calls
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
    faithfulness: str = ""  # absolute source-anchored verdict; "" = not judged
    faithfulness_rationale: str = ""
    risk_patterns: tuple[str, ...] = ()
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
        usage_tracker=tracker,
    )
    tracker.record(TokenUsage.from_response(response, call_type=call_type))
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
    if fixture.workload == "ask":
        prompt = ask_prompt(
            topic="eval",
            question=fixture.question,
            sources_block=_sources_block(fixture),
        )
        return _call(rc, "qa", prompt, "eval_ask", tracker)
    raise ValueError(f"unknown workload: {fixture.workload}")


def _hash(*parts: str) -> str:
    digest = hashlib.sha256()
    for part in parts:
        encoded = part.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, byteorder="big"))
        digest.update(encoded)
    return digest.hexdigest()


def _src_hash(fixture: Fixture) -> str:
    return _hash(
        "fixture-source-v2",
        fixture.question,
        *fixture.source_stems,
        fixture.source_text,
    )


def _sources_block(fixture: Fixture) -> str:
    stems = fixture.source_stems or (f"{fixture.id}_source",)
    if len(stems) == 1:
        return f"[{stems[0]}]\n{fixture.source_text}"
    return "\n\n---\n\n".join(f"[{stem}]\n{fixture.source_text}" for stem in stems)


def _judge_source(fixture: Fixture) -> str:
    if not fixture.question:
        return fixture.source_text
    return f"QUESTION:\n{fixture.question}\n\nCORPUS EXCERPTS:\n{_sources_block(fixture)}"


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
    provider = provider_for_model(model)
    endpoint = local_provider_endpoint(provider) if provider in LOCAL_PROVIDERS else ""
    key = _hash(
        "analysis-v2",
        model,
        fixture.id,
        _src_hash(fixture),
        provider,
        _eval_provider_type(provider),
        endpoint,
    )
    cached = _load_json(cache_dir, key)
    if cached is not None:
        try:
            return _Analysis(
                output=cached["output"],
                cost=float(cached.get("cost", 0.0)),
                input_tokens=int(cached.get("input_tokens", 0)),
                output_tokens=int(cached.get("output_tokens", 0)),
                cached=True,
            )
        except (KeyError, TypeError, ValueError):
            # Malformed cache entry (missing/ill-typed fields): ignore it and
            # recompute rather than crashing the sweep on a poisoned/corrupt row.
            logger.warning("Ignoring malformed eval cache entry for %s/%s", model, fixture.id)
    row_tracker = CostTracker()
    rc = RouterConfig(provider=provider, model=model)
    if provider == "adapter" and runner is _run_analysis:
        # Adapter plan-quota routes require a live adapter analyzer. A synthetic
        # output would create false graduation evidence, so the default path
        # records an errored zero-cost row instead.
        return _Analysis(
            output="",
            cost=0.0,
            input_tokens=0,
            output_tokens=0,
            cached=False,
            error="adapter eval requires a live adapter analyzer",
        )
    # A single model failing (timeout, provider error, OOM on a local model) must
    # not abort the whole sweep — record the partial cost, mark the row errored,
    # and let the run continue. Errored results are NOT cached (so a retry runs).
    try:
        output = runner(fixture, rc, row_tracker)
    except Exception as exc:
        external_cost_unavailable = _merge_eval_usage(row_tracker, run_tracker, provider)
        logger.warning("eval analysis failed for %s on %s: %s", model, fixture.id, exc)
        error = f"{type(exc).__name__}: {exc}"[:200]
        if external_cost_unavailable:
            error = f"external cost unavailable; {error}"[:200]
        return _Analysis(
            output="",
            cost=row_tracker.total_cost,
            input_tokens=row_tracker.total_input_tokens,
            output_tokens=row_tracker.total_output_tokens,
            cached=False,
            error=error,
        )
    external_cost_unavailable = _merge_eval_usage(row_tracker, run_tracker, provider)
    if external_cost_unavailable:
        return _Analysis(
            output="",
            cost=row_tracker.total_cost,
            input_tokens=row_tracker.total_input_tokens,
            output_tokens=row_tracker.total_output_tokens,
            cached=False,
            error="external cost unavailable for eval route",
        )
    analysis = _Analysis(
        output=output,
        cost=row_tracker.total_cost,
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


def _merge_eval_usage(
    row_tracker: CostTracker,
    run_tracker: CostTracker,
    provider: str,
) -> bool:
    """Normalize route identity, merge every attempt, and flag unknown cost."""

    route_type = _eval_provider_type(provider)
    normalized: list[TokenUsage] = []
    for entry in row_tracker.entries:
        if provider in LOCAL_PROVIDERS:
            normalized_entry = replace(
                entry,
                provider_name=provider,
                provider_type=route_type,
            )
        else:
            normalized_entry = replace(
                entry,
                provider_name=entry.provider_name or provider,
                provider_type=entry.provider_type or route_type,
            )
        normalized.append(normalized_entry)
    row_tracker.entries[:] = normalized
    for entry in normalized:
        run_tracker.record(entry)
    return any(entry.external_cost_unavailable for entry in normalized)


def _heuristic_summary(qs: QualityScore) -> str:
    """One-line advisory digest of the deterministic dimension scores for the judge."""
    dims = ", ".join(f"{d.name.lower()} {d.score:.2f}" for d in qs.dimensions)
    return f"{dims} (composite {qs.composite:.2f})"


def _validated_win_rate(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("pairwise win rate must be numeric")
    win_rate = float(value)
    if not math.isfinite(win_rate) or not 0.0 <= win_rate <= 1.0:
        raise ValueError("pairwise win rate must be finite and between zero and one")
    return win_rate


def _validated_rationale(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("judge rationale must be text")
    return value


def _validated_faithfulness_label(value: object) -> str:
    if not isinstance(value, str) or value not in FAITHFULNESS_ORDINAL:
        raise ValueError("faithfulness label is not recognized")
    return value


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
    key = _hash(
        "pairwise-v3",
        model,
        fixture.id,
        _src_hash(fixture),
        anchor,
        judge_model,
        _hash("candidate-output-v1", candidate_output),
        _hash("anchor-output-v1", anchor_output),
    )
    cached = _load_json(cache_dir, key)
    if cached is not None:
        try:
            return _validated_win_rate(cached.get("win_rate")), _validated_rationale(
                cached.get("rationale", "")
            )
        except (TypeError, ValueError):
            logger.warning("Ignoring malformed eval pairwise cache for %s/%s", model, fixture.id)

    def _scores(output: str) -> str:
        return _heuristic_summary(
            score_output(
                output,
                expected_sections=fixture.expected_sections,
                golden_concepts=fixture.golden_concepts,
                min_words=fixture.min_words,
            )
        )

    try:
        result = judge_pairwise(
            _judge_source(fixture),
            candidate_output,
            anchor_output,
            judge_model=judge_model,
            tracker=run_tracker,
            candidate_heuristics=_scores(candidate_output),
            anchor_heuristics=_scores(anchor_output),
        )
    except Exception as exc:
        logger.warning("eval pairwise judge failed for %s on %s: %s", model, fixture.id, exc)
        return None, ""
    if result is None:
        return None, ""
    try:
        win_rate = _validated_win_rate(result.win_rate)
        rationale = _validated_rationale(result.rationale)
    except ValueError:
        logger.warning("Ignoring malformed eval pairwise verdict for %s/%s", model, fixture.id)
        return None, ""
    # Don't cache a failed verdict (None) — otherwise a transient judge failure is
    # frozen in and every rerun reuses it instead of re-judging.
    _save_json(cache_dir, key, {"win_rate": win_rate, "rationale": rationale})
    return win_rate, rationale


def _faithfulness(
    model: str,
    fixture: Fixture,
    output: str,
    judge_model: str,
    run_tracker: CostTracker,
    cache_dir: Path | None,
) -> tuple[str, str]:
    """Absolute source-anchored faithfulness verdict for one output; cached.

    Returns ``(label, rationale)`` where ``label`` is "" when no verdict was
    produced (parse failure / judge error) — the row then carries no faithfulness
    signal rather than a fabricated one.
    """
    key = _hash(
        "faithful-v2",
        model,
        fixture.id,
        _src_hash(fixture),
        judge_model,
        _hash("judged-output-v1", output),
    )
    cached = _load_json(cache_dir, key)
    if cached is not None:
        try:
            return _validated_faithfulness_label(cached.get("label")), _validated_rationale(
                cached.get("rationale", "")
            )
        except (TypeError, ValueError):
            logger.warning(
                "Ignoring malformed eval faithfulness cache for %s/%s", model, fixture.id
            )
    try:
        verdict = judge_faithfulness(
            _judge_source(fixture), output, judge_model=judge_model, tracker=run_tracker
        )
    except Exception as exc:
        logger.warning("eval faithfulness judge failed for %s on %s: %s", model, fixture.id, exc)
        return "", ""
    if verdict is None:
        # Unparseable verdict: no signal, and don't cache (a rerun re-judges).
        return "", ""
    try:
        label = _validated_faithfulness_label(verdict.label)
        rationale = _validated_rationale(verdict.rationale)
    except ValueError:
        logger.warning("Ignoring malformed eval faithfulness verdict for %s/%s", model, fixture.id)
        return "", ""
    _save_json(cache_dir, key, {"label": label, "rationale": rationale})
    return label, rationale


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
            faith_label = ""
            faith_rationale = ""
            # Faithfulness: an absolute, anchor-free grading of THIS output against
            # the source — judged for every model (the anchor too) whenever a judge
            # is configured and the output is real. It is the migration veto floor.
            if judge_model and not a.error and a.output:
                faith_label, faith_rationale = _faithfulness(
                    model, fixture, a.output, judge_model, run_tracker, cache_dir
                )
            # Pairwise: candidate-vs-anchor, only for non-anchor models with both
            # outputs real. An empty judge_model means no neutral judge was
            # available -> no head-to-head signal (report fails closed).
            if (
                judge_model
                and model != anchor
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
                    faithfulness=faith_label,
                    faithfulness_rationale=faith_rationale,
                    risk_patterns=fixture.risk_patterns,
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
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    # Only object-shaped entries are usable cache rows; a valid-JSON list/scalar
    # would crash callers that do ``cached[...]`` / ``cached.get(...)``.
    return data if isinstance(data, dict) else None


def _save_json(cache_dir: Path | None, key: str, payload: dict) -> None:
    if cache_dir is None:
        return
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / f"{key}.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

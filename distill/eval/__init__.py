"""Model eval — sweep candidate models over fixtures, score quality + cost.

Public surface:
- ``run_model_eval`` / ``EvalRow`` (harness): analyze + score + cost + judge per row.
- ``summarize`` / ``EvalSummary`` / ``console_lines`` / ``render_markdown`` (report).
- ``load_fixtures`` / ``Fixture`` / ``WORKLOADS`` (fixtures).
- ``score_output`` / ``QualityScore`` (deterministic guardrail scoring); the model
  judges ``judge_faithfulness`` (absolute, source-anchored veto floor) and
  ``judge_pairwise`` (relative ranking) + ``judge_shares_family``.

A migration is gated by the model judges, not the deterministic composite: the
composite is a guardrail floor, faithfulness vetoes, and the pairwise win-rate
ranks the faithful (see ``docs/invariants.md`` and
``docs/design/model-judgment-vs-brittle-fallbacks.md``: LLM proposes, Python decides).
"""

from __future__ import annotations

from distill.eval.fixtures import WORKLOADS, Fixture, load_fixtures
from distill.eval.golden import GOLDEN_OUTPUTS, degraded_output
from distill.eval.graduation import (
    ADAPTER_GRADUATION_REQUIREMENTS,
    AdapterGraduationDecision,
    EvalGateDecision,
    adapter_route_graduation_decision,
    eval_gate_decision,
)
from distill.eval.harness import (
    EvalRow,
    estimate_eval_cost,
    provider_for_model,
    run_model_eval,
)
from distill.eval.judge import (
    DEFAULT_JUDGE_MODEL,
    FAITHFULNESS_ORDINAL,
    FaithfulnessVerdict,
    PairwiseResult,
    judge_faithfulness,
    judge_pairwise,
    judge_shares_family,
)
from distill.eval.report import (
    DEFAULT_THRESHOLD,
    MIGRATION_WINRATE_FLOOR,
    EvalSummary,
    ModelSummary,
    console_lines,
    render_markdown,
    results_log_lines,
    summarize,
)
from distill.eval.route_availability import (
    MIN_USABLE_HEADROOM_PERCENT,
    RouteAvailabilityDecision,
    RouteAvailabilitySignal,
    RouteQuotaStop,
    RouteQuotaWindow,
    route_availability_decision,
    route_availability_signal_from_manifest,
)
from distill.eval.route_pool import (
    RouteCandidate,
    RoutePoolEntry,
    RoutePoolSelection,
    select_route_pool,
)
from distill.eval.scoring import QualityScore, score_output

__all__ = [
    "ADAPTER_GRADUATION_REQUIREMENTS",
    "DEFAULT_JUDGE_MODEL",
    "DEFAULT_THRESHOLD",
    "FAITHFULNESS_ORDINAL",
    "GOLDEN_OUTPUTS",
    "MIGRATION_WINRATE_FLOOR",
    "MIN_USABLE_HEADROOM_PERCENT",
    "WORKLOADS",
    "AdapterGraduationDecision",
    "EvalGateDecision",
    "EvalRow",
    "EvalSummary",
    "FaithfulnessVerdict",
    "Fixture",
    "ModelSummary",
    "PairwiseResult",
    "QualityScore",
    "RouteAvailabilityDecision",
    "RouteAvailabilitySignal",
    "RouteCandidate",
    "RoutePoolEntry",
    "RoutePoolSelection",
    "RouteQuotaStop",
    "RouteQuotaWindow",
    "adapter_route_graduation_decision",
    "console_lines",
    "degraded_output",
    "estimate_eval_cost",
    "eval_gate_decision",
    "judge_faithfulness",
    "judge_pairwise",
    "judge_shares_family",
    "load_fixtures",
    "provider_for_model",
    "render_markdown",
    "results_log_lines",
    "route_availability_decision",
    "route_availability_signal_from_manifest",
    "run_model_eval",
    "score_output",
    "select_route_pool",
    "summarize",
]

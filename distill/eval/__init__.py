"""Model eval — sweep candidate models over fixtures, score quality + cost.

Public surface:
- ``run_model_eval`` / ``EvalRow`` (harness): analyze + score + cost + pairwise per row.
- ``summarize`` / ``EvalSummary`` / ``console_lines`` / ``render_markdown`` (report).
- ``load_fixtures`` / ``Fixture`` / ``WORKLOADS`` (fixtures).
- ``score_output`` / ``QualityScore`` (deterministic scoring) and ``judge_pairwise`` /
  ``judge_shares_family`` (advisory pairwise judge).

The deterministic composite is the decision signal; the pairwise judge is advisory
and only affects confidence (see ``docs/invariants.md``: LLM proposes, Python decides).
"""

from __future__ import annotations

from distill.eval.fixtures import WORKLOADS, Fixture, load_fixtures
from distill.eval.golden import GOLDEN_OUTPUTS, degraded_output
from distill.eval.harness import (
    EvalRow,
    estimate_eval_cost,
    provider_for_model,
    run_model_eval,
)
from distill.eval.judge import (
    DEFAULT_JUDGE_MODEL,
    PairwiseResult,
    judge_pairwise,
    judge_shares_family,
)
from distill.eval.report import (
    DEFAULT_THRESHOLD,
    EvalSummary,
    ModelSummary,
    console_lines,
    render_markdown,
    results_log_lines,
    summarize,
)
from distill.eval.scoring import QualityScore, score_output

__all__ = [
    "DEFAULT_JUDGE_MODEL",
    "DEFAULT_THRESHOLD",
    "GOLDEN_OUTPUTS",
    "WORKLOADS",
    "EvalRow",
    "EvalSummary",
    "Fixture",
    "ModelSummary",
    "PairwiseResult",
    "QualityScore",
    "console_lines",
    "degraded_output",
    "estimate_eval_cost",
    "judge_pairwise",
    "judge_shares_family",
    "load_fixtures",
    "provider_for_model",
    "render_markdown",
    "results_log_lines",
    "run_model_eval",
    "score_output",
    "summarize",
]

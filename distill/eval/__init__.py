"""Model eval — sweep candidate models over fixtures, score quality + cost.

Public surface:
- ``run_model_eval`` / ``EvalRow`` (harness): run + score + cost per (model, fixture).
- ``summarize`` / ``EvalSummary`` / ``console_lines`` / ``render_markdown`` (report).
- ``load_fixtures`` / ``Fixture`` / ``WORKLOADS`` (fixtures).
- ``score_output`` / ``QualityScore`` (scoring) and ``judge_output`` (advisory judge).

The judge is advisory; the threshold and recommended pick are deterministic
(see ``docs/invariants.md``: LLM proposes, Python decides).
"""

from __future__ import annotations

from distill.eval.fixtures import WORKLOADS, Fixture, load_fixtures
from distill.eval.harness import EvalRow, provider_for_model, run_model_eval
from distill.eval.judge import DEFAULT_JUDGE_MODEL, JudgeScore, judge_output
from distill.eval.report import (
    DEFAULT_THRESHOLD,
    EvalSummary,
    ModelSummary,
    console_lines,
    render_markdown,
    summarize,
)
from distill.eval.scoring import QualityScore, score_output

__all__ = [
    "DEFAULT_JUDGE_MODEL",
    "DEFAULT_THRESHOLD",
    "WORKLOADS",
    "EvalRow",
    "EvalSummary",
    "Fixture",
    "JudgeScore",
    "ModelSummary",
    "QualityScore",
    "console_lines",
    "judge_output",
    "load_fixtures",
    "provider_for_model",
    "render_markdown",
    "run_model_eval",
    "score_output",
    "summarize",
]

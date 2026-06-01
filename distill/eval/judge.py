"""Advisory LLM-judge for the model eval.

A *different* model scores a candidate analysis against its source on
faithfulness / depth / coverage. The result is advisory — it feeds the composite
at a capped weight (see ``scoring.JUDGE_WEIGHT``) and never makes the pass/pick
decision. Self-judging is refused (a model scoring its own output has a
self-preference bias), so when the judge equals the candidate this returns
``None`` and that row scores on the deterministic dimensions alone.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

from distill.llm import call as llm_call
from distill.llm.router import RouterConfig
from distill.pipeline.costs import CostTracker, TokenUsage

logger = logging.getLogger(__name__)

__all__ = ["DEFAULT_JUDGE_MODEL", "JudgeScore", "judge_output"]

DEFAULT_JUDGE_MODEL: str = "grok-4.3"
_MAX_SOURCE_CHARS: int = 6000
_MAX_OUTPUT_CHARS: int = 8000


@dataclass(frozen=True)
class JudgeScore:
    faithfulness: float
    depth: float
    coverage: float
    overall: float
    rationale: str


def _judge_prompt(source_excerpt: str, candidate_output: str) -> str:
    return f"""You are grading an AI-generated analysis against its SOURCE. Be strict and concrete.

Score each dimension from 0.0 to 1.0:
- faithfulness: are the analysis's claims actually supported by the SOURCE? Penalize anything invented or not present.
- depth: is it substantive (specific methods, numbers, named entities) rather than vague summary?
- coverage: does it capture the SOURCE's most important points, not just easy ones?

Return ONLY valid JSON:
{{"faithfulness": 0.0, "depth": 0.0, "coverage": 0.0, "rationale": "one concrete sentence"}}

SOURCE:
{source_excerpt[:_MAX_SOURCE_CHARS]}

ANALYSIS:
{candidate_output[:_MAX_OUTPUT_CHARS]}
"""


def _clamp(value: object) -> float:
    try:
        return max(0.0, min(1.0, float(value)))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


def _parse(text: str) -> JudgeScore | None:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        logger.warning("eval judge returned no JSON object; scoring deterministic-only")
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        logger.warning("eval judge JSON did not parse; scoring deterministic-only")
        return None
    faithfulness = _clamp(data.get("faithfulness"))
    depth = _clamp(data.get("depth"))
    coverage = _clamp(data.get("coverage"))
    overall = (faithfulness + depth + coverage) / 3.0
    rationale = str(data.get("rationale", "")).strip()[:300]
    return JudgeScore(faithfulness, depth, coverage, overall, rationale)


def judge_output(
    source_excerpt: str,
    candidate_output: str,
    *,
    candidate_model: str,
    judge_model: str = DEFAULT_JUDGE_MODEL,
    tracker: CostTracker | None = None,
    router_config: RouterConfig | None = None,
) -> JudgeScore | None:
    """Score ``candidate_output`` against ``source_excerpt`` with ``judge_model``.

    Returns ``None`` (deterministic-only) when the judge would grade its own
    model's output, or when the judge response can't be parsed. Cost-tracked.
    """
    if judge_model == candidate_model:
        return None
    rc = (router_config or RouterConfig()).with_model_override(judge_model)
    response = llm_call(
        rc,
        workload_tag="qa",
        prompt=_judge_prompt(source_excerpt, candidate_output),
        max_tokens=512,
        call_type="eval_judge",
        temperature=0.0,
    )
    if tracker:
        tracker.record(
            TokenUsage(
                prompt_tokens=response.input_tokens,
                completion_tokens=response.output_tokens,
                model=response.model,
                call_type="eval_judge",
            )
        )
    return _parse(response.text)

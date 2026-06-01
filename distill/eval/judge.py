"""Advisory pairwise LLM-judge for the model eval.

The judge compares a candidate analysis against the **anchor** (incumbent/reference)
analysis of the same source and reports the candidate's win-rate. It runs **both
orderings** (candidate as A, then as B) and averages, which cancels position bias
— the most common LLM-judge failure. It is reference-guided by construction (the
anchor is the reference).

The result is **advisory**: it feeds only the eval's *confidence* signal, never
the recommendation, which is computed from deterministic scores (``scoring`` +
``report``). When the judge shares the anchor's model family the comparison is
biased *toward the anchor* — i.e. conservative (it won't over-recommend switching
away); ``judge_shares_family`` lets the caller surface that caveat.
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

__all__ = [
    "DEFAULT_JUDGE_MODEL",
    "PairwiseResult",
    "judge_pairwise",
    "judge_shares_family",
]

DEFAULT_JUDGE_MODEL: str = "grok-4.3"
_MAX_SOURCE_CHARS: int = 6000
_MAX_OUTPUT_CHARS: int = 8000


@dataclass(frozen=True)
class PairwiseResult:
    win_rate: float  # candidate's win-rate vs anchor, 0.0-1.0 (0.5 = tie)
    comparisons: int  # number of order-randomized comparisons aggregated
    rationale: str


def _family(model: str) -> str:
    return model.lower().split("-")[0].split(":")[0].split(".")[0]


def judge_shares_family(judge_model: str, anchor_model: str) -> bool:
    """True when the judge and anchor are the same model family (conservative bias)."""
    return _family(judge_model) == _family(anchor_model)


def _pairwise_prompt(source: str, output_a: str, output_b: str) -> str:
    return f"""You are comparing two AI-generated analyses (A and B) of the same SOURCE. Decide which is the better analysis: faithful to the SOURCE (no invented claims), substantive (specific methods/numbers/entities), and covering the SOURCE's most important points. Ignore length — a shorter, tighter analysis can be better.

Return ONLY valid JSON:
{{"winner": "A" | "B" | "tie", "rationale": "one concrete sentence"}}

SOURCE:
{source[:_MAX_SOURCE_CHARS]}

ANALYSIS A:
{output_a[:_MAX_OUTPUT_CHARS]}

ANALYSIS B:
{output_b[:_MAX_OUTPUT_CHARS]}
"""


def _winner(text: str) -> str | None:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    winner = str(data.get("winner", "")).strip().upper()
    if winner in ("A", "B"):
        return winner
    if winner == "TIE":
        return "TIE"
    return None


def _rationale(text: str) -> str:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return ""
    try:
        return str(json.loads(match.group(0)).get("rationale", "")).strip()[:300]
    except json.JSONDecodeError:
        return ""


def _one_comparison(
    rc: RouterConfig, source: str, output_a: str, output_b: str, tracker: CostTracker | None
) -> tuple[str | None, str]:
    response = llm_call(
        rc,
        workload_tag="qa",
        prompt=_pairwise_prompt(source, output_a, output_b),
        max_tokens=400,
        call_type="eval_judge_pairwise",
        temperature=0.0,
    )
    if tracker:
        tracker.record(
            TokenUsage(
                prompt_tokens=response.input_tokens,
                completion_tokens=response.output_tokens,
                model=response.model,
                call_type="eval_judge_pairwise",
            )
        )
    return _winner(response.text), _rationale(response.text)


def judge_pairwise(
    source_excerpt: str,
    candidate_output: str,
    anchor_output: str,
    *,
    judge_model: str = DEFAULT_JUDGE_MODEL,
    tracker: CostTracker | None = None,
    router_config: RouterConfig | None = None,
) -> PairwiseResult | None:
    """Candidate-vs-anchor win-rate, averaged over both orderings (debiased).

    Returns ``None`` if neither ordering yields a parseable verdict (the row then
    has no judge signal and scores deterministic-only). Cost-tracked.
    """
    rc = (router_config or RouterConfig()).with_model_override(judge_model)
    # Ordering 1: candidate = A, anchor = B. Ordering 2: swapped. Averaging the
    # two cancels any A/B position preference the judge has.
    w1, r1 = _one_comparison(rc, source_excerpt, candidate_output, anchor_output, tracker)
    w2, r2 = _one_comparison(rc, source_excerpt, anchor_output, candidate_output, tracker)

    scores: list[float] = []
    if w1 is not None:
        scores.append(1.0 if w1 == "A" else 0.0 if w1 == "B" else 0.5)
    if w2 is not None:
        scores.append(1.0 if w2 == "B" else 0.0 if w2 == "A" else 0.5)
    if not scores:
        logger.warning("eval pairwise judge returned no parseable verdict; deterministic-only")
        return None
    rationale = next((r for r in (r1, r2) if r), "")
    return PairwiseResult(
        win_rate=sum(scores) / len(scores), comparisons=len(scores), rationale=rationale
    )

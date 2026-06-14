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

from distill.eval._models import provider_for_model
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


def _heuristics_block(heur_a: str | None, heur_b: str | None) -> str:
    """Render the advisory deterministic-score block, or empty if absent.

    These are the cheap string/length heuristics from ``scoring.py``. They are
    surfaced as a *prior*, explicitly flagged as noisy, never as the answer —
    the whole point of the judge is to override them when they are wrong (a
    paraphrase the regex missed, padding the word count rewarded). See the
    "brittle proxy metrics" failure mode in docs/design/agentic-balance.md.
    """
    if not heur_a and not heur_b:
        return ""
    return f"""
ADVISORY HEURISTIC SIGNALS (automated string/length matching — noisy, often wrong on paraphrase and easily gamed by padding; treat as a weak prior, not a verdict, and overrule them when your own reading disagrees):
  A: {heur_a or "n/a"}
  B: {heur_b or "n/a"}
"""


def _pairwise_prompt(
    source: str,
    output_a: str,
    output_b: str,
    heur_a: str | None = None,
    heur_b: str | None = None,
) -> str:
    """Reference-guided, rubric-structured pairwise prompt.

    Design follows current LLM-as-judge practice (analytic-rubric decomposition,
    reason-before-verdict, explicit bias guards, reference-guided): the model
    reads the SOURCE as ground truth, scores A and B against four named criteria,
    then commits a single verdict. Atomic criteria beat a holistic "which is
    better" vibe-check by blocking the halo effect (one strong dimension inflating
    the rest) and by pinning faithfulness above polish.
    """
    return f"""You are a meticulous, impartial evaluator comparing two AI-generated analyses (A and B) of the same SOURCE. The SOURCE is the ground truth.

Judge against these criteria, in priority order:
1. Faithfulness (highest priority): every claim is supported by the SOURCE. Invented facts, wrong numbers, or unsupported claims are the worst defect — an analysis that is fluent but unfaithful loses to a plainer faithful one.
2. Substance: specific methods, numbers, entities, and mechanisms from the SOURCE — not generic restatement that could apply to any source.
3. Coverage: captures the SOURCE's most important points, not just easy peripheral ones.
4. Conciseness: says it tightly. Length is NOT quality — padding, repetition, and filler are defects. A shorter, denser analysis beats a longer, padded one with the same content.

Method: assess A and B on each criterion, then decide. If they trade off, the higher-priority criterion wins (an unfaithful claim outweighs broader coverage). Judge content, not surface: ignore which analysis is shown first, ignore length itself, and do not reward a confident or polished tone that is not backed by the SOURCE.
{_heuristics_block(heur_a, heur_b)}
Return ONLY valid JSON, after reasoning to yourself:
{{"winner": "A" | "B" | "tie", "rationale": "one concrete sentence naming the deciding criterion and the specific evidence"}}

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
    rc: RouterConfig,
    source: str,
    output_a: str,
    output_b: str,
    tracker: CostTracker | None,
    heur_a: str | None = None,
    heur_b: str | None = None,
) -> tuple[str | None, str]:
    response = llm_call(
        rc,
        workload_tag="qa",
        prompt=_pairwise_prompt(source, output_a, output_b, heur_a, heur_b),
        # Generous cap: "thinking" models (Gemini 3.x, Qwen3) spend output budget
        # on a reasoning trace before the verdict; a tight cap truncates the JSON.
        max_tokens=2048,
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
    candidate_heuristics: str | None = None,
    anchor_heuristics: str | None = None,
) -> PairwiseResult | None:
    """Candidate-vs-anchor win-rate, averaged over both orderings (debiased).

    Returns ``None`` unless BOTH orderings yield a parseable verdict -- a single
    ordering is position-biased, so a half-result is reported as no judge signal
    (the row scores deterministic-only) rather than as a debiased win-rate.
    Cost-tracked.

    ``candidate_heuristics`` / ``anchor_heuristics`` are optional one-line
    summaries of the cheap deterministic scores; when supplied they are shown to
    the judge as an explicitly-noisy prior (see ``_heuristics_block``). They
    follow the *output*, not the slot — so they are swapped along with A/B in
    ordering 2, preserving the debias.
    """
    # Route to the judge model's own provider (a gemini judge must hit the gemini
    # endpoint, not the default xAI one) and force the judge model id.
    base = router_config or RouterConfig(provider=provider_for_model(judge_model))
    rc = base.with_model_override(judge_model)
    # Ordering 1: candidate = A, anchor = B. Ordering 2: swapped. Averaging the
    # two cancels any A/B position preference the judge has. The heuristic priors
    # swap with their outputs so each stays attached to the analysis it describes.
    w1, r1 = _one_comparison(
        rc,
        source_excerpt,
        candidate_output,
        anchor_output,
        tracker,
        candidate_heuristics,
        anchor_heuristics,
    )
    w2, r2 = _one_comparison(
        rc,
        source_excerpt,
        anchor_output,
        candidate_output,
        tracker,
        anchor_heuristics,
        candidate_heuristics,
    )

    # Both orderings must parse for a debiased win-rate. A single ordering
    # carries the judge's full A/B position bias, so a half-result is treated as
    # no signal (deterministic-only) rather than reported as if it were
    # debiased -- the win-rate's whole purpose is to cancel that bias.
    if w1 is None or w2 is None:
        logger.warning(
            "eval pairwise judge: only %d/2 orderings parsed; no debiased verdict",
            (w1 is not None) + (w2 is not None),
        )
        return None
    scores = [
        1.0 if w1 == "A" else 0.0 if w1 == "B" else 0.5,
        1.0 if w2 == "B" else 0.0 if w2 == "A" else 0.5,
    ]
    rationale = next((r for r in (r1, r2) if r), "")
    return PairwiseResult(win_rate=sum(scores) / len(scores), comparisons=2, rationale=rationale)

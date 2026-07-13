"""LLM-judge surfaces for the model eval — two complementary modes.

Both are model judgments graded against the SOURCE as ground truth (never a
regex/keyword proxy of quality — that is the "brittle proxy" failure mode in
``docs/design/agentic-balance.md``). They are used where June-2026 LLM-judge
practice says each mode is reliable:

- **Pairwise** (``judge_pairwise``) — compares a candidate analysis against the
  **anchor** (incumbent) analysis of the same source and reports the candidate's
  win-rate. Runs **both orderings** (candidate as A, then as B) and averages,
  cancelling position bias. Relative judgment is the *reliable* mode (rho~0.95
  ranking correlation), so this is the **primary ranking signal** among faithful
  candidates. ``report`` gates a migration on it.
- **Faithfulness** (``judge_faithfulness``) — grades ONE output absolutely
  against the source: are its load-bearing claims supported? This is the
  NLI/entailment-shaped, *coarse* end of absolute judging — deliberately a 3-way
  categorical (``faithful``/``minor``/``unfaithful``), not a fine-grained score,
  because absolute fine-grained scoring is the *unreliable* mode (kappa~0.45). It
  is an independent, anchor-free **veto floor**: a fluent-but-unfaithful candidate
  that wins pairwise is still refused, and a faithful candidate is not penalised
  merely for diverging from the incumbent's framing (the eval-gate #3 fix).

When the judge shares the anchor's model family the pairwise comparison is biased
*toward the anchor* — conservative (it won't over-recommend switching away);
``judge_shares_family`` lets the caller surface that caveat.
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
    "FAITHFULNESS_ORDINAL",
    "FaithfulnessVerdict",
    "PairwiseResult",
    "judge_faithfulness",
    "judge_pairwise",
    "judge_shares_family",
]

DEFAULT_JUDGE_MODEL: str = "grok-4.3"
_MAX_SOURCE_CHARS: int = 6000
_MAX_OUTPUT_CHARS: int = 8000

# Coarse, ordered faithfulness categories. Ordinal lets the report aggregate and
# compare (candidate vs anchor) without pretending to a fine-grained score the
# judge can't reliably assign (kappa~0.45 on absolute scoring). "unfaithful" is
# the migration veto; the middle "minor" is a soft, surfaced caveat.
FAITHFULNESS_ORDINAL: dict[str, int] = {"unfaithful": 0, "minor": 1, "faithful": 2}


@dataclass(frozen=True)
class PairwiseResult:
    win_rate: float  # candidate's win-rate vs anchor, 0.0-1.0 (0.5 = tie)
    comparisons: int  # number of order-randomized comparisons aggregated
    rationale: str


@dataclass(frozen=True)
class FaithfulnessVerdict:
    label: str  # one of FAITHFULNESS_ORDINAL keys
    unsupported: tuple[str, ...]  # load-bearing claims the judge could not ground
    rationale: str

    @property
    def ordinal(self) -> int:
        return FAITHFULNESS_ORDINAL[self.label]


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
        usage_tracker=tracker,
    )
    if tracker:
        tracker.record(TokenUsage.from_response(response, call_type="eval_judge_pairwise"))
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


def _faithfulness_prompt(source: str, output: str) -> str:
    """Absolute, source-anchored faithfulness prompt — coarse by design.

    Asks the judge to ground the analysis's load-bearing claims against the
    SOURCE and return a 3-way categorical verdict, NOT a fine-grained score.
    This is the NLI/entailment-shaped task (supported vs not) where absolute
    judging is reliable; a 0-100 "quality" number is the unreliable mode and is
    deliberately not requested. No pairwise comparison and no anchor: the whole
    point is an independent read so a candidate is judged on its own grounding,
    not on how closely it mirrors the incumbent's framing.
    """
    return f"""You are a meticulous fact-checker. Judge ONLY whether ANALYSIS is faithful to SOURCE. The SOURCE is the ground truth; you are not rating style, length, or polish.

A claim is a load-bearing statement of fact: a number, a named entity or method, a date, a quantitative comparison, or a causal/empirical assertion. For each load-bearing claim in ANALYSIS, decide if SOURCE supports it. Ignore generic framing that asserts nothing checkable.

Verdict scale (choose exactly one):
- "faithful": every load-bearing claim is supported by SOURCE. Omitting things is fine — this judges what is said, not coverage.
- "minor": broadly grounded, but one or two small unsupported or imprecise details (e.g. a hedged number, a slightly overstated qualifier) that do not change the substance.
- "unfaithful": one or more invented facts, wrong numbers, or claims SOURCE does not support. A fluent, confident analysis that asserts things absent from SOURCE is unfaithful — fluency is not faithfulness.

Be strict: when a specific claim has no support in SOURCE, it is unsupported even if it sounds plausible. Do not credit outside knowledge; only SOURCE counts.

Return ONLY valid JSON, after reasoning to yourself:
{{"verdict": "faithful" | "minor" | "unfaithful", "unsupported": ["<each unsupported load-bearing claim, verbatim or closely paraphrased>"], "rationale": "one concrete sentence naming the deciding claim(s)"}}

SOURCE:
{source[:_MAX_SOURCE_CHARS]}

ANALYSIS:
{output[:_MAX_OUTPUT_CHARS]}
"""


def _parse_faithfulness(text: str) -> FaithfulnessVerdict | None:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    label = str(data.get("verdict", "")).strip().lower()
    if label not in FAITHFULNESS_ORDINAL:
        return None
    raw_unsupported = data.get("unsupported", [])
    unsupported = (
        tuple(str(c).strip()[:200] for c in raw_unsupported if str(c).strip())
        if isinstance(raw_unsupported, list)
        else ()
    )
    rationale = str(data.get("rationale", "")).strip()[:300]
    return FaithfulnessVerdict(label=label, unsupported=unsupported, rationale=rationale)


def judge_faithfulness(
    source_excerpt: str,
    output: str,
    *,
    judge_model: str = DEFAULT_JUDGE_MODEL,
    tracker: CostTracker | None = None,
    router_config: RouterConfig | None = None,
) -> FaithfulnessVerdict | None:
    """Grade one analysis output's faithfulness against the source (coarse, absolute).

    Returns ``None`` when the verdict can't be parsed (the row then carries no
    faithfulness signal rather than a fabricated one). A single call is correct
    here — there is no A/B slot to debias, unlike the pairwise judge. Routed to
    the judge model's own provider and cost-tracked.
    """
    base = router_config or RouterConfig(provider=provider_for_model(judge_model))
    rc = base.with_model_override(judge_model)
    response = llm_call(
        rc,
        workload_tag="qa",
        prompt=_faithfulness_prompt(source_excerpt, output),
        # Generous cap: reasoning models spend output budget before the JSON.
        max_tokens=2048,
        call_type="eval_judge_faithfulness",
        temperature=0.0,
        usage_tracker=tracker,
    )
    if tracker:
        tracker.record(TokenUsage.from_response(response, call_type="eval_judge_faithfulness"))
    return _parse_faithfulness(response.text)

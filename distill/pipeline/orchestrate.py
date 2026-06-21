"""Route-orchestration selection core (see docs/design/route-orchestration.md).

The load-bearing "judge in the mode the evidence supports" primitive that every
route strategy (ensemble best-of-N, maker-checker, critic-refine) shares: given
several candidate outputs for the same source, pick the best one in the two
modes June-2026 LLM-judge practice says are reliable:

1. A coarse, source-anchored **faithfulness veto** drops any candidate the judge
   cannot ground in the receipts. This is the reliable *absolute* mode (the
   3-way faithful/minor/unfaithful categorical), used only as a floor.
2. Among the faithful survivors, **pairwise comparison** ranks them. This is the
   reliable *comparative* mode (rho~0.95). There is no per-candidate quality
   score and no argmax over scores -- that absolute fine-grained mode is the
   brittle proxy this layer exists to avoid.

Both judges already live in ``distill.eval.judge``; this module reuses them and
adds only the selection plan and an honest degradation/bias label. It is a pure
selection over outputs that already exist, so it is independent of how the
candidates were produced (local model, plan-quota CLI adapter, or a mock route)
and is fully testable with mock judges.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from distill.eval._models import provider_for_model
from distill.eval.judge import (
    DEFAULT_JUDGE_MODEL,
    judge_faithfulness,
    judge_pairwise,
    judge_shares_family,
)
from distill.llm import call as llm_call
from distill.llm.availability import model_available
from distill.llm.router import RouterConfig
from distill.pipeline.costs import CostTracker, TokenUsage
from distill.prompts.shared import UNTRUSTED_CONTENT_RULES

__all__ = [
    "Candidate",
    "EnsembleResult",
    "LlmRoute",
    "MakerCheckerResult",
    "Route",
    "Selection",
    "ensemble",
    "maker_checker",
    "select_best",
]

_MAX_SOURCE_CHARS = 6000
_MAX_DRAFT_CHARS = 8000


@dataclass(frozen=True)
class Candidate:
    """One route's output and the model that produced it.

    ``model`` is the route's model id; its family (derived in
    ``distill.eval.judge``) drives the same-family bias label.
    """

    output: str
    model: str


@dataclass(frozen=True)
class Selection:
    """The outcome of :func:`select_best`.

    ``method`` records how the winner was chosen, never a score:
    ``"no-faithful-candidate"``, ``"single-faithful"``, ``"pairwise"``, or
    ``"faithful-no-pairwise-signal"``. ``notice`` carries an honest degradation
    or bias label, or is empty.
    """

    winner: Candidate | None
    faithful: tuple[Candidate, ...]
    vetoed: tuple[Candidate, ...]
    method: str
    notice: str


def _partition_faithful(
    source_excerpt: str,
    candidates: Sequence[Candidate],
    *,
    judge_model: str,
    tracker: CostTracker | None,
    router_config: RouterConfig | None,
) -> tuple[list[Candidate], list[Candidate]]:
    """Split candidates into (faithful, vetoed) via the coarse faithfulness floor.

    Fail closed: only a positively-grounded verdict (``faithful`` or ``minor``)
    counts as faithful; an ``unfaithful`` or unparseable verdict is vetoed.
    """
    faithful: list[Candidate] = []
    vetoed: list[Candidate] = []
    for candidate in candidates:
        verdict = judge_faithfulness(
            source_excerpt,
            candidate.output,
            judge_model=judge_model,
            tracker=tracker,
            router_config=router_config,
        )
        if verdict is not None and verdict.label != "unfaithful":
            faithful.append(candidate)
        else:
            vetoed.append(candidate)
    return faithful, vetoed


def _pairwise_winner(
    source_excerpt: str,
    faithful: list[Candidate],
    *,
    judge_model: str,
    tracker: CostTracker | None,
    router_config: RouterConfig | None,
) -> tuple[Candidate, bool, bool]:
    """Run the pairwise tournament over the faithful survivors.

    Returns ``(winner, ranked, biased)``: each survivor challenges the current
    best and wins only on a debiased win-rate above 0.5; ``ranked`` is False when
    no comparison produced a signal; ``biased`` is True when the judge shared a
    compared candidate's family.
    """
    best = faithful[0]
    ranked = False
    biased = False
    for challenger in faithful[1:]:
        if judge_shares_family(judge_model, challenger.model) or judge_shares_family(
            judge_model, best.model
        ):
            biased = True
        result = judge_pairwise(
            source_excerpt,
            challenger.output,
            best.output,
            judge_model=judge_model,
            tracker=tracker,
            router_config=router_config,
        )
        if result is None:
            continue
        ranked = True
        if result.win_rate > 0.5:
            best = challenger
    return best, ranked, biased


def select_best(
    source_excerpt: str,
    candidates: Sequence[Candidate],
    *,
    judge_model: str = DEFAULT_JUDGE_MODEL,
    tracker: CostTracker | None = None,
    router_config: RouterConfig | None = None,
) -> Selection:
    """Pick the best candidate in the modes the evidence supports.

    Step 1 vetoes every candidate the faithfulness judge cannot ground against
    ``source_excerpt`` (a candidate with no parseable verdict fails closed and is
    treated as not faithful). Step 2 ranks the faithful survivors with a pairwise
    tournament: each survivor challenges the current best and wins only on a
    debiased win-rate above 0.5.

    Honest degradation (charter discipline 5): when no model route is available to
    judge, the winner is ``None`` with method ``"no-judge-model"`` -- the selection
    is skipped, never faked or disguised as a quality verdict. With zero faithful
    candidates the winner is ``None``; with exactly one it wins by default; when
    the pairwise judge yields no signal the first faithful candidate is returned,
    labeled as unranked. ``notice`` surfaces a same-family judge bias (the judge
    shares a compared candidate's family, so the comparison is conservatively
    biased) rather than hiding it.

    The pairwise step is a sequential tournament, so under non-transitive judge
    verdicts (A beats B, B beats C, C beats A) the winner can depend on candidate
    order. That is a known limit of the king-of-the-hill reduction, not a quality
    score.
    """
    if not model_available("qa"):
        return Selection(
            None,
            (),
            (),
            method="no-judge-model",
            notice="no model route available to judge candidates; selection skipped",
        )
    faithful, vetoed = _partition_faithful(
        source_excerpt,
        candidates,
        judge_model=judge_model,
        tracker=tracker,
        router_config=router_config,
    )
    if not faithful:
        return Selection(None, (), tuple(vetoed), method="no-faithful-candidate", notice="")
    if len(faithful) == 1:
        return Selection(
            faithful[0], tuple(faithful), tuple(vetoed), method="single-faithful", notice=""
        )

    best, ranked, biased = _pairwise_winner(
        source_excerpt,
        faithful,
        judge_model=judge_model,
        tracker=tracker,
        router_config=router_config,
    )
    notices: list[str] = []
    if biased:
        notices.append(
            "judge shares a candidate's family; pairwise comparison is conservatively biased"
        )
    if ranked:
        method = "pairwise"
    else:
        method = "faithful-no-pairwise-signal"
        notices.append("no pairwise signal; winner is the unranked first faithful candidate")
    return Selection(best, tuple(faithful), tuple(vetoed), method=method, notice="; ".join(notices))


class Route(Protocol):
    """A model route that turns a prompt into output text.

    ``model`` is the route's model id; its family drives the cross-family rule.
    Concrete routes wrap the LLM router (:class:`LlmRoute`), a plan-quota CLI
    adapter, or a test double.
    """

    model: str

    def run(self, prompt: str, *, tracker: CostTracker | None = None) -> str: ...


@dataclass(frozen=True)
class LlmRoute:
    """A :class:`Route` backed by the LLM router, forcing a specific model."""

    model: str
    workload_tag: str = "qa"
    router_config: RouterConfig | None = None

    def run(self, prompt: str, *, tracker: CostTracker | None = None) -> str:
        base = self.router_config or RouterConfig(provider=provider_for_model(self.model))
        response = llm_call(
            base.with_model_override(self.model),
            workload_tag=self.workload_tag,
            prompt=prompt,
            call_type="orchestrate_route",
            temperature=0.0,
        )
        if tracker:
            tracker.record(TokenUsage.from_response(response, call_type="orchestrate_route"))
        return response.text


@dataclass(frozen=True)
class MakerCheckerResult:
    """Outcome of :func:`maker_checker`.

    ``method`` is one of: ``"maker-checker"`` (kept the faithful cross-family
    refinement), ``"refinement-unfaithful-kept-draft"``,
    ``"single-route-same-family"`` (the checker shared the maker's family, so the
    refinement was skipped and only the draft was verified), ``"none-faithful"``
    (neither draft nor refinement was grounded), or ``"no-judge-model"``.
    """

    output: str | None  # the accepted, grounded output, or None if nothing was faithful
    draft: str  # the maker's draft
    refined: str | None  # the checker's refinement, or None when skipped
    method: str
    notice: str


def _refine_prompt(source_excerpt: str, draft: str) -> str:
    return f"""{UNTRUSTED_CONTENT_RULES}

You are reviewing a DRAFT analysis of the SOURCE. The SOURCE is the ground truth.

Correct the DRAFT against the SOURCE: remove or fix any claim the SOURCE does not
support (wrong numbers, invented facts, unsupported assertions) and tighten anything
vague, while keeping everything the SOURCE does support. Output only the corrected
analysis, with no commentary.

SOURCE:
{source_excerpt[:_MAX_SOURCE_CHARS]}

DRAFT:
{draft[:_MAX_DRAFT_CHARS]}
"""


def _is_faithful(
    source_excerpt: str,
    output: str,
    *,
    judge_model: str,
    tracker: CostTracker | None,
    router_config: RouterConfig | None,
) -> bool:
    """True when the faithfulness floor grounds ``output`` in the source.

    Coarse, absolute, anchor-free grounding -- the reliable, family-bias-resistant
    mode. Fails closed: an ``unfaithful`` or unparseable verdict is not faithful.
    """
    verdict = judge_faithfulness(
        source_excerpt,
        output,
        judge_model=judge_model,
        tracker=tracker,
        router_config=router_config,
    )
    return verdict is not None and verdict.label != "unfaithful"


def maker_checker(
    source_excerpt: str,
    task_prompt: str,
    *,
    maker: Route,
    checker: Route,
    judge_model: str = DEFAULT_JUDGE_MODEL,
    tracker: CostTracker | None = None,
    router_config: RouterConfig | None = None,
) -> MakerCheckerResult:
    """Draft on one route, then have a different-family route check and refine it.

    The maker drafts from ``task_prompt``; the checker -- which must be a different
    model family, since a model corrects an error presented externally but not the
    identical error in its own output -- reviews the draft against
    ``source_excerpt`` and returns a corrected version. The correction is the
    deliverable, verified against the source by the coarse faithfulness floor (the
    reliable absolute mode): keep the refinement when it is grounded, otherwise
    fall back to the faithful draft.

    No pairwise here, on purpose. A pairwise "is the refinement better" comparison
    would need a judge neutral to both routes to avoid self-preference bias, which
    is large; that comparison is the ensemble strategy's job, not a
    correct-then-verify pass. Grounding is the mode the evidence supports here, and
    it is family-bias-resistant.

    Degradation: a same-family checker cannot give independent feedback, so the
    refinement is skipped and only the draft is verified
    (``"single-route-same-family"``). With no model route to judge, nothing runs
    (``"no-judge-model"``).
    """
    if not model_available("qa"):
        return MakerCheckerResult(
            output=None,
            draft="",
            refined=None,
            method="no-judge-model",
            notice="no model route available; maker-checker skipped",
        )

    draft = maker.run(task_prompt, tracker=tracker)

    if judge_shares_family(maker.model, checker.model):
        grounded = _is_faithful(
            source_excerpt,
            draft,
            judge_model=judge_model,
            tracker=tracker,
            router_config=router_config,
        )
        return MakerCheckerResult(
            output=draft if grounded else None,
            draft=draft,
            refined=None,
            method="single-route-same-family",
            notice="maker and checker share a family; refinement skipped (no independent feedback)",
        )

    refined = checker.run(_refine_prompt(source_excerpt, draft), tracker=tracker)

    if _is_faithful(
        source_excerpt,
        refined,
        judge_model=judge_model,
        tracker=tracker,
        router_config=router_config,
    ):
        return MakerCheckerResult(
            output=refined,
            draft=draft,
            refined=refined,
            method="maker-checker",
            notice="kept the faithful cross-family refinement",
        )
    if _is_faithful(
        source_excerpt,
        draft,
        judge_model=judge_model,
        tracker=tracker,
        router_config=router_config,
    ):
        return MakerCheckerResult(
            output=draft,
            draft=draft,
            refined=refined,
            method="refinement-unfaithful-kept-draft",
            notice="the refinement was not faithful to the source; kept the faithful draft",
        )
    return MakerCheckerResult(
        output=None,
        draft=draft,
        refined=refined,
        method="none-faithful",
        notice="neither the draft nor the refinement was faithful to the source",
    )


@dataclass(frozen=True)
class EnsembleResult:
    """Outcome of :func:`ensemble`.

    ``method`` is one of: ``"ensemble-pairwise"`` (a neutral judge ranked the
    faithful candidates), ``"ensemble-faithful-unranked"`` (the judge was not
    neutral to every candidate, so the faithful candidates are returned in route
    order without a biased pairwise ranking), ``"no-faithful-candidate"``, or
    ``"no-judge-model"``.
    """

    output: str | None
    candidates: tuple[Candidate, ...]
    selection: Selection | None  # the select_best outcome when a neutral judge ranked
    method: str
    notice: str


def _judge_is_neutral(judge_model: str, candidates: Sequence[Candidate]) -> bool:
    """True when ``judge_model`` shares no candidate's family (safe to pairwise-rank)."""
    return not any(judge_shares_family(judge_model, candidate.model) for candidate in candidates)


def _unranked_faithful(
    source_excerpt: str,
    candidates: Sequence[Candidate],
    *,
    judge_model: str,
    tracker: CostTracker | None,
    router_config: RouterConfig | None,
) -> EnsembleResult:
    """Ground each candidate and return the faithful ones in route order, unranked.

    Used when the judge is not neutral to every candidate: a pairwise pick would be
    biased, so fall back to the family-bias-resistant faithfulness floor and an
    honest, clearly-labeled route order rather than a biased quality ranking.
    """
    faithful = [
        candidate
        for candidate in candidates
        if _is_faithful(
            source_excerpt,
            candidate.output,
            judge_model=judge_model,
            tracker=tracker,
            router_config=router_config,
        )
    ]
    if not faithful:
        return EnsembleResult(
            output=None,
            candidates=tuple(candidates),
            selection=None,
            method="no-faithful-candidate",
            notice="judge not neutral to all candidates; no candidate was faithful to the source",
        )
    return EnsembleResult(
        output=faithful[0].output,
        candidates=tuple(candidates),
        selection=None,
        method="ensemble-faithful-unranked",
        notice=(
            "judge shares a candidate's family; returned the first faithful candidate "
            "in route order, not quality-ranked"
        ),
    )


def ensemble(
    source_excerpt: str,
    task_prompt: str,
    *,
    routes: Sequence[Route],
    judge_model: str = DEFAULT_JUDGE_MODEL,
    tracker: CostTracker | None = None,
    router_config: RouterConfig | None = None,
) -> EnsembleResult:
    """Fan the same task out to several routes, then pick the best faithful output.

    Each route drafts the same ``task_prompt`` independently; the candidates are
    ranked by :func:`select_best` (faithfulness veto, then pairwise) -- but pairwise
    is trusted only when ``judge_model`` is neutral to every candidate's family,
    since pairwise is where self-preference bias is large. When the judge shares a
    candidate's family the faithful candidates are returned in route order,
    unranked and labeled, rather than picked by a biased judge.

    The judge sees candidates one or two at a time (faithfulness is per-candidate,
    pairwise is two at a time), so the orchestrator never accumulates all N outputs
    into a single prompt. Routes run sequentially; they are independent, so parallel
    fan-out is a later performance optimization, not a correctness concern.

    Degradation: with no model route to judge, nothing runs (``"no-judge-model"``);
    with no faithful candidate, the output is ``None``.
    """
    if not model_available("qa"):
        return EnsembleResult(
            output=None,
            candidates=(),
            selection=None,
            method="no-judge-model",
            notice="no model route available; ensemble skipped",
        )

    candidates = [
        Candidate(route.run(task_prompt, tracker=tracker), route.model) for route in routes
    ]

    if not _judge_is_neutral(judge_model, candidates):
        return _unranked_faithful(
            source_excerpt,
            candidates,
            judge_model=judge_model,
            tracker=tracker,
            router_config=router_config,
        )

    selection = select_best(
        source_excerpt,
        candidates,
        judge_model=judge_model,
        tracker=tracker,
        router_config=router_config,
    )
    winner = selection.winner
    return EnsembleResult(
        output=winner.output if winner is not None else None,
        candidates=tuple(candidates),
        selection=selection,
        method="ensemble-pairwise" if winner is not None else "no-faithful-candidate",
        notice=selection.notice,
    )

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
    "LlmRoute",
    "MakerCheckerResult",
    "Route",
    "Selection",
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

    ``method`` is ``"maker-checker"``, ``"single-route-same-family"`` (the checker
    shared the maker's family, so the refinement was skipped), or
    ``"no-judge-model"``.
    """

    output: str | None  # the accepted output, or None if nothing was faithful
    draft: str  # the maker's draft
    refined: str | None  # the checker's refinement, or None when skipped
    selection: Selection | None  # the select_best outcome over {draft, refined}
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


def _winner_output(selection: Selection) -> str | None:
    return selection.winner.output if selection.winner is not None else None


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
    model family, since a model corrects errors presented externally but not the
    identical error in its own output -- reviews the draft against
    ``source_excerpt`` and returns a corrected version. :func:`select_best` then
    faithfulness-vetoes both and keeps whichever faithful one wins pairwise, so a
    refinement is kept only when it is grounded and an improvement, never on faith.

    Degradation: when the checker shares the maker's family there is no independent
    external feedback, so the refinement is skipped and only the maker's draft is
    verified (method ``"single-route-same-family"``). When no model route is
    available to judge, nothing runs (method ``"no-judge-model"``).
    """
    if not model_available("qa"):
        return MakerCheckerResult(
            output=None,
            draft="",
            refined=None,
            selection=None,
            method="no-judge-model",
            notice="no model route available; maker-checker skipped",
        )

    draft = maker.run(task_prompt, tracker=tracker)

    if judge_shares_family(maker.model, checker.model):
        selection = select_best(
            source_excerpt,
            [Candidate(draft, maker.model)],
            judge_model=judge_model,
            tracker=tracker,
            router_config=router_config,
        )
        return MakerCheckerResult(
            output=_winner_output(selection),
            draft=draft,
            refined=None,
            selection=selection,
            method="single-route-same-family",
            notice="maker and checker share a family; refinement skipped (no independent feedback)",
        )

    refined = checker.run(_refine_prompt(source_excerpt, draft), tracker=tracker)
    selection = select_best(
        source_excerpt,
        [Candidate(draft, maker.model), Candidate(refined, checker.model)],
        judge_model=judge_model,
        tracker=tracker,
        router_config=router_config,
    )
    return MakerCheckerResult(
        output=_winner_output(selection),
        draft=draft,
        refined=refined,
        selection=selection,
        method="maker-checker",
        notice=selection.notice,
    )

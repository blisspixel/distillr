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

from distill.eval.judge import (
    DEFAULT_JUDGE_MODEL,
    judge_faithfulness,
    judge_pairwise,
    judge_shares_family,
)
from distill.llm.router import RouterConfig
from distill.pipeline.costs import CostTracker

__all__ = ["Candidate", "Selection", "select_best"]


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

    Honest degradation: with zero faithful candidates the winner is ``None``; with
    exactly one it wins by default; when the pairwise judge yields no signal the
    first faithful candidate is returned, labeled as unranked. ``notice`` surfaces
    a same-family judge bias (the judge shares a compared candidate's family, so
    the comparison is conservatively biased) rather than hiding it.
    """
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

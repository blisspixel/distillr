# pyright: strict
"""Route graduation decisions from eval evidence plus adapter doctor proof.

This module deliberately does not run models, adapters, or provider checks. It is
the rule-owned aggregation layer for already collected evidence:

- semantic quality comes from `distill eval` model-judge verdicts
- no-metered route safety comes from the adapter doctor probe

The deterministic composite is not consulted here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from distill.doctor.adapters import AdapterProbe
from distill.eval.report import MIGRATION_WINRATE_FLOOR, EvalSummary, ModelSummary

ADAPTER_GRADUATION_REQUIREMENTS: tuple[str, ...] = (
    "adapter doctor no-metered eligible",
    "current no-metered support statement",
    "installed-session auth proof",
    "scratch manifest and native usage ledger",
    "eval gate passed",
)


@dataclass(frozen=True)
class EvalGateDecision:
    """Whether one model clears eval evidence for route graduation."""

    model: str
    workload: str
    anchor: str
    passed: bool
    blocked_reasons: tuple[str, ...]
    rows: int = 0
    errors: int = 0
    unfaithful_fixtures: int = 0
    mean_winrate: float | None = None
    mean_faithfulness: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "workload": self.workload,
            "anchor": self.anchor,
            "passed": self.passed,
            "blocked_reasons": list(self.blocked_reasons),
            "rows": self.rows,
            "errors": self.errors,
            "unfaithful_fixtures": self.unfaithful_fixtures,
            "mean_winrate": self.mean_winrate,
            "mean_faithfulness": self.mean_faithfulness,
        }


@dataclass(frozen=True)
class AdapterGraduationDecision:
    """Whether one plan-quota adapter route may enter no-metered routing."""

    adapter: str
    model: str
    workload: str
    eligible: bool
    route_class: str
    auth_mode: str
    doctor_ready: bool
    eval_gate: EvalGateDecision
    blocked_reasons: tuple[str, ...]
    requirements: tuple[str, ...] = ADAPTER_GRADUATION_REQUIREMENTS

    def to_dict(self) -> dict[str, Any]:
        return {
            "adapter": self.adapter,
            "model": self.model,
            "workload": self.workload,
            "eligible": self.eligible,
            "route_class": self.route_class,
            "auth_mode": self.auth_mode,
            "doctor_ready": self.doctor_ready,
            "eval_gate": self.eval_gate.to_dict(),
            "blocked_reasons": list(self.blocked_reasons),
            "requirements": list(self.requirements),
        }


def eval_gate_decision(
    summary: EvalSummary,
    model: str,
    *,
    allow_anchor: bool = False,
    winrate_floor: float = MIGRATION_WINRATE_FLOOR,
) -> EvalGateDecision:
    """Return whether ``model`` clears model-judged eval gates.

    For route graduation, a candidate must be evaluated against an incumbent
    anchor. Passing means:

    - the model produced valid output on every fixture
    - the faithfulness judge produced a signal and did not find unfaithfulness
    - the pairwise judge certified the model at par with the anchor
    - if both models have faithfulness means, the candidate is not less faithful
      than the anchor
    """

    candidate = _find_model(summary, model)
    anchor = _find_model(summary, summary.anchor)
    if candidate is None:
        return EvalGateDecision(
            model=model,
            workload=summary.workload,
            anchor=summary.anchor,
            passed=False,
            blocked_reasons=("model is not present in eval summary",),
        )

    blocked = [
        *_valid_output_blocks(candidate, summary=summary, allow_anchor=allow_anchor),
        *_judge_gate_blocks(candidate, anchor=anchor, summary=summary, winrate_floor=winrate_floor),
    ]

    return EvalGateDecision(
        model=model,
        workload=summary.workload,
        anchor=summary.anchor,
        passed=not blocked,
        blocked_reasons=tuple(blocked),
        rows=candidate.rows,
        errors=candidate.errors,
        unfaithful_fixtures=candidate.unfaithful_fixtures,
        mean_winrate=candidate.mean_winrate,
        mean_faithfulness=candidate.mean_faithfulness,
    )


def adapter_route_graduation_decision(
    summary: EvalSummary,
    probe: AdapterProbe,
    *,
    model: str,
) -> AdapterGraduationDecision:
    """Combine adapter doctor readiness with model-judged eval evidence."""

    eval_gate = eval_gate_decision(summary, model, allow_anchor=False)
    blocked: list[str] = []

    if probe.route_class != "included-plan":
        blocked.append(f"adapter route class is {probe.route_class}, not included-plan")
    if not probe.no_metered_candidate:
        blocked.append("adapter is not a no-metered candidate")
    if not probe.no_metered_eligible:
        if probe.blocked_reasons:
            blocked.extend(f"adapter doctor: {reason}" for reason in probe.blocked_reasons)
        else:
            blocked.append("adapter doctor did not prove no-metered eligibility")
    blocked.extend(f"eval gate: {reason}" for reason in eval_gate.blocked_reasons)

    return AdapterGraduationDecision(
        adapter=probe.name,
        model=model,
        workload=summary.workload,
        eligible=not blocked,
        route_class=probe.route_class,
        auth_mode=probe.auth_mode,
        doctor_ready=probe.no_metered_eligible,
        eval_gate=eval_gate,
        blocked_reasons=tuple(blocked),
    )


def _find_model(summary: EvalSummary, model: str) -> ModelSummary | None:
    return next((candidate for candidate in summary.models if candidate.model == model), None)


def _valid_output_blocks(
    candidate: ModelSummary,
    *,
    summary: EvalSummary,
    allow_anchor: bool,
) -> list[str]:
    blocked: list[str] = []
    if candidate.model == summary.anchor and not allow_anchor:
        blocked.append("candidate is the anchor; compare it against an incumbent anchor")
    if candidate.rows == 0:
        blocked.append("model produced no valid eval output")
    if candidate.errors:
        blocked.append(f"model errored on {candidate.errors} fixture(s)")
    if candidate.unfaithful_fixtures:
        blocked.append(f"model was unfaithful on {candidate.unfaithful_fixtures} fixture(s)")
    return blocked


def _judge_gate_blocks(
    candidate: ModelSummary,
    *,
    anchor: ModelSummary | None,
    summary: EvalSummary,
    winrate_floor: float,
) -> list[str]:
    if candidate.model == summary.anchor:
        return []

    blocked: list[str] = []
    if candidate.faithfulness_fixtures == 0:
        blocked.append("faithfulness judge did not produce a signal")
    elif candidate.faithfulness_fixtures != candidate.rows:
        blocked.append(
            "faithfulness judge produced signals for "
            f"{candidate.faithfulness_fixtures} of {candidate.rows} fixtures"
        )
    if candidate.pairwise_fixtures == 0 or candidate.mean_winrate is None:
        blocked.append("pairwise judge did not produce a signal")
    elif candidate.pairwise_fixtures != candidate.rows:
        blocked.append(
            "pairwise judge produced signals for "
            f"{candidate.pairwise_fixtures} of {candidate.rows} fixtures"
        )
    elif candidate.mean_winrate < winrate_floor:
        blocked.append(
            f"pairwise win-rate {candidate.mean_winrate:.2f} is below "
            f"at-par floor {winrate_floor:.2f}"
        )
    if _is_less_faithful_than_anchor(candidate, anchor):
        blocked.append("model is less faithful than the anchor")
    return blocked


def _is_less_faithful_than_anchor(candidate: ModelSummary, anchor: ModelSummary | None) -> bool:
    return (
        candidate.mean_faithfulness is not None
        and anchor is not None
        and anchor.mean_faithfulness is not None
        and candidate.mean_faithfulness < anchor.mean_faithfulness
    )

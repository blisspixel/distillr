"""Tests for route-pool admission over cost policy and graduation proof."""

from __future__ import annotations

from distill.eval.graduation import AdapterGraduationDecision, EvalGateDecision
from distill.eval.route_pool import RouteCandidate, select_route_pool


def _eval_gate(*, passed: bool = True) -> EvalGateDecision:
    return EvalGateDecision(
        model="adapter:grok-4.3",
        workload="analysis",
        anchor="grok-4.3",
        passed=passed,
        blocked_reasons=() if passed else ("pairwise judge did not produce a signal",),
        rows=3 if passed else 0,
        mean_winrate=0.60 if passed else None,
        mean_faithfulness=1.0 if passed else None,
    )


def _graduation(
    *,
    adapter: str = "grok",
    model: str = "adapter:grok-4.3",
    workload: str = "analysis",
    eligible: bool = True,
) -> AdapterGraduationDecision:
    return AdapterGraduationDecision(
        adapter=adapter,
        model=model,
        workload=workload,
        eligible=eligible,
        route_class="included-plan",
        auth_mode="included-plan",
        doctor_ready=eligible,
        eval_gate=_eval_gate(passed=eligible),
        blocked_reasons=() if eligible else ("eval gate: pairwise judge did not produce a signal",),
    )


def test_no_metered_selects_local_and_blocks_metered_api() -> None:
    selection = select_route_pool(
        [
            RouteCandidate(provider="xai", model="grok-4.3", workload="analysis"),
            RouteCandidate(provider="ollama", model="qwen3.5:27b", workload="analysis"),
        ],
        cost_mode="no-metered",
        workload="analysis",
    )

    assert selection.selected is not None
    assert selection.selected.candidate.provider == "ollama"
    assert [entry.candidate.provider for entry in selection.allowed] == ["ollama"]
    assert [entry.candidate.provider for entry in selection.blocked] == ["xai"]
    assert "API-billed" in selection.blocked[0].blocked_reasons[0]


def test_included_plan_route_requires_graduation_even_in_auto_mode() -> None:
    selection = select_route_pool(
        [RouteCandidate(provider="grok", model="adapter:grok-4.3", workload="analysis")],
        cost_mode="auto",
        workload="analysis",
    )

    assert selection.selected is None
    assert selection.allowed == ()
    assert selection.blocked[0].cost_class == "included-plan"
    assert "adapter graduation proof is missing" in selection.blocked[0].blocked_reasons


def test_graduated_included_plan_route_enters_pool_before_metered_api() -> None:
    selection = select_route_pool(
        [
            RouteCandidate(provider="xai", model="grok-4.3", workload="analysis"),
            RouteCandidate(provider="grok", model="adapter:grok-4.3", workload="analysis"),
        ],
        cost_mode="auto",
        workload="analysis",
        graduations=[_graduation()],
    )

    assert selection.selected is not None
    assert selection.selected.candidate.provider == "grok"
    assert [entry.candidate.provider for entry in selection.allowed] == ["xai", "grok"]
    assert selection.selected.graduation is not None
    assert selection.selected.graduation.eligible


def test_ineligible_graduation_blocks_adapter_route_with_reasons() -> None:
    selection = select_route_pool(
        [RouteCandidate(provider="grok", model="adapter:grok-4.3", workload="analysis")],
        cost_mode="auto",
        workload="analysis",
        graduations=[_graduation(eligible=False)],
    )

    assert selection.selected is None
    assert selection.blocked[0].graduation is not None
    assert (
        "adapter graduation: eval gate: pairwise judge did not produce a signal"
        in selection.blocked[0].blocked_reasons
    )


def test_credit_metered_route_requires_paid_ok() -> None:
    auto = select_route_pool(
        [RouteCandidate(provider="copilot", model="copilot-cli", workload="analysis")],
        cost_mode="auto",
        workload="analysis",
    )
    paid = select_route_pool(
        [RouteCandidate(provider="copilot", model="copilot-cli", workload="analysis")],
        cost_mode="paid-ok",
        workload="analysis",
    )

    assert auto.selected is None
    assert "credit-metered route requires paid-ok" in auto.blocked[0].blocked_reasons[0]
    assert paid.selected is not None
    assert paid.selected.candidate.provider == "copilot"


def test_unknown_route_never_enters_pool() -> None:
    selection = select_route_pool(
        [RouteCandidate(provider="mystery", model="model", workload="analysis")],
        cost_mode="paid-ok",
        workload="analysis",
    )

    assert selection.selected is None
    assert selection.blocked[0].cost_class == "unknown"
    assert any(
        "unknown billing semantics" in reason for reason in selection.blocked[0].blocked_reasons
    )


def test_route_pool_selection_serializes_for_loop_consumers() -> None:
    selection = select_route_pool(
        [RouteCandidate(provider="ollama", model="qwen3.5:27b", workload="analysis")],
        cost_mode="no-metered",
        workload="analysis",
    )

    data = selection.to_dict()

    assert data["selected"]["candidate"]["provider"] == "ollama"
    assert data["cost_mode"] == "no-metered"
    assert data["workload"] == "analysis"

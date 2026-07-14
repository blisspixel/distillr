"""Tests for route graduation decisions over eval and adapter doctor evidence."""

from dataclasses import replace

from distill.doctor.adapters import AdapterProbe
from distill.eval.graduation import adapter_route_graduation_decision, eval_gate_decision
from distill.eval.harness import EvalRow
from distill.eval.report import summarize
from distill.eval.scoring import QualityScore


def _rows(
    model: str,
    *,
    winrate: float | None,
    faithfulness: str = "faithful",
    cost: float = 0.0,
    error: str = "",
) -> list[EvalRow]:
    return [
        EvalRow(
            workload="paper",
            fixture_id=f"f{i}",
            model=model,
            quality=QualityScore(dimensions=[], composite=0.90),
            cost=cost,
            input_tokens=100,
            output_tokens=50,
            pairwise_winrate=winrate,
            faithfulness=faithfulness,
            error=error,
        )
        for i in range(3)
    ]


def _summary(*extra_rows: EvalRow | list[EvalRow]):
    rows = _rows("grok-4.3", winrate=None, faithfulness="faithful", cost=0.1)
    for item in extra_rows:
        rows.extend(item if isinstance(item, list) else [item])
    return summarize(rows, anchor="grok-4.3")


def _probe(
    *,
    eligible: bool = True,
    route_class: str = "included-plan",
    candidate: bool = True,
    blocked: list[str] | None = None,
) -> AdapterProbe:
    return AdapterProbe(
        name="grok",
        binary="grok",
        route_class=route_class,
        installed=True,
        no_metered_candidate=candidate,
        no_metered_eligible=eligible,
        support_statement="current",
        auth_mode="included-plan",
        blocked_reasons=blocked or [],
    )


def test_eval_gate_passes_when_faithful_and_at_par():
    summary = _summary(_rows("adapter:grok-4.3", winrate=0.55, faithfulness="faithful"))

    decision = eval_gate_decision(summary, "adapter:grok-4.3")

    assert decision.passed
    assert decision.blocked_reasons == ()
    assert decision.rows == 3
    assert decision.mean_winrate == 0.55


def test_eval_gate_blocks_anchor_as_graduation_candidate():
    summary = _summary()

    decision = eval_gate_decision(summary, "grok-4.3")

    assert not decision.passed
    assert "candidate is the anchor" in decision.blocked_reasons[0]


def test_eval_gate_blocks_missing_judge_signal():
    summary = _summary(_rows("adapter:grok-4.3", winrate=None, faithfulness="faithful"))

    decision = eval_gate_decision(summary, "adapter:grok-4.3")

    assert not decision.passed
    assert "pairwise judge did not produce a signal" in decision.blocked_reasons


def test_eval_gate_blocks_partial_judge_evidence():
    candidate = _rows("adapter:grok-4.3", winrate=0.55, faithfulness="faithful")
    candidate[1] = replace(candidate[1], pairwise_winrate=None)
    candidate[2] = replace(candidate[2], faithfulness="unknown")
    summary = _summary(candidate)

    decision = eval_gate_decision(summary, "adapter:grok-4.3")

    assert not decision.passed
    assert "faithfulness judge produced signals for 2 of 3 fixtures" in decision.blocked_reasons
    assert "pairwise judge produced signals for 2 of 3 fixtures" in decision.blocked_reasons


def test_eval_gate_blocks_unfaithful_or_errored_models():
    unfaithful = _summary(_rows("adapter:grok-4.3", winrate=0.70, faithfulness="unfaithful"))
    errored = _summary(_rows("adapter:grok-4.3", winrate=0.70, faithfulness="faithful", error="x"))

    assert (
        "model was unfaithful on 3 fixture(s)"
        in eval_gate_decision(unfaithful, "adapter:grok-4.3").blocked_reasons
    )
    assert (
        "model produced no valid eval output"
        in eval_gate_decision(errored, "adapter:grok-4.3").blocked_reasons
    )


def test_eval_gate_blocks_candidate_less_faithful_than_anchor():
    summary = _summary(_rows("adapter:grok-4.3", winrate=0.70, faithfulness="minor"))

    decision = eval_gate_decision(summary, "adapter:grok-4.3")

    assert not decision.passed
    assert "model is less faithful than the anchor" in decision.blocked_reasons


def test_adapter_graduation_requires_doctor_and_eval_gate():
    summary = _summary(_rows("adapter:grok-4.3", winrate=0.60, faithfulness="faithful"))

    decision = adapter_route_graduation_decision(
        summary,
        _probe(),
        model="adapter:grok-4.3",
    )

    assert decision.eligible
    assert decision.doctor_ready
    assert decision.eval_gate.passed
    assert decision.to_dict()["eligible"] is True


def test_adapter_graduation_blocks_doctor_failure():
    summary = _summary(_rows("adapter:grok-4.3", winrate=0.60, faithfulness="faithful"))

    decision = adapter_route_graduation_decision(
        summary,
        _probe(eligible=False, blocked=["support statement is not current"]),
        model="adapter:grok-4.3",
    )

    assert not decision.eligible
    assert "adapter doctor: support statement is not current" in decision.blocked_reasons


def test_adapter_graduation_blocks_credit_metered_routes():
    summary = _summary(_rows("adapter:copilot", winrate=0.60, faithfulness="faithful"))

    decision = adapter_route_graduation_decision(
        summary,
        _probe(route_class="credit-metered", candidate=False),
        model="adapter:copilot",
    )

    assert not decision.eligible
    assert "not included-plan" in decision.blocked_reasons[0]
    assert "adapter is not a no-metered candidate" in decision.blocked_reasons

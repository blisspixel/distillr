"""Tests for route-pool admission over cost policy and graduation proof."""

from __future__ import annotations

import pytest

from distill.doctor.adapter_manifest import (
    ADAPTER_RESULT_SCHEMA_VERSION,
    validate_adapter_result_manifest,
)
from distill.eval.graduation import AdapterGraduationDecision, EvalGateDecision
from distill.eval.route_availability import (
    RouteAvailabilitySignal,
    RouteQuotaStop,
    RouteQuotaWindow,
    load_route_availability_snapshot,
    local_service_route_availability_signal,
    parse_route_availability_snapshot,
    route_availability_signal_from_manifest,
)
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


def test_route_availability_quota_stop_evicts_graduated_adapter() -> None:
    selection = select_route_pool(
        [RouteCandidate(provider="grok", model="adapter:grok-4.3", workload="analysis")],
        cost_mode="auto",
        workload="analysis",
        graduations=[_graduation()],
        availability_signals=[
            RouteAvailabilitySignal(
                provider="grok",
                model="adapter:grok-4.3",
                workload="analysis",
                checked_at=1_000,
                quota_stop=RouteQuotaStop(
                    reached=True,
                    reason="daily plan quota exhausted",
                    retry_after_seconds=3_600,
                ),
            )
        ],
        now=1_000,
    )

    assert selection.selected is None
    assert selection.blocked[0].availability is not None
    assert selection.blocked[0].availability.blocked_until == 4_600
    assert "route availability: daily plan quota exhausted" in selection.blocked[0].blocked_reasons


def test_route_availability_binding_window_blocks_even_when_short_window_is_green() -> None:
    selection = select_route_pool(
        [RouteCandidate(provider="claude", model="adapter:opus", workload="analysis")],
        cost_mode="auto",
        workload="analysis",
        graduations=[_graduation(adapter="claude", model="adapter:opus")],
        availability_signals=[
            RouteAvailabilitySignal(
                provider="claude",
                workload="analysis",
                checked_at=1_000,
                windows=(
                    RouteQuotaWindow(label="5h", remaining_percent=80.0, resets_at=2_000),
                    RouteQuotaWindow(label="weekly", used_percent=100.0, resets_at=90_000),
                ),
            )
        ],
        now=1_000,
    )

    assert selection.selected is None
    availability = selection.blocked[0].availability
    assert availability is not None
    assert availability.binding_window is not None
    assert availability.binding_window.label == "weekly"
    assert availability.blocked_until == 90_000


def test_require_live_availability_blocks_included_plan_without_signal() -> None:
    selection = select_route_pool(
        [RouteCandidate(provider="grok", model="adapter:grok-4.3", workload="analysis")],
        cost_mode="auto",
        workload="analysis",
        graduations=[_graduation()],
        require_live_availability=True,
    )

    assert selection.selected is None
    assert "live route availability proof is missing" in selection.blocked[0].blocked_reasons


def test_require_live_availability_blocks_local_route_without_signal() -> None:
    selection = select_route_pool(
        [RouteCandidate(provider="ollama", model="qwen3.5:27b", workload="analysis")],
        cost_mode="no-metered",
        workload="analysis",
        require_live_availability=True,
    )

    assert selection.selected is None
    assert "live route availability proof is missing" in selection.blocked[0].blocked_reasons


def test_local_service_signal_allows_running_local_route() -> None:
    selection = select_route_pool(
        [RouteCandidate(provider="ollama", model="qwen3.5:27b", workload="analysis")],
        cost_mode="no-metered",
        workload="analysis",
        availability_signals=[
            local_service_route_availability_signal(
                provider="ollama",
                status="running",
                checked_at=1_000,
                models=("qwen3.5:27b",),
                model="qwen3.5:27b",
                workload="analysis",
            )
        ],
        now=1_000,
        require_live_availability=True,
    )

    assert selection.selected is not None
    assert selection.selected.candidate.provider == "ollama"
    assert selection.selected.availability is not None
    assert selection.selected.availability.available is True


def test_local_service_signal_blocks_unreachable_local_route() -> None:
    selection = select_route_pool(
        [RouteCandidate(provider="lmstudio", model="qwen3.5:27b", workload="analysis")],
        cost_mode="no-metered",
        workload="analysis",
        availability_signals=[
            local_service_route_availability_signal(
                provider="lmstudio",
                status="unavailable",
                checked_at=1_000,
                workload="analysis",
            )
        ],
        now=1_000,
        require_live_availability=True,
    )

    assert selection.selected is None
    assert "route availability: lmstudio local service is not reachable" in (
        selection.blocked[0].blocked_reasons
    )


def test_local_doctor_provider_signal_does_not_prove_model_route() -> None:
    selection = select_route_pool(
        [RouteCandidate(provider="ollama", model="missing-model", workload="analysis")],
        cost_mode="no-metered",
        workload="analysis",
        availability_signals=[
            local_service_route_availability_signal(
                provider="ollama",
                status="running",
                checked_at=1_000,
                models=("qwen3.5:27b",),
                workload="analysis",
            )
        ],
        now=1_000,
        require_live_availability=True,
    )

    assert selection.selected is None
    assert "live local model proof is missing" in selection.blocked[0].blocked_reasons


def test_stale_availability_signal_does_not_prove_route_live() -> None:
    selection = select_route_pool(
        [RouteCandidate(provider="grok", model="adapter:grok-4.3", workload="analysis")],
        cost_mode="auto",
        workload="analysis",
        graduations=[_graduation()],
        availability_signals=[
            RouteAvailabilitySignal(
                provider="grok",
                workload="analysis",
                checked_at=1_000,
                stale=True,
                windows=(RouteQuotaWindow(label="daily", remaining_percent=99.0),),
            )
        ],
        now=1_500,
    )

    assert selection.selected is None
    assert "route availability: route availability proof is stale" in (
        selection.blocked[0].blocked_reasons
    )


def test_same_class_route_selection_prefers_higher_headroom() -> None:
    selection = select_route_pool(
        [
            RouteCandidate(provider="grok", model="adapter:grok-4.3", workload="analysis"),
            RouteCandidate(provider="claude", model="adapter:opus", workload="analysis"),
        ],
        cost_mode="auto",
        workload="analysis",
        graduations=[
            _graduation(),
            _graduation(adapter="claude", model="adapter:opus"),
        ],
        availability_signals=[
            RouteAvailabilitySignal(
                provider="grok",
                workload="analysis",
                windows=(RouteQuotaWindow(label="daily", remaining_percent=15.0),),
            ),
            RouteAvailabilitySignal(
                provider="claude",
                workload="analysis",
                windows=(RouteQuotaWindow(label="daily", remaining_percent=75.0),),
            ),
        ],
        now=1_000,
    )

    assert selection.selected is not None
    assert selection.selected.candidate.provider == "claude"


def test_rolled_over_window_is_treated_as_fresh() -> None:
    selection = select_route_pool(
        [RouteCandidate(provider="grok", model="adapter:grok-4.3", workload="analysis")],
        cost_mode="auto",
        workload="analysis",
        graduations=[_graduation()],
        availability_signals=[
            RouteAvailabilitySignal(
                provider="grok",
                workload="analysis",
                windows=(RouteQuotaWindow(label="daily", used_percent=100.0, resets_at=999),),
            )
        ],
        now=1_000,
    )

    assert selection.selected is not None
    assert selection.selected.availability is not None
    assert selection.selected.availability.headroom_percent == 100.0


def test_adapter_manifest_quota_stop_builds_availability_signal() -> None:
    manifest = validate_adapter_result_manifest(
        {
            "schema_version": ADAPTER_RESULT_SCHEMA_VERSION,
            "adapter": "grok",
            "adapter_version": "grok 0.2.50",
            "auth_class": "included-plan",
            "command_class": "read-only",
            "model": "grok-4.3",
            "prompt_hash": "sha256:prompt",
            "source_hash": "sha256:source",
            "elapsed_ms": 100,
            "usage": {
                "input_tokens": 10,
                "output_tokens": 5,
                "native": {"adapter_format": "grok-json"},
            },
            "stop_reason": "quota",
            "files_read": ["sources/input.md"],
            "files_written": [],
            "output": {"summary": "quota reached"},
            "policy": {
                "cost_mode": "no-metered",
                "blocked_api_key_env": [],
                "metered_allowed": False,
            },
            "quota_stop": {
                "reached": True,
                "reason": "monthly credits exhausted",
                "retry_after_seconds": 120,
                "provider_code": "quota",
                "native": {"remaining_requests": 0},
            },
        }
    )

    signal = route_availability_signal_from_manifest(manifest, now=2_000, workload="analysis")

    assert signal.provider == "grok"
    assert signal.model == "grok-4.3"
    assert signal.evidence_source == "adapter-result-manifest"
    assert signal.quota_stop is not None
    assert signal.quota_stop.blocked_until(2_000) == 2_120


def test_portable_route_availability_snapshot_parses_quota_windows() -> None:
    snapshot = parse_route_availability_snapshot(
        {
            "schema_version": "route-availability.v1",
            "checked_at": 1_000,
            "signals": [
                {
                    "provider": "claude",
                    "model": "adapter:opus",
                    "workload": "analysis",
                    "windows": [{"label": "5h", "remaining_percent": 42.0, "resets_at": 2_000}],
                }
            ],
        }
    )

    signal = snapshot.signals[0]
    assert snapshot.checked_at == 1_000
    assert signal.checked_at == 1_000
    assert signal.evidence_source == "snapshot"
    assert signal.provider == "claude"
    assert signal.windows[0].remaining(1_000) == 42.0
    assert snapshot.to_dict()["schema_version"] == "route-availability.v1"


def test_portable_route_availability_snapshot_rejects_identity_metadata() -> None:
    with pytest.raises(ValueError, match="identity field 'email'"):
        parse_route_availability_snapshot(
            {
                "schema_version": "route-availability.v1",
                "checked_at": 1_000,
                "signals": [
                    {
                        "provider": "claude",
                        "quota_stop": {
                            "reached": True,
                            "reason": "weekly quota exhausted",
                            "native": {"email": "user@example.test"},
                        },
                    }
                ],
            }
        )


def test_load_route_availability_snapshot_accepts_yaml(tmp_path) -> None:
    path = tmp_path / "availability.yaml"
    path.write_text(
        "\n".join(
            [
                "schema_version: route-availability.v1",
                "checked_at: 1000",
                "signals:",
                "  - provider: ollama",
                "    model: qwen3.5:27b",
                "    unavailable_reason: ''",
            ]
        ),
        encoding="utf-8",
    )

    snapshot = load_route_availability_snapshot(path)

    assert snapshot.signals[0].provider == "ollama"

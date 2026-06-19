from __future__ import annotations

import pytest

from distill.llm.cost_policy import (
    CostPolicyError,
    classify_provider,
    normalize_cost_mode,
    require_route_allowed,
    route_block_report,
)


@pytest.mark.parametrize("value", ["auto", "AUTO", " no-metered ", "paid-ok"])
def test_normalize_cost_mode_accepts_supported_values(value: str) -> None:
    assert normalize_cost_mode(value) in {"auto", "no-metered", "paid-ok"}


def test_normalize_cost_mode_rejects_unknown_values() -> None:
    with pytest.raises(ValueError, match="cost_mode"):
        normalize_cost_mode("free")


@pytest.mark.parametrize("provider", ["ollama", "lmstudio"])
def test_local_providers_are_local(provider: str) -> None:
    assert classify_provider(provider) == "local"


@pytest.mark.parametrize("provider", ["xai", "gemini", "openai", "anthropic"])
def test_cloud_api_providers_are_metered(provider: str) -> None:
    assert classify_provider(provider) == "metered-api"


def test_no_metered_allows_local_routes() -> None:
    decision = require_route_allowed(
        cost_mode="no-metered",
        provider="ollama",
        workload="analysis",
    )

    assert decision.allowed
    assert decision.cost_class == "local"
    assert decision.workload == "analysis"


@pytest.mark.parametrize("provider", ["xai", "gemini"])
def test_no_metered_blocks_api_billed_routes(provider: str) -> None:
    with pytest.raises(CostPolicyError, match="Blocked provider"):
        require_route_allowed(
            cost_mode="no-metered",
            provider=provider,
            workload="analysis",
        )


def test_no_metered_blocks_unproven_agent_provider() -> None:
    with pytest.raises(CostPolicyError, match="unknown billing"):
        require_route_allowed(
            cost_mode="no-metered",
            provider="agent",
            workload="analysis",
        )


def test_route_block_report_includes_recovery_hint_for_metered_api() -> None:
    report = route_block_report(
        cost_mode="no-metered",
        provider="xai",
        workload="synthesis",
    )

    assert report["allowed"] is False
    assert report["provider"] == "xai"
    assert report["workload"] == "synthesis"
    assert report["cost_class"] == "metered-api"
    assert "paid-ok" in str(report["recovery_hint"])
    assert "Blocked provider: xai" in str(report["message"])


def test_route_block_report_includes_plan_quota_proof_requirements() -> None:
    report = route_block_report(
        cost_mode="no-metered",
        provider="codex",
        workload="analysis",
    )

    assert report["allowed"] is False
    assert report["cost_class"] == "included-plan"
    assert report["requirements"] == [
        "adapter doctor",
        "support statement",
        "usage ledger",
        "scratch manifest",
        "eval proof",
    ]
    assert "Required proof" in str(report["message"])

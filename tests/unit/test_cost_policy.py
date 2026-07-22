from __future__ import annotations

import pytest

from distill.llm.cost_policy import (
    CostPolicyError,
    classify_provider,
    local_provider_endpoint_is_valid,
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


@pytest.mark.parametrize(
    ("provider", "env_name", "base_url"),
    [
        ("ollama", "OLLAMA_BASE_URL", "http://localhost:11434"),
        ("ollama", "OLLAMA_BASE_URL", "http://127.0.0.2:11434"),
        ("ollama", "OLLAMA_BASE_URL", "http://[::1]:11434"),
        ("lmstudio", "LMSTUDIO_BASE_URL", "http://localhost:1234/v1"),
    ],
)
def test_loopback_local_providers_are_local(
    monkeypatch: pytest.MonkeyPatch,
    provider: str,
    env_name: str,
    base_url: str,
) -> None:
    monkeypatch.setenv(env_name, base_url)

    assert classify_provider(provider) == "local"


@pytest.mark.parametrize(
    ("provider", "env_name", "base_url"),
    [
        ("ollama", "OLLAMA_BASE_URL", "https://hosted.example/v1"),
        ("ollama", "OLLAMA_BASE_URL", "http://localhost.example:11434"),
        ("ollama", "OLLAMA_BASE_URL", "http://127.0.0.1.example:11434"),
        ("ollama", "OLLAMA_BASE_URL", "ftp://localhost:11434"),
        ("ollama", "OLLAMA_BASE_URL", "not-a-url"),
        ("lmstudio", "LMSTUDIO_BASE_URL", "http://0.0.0.0:1234/v1"),
        ("lmstudio", "LMSTUDIO_BASE_URL", "https://hosted.example/v1"),
        ("ollama", "OLLAMA_BASE_URL", "http://user:secret@localhost:11434"),
        ("ollama", "OLLAMA_BASE_URL", "http://localhost:11434?token=secret"),
        ("ollama", "OLLAMA_BASE_URL", "http://localhost:11434?"),
        ("ollama", "OLLAMA_BASE_URL", "http://localhost:11434#fragment"),
        ("ollama", "OLLAMA_BASE_URL", "http://localhost:11434#"),
        ("ollama", "OLLAMA_BASE_URL", "http://local\nhost:11434"),
    ],
)
def test_unproven_local_provider_endpoints_are_unknown(
    monkeypatch: pytest.MonkeyPatch,
    provider: str,
    env_name: str,
    base_url: str,
) -> None:
    monkeypatch.setenv(env_name, base_url)

    assert classify_provider(provider) == "unknown"


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://user:secret@localhost:11434",
        "http://localhost:11434?token=secret",
        "http://localhost:11434?",
        "http://localhost:11434#fragment",
        "http://localhost:11434#",
        "http://local\rhost:11434",
        "http://local\thost:11434",
        "http://localhost:11434/\x00path",
        "http://localhost:11434/\x01path",
    ],
)
def test_local_provider_endpoint_validator_rejects_ambiguous_or_sensitive_urls(
    endpoint: str,
) -> None:
    assert local_provider_endpoint_is_valid(endpoint) is False


@pytest.mark.parametrize("provider", ["xai", "gemini", "openai", "anthropic"])
def test_cloud_api_providers_are_metered(provider: str) -> None:
    assert classify_provider(provider) == "metered-api"


def test_no_metered_allows_local_routes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")

    decision = require_route_allowed(
        cost_mode="no-metered",
        provider="ollama",
        workload="analysis",
    )

    assert decision.allowed
    assert decision.cost_class == "local"
    assert decision.workload == "analysis"


def test_no_metered_blocks_non_loopback_local_route(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OLLAMA_BASE_URL", "https://hosted.example/v1")

    with pytest.raises(CostPolicyError) as exc_info:
        require_route_allowed(
            cost_mode="no-metered",
            provider="ollama",
            workload="analysis",
        )

    message = str(exc_info.value)
    assert "Cost class: unknown" in message
    assert "loopback" in message
    assert "paid-ok" in message


@pytest.mark.parametrize("cost_mode", ["auto", "paid-ok"])
def test_permissive_modes_keep_remote_local_provider_available_but_unproven(
    monkeypatch: pytest.MonkeyPatch,
    cost_mode: str,
) -> None:
    monkeypatch.setenv("LMSTUDIO_BASE_URL", "https://hosted.example/v1")

    decision = require_route_allowed(
        cost_mode=cost_mode,  # type: ignore[arg-type]
        provider="lmstudio",
        workload="analysis",
    )

    assert decision.allowed
    assert decision.cost_class == "unknown"


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

# pyright: strict
"""Cost-mode policy helpers for LLM routes."""

from __future__ import annotations

import ipaddress
import os
from dataclasses import dataclass
from typing import Literal, cast
from urllib.parse import urlsplit

type CostMode = Literal["auto", "no-metered", "paid-ok"]
type RouteCostClass = Literal[
    "local",
    "metered-api",
    "included-plan",
    "credit-metered",
    "unknown",
]

VALID_COST_MODES: frozenset[str] = frozenset({"auto", "no-metered", "paid-ok"})
LOCAL_PROVIDER_NAMES: frozenset[str] = frozenset({"ollama", "lmstudio"})
METERED_API_PROVIDER_NAMES: frozenset[str] = frozenset({"xai", "gemini", "openai", "anthropic"})
CREDIT_METERED_PROVIDER_NAMES: frozenset[str] = frozenset({"copilot"})
PLAN_QUOTA_PROVIDER_NAMES: frozenset[str] = frozenset(
    {"codex", "claude", "grok", "gemini-cli", "antigravity"}
)
_LOCAL_PROVIDER_ENDPOINTS: dict[str, tuple[str, str]] = {
    "ollama": ("OLLAMA_BASE_URL", "http://localhost:11434"),
    "lmstudio": ("LMSTUDIO_BASE_URL", "http://localhost:1234/v1"),
}


@dataclass(frozen=True)
class CostPolicyDecision:
    """Decision for one route under one cost mode."""

    allowed: bool
    cost_mode: CostMode
    provider: str
    workload: str
    cost_class: RouteCostClass
    reason: str
    recovery_hint: str = ""
    requirements: tuple[str, ...] = ()


class CostPolicyError(ValueError):
    """A route is not allowed under the selected cost mode."""


def metered_api_spend_notice() -> str:
    """Operator notice when a run will bill a cloud API.

    Local loopback inference is $0. Subscription quota CLIs are not a Distill
    no-metered route until adapter proof exists. This copy must stay honest on
    both points.
    """
    return (
        "Metered cloud API: provider token billing applies. "
        "This is not local $0 inference (Ollama or LM Studio), and Distill "
        "cannot treat subscription quota CLIs as included-plan until adapter "
        "proof exists. Use --cost-mode no-metered to refuse API-billed routes."
    )


def normalize_cost_mode(value: object) -> CostMode:
    """Normalize and validate a configured cost mode."""

    text = str(value or "").strip().lower()
    if text not in VALID_COST_MODES:
        allowed = ", ".join(sorted(VALID_COST_MODES))
        raise ValueError(f"cost_mode must be one of: {allowed}")
    return cast(CostMode, text)


def local_provider_endpoint(provider: str) -> str:
    """Snapshot the configured endpoint for a local-provider label."""
    endpoint = _LOCAL_PROVIDER_ENDPOINTS.get(provider)
    if endpoint is None:
        return ""
    env_name, default_url = endpoint
    return os.environ.get(env_name, default_url)


def local_provider_endpoint_is_valid(endpoint: str) -> bool:
    """Return whether a local-provider URL is safe to pass to an HTTP client."""

    if (
        endpoint != endpoint.strip()
        or not endpoint
        or "?" in endpoint
        or "#" in endpoint
        or any(ord(character) < 32 or ord(character) == 127 for character in endpoint)
    ):
        return False
    try:
        parsed = urlsplit(endpoint)
        host = (parsed.hostname or "").rstrip(".").lower()
        port = parsed.port
    except ValueError:
        return False
    return bool(
        parsed.scheme in {"http", "https"}
        and host
        and (port is None or port > 0)
        and parsed.username is None
        and parsed.password is None
        and not parsed.query
        and not parsed.fragment
    )


def _local_endpoint_is_loopback(provider: str, endpoint: str | None = None) -> bool:
    raw_url = local_provider_endpoint(provider) if endpoint is None else endpoint
    if not local_provider_endpoint_is_valid(raw_url):
        return False
    try:
        parsed = urlsplit(raw_url)
        host = (parsed.hostname or "").rstrip(".").lower()
    except ValueError:
        return False
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def classify_provider(provider: str, *, endpoint: str | None = None) -> RouteCostClass:
    """Classify a provider by structural cost policy, not output quality."""

    normalized = provider.strip().lower()
    if normalized in LOCAL_PROVIDER_NAMES:
        return "local" if _local_endpoint_is_loopback(normalized, endpoint=endpoint) else "unknown"
    if normalized in METERED_API_PROVIDER_NAMES:
        return "metered-api"
    if normalized in CREDIT_METERED_PROVIDER_NAMES:
        return "credit-metered"
    if normalized in PLAN_QUOTA_PROVIDER_NAMES:
        return "included-plan"
    return "unknown"


def _recovery_hint(cost_class: RouteCostClass, provider: str) -> str:
    """Return operator guidance for a blocked route class."""

    if cost_class == "metered-api":
        return (
            "Rerun with `distill --cost-mode paid-ok <same command>` or set "
            "`DISTILL_COST_MODE=paid-ok` after confirming the spend cap."
        )
    if cost_class == "credit-metered":
        return (
            "Use `paid-ok` only after confirming credit usage is acceptable, or "
            "wait for an explicit credit policy."
        )
    if cost_class == "included-plan":
        return "Add adapter proof before using this provider in no-metered mode."
    if provider in LOCAL_PROVIDER_NAMES:
        return (
            "Use the provider's default loopback endpoint for proven local inference, "
            "or select `paid-ok` only after verifying the remote endpoint's billing "
            "and data boundary."
        )
    return "Use Ollama or LM Studio, or select `paid-ok` after verifying billing."


def _requirements(cost_class: RouteCostClass) -> tuple[str, ...]:
    """Return proof requirements for route classes that need them."""

    if cost_class != "included-plan":
        return ()
    return (
        "adapter doctor",
        "support statement",
        "usage ledger",
        "scratch manifest",
        "eval proof",
    )


def evaluate_route_cost_policy(
    *,
    cost_mode: CostMode,
    provider: str,
    workload: str = "",
    endpoint: str | None = None,
) -> CostPolicyDecision:
    """Return whether a provider route is allowed under ``cost_mode``."""

    normalized_provider = provider.strip().lower()
    cost_class = classify_provider(normalized_provider, endpoint=endpoint)
    label = workload or "default"
    requirements = _requirements(cost_class)

    if cost_mode != "no-metered":
        return CostPolicyDecision(
            allowed=True,
            cost_mode=cost_mode,
            provider=normalized_provider,
            workload=label,
            cost_class=cost_class,
            reason=f"{cost_mode} permits {normalized_provider} for {label}.",
        )

    if cost_class == "local":
        return CostPolicyDecision(
            allowed=True,
            cost_mode=cost_mode,
            provider=normalized_provider,
            workload=label,
            cost_class=cost_class,
            reason=f"no-metered permits local provider {normalized_provider} for {label}.",
        )

    if cost_class == "included-plan":
        reason = (
            f"Provider {normalized_provider} for {label} needs adapter doctor, "
            "support-statement, ledger, scratch-manifest, and eval proof before "
            "it can run in no-metered mode."
        )
    elif cost_class == "metered-api":
        reason = (
            f"Provider {normalized_provider} for {label} is an API-billed route; "
            "select auto or paid-ok to allow metered API spend."
        )
    elif cost_class == "credit-metered":
        reason = (
            f"Provider {normalized_provider} for {label} is credit-metered; "
            "select paid-ok or a future credit policy to allow it."
        )
    elif normalized_provider in LOCAL_PROVIDER_NAMES:
        reason = (
            f"Provider {normalized_provider} for {label} uses a non-loopback or invalid "
            "endpoint, so Distill cannot prove local topology or no-metered billing."
        )
    else:
        reason = (
            f"Provider {normalized_provider or provider} for {label} has unknown "
            "billing semantics and is blocked in no-metered mode."
        )

    return CostPolicyDecision(
        allowed=False,
        cost_mode=cost_mode,
        provider=normalized_provider,
        workload=label,
        cost_class=cost_class,
        reason=reason,
        recovery_hint=_recovery_hint(cost_class, normalized_provider),
        requirements=requirements,
    )


def blocked_route_message(decision: CostPolicyDecision) -> str:
    """Format a blocked route decision for CLI and configuration errors."""

    lines = [
        "Route blocked by no-metered cost policy.",
        f"Blocked provider: {decision.provider or '(empty)'}",
        f"Workload: {decision.workload}",
        f"Cost class: {decision.cost_class}",
        f"Reason: {decision.reason}",
    ]
    if decision.requirements:
        lines.append(f"Required proof: {', '.join(decision.requirements)}")
    if decision.recovery_hint:
        lines.append(f"Next step: {decision.recovery_hint}")
    return "\n".join(lines)


def route_block_report(
    *,
    cost_mode: CostMode,
    provider: str,
    workload: str = "",
) -> dict[str, object]:
    """Return a structured route-policy report for loop consumers."""

    decision = evaluate_route_cost_policy(
        cost_mode=cost_mode,
        provider=provider,
        workload=workload,
    )
    return {
        "allowed": decision.allowed,
        "cost_mode": decision.cost_mode,
        "provider": decision.provider,
        "workload": decision.workload,
        "cost_class": decision.cost_class,
        "reason": decision.reason,
        "recovery_hint": decision.recovery_hint,
        "requirements": list(decision.requirements),
        "message": "" if decision.allowed else blocked_route_message(decision),
    }


def require_route_allowed(
    *,
    cost_mode: CostMode,
    provider: str,
    workload: str = "",
    endpoint: str | None = None,
) -> CostPolicyDecision:
    """Return the decision or raise ``CostPolicyError`` when blocked."""

    decision = evaluate_route_cost_policy(
        cost_mode=cost_mode,
        provider=provider,
        workload=workload,
        endpoint=endpoint,
    )
    if not decision.allowed:
        raise CostPolicyError(blocked_route_message(decision))
    return decision


def route_block_reason(*, cost_mode: CostMode, provider: str, workload: str = "") -> str:
    """Return the block reason, or an empty string when the route is allowed."""

    decision = evaluate_route_cost_policy(
        cost_mode=cost_mode,
        provider=provider,
        workload=workload,
    )
    return "" if decision.allowed else blocked_route_message(decision)

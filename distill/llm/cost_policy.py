# pyright: strict
"""Cost-mode policy helpers for LLM routes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, cast

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


def normalize_cost_mode(value: object) -> CostMode:
    """Normalize and validate a configured cost mode."""

    text = str(value or "").strip().lower()
    if text not in VALID_COST_MODES:
        allowed = ", ".join(sorted(VALID_COST_MODES))
        raise ValueError(f"cost_mode must be one of: {allowed}")
    return cast(CostMode, text)


def classify_provider(provider: str) -> RouteCostClass:
    """Classify a provider by structural cost policy, not output quality."""

    normalized = provider.strip().lower()
    if normalized in LOCAL_PROVIDER_NAMES:
        return "local"
    if normalized in METERED_API_PROVIDER_NAMES:
        return "metered-api"
    if normalized in CREDIT_METERED_PROVIDER_NAMES:
        return "credit-metered"
    if normalized in PLAN_QUOTA_PROVIDER_NAMES:
        return "included-plan"
    return "unknown"


def _recovery_hint(cost_class: RouteCostClass) -> str:
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
) -> CostPolicyDecision:
    """Return whether a provider route is allowed under ``cost_mode``."""

    normalized_provider = provider.strip().lower()
    cost_class = classify_provider(normalized_provider)
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
        recovery_hint=_recovery_hint(cost_class),
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
) -> CostPolicyDecision:
    """Return the decision or raise ``CostPolicyError`` when blocked."""

    decision = evaluate_route_cost_policy(
        cost_mode=cost_mode,
        provider=provider,
        workload=workload,
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

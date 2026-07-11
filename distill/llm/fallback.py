# pyright: strict
"""Fallback routing policy shared by the synchronous LLM router."""

from __future__ import annotations

from typing import Protocol

from distill.llm.cost_policy import CostMode, require_route_allowed
from distill.llm.errors import ProviderBusyTimeoutError, is_credit_or_auth_error


class FallbackConfig(Protocol):
    """Configuration fields required to evaluate an optional fallback route."""

    @property
    def fallback_provider(self) -> str: ...

    @property
    def fallback_model(self) -> str: ...

    @property
    def cost_mode(self) -> CostMode: ...


def fallback_target(
    config: FallbackConfig,
    failed_provider: str,
    exc: Exception,
) -> tuple[str, str] | None:
    """Return the configured fallback for a credit or auth failure, if eligible."""
    if not config.fallback_provider or not config.fallback_model:
        return None
    if config.fallback_provider == failed_provider:
        return None
    if not is_credit_or_auth_error(exc):
        return None
    return config.fallback_provider, config.fallback_model


def require_fallback_route_allowed(
    config: FallbackConfig,
    provider: str,
    workload_tag: str,
) -> None:
    """Fail before constructing a fallback that violates the active cost mode."""
    require_route_allowed(
        cost_mode=config.cost_mode,
        provider=provider,
        workload=workload_tag,
    )


def fallback_failure_to_surface(
    primary_error: Exception,
    fallback_error: Exception,
) -> Exception:
    """Keep a retryable local-capacity signal; otherwise retain primary context."""
    if isinstance(fallback_error, ProviderBusyTimeoutError):
        return fallback_error
    return primary_error

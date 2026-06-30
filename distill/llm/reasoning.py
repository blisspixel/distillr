# pyright: strict
"""Provider-specific reasoning effort policy."""

from __future__ import annotations

import os
from typing import Protocol

__all__ = ["configured_anthropic_effort", "resolve_xai_reasoning_effort"]

_VALID_XAI_REASONING_EFFORTS: frozenset[str] = frozenset({"low", "medium", "high"})
_VALID_ANTHROPIC_REASONING_EFFORTS: frozenset[str] = frozenset(
    {"low", "medium", "high", "xhigh", "max"}
)


class _ReasoningConfig(Protocol):
    PREMIUM_WORKLOADS: tuple[str, ...]


def resolve_xai_reasoning_effort(config: _ReasoningConfig, workload_tag: str) -> str | None:
    env_val = _workload_effort_env(workload_tag)
    if env_val in _VALID_XAI_REASONING_EFFORTS:
        return env_val
    return "high" if workload_tag in config.PREMIUM_WORKLOADS else "medium"


def configured_anthropic_effort(workload_tag: str) -> str | None:
    env_val = _workload_effort_env(workload_tag)
    return env_val if env_val in _VALID_ANTHROPIC_REASONING_EFFORTS else None


def _workload_effort_env(workload_tag: str) -> str:
    return os.environ.get(f"DISTILL_{workload_tag.upper()}_REASONING_EFFORT", "").strip().lower()

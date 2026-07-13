# pyright: strict
"""Dependency-light public value types for LLM providers and routing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from distill.llm.usage import LLMUsageAttempt


@dataclass(frozen=True)
class LLM_Response:
    """Uniform response from any LLM provider (immutable, hashable)."""

    text: str
    input_tokens: int
    output_tokens: int
    model: str
    provider_name: str = ""
    provider_type: str = ""
    usage_source: str = "reported"
    usage_attempts: tuple[LLMUsageAttempt, ...] = ()


class UsageTracker(Protocol):
    """Minimal cost-ledger interface accepted by the foundational router."""

    def record_attempt(self, attempt: LLMUsageAttempt, *, call_type: str = "") -> None:
        """Record one provider request and enforce any active spend limit."""
        ...

    def record_attempts(
        self,
        attempts: tuple[LLMUsageAttempt, ...],
        *,
        call_type: str = "",
    ) -> None:
        """Atomically record evidence for requests completed before observation."""
        ...

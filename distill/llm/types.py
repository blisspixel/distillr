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
    billed_cost_usd: float | None = None
    upstream_provider: str = ""
    # Phase timings, when the provider reports them. Local runtimes separate
    # weight loading, prompt prefill, and token decode, and those rates differ
    # by several times -- a single "tokens per second" over total elapsed time
    # conflates all three and understates decode by up to 100x on a cold call.
    # 0.0 means "not reported", never "zero seconds".
    load_seconds: float = 0.0
    prefill_seconds: float = 0.0
    decode_seconds: float = 0.0
    # Context window the provider actually resolved for this call. Recorded
    # because two machines running one model can silently use different
    # windows, and the window changes both memory use and speed.
    num_ctx: int = 0


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

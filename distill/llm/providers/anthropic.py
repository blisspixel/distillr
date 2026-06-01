# pyright: strict
"""Anthropic provider stub — not yet implemented for 0.3.

Satisfies the Provider protocol but raises NotImplementedError on call.
"""

from __future__ import annotations

from distill.llm.router import LLM_Response


class AnthropicProvider:
    """Stub Anthropic provider — raises NotImplementedError."""

    async def call(
        self,
        model: str,
        prompt: str,
        *,
        max_tokens: int = 8192,
        timeout: int = 300,
        retries: int = 2,
        temperature: float | None = None,
        call_type: str = "",
        reasoning_effort: str | None = None,
    ) -> LLM_Response:
        """Raise NotImplementedError with install hint."""
        raise NotImplementedError(
            "Anthropic provider not yet implemented. Set DISTILL_PROVIDER=xai to use Grok."
        )

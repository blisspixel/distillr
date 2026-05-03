# pyright: strict
"""OpenAI provider stub — not yet implemented for 0.3.

Satisfies the Provider protocol but raises NotImplementedError on call.
"""

from __future__ import annotations

from distill.llm.router import LLM_Response


class OpenAIProvider:
    """Stub OpenAI provider — raises NotImplementedError."""

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
    ) -> LLM_Response:
        """Raise NotImplementedError with install hint."""
        raise NotImplementedError(
            "OpenAI provider not yet implemented. Set DISTILL_PROVIDER=xai to use Grok."
        )

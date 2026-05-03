# pyright: strict
"""Ollama provider stub — planned for 0.6.

Satisfies the Provider protocol but raises NotImplementedError on call.
"""

from __future__ import annotations

from distill.llm.router import LLM_Response


class OllamaProvider:
    """Stub Ollama provider — raises NotImplementedError."""

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
        """Raise NotImplementedError with version hint."""
        raise NotImplementedError(
            "Ollama provider available in 0.6. Set DISTILL_PROVIDER=xai to use Grok."
        )

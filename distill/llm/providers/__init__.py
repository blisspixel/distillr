# pyright: strict
"""Provider protocol and registry for LLM backends.

Defines the structural protocol that all LLM providers must satisfy.
Uses typing.Protocol for duck-typed structural subtyping — no inheritance required.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from distill.llm.router import LLM_Response


@runtime_checkable
class Provider(Protocol):
    """Structural protocol for LLM provider backends.

    All providers must implement ``call()`` with this exact signature.
    The protocol is async from day one; the 0.3 router wraps with
    ``asyncio.run()`` for sync callers.
    """

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
        """Send a prompt to the LLM and return a uniform response."""
        ...

# pyright: strict
"""Everything Distill reads from Ollama's ``/api/show`` endpoint.

Two per-model facts come from this one endpoint, each cached for the life of the
provider:

* **Capabilities** (``completion`` / ``tools`` / ``thinking`` / ``vision``).
  Asking the server beats guessing from the model name: ``qwen3-coder`` shares
  the ``qwen3`` prefix with a thinking model but rejects ``think`` with HTTP 400,
  and no hardcoded prefix list stays correct as new models ship.
* **Context window**, so a model's huge default window does not size a KV cache
  that spills VRAM.

Split out of ``ollama.py`` to keep that module under the 500-line cap.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

import httpx

from distill.llm.providers._ollama_metadata import is_terminal_show_status, parse_capabilities

logger = logging.getLogger(__name__)

_SHOW_TIMEOUT_SECONDS = 5
DEFAULT_CONTEXT_WINDOW = 4096


class ShowProbe:
    """Cached ``/api/show`` lookups for one Ollama endpoint."""

    def __init__(
        self,
        base_url: str,
        *,
        trust_env: bool,
        parse_context_window: Callable[[object], int],
    ) -> None:
        self._base_url = base_url
        self._trust_env = trust_env
        # Injected so the provider keeps exposing its own patchable parser seam.
        self._parse_context_window = parse_context_window
        self._capabilities_cache: dict[str, frozenset[str]] = {}
        self._thinking_unsupported: set[str] = set()
        self.context_window_cache: dict[str, int] = {}

    async def _post_show(self, model: str) -> object:
        async with httpx.AsyncClient(
            timeout=_SHOW_TIMEOUT_SECONDS,
            trust_env=self._trust_env,
        ) as client:
            response = await client.post(f"{self._base_url}/api/show", json={"name": model})
            response.raise_for_status()
            return response.json()

    async def capabilities(self, model: str) -> frozenset[str]:
        """Capabilities Ollama reports for this model. Cached; empty if unknown."""
        cached = self._capabilities_cache.get(model)
        if cached is not None:
            return cached
        try:
            discovered = parse_capabilities(await self._post_show(model))
        except Exception as exc:
            # Capability discovery only refines the name heuristic, so an
            # unreachable or unreadable server must never fail the call itself.
            logger.debug("Could not read Ollama capabilities for '%s': %s", model, exc)
            return frozenset()
        self._capabilities_cache[model] = discovered
        return discovered

    async def supports_thinking(self, model: str) -> bool | None:
        """True/False from the server, or None when it cannot be determined.

        None means the caller should fall back to its own heuristic; this never
        guesses on the server's behalf.
        """
        if model in self._thinking_unsupported:
            return False
        discovered = await self.capabilities(model)
        if not discovered:
            return None
        return "thinking" in discovered

    def mark_thinking_unsupported(self, model: str) -> None:
        """Record a server refusal so later calls skip the thinking flag."""
        self._thinking_unsupported.add(model)

    @staticmethod
    def is_thinking_rejection(exc: Exception) -> bool:
        """True for the server refusing ``think`` on a model that lacks it."""
        if not isinstance(exc, httpx.HTTPStatusError):
            return False
        if exc.response.status_code != 400:
            return False
        return "does not support thinking" in exc.response.text.casefold()

    async def context_window(self, model: str) -> int:
        """Model context window from ``/api/show``. Cached per model."""
        if model in self.context_window_cache:
            return self.context_window_cache[model]
        try:
            ctx = self._parse_context_window(await self._post_show(model))
            if not ctx:
                ctx = DEFAULT_CONTEXT_WINDOW
                logger.warning(
                    "Could not determine context window for '%s'; defaulting to %d",
                    model,
                    ctx,
                )
            self.context_window_cache[model] = ctx
            return ctx
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            raise ConnectionError(
                f"Cannot reach Ollama at {self._base_url}. Run `ollama serve` to start the server."
            ) from exc
        except httpx.HTTPStatusError as exc:
            # Ollama is reachable but /api/show returned an error status for this
            # model (an unpulled model 404s). Degrade to the default context
            # window rather than failing the run. Connection and timeout errors
            # are deliberately not caught here, so retry/backoff behavior and the
            # "start Ollama" hint above are unchanged.
            status = exc.response.status_code
            logger.warning(
                "Ollama /api/show returned %s for '%s'; defaulting context window to %d",
                status,
                model,
                DEFAULT_CONTEXT_WINDOW,
            )
            # Only a terminal status means "this model has no window to discover"
            # (an unpulled model 404s). Caching a transient 5xx/429 pinned the
            # window to 4096 for the whole process, so every later call silently
            # truncated long prompts to ~4k tokens while still reporting success.
            # Leave the cache untouched for retryable statuses so the next call
            # re-probes.
            if is_terminal_show_status(status):
                self.context_window_cache[model] = DEFAULT_CONTEXT_WINDOW
            return DEFAULT_CONTEXT_WINDOW

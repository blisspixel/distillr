# pyright: strict
"""Ollama model metadata and uncached local-inference admission.

The ``/api/show`` metadata caches are refreshed after each successful local
proof. Independent inspection may also populate them:

* **Capabilities** (``completion`` / ``tools`` / ``thinking`` / ``vision``).
  Asking the server beats guessing from the model name: ``qwen3-coder`` shares
  the ``qwen3`` prefix with a thinking model but rejects ``think`` with HTTP 400,
  and no hardcoded prefix list stays correct as new models ship.
* **Context window**, so a model's huge default window does not size a KV cache
  that spills VRAM.

Admission checks the live ``/api/status`` contract and exact model backing
before every inference attempt. That proof is never cached.

Split out of ``ollama.py`` to keep that module under the 500-line cap.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from typing import Any, cast

import httpx

from distill.llm.cost_policy import CostPolicyError
from distill.llm.providers._ollama_metadata import is_terminal_show_status, parse_capabilities

logger = logging.getLogger(__name__)

_SHOW_TIMEOUT_SECONDS = 5
_LOCAL_PROOF_BYTES = 1_000_000
_LOCAL_PROOF_RECOVERY = (
    "Distill requires a local-only Ollama daemon with a supported /api/status contract. "
    "Set OLLAMA_NO_CLOUD=1 for the Ollama daemon or disable_ollama_cloud=true in its "
    "server.json, restart Ollama, and select an installed local model. "
    "Cloud-backed Ollama is unsupported in every cost mode."
)
DEFAULT_CONTEXT_WINDOW = 4096


def _proof_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Reject ambiguous duplicate fields in the experimental proof contract."""
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Ollama local-proof metadata contains duplicate fields")
        result[key] = value
    return result


def _reject_proof_constant(value: str) -> None:
    raise ValueError(f"Ollama local-proof metadata contains invalid JSON constant {value}")


class ShowProbe:
    """Model metadata and local-only admission for one Ollama endpoint."""

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

    async def _proof_document(self, path: str, model: str | None = None) -> object:
        """Read one bounded metadata document without redirects or prompt content."""
        raw = bytearray()
        async with (
            httpx.AsyncClient(timeout=_SHOW_TIMEOUT_SECONDS, trust_env=self._trust_env) as client,
            client.stream(
                "GET" if model is None else "POST",
                f"{self._base_url}{path}",
                json={"model": model} if model is not None else None,
            ) as response,
        ):
            response.raise_for_status()
            async for chunk in response.aiter_bytes():
                if len(raw) + len(chunk) > _LOCAL_PROOF_BYTES:
                    raise ValueError("Ollama local-proof metadata exceeds its byte limit")
                raw.extend(chunk)
        return json.loads(
            raw, object_pairs_hook=_proof_object, parse_constant=_reject_proof_constant
        )

    async def require_local(self, model: str) -> None:
        """Prove live daemon and exact model locality afresh before every attempt.

        Ollama 0.34.0 publishes this experimental status contract. Its presence
        and strict schema are the support gate; an older or changed contract
        fails closed. A loopback address and a model's name are not local proof.
        """
        try:
            async with asyncio.timeout(_SHOW_TIMEOUT_SECONDS):
                status = await self._proof_document("/api/status")
                if not isinstance(status, dict):
                    raise ValueError("Ollama local-only status is missing or unsupported")
                status = cast(dict[str, Any], status)
                if set(status) != {"cloud"} or not isinstance(status.get("cloud"), dict):
                    raise ValueError("Ollama local-only status is missing or unsupported")
                cloud = cast(dict[str, Any], status["cloud"])
                if (
                    set(cloud) != {"disabled", "source"}
                    or cloud.get("disabled") is not True
                    or not isinstance(cloud.get("source"), str)
                    or not cloud["source"]
                    or len(cloud["source"]) > 64
                ):
                    raise ValueError("Ollama daemon has not proved cloud features disabled")
                data = await self._proof_document("/api/show", model)
                if not isinstance(data, dict):
                    raise ValueError("Ollama model metadata must be an object")
                metadata = cast(dict[str, Any], data)
                require_no_remote_metadata(metadata)
                details = metadata.get("details")
                info = metadata.get("model_info")
                if not isinstance(details, dict) or not isinstance(info, dict):
                    raise ValueError("Ollama model has not proved installed local backing")
                details = cast(dict[str, Any], details)
                info = cast(dict[str, Any], info)
                if (
                    details.get("format") not in {"gguf", "safetensors"}
                    or not isinstance(info.get("general.architecture"), str)
                    or not info["general.architecture"]
                ):
                    raise ValueError("Ollama model has not proved installed local backing")
        except (httpx.HTTPError, TimeoutError, ValueError, TypeError, RecursionError) as exc:
            raise CostPolicyError(_LOCAL_PROOF_RECOVERY) from exc
        # Refresh only after the complete proof succeeds. Locality itself is
        # never cached, including after a transient retry or model replacement.
        self._capabilities_cache[model] = parse_capabilities(metadata)
        self.context_window_cache[model] = (
            self._parse_context_window(metadata) or DEFAULT_CONTEXT_WINDOW
        )

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


def require_no_remote_metadata(metadata: dict[str, Any]) -> None:
    """Reject upstream backing in model metadata or any inference frame."""
    if any(metadata.get(field, "") != "" for field in ("remote_host", "remote_model")):
        raise CostPolicyError(_LOCAL_PROOF_RECOVERY)

# pyright: strict
"""LLM Router — workload-to-provider dispatch, data models, and configuration.

This module defines the core data types (LLM_Response, RouterConfig), custom
exceptions, the workload tag registry, and the ``call()`` dispatch function
for the distill/llm/ package.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LLM_Response:
    """Uniform response from any LLM provider.

    frozen=True makes instances immutable and hashable.  The type is
    intentionally minimal — it carries only what every consumer needs.
    """

    text: str
    input_tokens: int
    output_tokens: int
    model: str


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class LLMRouterError(Exception):
    """Base exception for the LLM router package."""


class ConfigurationError(LLMRouterError):
    """Raised when router configuration is invalid or incomplete."""


class PendingTaskError(LLMRouterError):
    """Raised when an Agent mode task is awaiting external processing."""

    def __init__(self, message: str, task_path: str = "") -> None:
        super().__init__(message)
        self.task_path = task_path


# ---------------------------------------------------------------------------
# Workload tag registry
# ---------------------------------------------------------------------------

WORKLOAD_TAGS: frozenset[str] = frozenset(
    {
        "analysis",
        "rerank",
        "synthesis",
        "site",
        "accordion",
        "brief",
        "report",
        "qa",
        # Reserved for 0.7-0.8 wiki-maintenance workloads.
        # Must never be premium-tier by default.
        "maintenance",
    }
)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class RouterConfig:
    """LLM routing configuration.  Injected by the caller — no distill.* imports.

    Resolution precedence for *model*:
        1. Per-workload model override  (e.g. ``analysis_model``)
        2. Tier default (``premium_model`` for premium workloads, ``fast_model`` otherwise)

    Resolution precedence for *provider*:
        1. Per-workload provider override  (e.g. ``analysis_provider``)
        2. Global ``provider``
    """

    # API keys
    xai_api_key: str = ""
    gemini_api_key: str = ""
    anthropic_api_key: str = ""
    openai_api_key: str = ""

    # Global provider (default: xai)
    provider: str = "xai"

    # Tier defaults (both default to grok-4.3)
    fast_model: str = "grok-4.3"
    premium_model: str = "grok-4.3"

    # Per-workload model overrides (empty = use tier default)
    analysis_model: str = ""
    rerank_model: str = ""
    synthesis_model: str = ""
    site_model: str = ""
    accordion_model: str = ""
    brief_model: str = ""
    report_model: str = ""
    qa_model: str = ""
    maintenance_model: str = ""

    # Per-workload provider overrides (empty = use global provider)
    analysis_provider: str = ""
    rerank_provider: str = ""
    synthesis_provider: str = ""
    site_provider: str = ""
    accordion_provider: str = ""
    brief_provider: str = ""
    report_provider: str = ""
    qa_provider: str = ""
    maintenance_provider: str = ""

    # Ops directory for telemetry and task files
    ops_dir: str = ""

    # Workload → tier mapping
    PREMIUM_WORKLOADS: tuple[str, ...] = ("site", "report")

    def resolve(self, workload_tag: str) -> tuple[str, str]:
        """Resolve ``(provider_name, model_id)`` for a workload tag.

        Returns the provider and model that should be used for the given
        workload, following the precedence hierarchy documented on the class.
        """
        # --- provider ---
        per_workload_provider: str = getattr(self, f"{workload_tag}_provider", "")
        provider_name: str = per_workload_provider or self.provider

        # --- model ---
        per_workload_model: str = getattr(self, f"{workload_tag}_model", "")
        if per_workload_model:
            model_id = per_workload_model
        elif workload_tag in self.PREMIUM_WORKLOADS:
            model_id = self.premium_model
        else:
            model_id = self.fast_model

        return provider_name, model_id

    def validate(self, workload_tag: str = "") -> None:
        """Validate configuration eagerly.  Raise ``ConfigurationError`` early.

        Call once at router entry to prevent "mysterious 401 halfway through a
        20-paper run" class of bugs.  If *workload_tag* is provided, validates
        the specific provider for that workload.  Otherwise validates the
        global provider.
        """
        if workload_tag:
            provider_name, _ = self.resolve(workload_tag)
        else:
            provider_name = self.provider

        key_map: dict[str, tuple[str | None, str | None]] = {
            "xai": ("xai_api_key", "XAI_API_KEY"),
            "gemini": ("gemini_api_key", "GEMINI_API_KEY"),
            "anthropic": ("anthropic_api_key", "ANTHROPIC_API_KEY"),
            "openai": ("openai_api_key", "OPENAI_API_KEY"),
            "agent": (None, None),  # No key needed
            "ollama": (None, None),  # Local — no key needed
        }

        if provider_name not in key_map:
            raise ConfigurationError(
                f"Unknown provider '{provider_name}'. Valid providers: {', '.join(key_map)}"
            )

        attr, env_name = key_map[provider_name]
        if attr and not getattr(self, attr, ""):
            raise ConfigurationError(
                f"Provider '{provider_name}' requires {env_name} to be set. "
                f"Add it to your .env file."
            )


# ---------------------------------------------------------------------------
# Provider registry (cached)
# ---------------------------------------------------------------------------

_provider_cache: dict[str, Any] = {}


def _get_provider(provider_name: str, config: RouterConfig) -> Any:
    """Map *provider_name* to a Provider instance, caching per name.

    Raises ``ConfigurationError`` for unknown provider names.
    """
    if provider_name in _provider_cache:
        return _provider_cache[provider_name]

    provider: Any
    if provider_name == "xai":
        from distill.llm.providers.grok import GrokProvider

        provider = GrokProvider(config.xai_api_key)
    elif provider_name == "gemini":
        from distill.llm.providers.gemini import GeminiProvider

        provider = GeminiProvider(config.gemini_api_key)
    elif provider_name == "agent":
        from distill.llm.providers.agent import AgentProvider

        provider = AgentProvider(config.ops_dir)
    elif provider_name == "anthropic":
        from distill.llm.providers.anthropic import AnthropicProvider

        provider = AnthropicProvider()
    elif provider_name == "openai":
        from distill.llm.providers.openai_prov import OpenAIProvider

        provider = OpenAIProvider()
    elif provider_name == "ollama":
        from distill.llm.providers.ollama import OllamaProvider

        provider = OllamaProvider()
    else:
        raise ConfigurationError(
            f"Unknown provider '{provider_name}'. "
            f"Valid providers: xai, gemini, agent, anthropic, openai, ollama"
        )

    _provider_cache[provider_name] = provider
    return provider


# ---------------------------------------------------------------------------
# Router dispatch
# ---------------------------------------------------------------------------


def call(
    config: RouterConfig,
    workload_tag: str,
    prompt: str,
    *,
    max_tokens: int = 8192,
    timeout: int = 300,
    retries: int = 2,
    temperature: float | None = None,
    call_type: str = "",
    ops_dir: str = "",
    run_id: str = "",
) -> LLM_Response:
    """Dispatch an LLM call through the configured provider.

    This is the single entry point for all LLM interactions in distillr.
    The *run_id* (UUID per top-level CLI command or MCP invocation) is passed
    through to telemetry so "biggest prompts" can be scoped per research run.
    """
    # Validate configuration eagerly
    config.validate(workload_tag)

    if workload_tag not in WORKLOAD_TAGS:
        logger.warning(
            "Unknown workload tag '%s'; falling back to default tier model",
            workload_tag,
        )

    # Resolve provider and model
    provider_name, model_id = config.resolve(workload_tag)

    # Get provider instance
    provider = _get_provider(provider_name, config)

    # Execute with telemetry
    effective_ops_dir = ops_dir or config.ops_dir
    start_time = time.monotonic()
    outcome = "success"
    error_type = ""
    response: LLM_Response | None = None

    try:
        # Call the async provider from sync context
        coro = provider.call(
            model_id,
            prompt,
            max_tokens=max_tokens,
            timeout=timeout,
            retries=retries,
            temperature=temperature,
            call_type=call_type,
        )
        try:
            response = asyncio.run(coro)
        except RuntimeError as rt_err:
            # Only fall back if the error is about an already-running loop
            if "cannot be called from a running event loop" in str(rt_err):
                loop = asyncio.get_event_loop()
                response = loop.run_until_complete(coro)
            else:
                raise
    except Exception as exc:
        outcome = "error"
        error_type = type(exc).__name__
        # Emit telemetry for the error case
        elapsed = time.monotonic() - start_time
        _emit_telemetry(
            ops_dir=effective_ops_dir,
            model=model_id,
            workload_tag=workload_tag,
            input_tokens=0,
            output_tokens=0,
            elapsed_seconds=round(elapsed, 3),
            outcome=outcome,
            error_type=error_type,
            call_type=call_type,
            run_id=run_id,
        )
        raise

    # Emit telemetry for the success case
    elapsed = time.monotonic() - start_time
    _emit_telemetry(
        ops_dir=effective_ops_dir,
        model=response.model,
        workload_tag=workload_tag,
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
        elapsed_seconds=round(elapsed, 3),
        outcome=outcome,
        error_type=error_type,
        call_type=call_type,
        run_id=run_id,
    )

    return response


def _emit_telemetry(
    *,
    ops_dir: str,
    model: str,
    workload_tag: str,
    input_tokens: int,
    output_tokens: int,
    elapsed_seconds: float,
    outcome: str,
    error_type: str,
    call_type: str,
    run_id: str,
) -> None:
    """Write a telemetry record if ops_dir is configured."""
    if not ops_dir:
        return
    from distill.llm.telemetry import Telemetry_Record, write_record

    record = Telemetry_Record(
        model=model,
        workload_tag=workload_tag,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        elapsed_seconds=elapsed_seconds,
        outcome=outcome,
        error_type=error_type,
        call_type=call_type,
        run_id=run_id,
    )
    write_record(ops_dir, record)

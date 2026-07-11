# pyright: strict
"""LLM Router — workload-to-provider dispatch and configuration."""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, replace
from typing import Any

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings

from distill.llm.async_compat import run_coroutine_sync
from distill.llm.cost_policy import CostMode, normalize_cost_mode, require_route_allowed
from distill.llm.fallback import (
    fallback_failure_to_surface as _fallback_failure_to_surface,
)
from distill.llm.fallback import fallback_target as _fallback_target
from distill.llm.fallback import (
    require_fallback_route_allowed as _require_fallback_route_allowed,
)
from distill.llm.metadata import LOCAL_PROVIDERS, local_call_timeout
from distill.llm.model_policy import (
    RETIRED_MODELS,
    RETIREMENT_DATE,
    is_xai_media_generation_model,
    xai_media_generation_refusal,
)
from distill.llm.provider_cache import provider_cache_key
from distill.llm.reasoning import configured_anthropic_effort, resolve_xai_reasoning_effort

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LLM_Response:
    """Uniform response from any LLM provider (immutable, hashable)."""

    text: str
    input_tokens: int
    output_tokens: int
    model: str
    provider_name: str = ""
    provider_type: str = ""


class LLMRouterError(Exception):
    """Base exception for the LLM router package."""


class ConfigurationError(LLMRouterError):
    """Raised when router configuration is invalid or incomplete."""


class PendingTaskError(LLMRouterError):
    """Raised when an Agent mode task is awaiting external processing."""

    def __init__(self, message: str, task_path: str = "") -> None:
        super().__init__(message)
        self.task_path = task_path


WORKLOAD_TAGS: frozenset[str] = frozenset(
    "analysis rerank synthesis site accordion brief report qa maintenance concepts".split()  # noqa: SIM905
)


class RouterConfig(BaseSettings):
    """LLM routing configuration.  Reads directly from environment variables.

    Model precedence: per-workload override > tier default > global default.
    Provider precedence: per-workload override > global provider.
    Env mapping: API keys use own names (XAI_API_KEY); routing uses DISTILL_ prefix.
    """

    model_config = {"env_prefix": "DISTILL_", "env_file": ".env", "extra": "ignore"}

    # API keys (populated from non-prefixed env vars via validator)
    xai_api_key: str = ""
    gemini_api_key: str = ""
    anthropic_api_key: str = ""
    openai_api_key: str = ""

    # Global provider
    provider: str = "xai"
    # DISTILL_COST_MODE: auto | no-metered | paid-ok
    cost_mode: CostMode = "auto"
    # Tier defaults
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
    concepts_model: str = ""

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
    concepts_provider: str = ""

    # Ops directory for telemetry and task files
    ops_dir: str = ""
    # Model override (CLI --model or DISTILL_MODEL env var)
    model: str = ""

    # Opt-in fallback: on a credit/auth failure from the primary provider, retry
    # once on this provider+model (e.g. a local Ollama model) instead of crashing.
    # Both must be set; empty disables the fallback.
    fallback_provider: str = ""
    fallback_model: str = ""

    PREMIUM_WORKLOADS: tuple[str, ...] = ("site", "report")

    @field_validator("cost_mode", mode="before")
    @classmethod
    def _normalize_cost_mode(cls, value: object) -> CostMode:
        return normalize_cost_mode(value)

    @model_validator(mode="before")
    @classmethod
    def _populate_api_keys_from_env(cls, data: Any) -> Any:
        """Read API keys from their canonical (non-prefixed) env var names."""
        if not isinstance(data, dict):
            return data
        key_env_map = {
            "xai_api_key": "XAI_API_KEY",
            "gemini_api_key": "GEMINI_API_KEY",
            "anthropic_api_key": "ANTHROPIC_API_KEY",
            "openai_api_key": "OPENAI_API_KEY",
        }
        dotenv_vals: dict[str, str | None] = {}
        for field_name, env_name in key_env_map.items():
            if field_name not in data:  # Only populate if not explicitly provided
                env_val = os.environ.get(env_name, "")
                if not env_val:
                    if not dotenv_vals:
                        try:
                            from dotenv import dotenv_values as _dv

                            loaded: dict[str, str | None] = _dv(".env") or {}
                            dotenv_vals = loaded
                        except ImportError:
                            dotenv_vals = {}
                    env_val = dotenv_vals.get(env_name) or ""
                if env_val:
                    data[field_name] = env_val
        return data  # type: ignore[return-value]  # Pydantic model_validator(mode="before") returns Any

    @model_validator(mode="after")
    def _default_ops_dir_to_library(self) -> RouterConfig:
        """Fall back to ``<library_dir>/.distill`` when ops_dir is unset."""
        if self.ops_dir:
            return self
        from pathlib import Path as _Path

        env_dir = os.environ.get("DISTILL_OUTPUT_DIR", "").strip()
        if env_dir:
            library_dir = _Path(env_dir)
        else:
            # Mirrors ``distill.config._default_library_dir``: library/ sits
            # next to the ``distill`` package on the filesystem.
            library_dir = _Path(__file__).resolve().parent.parent.parent / "library"
        if not library_dir.is_absolute():
            library_dir = _Path.cwd() / library_dir
        # ``model_copy`` would re-trigger validators; mutate the field directly
        # because BaseSettings instances are not frozen.
        object.__setattr__(self, "ops_dir", str(library_dir / ".distill"))
        return self

    def resolve(self, workload_tag: str) -> tuple[str, str]:
        """Resolve ``(provider_name, model_id)`` for a workload tag."""
        per_workload_provider: str = getattr(self, f"{workload_tag}_provider", "")
        provider_name: str = per_workload_provider or self.provider

        if self.model:
            model_id = self.model
        else:
            per_workload_model: str = getattr(self, f"{workload_tag}_model", "")
            if per_workload_model:
                model_id = per_workload_model
            elif workload_tag in self.PREMIUM_WORKLOADS:
                model_id = self.premium_model
            else:
                model_id = self.fast_model

        if model_id in RETIRED_MODELS:
            replacement = RETIRED_MODELS[model_id]
            logger.warning(
                "Model '%s' is retired (effective %s). "
                "Falling back to '%s'. Update your config to silence this warning.",
                model_id,
                RETIREMENT_DATE,
                replacement,
            )
            model_id = replacement

        return provider_name, model_id

    def validate_config(self, workload_tag: str = "") -> None:
        """Validate configuration eagerly.  Raise ``ConfigurationError`` early."""
        provider_name, model_id = (
            self.resolve(workload_tag)
            if workload_tag
            else (self.provider, self.model or self.fast_model)
        )
        require_route_allowed(
            cost_mode=self.cost_mode,
            provider=provider_name,
            workload=workload_tag,
        )

        key_map: dict[str, tuple[str | None, str | None]] = {
            "xai": ("xai_api_key", "XAI_API_KEY"),
            "gemini": ("gemini_api_key", "GEMINI_API_KEY"),
            "anthropic": ("anthropic_api_key", "ANTHROPIC_API_KEY"),
            "agent": (None, None),
            "ollama": (None, None),
            "lmstudio": (None, None),
        }
        if provider_name == "openai":
            raise ConfigurationError(
                f"Provider '{provider_name}' is not implemented yet. "
                "Use xai, gemini, anthropic, agent, ollama, or lmstudio."
            )

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

        if provider_name == "xai" and is_xai_media_generation_model(model_id):
            raise ConfigurationError(xai_media_generation_refusal(model_id))

    def with_model_override(self, override: str) -> RouterConfig:
        """Return a new RouterConfig with the model override applied."""
        if not override:
            return self
        overrides: dict[str, Any] = {
            "fast_model": override,
            "premium_model": override,
            "model": override,
        }
        for field_name in type(self).model_fields:
            if field_name.endswith("_model") and field_name not in (
                "fast_model",
                "premium_model",
                "model",
            ):
                overrides[field_name] = ""
        return self.model_copy(update=overrides)


_provider_cache: dict[str, Any] = {}


def _get_provider(provider_name: str, config: RouterConfig) -> Any:
    """Map *provider_name* to a Provider instance, caching per name."""
    cache_key = provider_cache_key(
        provider_name,
        ops_dir=config.ops_dir,
        xai_api_key=config.xai_api_key,
        gemini_api_key=config.gemini_api_key,
        anthropic_api_key=config.anthropic_api_key,
    )
    if cache_key in _provider_cache:
        return _provider_cache[cache_key]

    provider: Any
    if provider_name == "xai":
        from distill.llm.providers.grok import GrokProvider

        provider = GrokProvider(config.xai_api_key)
    elif provider_name == "gemini":
        from distill.llm.providers.gemini import GeminiProvider

        provider = GeminiProvider(config.gemini_api_key)
    elif provider_name == "anthropic":
        from distill.llm.providers.anthropic import AnthropicProvider

        provider = AnthropicProvider(config.anthropic_api_key)
    elif provider_name == "agent":
        from distill.llm.providers.agent import AgentProvider

        provider = AgentProvider(config.ops_dir)
    elif provider_name == "openai":
        raise ConfigurationError(
            f"Provider '{provider_name}' is not implemented yet. "
            "Use xai, gemini, anthropic, agent, ollama, or lmstudio."
        )
    elif provider_name == "ollama":
        from distill.llm.providers.ollama import OllamaProvider

        provider = OllamaProvider()
    elif provider_name == "lmstudio":
        from distill.llm.providers.lmstudio import LMStudioProvider

        provider = LMStudioProvider()
    else:
        valid = "xai, gemini, anthropic, agent, ollama, lmstudio"
        raise ConfigurationError(f"Unknown provider '{provider_name}'. Valid providers: {valid}")

    _provider_cache[cache_key] = provider
    return provider


get_provider = _get_provider


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
    """Dispatch an LLM call through the configured provider, with optional local fallback."""
    config.validate_config(workload_tag)

    if workload_tag not in WORKLOAD_TAGS:
        logger.warning(
            "Unknown workload tag '%s'; falling back to default tier model",
            workload_tag,
        )

    provider_name, model_id = config.resolve(workload_tag)
    effective_ops_dir = ops_dir or config.ops_dir

    def _attempt(p_name: str, m_id: str) -> LLM_Response:
        provider = _get_provider(p_name, config)
        # Local models need a longer read timeout than the cloud-tuned default.
        effective_timeout = local_call_timeout(timeout) if p_name in LOCAL_PROVIDERS else timeout
        reasoning_effort: str | None = None
        if p_name == "xai" and m_id.startswith("grok-4.3"):
            reasoning_effort = resolve_xai_reasoning_effort(config, workload_tag)
        elif p_name == "anthropic" and m_id.startswith("claude-sonnet-5"):
            reasoning_effort = configured_anthropic_effort(workload_tag)
        coro = provider.call(
            m_id,
            prompt,
            max_tokens=max_tokens,
            timeout=effective_timeout,
            retries=retries,
            temperature=temperature,
            call_type=call_type,
            reasoning_effort=reasoning_effort,
        )
        # Run the provider coroutine to completion from this sync path. When a
        # loop is already running (e.g. the async MCP server), run_coroutine_sync
        # offloads to a dedicated thread instead of failing on a nested loop.
        response = run_coroutine_sync(coro)
        provider_type = "local" if p_name in LOCAL_PROVIDERS else "cloud"
        return replace(response, provider_name=p_name, provider_type=provider_type)

    def _record(
        p_name: str,
        m_id: str,
        resp: LLM_Response | None,
        outcome: str,
        error_type: str,
        elapsed: float,
    ) -> None:
        provider_type = "local" if p_name in LOCAL_PROVIDERS else "cloud"
        tps = 0.0
        if resp is not None and provider_type == "local" and elapsed > 0:
            tps = resp.output_tokens / elapsed
        _emit_telemetry(
            ops_dir=effective_ops_dir,
            model=resp.model if resp is not None else m_id,
            workload_tag=workload_tag,
            input_tokens=resp.input_tokens if resp is not None else 0,
            output_tokens=resp.output_tokens if resp is not None else 0,
            elapsed_seconds=round(elapsed, 3),
            outcome=outcome,
            error_type=error_type,
            call_type=call_type,
            run_id=run_id,
            provider_type=provider_type,
            provider_name=p_name,
            tokens_per_second=round(tps, 2),
        )

    start_time = time.monotonic()
    try:
        response = _attempt(provider_name, model_id)
    except Exception as exc:
        _record(
            provider_name,
            model_id,
            None,
            "error",
            type(exc).__name__,
            time.monotonic() - start_time,
        )
        target = _fallback_target(config, provider_name, exc)
        if target is None:
            raise
        fb_provider, fb_model = target
        _require_fallback_route_allowed(config, fb_provider, workload_tag)
        logger.warning(
            "Primary provider '%s' failed (%s); falling back to '%s' / '%s'.",
            provider_name,
            type(exc).__name__,
            fb_provider,
            fb_model,
        )
        fb_start = time.monotonic()
        try:
            response = _attempt(fb_provider, fb_model)
        except Exception as fallback_exc:
            _record(
                fb_provider, fb_model, None, "error", "FallbackFailed", time.monotonic() - fb_start
            )
            raise _fallback_failure_to_surface(exc, fallback_exc) from None
        _record(fb_provider, fb_model, response, "success", "", time.monotonic() - fb_start)
        return response

    _record(provider_name, model_id, response, "success", "", time.monotonic() - start_time)
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
    provider_type: str,
    provider_name: str,
    tokens_per_second: float,
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
        provider_type=provider_type,
        provider_name=provider_name,
        tokens_per_second=tokens_per_second,
    )
    write_record(ops_dir, record)

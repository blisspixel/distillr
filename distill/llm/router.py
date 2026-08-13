# pyright: strict
"""LLM Router — workload-to-provider dispatch and configuration."""

from __future__ import annotations

import logging
import os
import threading
from typing import Any

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings

from distill.llm.call_execution import CallOptions, execute_call
from distill.llm.cost_policy import (
    LOCAL_PROVIDER_NAMES,
    CostMode,
    local_provider_endpoint,
    local_provider_endpoint_is_valid,
    normalize_cost_mode,
    require_route_allowed,
)
from distill.llm.fallback import fallback_target
from distill.llm.model_policy import (
    RETIRED_MODELS,
    RETIREMENT_DATE,
    is_xai_media_generation_model,
    xai_media_generation_refusal,
)
from distill.llm.provider_cache import provider_cache_key
from distill.llm.run_context import current_run_id
from distill.llm.types import LLM_Response, UsageTracker
from distill.llm.usage import LLMUsageAttempt, UsageAttemptBatchSink, UsageAttemptSink

logger = logging.getLogger(__name__)


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

_KNOWN_CLOUD_MODEL_PREFIXES: tuple[tuple[str, str], ...] = (
    ("grok-", "xai"),
    ("gemini-", "gemini"),
    ("claude-", "anthropic"),
    ("gpt-", "openai"),
)


def _known_cloud_model_provider(model: str) -> str:
    normalized = model.casefold()
    for prefix, provider in _KNOWN_CLOUD_MODEL_PREFIXES:
        if normalized.startswith(prefix):
            return provider
    return ""


class RouterConfig(BaseSettings):
    """LLM routing configuration.  Reads directly from environment variables.

    Model precedence: per-workload override > tier default > global default.
    Provider precedence: per-workload override > global provider.
    Env mapping: API keys use own names (XAI_API_KEY); routing uses DISTILL_ prefix.
    """

    model_config = {"env_prefix": "DISTILL_", "env_file": ".env", "extra": "ignore"}

    # API keys (populated from non-prefixed env vars via validator)
    xai_api_key: str = Field(default="", repr=False)
    gemini_api_key: str = Field(default="", repr=False)
    anthropic_api_key: str = Field(default="", repr=False)
    openai_api_key: str = Field(default="", repr=False)

    # Global provider
    provider: str = "xai"
    # DISTILL_COST_MODE: auto | no-metered | paid-ok
    cost_mode: CostMode = "auto"
    # Tier defaults
    fast_model: str = "grok-4.6"
    premium_model: str = "grok-4.6"

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
    def _populate_compatibility_env(cls, data: Any) -> Any:
        """Read canonical keys and supported legacy model aliases from the environment."""
        if not isinstance(data, dict):
            return data
        compatibility_env_map = {
            "xai_api_key": "XAI_API_KEY",
            "gemini_api_key": "GEMINI_API_KEY",
            "anthropic_api_key": "ANTHROPIC_API_KEY",
            "openai_api_key": "OPENAI_API_KEY",
            "fast_model": "XAI_FAST_MODEL",
            "premium_model": "XAI_PREMIUM_MODEL",
            "analysis_model": "XAI_ANALYSIS_MODEL",
            "rerank_model": "XAI_RERANK_MODEL",
            "synthesis_model": "XAI_SYNTHESIS_MODEL",
            "site_model": "XAI_SITE_MODEL",
            "accordion_model": "ACCORDION_SECTION_MODEL",
        }
        dotenv_vals: dict[str, str | None] = {}
        for field_name, env_name in compatibility_env_map.items():
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

        if (
            not model_id.strip()
            or model_id != model_id.strip()
            or len(model_id) > 512
            or any(ord(character) < 32 or ord(character) == 127 for character in model_id)
        ):
            raise ConfigurationError("The configured model identifier is invalid.")

        if provider_name in {"ollama", "lmstudio"} and not self.has_explicit_local_model(
            workload_tag
        ):
            raise ConfigurationError(
                f"Provider '{provider_name}' requires an explicit local model. "
                "Set DISTILL_MODEL to the exact installed model identifier, or configure "
                "the matching workload or tier model."
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

        expected_provider = _known_cloud_model_provider(model_id)
        if (
            provider_name in {"xai", "gemini", "anthropic"}
            and expected_provider
            and expected_provider != provider_name
        ):
            raise ConfigurationError(
                f"Model '{model_id}' belongs to provider '{expected_provider}', not "
                f"configured provider '{provider_name}'."
            )

        if provider_name == "xai" and is_xai_media_generation_model(model_id):
            raise ConfigurationError(xai_media_generation_refusal(model_id))

    def has_explicit_local_model(self, workload_tag: str) -> bool:
        """Return whether local routing selected a model supplied by the operator."""
        if self.model.strip():
            return True

        if workload_tag:
            workload_field = f"{workload_tag}_model"
            workload_model = str(getattr(self, workload_field, "")).strip()
            if workload_model:
                return True

        tier_field = "premium_model" if workload_tag in self.PREMIUM_WORKLOADS else "fast_model"
        tier_model = str(getattr(self, tier_field, "")).strip()
        return tier_field in self.model_fields_set and bool(tier_model)

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
_provider_cache_lock = threading.RLock()


def _validated_local_endpoint(provider_name: str, config: RouterConfig) -> str:
    """Snapshot and validate one local-provider endpoint before construction."""

    if provider_name not in LOCAL_PROVIDER_NAMES:
        return ""
    endpoint = local_provider_endpoint(provider_name)
    if not local_provider_endpoint_is_valid(endpoint):
        raise ConfigurationError(
            f"Provider '{provider_name}' requires a valid HTTP(S) endpoint without "
            "credentials, query parameters, or fragments."
        )
    require_route_allowed(
        cost_mode=config.cost_mode,
        provider=provider_name,
        workload="provider-construction",
        endpoint=endpoint,
    )
    return endpoint


def _get_provider(provider_name: str, config: RouterConfig) -> Any:
    """Map *provider_name* to a Provider instance, caching per route identity."""
    local_endpoint = _validated_local_endpoint(provider_name, config)
    cache_key = provider_cache_key(
        provider_name,
        ops_dir=config.ops_dir,
        xai_api_key=config.xai_api_key,
        gemini_api_key=config.gemini_api_key,
        anthropic_api_key=config.anthropic_api_key,
        local_endpoint=local_endpoint,
    )
    with _provider_cache_lock:
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

            provider = OllamaProvider(base_url=local_endpoint)
        elif provider_name == "lmstudio":
            from distill.llm.providers.lmstudio import LMStudioProvider

            provider = LMStudioProvider(base_url=local_endpoint)
        else:
            valid = "xai, gemini, anthropic, agent, ollama, lmstudio"
            raise ConfigurationError(
                f"Unknown provider '{provider_name}'. Valid providers: {valid}"
            )

        _provider_cache[cache_key] = provider
        return provider


get_provider = _get_provider
_fallback_target = fallback_target  # pyright: ignore[reportUnusedVariable] "legacy monkeypatch seam retained for compatibility"


def _usage_sinks(
    usage_tracker: UsageTracker | None,
    *,
    call_type: str,
) -> tuple[UsageAttemptSink | None, UsageAttemptBatchSink | None]:
    """Build one-call sinks that deliver each identified attempt once."""

    if usage_tracker is None:
        return None, None
    emitted_attempt_ids: set[str] = set()

    def record_one(attempt: LLMUsageAttempt) -> None:
        if attempt.attempt_id and attempt.attempt_id in emitted_attempt_ids:
            return
        if attempt.attempt_id:
            emitted_attempt_ids.add(attempt.attempt_id)
        usage_tracker.record_attempt(attempt, call_type=call_type)

    def record_batch(attempts: tuple[LLMUsageAttempt, ...]) -> None:
        pending: list[LLMUsageAttempt] = []
        for attempt in attempts:
            if attempt.attempt_id and attempt.attempt_id in emitted_attempt_ids:
                continue
            if attempt.attempt_id:
                emitted_attempt_ids.add(attempt.attempt_id)
            pending.append(attempt)
        if pending:
            usage_tracker.record_attempts(tuple(pending), call_type=call_type)

    return record_one, record_batch


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
    usage_tracker: UsageTracker | None = None,
) -> LLM_Response:
    """Dispatch an LLM call through the configured provider, with optional local fallback."""
    config.validate_config(workload_tag)
    if workload_tag not in WORKLOAD_TAGS:
        logger.warning(
            "Unknown workload tag '%s'; falling back to default tier model",
            workload_tag,
        )

    provider_name, model_id = config.resolve(workload_tag)
    sink, batch_sink = _usage_sinks(usage_tracker, call_type=call_type)

    def _provider_getter(name: str) -> Any:
        return _get_provider(name, config)

    options = CallOptions(
        config=config,
        workload_tag=workload_tag,
        prompt=prompt,
        max_tokens=max_tokens,
        timeout=timeout,
        retries=retries,
        temperature=temperature,
        call_type=call_type,
        ops_dir=ops_dir or config.ops_dir,
        run_id=run_id or current_run_id(),
        usage_sink=sink,
        usage_batch_sink=batch_sink,
        provider_getter=_provider_getter,
    )
    return execute_call(options, provider_name, model_id)

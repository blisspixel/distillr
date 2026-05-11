# pyright: strict
"""LLM Router — workload-to-provider dispatch and configuration."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass
from typing import Any

from pydantic import model_validator
from pydantic_settings import BaseSettings

from distill.llm.metadata import LOCAL_PROVIDERS

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LLM_Response:
    """Uniform response from any LLM provider (immutable, hashable)."""

    text: str
    input_tokens: int
    output_tokens: int
    model: str


class LLMRouterError(Exception):
    """Base exception for the LLM router package."""


class ConfigurationError(LLMRouterError):
    """Raised when router configuration is invalid or incomplete."""


class PendingTaskError(LLMRouterError):
    """Raised when an Agent mode task is awaiting external processing."""

    def __init__(self, message: str, task_path: str = "") -> None:
        super().__init__(message)
        self.task_path = task_path


RETIREMENT_DATE = "May 15, 2026"
RETIRED_MODELS: dict[str, str] = {
    "grok-4-1-fast-reasoning": "grok-4.3",
    "grok-4-1-fast-non-reasoning": "grok-4.20-non-reasoning",
    "grok-4-fast-reasoning": "grok-4.3",
    "grok-4-fast-non-reasoning": "grok-4.20-non-reasoning",
    "grok-4-0709": "grok-4.3",
    "grok-code-fast-1": "grok-4.3",
    "grok-3": "grok-4.3",
    "grok-imagine-image-pro": "grok-imagine-image",
}

WORKLOAD_TAGS: frozenset[str] = frozenset(
    {"analysis", "rerank", "synthesis", "site", "accordion", "brief", "report", "qa", "maintenance"}
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
    # Model override (CLI --model or DISTILL_MODEL env var)
    model: str = ""

    PREMIUM_WORKLOADS: tuple[str, ...] = ("site", "report")

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
        """Fall back to ``<library_dir>/.distill`` when ops_dir is unset.

        Without this, a bare ``RouterConfig()`` produced by the many pipeline
        call sites would leave ``ops_dir=""``. That value then propagates into
        the agent provider, where ``Path("")`` resolves relative to the
        current working directory and task files (which include full prompts /
        transcripts / synthesis context) would be written next to the user's
        shell. Anchoring the default to the library directory keeps those
        files inside the user's existing library boundary.

        We read the library path from the env var ``DISTILL_OUTPUT_DIR``
        directly rather than importing ``distill.config``; the test suite
        enforces that ``distill.llm`` stays decoupled from the rest of
        the codebase.
        """
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
        if workload_tag:
            provider_name, _ = self.resolve(workload_tag)
        else:
            provider_name = self.provider

        key_map: dict[str, tuple[str | None, str | None]] = {
            "xai": ("xai_api_key", "XAI_API_KEY"),
            "gemini": ("gemini_api_key", "GEMINI_API_KEY"),
            "anthropic": ("anthropic_api_key", "ANTHROPIC_API_KEY"),
            "openai": ("openai_api_key", "OPENAI_API_KEY"),
            "agent": (None, None),
            "ollama": (None, None),
            "lmstudio": (None, None),
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
    elif provider_name == "lmstudio":
        from distill.llm.providers.lmstudio import LMStudioProvider

        provider = LMStudioProvider()
    else:
        valid = "xai, gemini, agent, anthropic, openai, ollama, lmstudio"
        raise ConfigurationError(f"Unknown provider '{provider_name}'. Valid providers: {valid}")

    _provider_cache[provider_name] = provider
    return provider


_VALID_REASONING_EFFORTS: frozenset[str] = frozenset({"low", "medium", "high"})


def _resolve_reasoning_effort(config: RouterConfig, workload_tag: str) -> str | None:
    """Resolve reasoning effort for a workload."""
    env_key = f"DISTILL_{workload_tag.upper()}_REASONING_EFFORT"
    env_val = os.environ.get(env_key, "").strip().lower()
    if env_val in _VALID_REASONING_EFFORTS:
        return env_val
    # Default based on tier
    if workload_tag in config.PREMIUM_WORKLOADS:
        return "high"
    return "medium"


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
    """Dispatch an LLM call through the configured provider."""
    config.validate_config(workload_tag)

    if workload_tag not in WORKLOAD_TAGS:
        logger.warning(
            "Unknown workload tag '%s'; falling back to default tier model",
            workload_tag,
        )

    provider_name, model_id = config.resolve(workload_tag)
    provider = _get_provider(provider_name, config)

    reasoning_effort: str | None = None
    if provider_name == "xai" and model_id.startswith("grok-4.3"):
        reasoning_effort = _resolve_reasoning_effort(config, workload_tag)

    provider_type = "local" if provider_name in LOCAL_PROVIDERS else "cloud"
    effective_ops_dir = ops_dir or config.ops_dir
    start_time = time.monotonic()
    outcome = "success"
    error_type = ""
    response: LLM_Response | None = None

    try:
        coro = provider.call(
            model_id,
            prompt,
            max_tokens=max_tokens,
            timeout=timeout,
            retries=retries,
            temperature=temperature,
            call_type=call_type,
            reasoning_effort=reasoning_effort,
        )
        try:
            response = asyncio.run(coro)
        except RuntimeError as rt_err:
            if "cannot be called from a running event loop" in str(rt_err):
                loop = asyncio.get_event_loop()
                response = loop.run_until_complete(coro)
            else:
                raise
    except Exception as exc:
        outcome = "error"
        error_type = type(exc).__name__
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
            provider_type=provider_type,
            provider_name=provider_name,
            tokens_per_second=0.0,
        )
        raise

    elapsed = time.monotonic() - start_time
    tokens_per_second = 0.0
    if provider_type == "local" and elapsed > 0:
        tokens_per_second = response.output_tokens / elapsed

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
        provider_type=provider_type,
        provider_name=provider_name,
        tokens_per_second=round(tokens_per_second, 2),
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

# pyright: strict
"""Property-based tests for the provider metadata module.

Feature: local-inference
"""

from __future__ import annotations

import asyncio

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from distill.llm.metadata import (
    DEFAULT_CONTEXT_WINDOW,
    LOCAL_CALL_TIMEOUT_MAX,
    LOCAL_FALLBACK_CONTEXT_WINDOW,
    LOCAL_PROVIDERS,
    local_call_timeout,
    resolve_metadata,
    resolve_metadata_sync,
)

# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------

# All valid provider names (local + cloud)
_all_providers = st.sampled_from(
    ["xai", "gemini", "anthropic", "openai", "agent", "ollama", "lmstudio"]
)

_model_names = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P"),
        blacklist_characters="\x00\n\r",
    ),
    min_size=1,
    max_size=50,
)


# ---------------------------------------------------------------------------
# Property 4: Provider type classification
# Feature: local-inference, Property 4: Provider type classification
# ---------------------------------------------------------------------------


@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
@given(provider_name=_all_providers, model=_model_names)
def test_provider_type_classification(provider_name: str, model: str) -> None:
    """provider_type is "local" iff provider_name in {"ollama", "lmstudio"}.

    **Validates: Requirements 4.1, 4.2, 17.4**
    """
    # resolve_metadata without a provider instance (cloud path or local fallback)
    metadata = asyncio.run(resolve_metadata(provider_name, model, provider=None))

    if provider_name in LOCAL_PROVIDERS:
        assert metadata.provider_type == "local", (
            f"Expected 'local' for provider '{provider_name}', got '{metadata.provider_type}'"
        )
    else:
        assert metadata.provider_type == "cloud", (
            f"Expected 'cloud' for provider '{provider_name}', got '{metadata.provider_type}'"
        )

    # provider_name is always preserved
    assert metadata.provider_name == provider_name


# ---------------------------------------------------------------------------
# Unit tests — cloud context window resolution
# ---------------------------------------------------------------------------


def test_exact_cloud_model_lookup() -> None:
    """Known cloud models resolve to their documented context window."""
    metadata = asyncio.run(resolve_metadata("xai", "grok-4.3"))
    assert metadata.context_window == 1_000_000
    assert metadata.provider_type == "cloud"


def test_anthropic_sonnet5_context_window_lookup() -> None:
    """Claude Sonnet 5 resolves to the documented 1M context window."""
    metadata = asyncio.run(resolve_metadata("anthropic", "claude-sonnet-5"))
    assert metadata.context_window == 1_000_000
    assert metadata.provider_type == "cloud"


def test_prefix_cloud_model_lookup() -> None:
    """Cloud models with suffixes resolve via prefix matching."""
    metadata = asyncio.run(resolve_metadata("xai", "grok-4.3-some-variant"))
    assert metadata.context_window == 1_000_000


def test_unknown_cloud_model_defaults() -> None:
    """Unknown cloud models get the default context window."""
    metadata = asyncio.run(resolve_metadata("xai", "unknown-model-xyz"))
    assert metadata.context_window == DEFAULT_CONTEXT_WINDOW


def test_local_provider_without_instance_defaults() -> None:
    """Local provider without a provider instance uses the local fallback window."""
    metadata = asyncio.run(resolve_metadata("ollama", "llama3:8b", provider=None))
    assert metadata.context_window == LOCAL_FALLBACK_CONTEXT_WINDOW
    assert metadata.provider_type == "local"


def test_local_provider_with_context_window_method() -> None:
    """Local provider with get_context_window method uses it."""

    class MockProvider:
        async def get_context_window(self, model: str) -> int:
            return 131_072

    metadata = asyncio.run(resolve_metadata("ollama", "llama3:8b", provider=MockProvider()))
    assert metadata.context_window == 131_072


def test_resolve_metadata_sync_matches_async_cloud_path() -> None:
    metadata = resolve_metadata_sync("xai", "grok-4.3")
    assert metadata.context_window == 1_000_000
    assert metadata.provider_type == "cloud"


def test_local_provider_with_failing_context_window() -> None:
    """Local provider that raises falls back to the local conservative window."""

    class FailingProvider:
        async def get_context_window(self, model: str) -> int:
            raise ConnectionError("Cannot reach server")

    metadata = asyncio.run(resolve_metadata("ollama", "llama3:8b", provider=FailingProvider()))
    assert metadata.context_window == LOCAL_FALLBACK_CONTEXT_WINDOW


def test_resolve_metadata_sync_local_unreachable() -> None:
    class FailingProvider:
        async def get_context_window(self, model: str) -> int:
            raise ConnectionError("Cannot reach server")

    metadata = resolve_metadata_sync("ollama", "llama3:8b", provider=FailingProvider())
    assert metadata.context_window == LOCAL_FALLBACK_CONTEXT_WINDOW


# ---------------------------------------------------------------------------
# Local-provider call timeout
# ---------------------------------------------------------------------------


def test_local_call_timeout_raises_short_cloud_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The cloud-tuned default is raised to the local floor for slow local models."""
    monkeypatch.delenv("DISTILL_LOCAL_TIMEOUT", raising=False)
    assert local_call_timeout(300) == 600


def test_local_call_timeout_keeps_larger_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A caller-supplied default above the floor is preserved, not lowered."""
    monkeypatch.delenv("DISTILL_LOCAL_TIMEOUT", raising=False)
    assert local_call_timeout(3600) == 3600


def test_local_call_timeout_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """A valid positive DISTILL_LOCAL_TIMEOUT wins over the floor."""
    monkeypatch.setenv("DISTILL_LOCAL_TIMEOUT", "2400")
    assert local_call_timeout(300) == 2400


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "  ",
        "0",
        "-5",
        "not-a-number",
        "12.5",
        "\u00b2",
        "\u0661\u0662",
        "86401",
        "9" * 4000,
        "9" * 5000,
    ],
)
def test_local_call_timeout_ignores_invalid_env(monkeypatch: pytest.MonkeyPatch, bad: str) -> None:
    """Blank, non-numeric, or non-positive overrides fall back to the floor."""
    monkeypatch.setenv("DISTILL_LOCAL_TIMEOUT", bad)
    assert local_call_timeout(300) == 600


def test_local_call_timeout_clamps_unbounded_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DISTILL_LOCAL_TIMEOUT", raising=False)

    assert local_call_timeout(10**4000) == LOCAL_CALL_TIMEOUT_MAX


@pytest.mark.parametrize("model", ["claude-opus-4-8", "claude-opus-4-7", "claude-opus-4-6"])
def test_anthropic_opus_context_window_lookup(model: str) -> None:
    """The Opus tier is 1M-context; a missing entry silently over-chunked input."""
    metadata = asyncio.run(resolve_metadata("anthropic", model))
    assert metadata.context_window == 1_000_000
    assert metadata.provider_type == "cloud"


@pytest.mark.parametrize(
    ("provider", "model"),
    [
        ("anthropic", "Claude-Opus-4-8"),
        ("anthropic", "  claude-sonnet-5  "),
        ("xai", "GROK-4.3"),
    ],
)
def test_context_window_lookup_is_case_and_whitespace_insensitive(
    provider: str, model: str
) -> None:
    """A differently-cased id must not fall back to the small default window."""
    metadata = asyncio.run(resolve_metadata(provider, model))
    assert metadata.context_window != DEFAULT_CONTEXT_WINDOW
    assert metadata.context_window == 1_000_000

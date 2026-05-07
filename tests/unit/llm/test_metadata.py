# pyright: strict
"""Property-based tests for the provider metadata module.

Feature: local-inference
"""

from __future__ import annotations

import asyncio

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from distill.llm.metadata import (
    DEFAULT_CONTEXT_WINDOW,
    LOCAL_PROVIDERS,
    resolve_metadata,
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


def test_prefix_cloud_model_lookup() -> None:
    """Cloud models with suffixes resolve via prefix matching."""
    metadata = asyncio.run(resolve_metadata("xai", "grok-4.3-some-variant"))
    assert metadata.context_window == 1_000_000


def test_unknown_cloud_model_defaults() -> None:
    """Unknown cloud models get the default context window."""
    metadata = asyncio.run(resolve_metadata("xai", "unknown-model-xyz"))
    assert metadata.context_window == DEFAULT_CONTEXT_WINDOW


def test_local_provider_without_instance_defaults() -> None:
    """Local provider without a provider instance gets default context window."""
    metadata = asyncio.run(resolve_metadata("ollama", "llama3:8b", provider=None))
    assert metadata.context_window == DEFAULT_CONTEXT_WINDOW
    assert metadata.provider_type == "local"


def test_local_provider_with_context_window_method() -> None:
    """Local provider with get_context_window method uses it."""

    class MockProvider:
        async def get_context_window(self, model: str) -> int:
            return 131_072

    metadata = asyncio.run(resolve_metadata("ollama", "llama3:8b", provider=MockProvider()))
    assert metadata.context_window == 131_072


def test_local_provider_with_failing_context_window() -> None:
    """Local provider that raises falls back to default."""

    class FailingProvider:
        async def get_context_window(self, model: str) -> int:
            raise ConnectionError("Cannot reach server")

    metadata = asyncio.run(resolve_metadata("ollama", "llama3:8b", provider=FailingProvider()))
    assert metadata.context_window == DEFAULT_CONTEXT_WINDOW

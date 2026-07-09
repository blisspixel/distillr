"""Tests for eval model-provider inference."""

from __future__ import annotations

import pytest

from distill.eval._models import is_local, provider_for_model


@pytest.mark.parametrize(
    ("model", "provider"),
    [
        ("grok-4.3", "xai"),
        ("GROK-4.3", "xai"),
        ("gemini-3-pro", "gemini"),
        ("deep-research-pro", "gemini"),
        ("claude-sonnet-5", "anthropic"),
        ("gpt-5.1", "openai"),
        ("o1-preview", "openai"),
        ("o3-mini", "openai"),
        ("adapter:grok-4.3", "adapter"),
        ("qwen3.5:27b", "ollama"),
    ],
)
def test_provider_for_model_prefixes(model: str, provider: str) -> None:
    assert provider_for_model(model) == provider


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        ("qwen3.5:27b", True),
        ("grok-4.3", False),
        ("gemini-3-pro", False),
        ("claude-sonnet-5", False),
        ("gpt-5.1", False),
        ("adapter:grok-4.3", False),
    ],
)
def test_is_local_uses_inferred_provider(model: str, expected: bool) -> None:
    assert is_local(model) is expected

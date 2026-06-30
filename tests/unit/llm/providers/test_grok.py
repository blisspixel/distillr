# pyright: strict
"""Property and unit tests for GrokProvider.

Feature: llm-router-model-upgrade
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from distill.llm.providers.grok import GrokProvider
from distill.llm.router import LLM_Response

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_response(
    text: str = "hello",
    prompt_tokens: int = 10,
    completion_tokens: int = 20,
    empty_choices: bool = False,
) -> SimpleNamespace:
    """Build a mock OpenAI chat completion response."""
    if empty_choices:
        return SimpleNamespace(choices=[], usage=None)
    message = SimpleNamespace(content=text)
    choice = SimpleNamespace(message=message)
    usage = SimpleNamespace(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)
    return SimpleNamespace(choices=[choice], usage=usage)


def _build_provider() -> tuple[GrokProvider, MagicMock]:
    """Create a GrokProvider with a mocked OpenAI client."""
    with patch("distill.llm.providers.grok.OpenAI") as mock_cls:
        mock_client = MagicMock()
        mock_cls.return_value = mock_client
        provider = GrokProvider(api_key="test-key")
    return provider, mock_client


# ---------------------------------------------------------------------------
# Property test — Property 3: Provider retry behavior
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(retries=st.integers(min_value=0, max_value=5))
def test_retry_count(retries: int) -> None:
    """Feature: llm-router-model-upgrade, Property 3: Provider retry behavior

    For any retry count N (0 ≤ N ≤ 5), when a provider call fails with a
    transient error on every attempt, the provider makes exactly N+1 total
    attempts before raising.

    **Validates: Requirements 2.4, 2.5**
    """
    provider, mock_client = _build_provider()
    mock_client.chat.completions.create.side_effect = RuntimeError("transient")

    call_count = 0
    original_create = mock_client.chat.completions.create

    def counting_create(**kwargs: Any) -> None:
        nonlocal call_count
        call_count += 1
        return original_create(**kwargs)

    mock_client.chat.completions.create = counting_create

    with (
        patch("distill.llm.providers.grok.time.sleep"),
        pytest.raises(RuntimeError, match="transient"),
    ):
        asyncio.run(provider.call("grok-4.3", "test prompt", retries=retries))

    assert call_count == retries + 1, f"Expected {retries + 1} attempts, got {call_count}"


# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------


class TestGrokProviderSuccess:
    """Test successful GrokProvider calls."""

    def test_media_generation_model_is_refused_before_api_call(self) -> None:
        """Media model slugs are not valid for xAI chat completions."""
        provider, mock_client = _build_provider()

        with pytest.raises(ValueError, match="media generation model"):
            asyncio.run(provider.call("grok-imagine-image", "hello"))

        mock_client.chat.completions.create.assert_not_called()

    def test_successful_call_returns_correct_fields(self) -> None:
        """A successful call returns an LLM_Response with correct fields."""
        provider, mock_client = _build_provider()
        mock_client.chat.completions.create.return_value = _make_mock_response(
            text="response text", prompt_tokens=100, completion_tokens=50
        )

        result = asyncio.run(provider.call("grok-4.3", "hello"))

        assert isinstance(result, LLM_Response)
        assert result.text == "response text"
        assert result.input_tokens == 100
        assert result.output_tokens == 50
        assert result.model == "grok-4.3"

    def test_empty_choices_returns_empty_response(self) -> None:
        """Empty choices in API response returns LLM_Response with empty text."""
        provider, mock_client = _build_provider()
        mock_client.chat.completions.create.return_value = _make_mock_response(empty_choices=True)

        result = asyncio.run(provider.call("grok-4.3", "hello"))

        assert result.text == ""
        assert result.input_tokens == 0
        assert result.output_tokens == 0
        assert result.model == "grok-4.3"


class TestGrokProviderRetry:
    """Test GrokProvider retry behavior."""

    def test_retry_on_transient_error(self) -> None:
        """Provider retries on transient error and succeeds on second attempt."""
        provider, mock_client = _build_provider()
        mock_client.chat.completions.create.side_effect = [
            RuntimeError("transient"),
            _make_mock_response(text="ok", prompt_tokens=5, completion_tokens=3),
        ]

        with patch("distill.llm.providers.grok.time.sleep") as mock_sleep:
            result = asyncio.run(provider.call("grok-4.3", "hello", retries=2))

        assert result.text == "ok"
        assert result.input_tokens == 5
        assert result.output_tokens == 3
        mock_sleep.assert_called_once_with(5)  # 2^0 * 5 = 5

    def test_raise_after_exhausted_retries(self) -> None:
        """Provider raises after all retries are exhausted."""
        provider, mock_client = _build_provider()
        mock_client.chat.completions.create.side_effect = RuntimeError("permanent")

        with (
            patch("distill.llm.providers.grok.time.sleep"),
            pytest.raises(RuntimeError, match="permanent"),
        ):
            asyncio.run(provider.call("grok-4.3", "hello", retries=2))

        assert mock_client.chat.completions.create.call_count == 3

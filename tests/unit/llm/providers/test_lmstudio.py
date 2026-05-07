# pyright: strict
"""Property and unit tests for LMStudioProvider.

Feature: local-inference
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from distill.llm.providers.lmstudio import LMStudioProvider
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


def _build_provider() -> tuple[LMStudioProvider, MagicMock]:
    """Create an LMStudioProvider with a mocked OpenAI client."""
    with patch("distill.llm.providers.lmstudio.OpenAI") as mock_cls:
        mock_client = MagicMock()
        mock_cls.return_value = mock_client
        provider = LMStudioProvider(base_url="http://localhost:1234/v1")
    return provider, mock_client


# ---------------------------------------------------------------------------
# Property test — P1: Response parsing preserves fields (LM Studio variant)
# ---------------------------------------------------------------------------


@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
@given(
    text=st.text(min_size=0, max_size=200),
    input_tokens=st.integers(min_value=0, max_value=100000),
    output_tokens=st.integers(min_value=0, max_value=100000),
    model=st.text(min_size=1, max_size=50, alphabet=st.characters(categories=("L", "N", "P"))),
)
def test_response_parsing_preserves_fields(
    text: str, input_tokens: int, output_tokens: int, model: str
) -> None:
    """Feature: local-inference, Property 1: Response parsing preserves fields

    For any valid LM Studio API response containing input_tokens, output_tokens,
    model, and text fields, parsing it into an LLM_Response shall produce a
    dataclass where each field exactly matches the corresponding API response value.

    **Validates: Requirements 1.3, 2.4**
    """
    provider, mock_client = _build_provider()
    mock_client.chat.completions.create.return_value = _make_mock_response(
        text=text, prompt_tokens=input_tokens, completion_tokens=output_tokens
    )

    result = asyncio.run(provider.call(model, "test prompt"))

    assert result.text == text
    assert result.input_tokens == input_tokens
    assert result.output_tokens == output_tokens
    assert result.model == model


# ---------------------------------------------------------------------------
# Property test — P2: Model name passthrough (LM Studio variant)
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(
    model=st.text(
        min_size=1,
        max_size=100,
        alphabet=st.characters(categories=("L", "N", "P", "S")),
    ).filter(lambda s: s.strip() == s and len(s.strip()) > 0),
)
def test_model_name_passthrough(model: str) -> None:
    """Feature: local-inference, Property 2: Model name passthrough

    For any non-empty model name string, when the router dispatches a call to
    LM Studio, the model name in the outgoing request shall be identical to
    the configured model name.

    **Validates: Requirements 1.6, 3.4, 15.1, 15.3**
    """
    provider, mock_client = _build_provider()
    mock_client.chat.completions.create.return_value = _make_mock_response()

    asyncio.run(provider.call(model, "test prompt"))

    call_kwargs = mock_client.chat.completions.create.call_args
    assert call_kwargs.kwargs["model"] == model


# ---------------------------------------------------------------------------
# Property test — P3: Retry attempt count (LM Studio variant)
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(retries=st.integers(min_value=0, max_value=5))
def test_retry_count(retries: int) -> None:
    """Feature: local-inference, Property 3: Retry attempt count

    For any retry count N (0 ≤ N ≤ 5), when all attempts fail with transient
    errors, the provider shall make exactly N + 1 total attempts before raising.

    **Validates: Requirements 1.5**
    """
    provider, mock_client = _build_provider()
    # Use a non-connection error so it retries rather than raising immediately
    mock_client.chat.completions.create.side_effect = RuntimeError("transient server error")

    call_count = 0
    original_create = mock_client.chat.completions.create

    def counting_create(**kwargs: Any) -> None:
        nonlocal call_count
        call_count += 1
        return original_create(**kwargs)

    mock_client.chat.completions.create = counting_create

    with (
        patch("distill.llm.providers.lmstudio.time.sleep"),
        pytest.raises(RuntimeError, match="transient server error"),
    ):
        asyncio.run(provider.call("test-model", "test prompt", retries=retries))

    assert call_count == retries + 1, f"Expected {retries + 1} attempts, got {call_count}"


# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------


class TestLMStudioProviderSuccess:
    """Test successful LMStudioProvider calls."""

    def test_successful_call_returns_correct_fields(self) -> None:
        """A successful call returns an LLM_Response with correct fields."""
        provider, mock_client = _build_provider()
        mock_client.chat.completions.create.return_value = _make_mock_response(
            text="response text", prompt_tokens=100, completion_tokens=50
        )

        result = asyncio.run(provider.call("local-model", "hello"))

        assert isinstance(result, LLM_Response)
        assert result.text == "response text"
        assert result.input_tokens == 100
        assert result.output_tokens == 50
        assert result.model == "local-model"

    def test_empty_choices_returns_empty_response(self) -> None:
        """Empty choices in API response returns LLM_Response with empty text."""
        provider, mock_client = _build_provider()
        mock_client.chat.completions.create.return_value = _make_mock_response(empty_choices=True)

        result = asyncio.run(provider.call("local-model", "hello"))

        assert result.text == ""
        assert result.input_tokens == 0
        assert result.output_tokens == 0
        assert result.model == "local-model"

    def test_temperature_passed_to_client(self) -> None:
        """Temperature is passed to the OpenAI client when specified."""
        provider, mock_client = _build_provider()
        mock_client.chat.completions.create.return_value = _make_mock_response()

        asyncio.run(provider.call("local-model", "hello", temperature=0.5))

        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert call_kwargs["temperature"] == 0.5

    def test_temperature_not_passed_when_none(self) -> None:
        """Temperature is not passed when None."""
        provider, mock_client = _build_provider()
        mock_client.chat.completions.create.return_value = _make_mock_response()

        asyncio.run(provider.call("local-model", "hello"))

        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert "temperature" not in call_kwargs


class TestLMStudioProviderConnectionError:
    """Test LMStudioProvider connection error handling."""

    def test_connection_refused_raises_connection_error(self) -> None:
        """Connection refused raises ConnectionError with helpful message."""
        provider, mock_client = _build_provider()
        mock_client.chat.completions.create.side_effect = Exception("Connection refused by server")

        with pytest.raises(ConnectionError, match="Cannot reach LM Studio"):
            asyncio.run(provider.call("local-model", "hello"))

    def test_timeout_raises_connection_error(self) -> None:
        """Timeout raises ConnectionError with helpful message."""
        provider, mock_client = _build_provider()
        mock_client.chat.completions.create.side_effect = Exception("Connection timeout reached")

        with pytest.raises(ConnectionError, match="Cannot reach LM Studio"):
            asyncio.run(provider.call("local-model", "hello"))


class TestLMStudioProviderRetry:
    """Test LMStudioProvider retry behavior."""

    def test_retry_on_transient_error(self) -> None:
        """Provider retries on transient error and succeeds on second attempt."""
        provider, mock_client = _build_provider()
        mock_client.chat.completions.create.side_effect = [
            RuntimeError("transient server error"),
            _make_mock_response(text="ok", prompt_tokens=5, completion_tokens=3),
        ]

        with patch("distill.llm.providers.lmstudio.time.sleep") as mock_sleep:
            result = asyncio.run(provider.call("local-model", "hello", retries=2))

        assert result.text == "ok"
        assert result.input_tokens == 5
        assert result.output_tokens == 3
        mock_sleep.assert_called_once_with(2)  # 2^0 * 2 = 2

    def test_raise_after_exhausted_retries(self) -> None:
        """Provider raises after all retries are exhausted."""
        provider, mock_client = _build_provider()
        mock_client.chat.completions.create.side_effect = RuntimeError("permanent error")

        with (
            patch("distill.llm.providers.lmstudio.time.sleep"),
            pytest.raises(RuntimeError, match="permanent error"),
        ):
            asyncio.run(provider.call("local-model", "hello", retries=2))

        assert mock_client.chat.completions.create.call_count == 3


class TestLMStudioProviderInit:
    """Test LMStudioProvider initialization."""

    def test_default_base_url(self) -> None:
        """Default base URL is http://localhost:1234/v1."""
        with patch("distill.llm.providers.lmstudio.OpenAI") as mock_cls:
            mock_cls.return_value = MagicMock()
            import os

            os.environ.pop("LMSTUDIO_BASE_URL", None)
            provider = LMStudioProvider()
        assert provider._base_url == "http://localhost:1234/v1"

    def test_custom_base_url(self) -> None:
        """Custom base URL is used when provided."""
        with patch("distill.llm.providers.lmstudio.OpenAI") as mock_cls:
            mock_cls.return_value = MagicMock()
            provider = LMStudioProvider(base_url="http://custom:9999/v1")
        assert provider._base_url == "http://custom:9999/v1"

    def test_env_var_override(self) -> None:
        """LMSTUDIO_BASE_URL environment variable overrides default."""
        with (
            patch("distill.llm.providers.lmstudio.OpenAI") as mock_cls,
            patch.dict("os.environ", {"LMSTUDIO_BASE_URL": "http://env:8888/v1"}),
        ):
            mock_cls.return_value = MagicMock()
            provider = LMStudioProvider()
        assert provider._base_url == "http://env:8888/v1"

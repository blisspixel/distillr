# pyright: strict
"""Unit tests for GeminiProvider.

Feature: llm-router-model-upgrade
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from distill.llm.providers.gemini import GeminiProvider
from distill.llm.router import LLM_Response

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_response(
    text: str = "gemini response",
    prompt_token_count: int = 10,
    candidates_token_count: int = 20,
    has_usage: bool = True,
) -> SimpleNamespace:
    """Build a mock Gemini generate_content response."""
    usage = None
    if has_usage:
        usage = SimpleNamespace(
            prompt_token_count=prompt_token_count,
            candidates_token_count=candidates_token_count,
        )
    return SimpleNamespace(text=text, usage_metadata=usage)


def _build_provider() -> tuple[GeminiProvider, MagicMock]:
    """Create a GeminiProvider with a mocked google.genai client."""
    mock_genai = MagicMock()
    mock_client = MagicMock()
    mock_genai.Client.return_value = mock_client

    with patch.dict("sys.modules", {"google": MagicMock(), "google.genai": mock_genai}):
        provider = GeminiProvider.__new__(GeminiProvider)
        object.__setattr__(provider, "_client", mock_client)

    return provider, mock_client


# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------


def test_init_builds_google_genai_client() -> None:
    """Provider construction passes the API key to the lazy google-genai client."""
    mock_genai = MagicMock()
    mock_google = MagicMock()
    mock_google.genai = mock_genai

    with patch.dict("sys.modules", {"google": mock_google, "google.genai": mock_genai}):
        from distill.llm.providers.gemini import GeminiProvider

        provider = GeminiProvider("test-key")

    mock_genai.Client.assert_called_once_with(api_key="test-key")
    assert provider._client is mock_genai.Client.return_value  # pyright: ignore[reportPrivateUsage]


class TestGeminiProviderSuccess:
    """Test successful GeminiProvider calls."""

    def test_successful_call_returns_correct_fields(self) -> None:
        """A successful call returns an LLM_Response with correct fields."""
        provider, mock_client = _build_provider()
        mock_client.models.generate_content.return_value = _make_mock_response(
            text="hello from gemini",
            prompt_token_count=100,
            candidates_token_count=50,
        )

        result = asyncio.run(provider.call("gemini-3.1-pro", "hello"))

        assert isinstance(result, LLM_Response)
        assert result.text == "hello from gemini"
        assert result.input_tokens == 100
        assert result.output_tokens == 50
        assert result.model == "gemini-3.1-pro"

    def test_missing_usage_metadata_returns_zero_tokens(self) -> None:
        """Missing usage_metadata returns zero token counts."""
        provider, mock_client = _build_provider()
        mock_client.models.generate_content.return_value = _make_mock_response(
            text="no usage", has_usage=False
        )

        result = asyncio.run(provider.call("gemini-3.1-flash", "hello"))

        assert result.text == "no usage"
        assert result.input_tokens == 0
        assert result.output_tokens == 0

    def test_none_token_counts_default_to_zero(self) -> None:
        """None values in usage metadata default to zero."""
        provider, mock_client = _build_provider()
        usage = SimpleNamespace(prompt_token_count=None, candidates_token_count=None)
        mock_client.models.generate_content.return_value = SimpleNamespace(
            text="partial", usage_metadata=usage
        )

        result = asyncio.run(provider.call("gemini-3.1-flash", "hello"))

        assert result.input_tokens == 0
        assert result.output_tokens == 0

    def test_temperature_is_forwarded_when_supplied(self) -> None:
        """Temperature is included only when the caller explicitly supplies it."""
        provider, mock_client = _build_provider()
        mock_client.models.generate_content.return_value = _make_mock_response()

        asyncio.run(
            provider.call(
                "gemini-3.1-flash",
                "hello",
                max_tokens=123,
                temperature=0.4,
            )
        )

        assert mock_client.models.generate_content.call_args.kwargs["config"] == {
            "max_output_tokens": 123,
            "temperature": 0.4,
        }

    def test_temperature_is_omitted_when_not_supplied(self) -> None:
        """Default calls do not forward a null temperature value to Gemini."""
        provider, mock_client = _build_provider()
        mock_client.models.generate_content.return_value = _make_mock_response()

        asyncio.run(provider.call("gemini-3.1-flash", "hello", max_tokens=456))

        assert mock_client.models.generate_content.call_args.kwargs["config"] == {
            "max_output_tokens": 456
        }


class TestGeminiProviderRetry:
    """Test GeminiProvider retry behavior."""

    def test_retry_on_transient_error(self) -> None:
        """Provider retries on transient error and succeeds on second attempt."""
        provider, mock_client = _build_provider()
        mock_client.models.generate_content.side_effect = [
            RuntimeError("transient"),
            _make_mock_response(text="ok"),
        ]

        with patch("distill.llm.providers.gemini.time.sleep") as mock_sleep:
            result = asyncio.run(provider.call("gemini-3.1-pro", "hello", retries=2))

        assert result.text == "ok"
        mock_sleep.assert_called_once_with(5)  # 2^0 * 5 = 5

    def test_raise_after_exhausted_retries(self) -> None:
        """Provider raises after all retries are exhausted."""
        provider, mock_client = _build_provider()
        mock_client.models.generate_content.side_effect = RuntimeError("permanent")

        with (
            patch("distill.llm.providers.gemini.time.sleep"),
            pytest.raises(RuntimeError, match="permanent"),
        ):
            asyncio.run(provider.call("gemini-3.1-pro", "hello", retries=2))

        assert mock_client.models.generate_content.call_count == 3

    def test_permanent_error_does_not_retry(self) -> None:
        """Permanent Gemini API errors raise immediately without sleeping or retrying."""

        class PermanentGeminiError(Exception):
            code = 401

        provider, mock_client = _build_provider()
        mock_client.models.generate_content.side_effect = PermanentGeminiError("auth")

        with (
            patch("distill.llm.providers.gemini.time.sleep") as mock_sleep,
            pytest.raises(PermanentGeminiError, match="auth"),
        ):
            asyncio.run(provider.call("gemini-3.1-pro", "hello", retries=2))

        mock_sleep.assert_not_called()
        assert mock_client.models.generate_content.call_count == 1

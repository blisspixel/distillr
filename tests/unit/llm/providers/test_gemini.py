# pyright: strict
"""Unit tests for GeminiProvider.

Feature: llm-router-model-upgrade
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

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


def _build_provider() -> tuple[object, MagicMock]:
    """Create a GeminiProvider with a mocked google.genai client."""
    mock_genai = MagicMock()
    mock_client = MagicMock()
    mock_genai.Client.return_value = mock_client

    with patch.dict("sys.modules", {"google": MagicMock(), "google.genai": mock_genai}):
        from distill.llm.providers.gemini import GeminiProvider

        provider = GeminiProvider.__new__(GeminiProvider)
        provider._client = mock_client  # type: ignore[attr-defined]

    return provider, mock_client


# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------


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

        result = asyncio.get_event_loop().run_until_complete(
            provider.call("gemini-3.1-pro", "hello")  # type: ignore[union-attr]
        )

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

        result = asyncio.get_event_loop().run_until_complete(
            provider.call("gemini-3.1-flash", "hello")  # type: ignore[union-attr]
        )

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

        result = asyncio.get_event_loop().run_until_complete(
            provider.call("gemini-3.1-flash", "hello")  # type: ignore[union-attr]
        )

        assert result.input_tokens == 0
        assert result.output_tokens == 0


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
            result = asyncio.get_event_loop().run_until_complete(
                provider.call("gemini-3.1-pro", "hello", retries=2)  # type: ignore[union-attr]
            )

        assert result.text == "ok"
        mock_sleep.assert_called_once_with(5)  # 2^0 * 5 = 5

    def test_raise_after_exhausted_retries(self) -> None:
        """Provider raises after all retries are exhausted."""
        provider, mock_client = _build_provider()
        mock_client.models.generate_content.side_effect = RuntimeError("permanent")

        with patch("distill.llm.providers.gemini.time.sleep"):
            with pytest.raises(RuntimeError, match="permanent"):
                asyncio.get_event_loop().run_until_complete(
                    provider.call("gemini-3.1-pro", "hello", retries=2)  # type: ignore[union-attr]
                )

        assert mock_client.models.generate_content.call_count == 3

# pyright: strict
"""Property and unit tests for OllamaProvider.

Feature: local-inference
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from distill.llm.providers.ollama import OllamaProvider
from distill.llm.router import LLM_Response

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_generate_response(
    text: str = "hello",
    prompt_eval_count: int = 10,
    eval_count: int = 20,
) -> dict[str, Any]:
    """Build a mock Ollama /api/chat response dict."""
    return {
        "message": {"content": text, "thinking": ""},
        "prompt_eval_count": prompt_eval_count,
        "eval_count": eval_count,
        "model": "test-model",
        "done": True,
    }


def _make_show_response(
    context_length: int = 8192,
    *,
    use_model_info: bool = True,
) -> dict[str, Any]:
    """Build a mock Ollama /api/show response dict."""
    resp: dict[str, Any] = {"parameters": "", "model_info": {}}
    if use_model_info:
        resp["model_info"] = {"general.context_length": context_length}
    else:
        resp["parameters"] = f"num_ctx {context_length}\ntemperature 0.7"
    return resp


def _make_tags_response(models: list[str] | None = None) -> dict[str, Any]:
    """Build a mock Ollama /api/tags response dict."""
    if models is None:
        models = ["llama3:8b", "qwen3.5:27b"]
    return {"models": [{"name": m, "size": 1000000} for m in models]}


def _mock_httpx_response(json_data: dict[str, Any], status_code: int = 200) -> httpx.Response:
    """Create a mock httpx.Response."""
    response = httpx.Response(
        status_code=status_code,
        json=json_data,
        request=httpx.Request("POST", "http://localhost:11434/api/chat"),
    )
    return response


# ---------------------------------------------------------------------------
# Property test — P1: Response parsing preserves fields
# ---------------------------------------------------------------------------


@settings(max_examples=100)
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

    For any valid Ollama API response containing input_tokens, output_tokens,
    model, and text fields, parsing it into an LLM_Response shall produce a
    dataclass where each field exactly matches the corresponding API response value.

    **Validates: Requirements 1.3, 2.4**
    """
    provider = OllamaProvider(base_url="http://localhost:11434")
    json_data = _make_generate_response(
        text=text,
        prompt_eval_count=input_tokens,
        eval_count=output_tokens,
    )

    mock_response = _mock_httpx_response(json_data)

    async def mock_post(*args: Any, **kwargs: Any) -> httpx.Response:
        return mock_response

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post = mock_post
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client_cls.return_value = mock_client

        result = asyncio.run(provider.call(model, "test prompt"))

    assert result.text == text
    assert result.input_tokens == input_tokens
    assert result.output_tokens == output_tokens
    assert result.model == model


# ---------------------------------------------------------------------------
# Property test — P2: Model name passthrough
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
    a local provider (ollama), the model name in the outgoing HTTP request body
    shall be identical to the configured model name.

    **Validates: Requirements 1.6, 3.4, 15.1, 15.3**
    """
    provider = OllamaProvider(base_url="http://localhost:11434")
    json_data = _make_generate_response()
    mock_response = _mock_httpx_response(json_data)

    captured_payload: dict[str, Any] = {}

    async def mock_post(*args: Any, **kwargs: Any) -> httpx.Response:
        if "json" in kwargs:
            captured_payload.update(kwargs["json"])
        return mock_response

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post = mock_post
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client_cls.return_value = mock_client

        asyncio.run(provider.call(model, "test prompt"))

    assert captured_payload["model"] == model


# ---------------------------------------------------------------------------
# Property test — P3: Retry attempt count
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(retries=st.integers(min_value=0, max_value=5))
def test_retry_count(retries: int) -> None:
    """Feature: local-inference, Property 3: Retry attempt count

    For any retry count N (0 ≤ N ≤ 5), when all attempts fail with transient
    errors, the provider shall make exactly N + 1 total attempts before raising.

    **Validates: Requirements 1.5**
    """
    provider = OllamaProvider(base_url="http://localhost:11434")
    call_count = 0

    async def mock_post(*args: Any, **kwargs: Any) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        raise httpx.TimeoutException("timeout")

    with (
        patch("httpx.AsyncClient") as mock_client_cls,
        patch("distill.llm.providers.ollama.time.sleep"),
    ):
        mock_client = AsyncMock()
        mock_client.post = mock_post
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client_cls.return_value = mock_client

        with pytest.raises(httpx.TimeoutException):
            asyncio.run(provider.call("test-model", "test prompt", retries=retries))

    assert call_count == retries + 1, f"Expected {retries + 1} attempts, got {call_count}"


# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------


class TestOllamaProviderSuccess:
    """Test successful OllamaProvider calls."""

    def test_successful_call_returns_correct_fields(self) -> None:
        """A successful call returns an LLM_Response with correct fields."""
        provider = OllamaProvider(base_url="http://localhost:11434")
        json_data = _make_generate_response(
            text="response text", prompt_eval_count=100, eval_count=50
        )
        mock_response = _mock_httpx_response(json_data)

        async def mock_post(*args: Any, **kwargs: Any) -> httpx.Response:
            return mock_response

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = mock_post
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            result = asyncio.run(provider.call("llama3:8b", "hello"))

        assert isinstance(result, LLM_Response)
        assert result.text == "response text"
        assert result.input_tokens == 100
        assert result.output_tokens == 50
        assert result.model == "llama3:8b"

    def test_temperature_passed_in_options(self) -> None:
        """Temperature is passed in the options payload when specified."""
        provider = OllamaProvider(base_url="http://localhost:11434")
        json_data = _make_generate_response()
        mock_response = _mock_httpx_response(json_data)

        captured_payload: dict[str, Any] = {}

        async def mock_post(*args: Any, **kwargs: Any) -> httpx.Response:
            if "json" in kwargs:
                captured_payload.update(kwargs["json"])
            return mock_response

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = mock_post
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            asyncio.run(provider.call("llama3:8b", "hello", temperature=0.7))

        assert captured_payload["options"]["temperature"] == 0.7

    def test_null_token_counts_default_to_zero(self) -> None:
        """Null token counts in response default to zero."""
        provider = OllamaProvider(base_url="http://localhost:11434")
        json_data = {
            "message": {"content": "text", "thinking": ""},
            "prompt_eval_count": None,
            "eval_count": None,
        }
        mock_response = _mock_httpx_response(json_data)

        async def mock_post(*args: Any, **kwargs: Any) -> httpx.Response:
            return mock_response

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = mock_post
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            result = asyncio.run(provider.call("llama3:8b", "hello"))

        assert result.input_tokens == 0
        assert result.output_tokens == 0


class TestOllamaProviderConnectionError:
    """Test OllamaProvider connection error handling."""

    def test_connect_error_raises_connection_error(self) -> None:
        """ConnectError raises ConnectionError with helpful message."""
        provider = OllamaProvider(base_url="http://localhost:11434")

        async def mock_post(*args: Any, **kwargs: Any) -> httpx.Response:
            raise httpx.ConnectError("Connection refused")

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = mock_post
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            with pytest.raises(ConnectionError, match="Cannot reach Ollama"):
                asyncio.run(provider.call("llama3:8b", "hello"))

    def test_connect_timeout_raises_connection_error(self) -> None:
        """ConnectTimeout raises ConnectionError with helpful message."""
        provider = OllamaProvider(base_url="http://localhost:11434")

        async def mock_post(*args: Any, **kwargs: Any) -> httpx.Response:
            raise httpx.ConnectTimeout("Timed out")

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = mock_post
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            with pytest.raises(ConnectionError, match="ollama serve"):
                asyncio.run(provider.call("llama3:8b", "hello"))


class TestOllamaProviderRetry:
    """Test OllamaProvider retry behavior."""

    def test_retry_on_timeout(self) -> None:
        """Provider retries on timeout and succeeds on second attempt."""
        provider = OllamaProvider(base_url="http://localhost:11434")
        json_data = _make_generate_response(text="ok", prompt_eval_count=5, eval_count=3)
        mock_response = _mock_httpx_response(json_data)

        call_count = 0

        async def mock_post(*args: Any, **kwargs: Any) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise httpx.TimeoutException("timeout")
            return mock_response

        with (
            patch("httpx.AsyncClient") as mock_client_cls,
            patch("distill.llm.providers.ollama.time.sleep") as mock_sleep,
        ):
            mock_client = AsyncMock()
            mock_client.post = mock_post
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            result = asyncio.run(provider.call("llama3:8b", "hello", retries=2))

        assert result.text == "ok"
        mock_sleep.assert_called_once_with(2)  # 2^0 * 2 = 2

    def test_raise_after_exhausted_retries(self) -> None:
        """Provider raises after all retries are exhausted."""
        provider = OllamaProvider(base_url="http://localhost:11434")

        async def mock_post(*args: Any, **kwargs: Any) -> httpx.Response:
            raise httpx.TimeoutException("permanent timeout")

        with (
            patch("httpx.AsyncClient") as mock_client_cls,
            patch("distill.llm.providers.ollama.time.sleep"),
        ):
            mock_client = AsyncMock()
            mock_client.post = mock_post
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            with pytest.raises(httpx.TimeoutException):
                asyncio.run(provider.call("llama3:8b", "hello", retries=2))


class TestOllamaGetContextWindow:
    """Test OllamaProvider.get_context_window()."""

    def test_get_context_window_from_model_info(self) -> None:
        """Context window is read from model_info."""
        provider = OllamaProvider(base_url="http://localhost:11434")
        json_data = _make_show_response(context_length=131072, use_model_info=True)
        mock_response = _mock_httpx_response(json_data)

        async def mock_post(*args: Any, **kwargs: Any) -> httpx.Response:
            return mock_response

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = mock_post
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            result = asyncio.run(provider.get_context_window("qwen3.5:27b"))

        assert result == 131072

    def test_get_context_window_from_parameters(self) -> None:
        """Context window falls back to parameters string."""
        provider = OllamaProvider(base_url="http://localhost:11434")
        json_data = _make_show_response(context_length=32768, use_model_info=False)
        mock_response = _mock_httpx_response(json_data)

        async def mock_post(*args: Any, **kwargs: Any) -> httpx.Response:
            return mock_response

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = mock_post
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            result = asyncio.run(provider.get_context_window("llama3:8b"))

        assert result == 32768

    def test_get_context_window_caches_result(self) -> None:
        """Context window is cached after first query."""
        provider = OllamaProvider(base_url="http://localhost:11434")
        json_data = _make_show_response(context_length=8192)
        mock_response = _mock_httpx_response(json_data)

        call_count = 0

        async def mock_post(*args: Any, **kwargs: Any) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            return mock_response

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = mock_post
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            asyncio.run(provider.get_context_window("llama3:8b"))
            asyncio.run(provider.get_context_window("llama3:8b"))

        assert call_count == 1

    def test_get_context_window_defaults_to_4096(self) -> None:
        """Context window defaults to 4096 when not found."""
        provider = OllamaProvider(base_url="http://localhost:11434")
        json_data: dict[str, Any] = {"parameters": "", "model_info": {}}
        mock_response = _mock_httpx_response(json_data)

        async def mock_post(*args: Any, **kwargs: Any) -> httpx.Response:
            return mock_response

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = mock_post
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            result = asyncio.run(provider.get_context_window("unknown-model"))

        assert result == 4096


class TestOllamaListModels:
    """Test OllamaProvider.list_models()."""

    def test_list_models_returns_model_list(self) -> None:
        """list_models returns the models from /api/tags."""
        provider = OllamaProvider(base_url="http://localhost:11434")
        json_data = _make_tags_response(["llama3:8b", "qwen3.5:27b"])
        mock_response = httpx.Response(
            status_code=200,
            json=json_data,
            request=httpx.Request("GET", "http://localhost:11434/api/tags"),
        )

        async def mock_get(*args: Any, **kwargs: Any) -> httpx.Response:
            return mock_response

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = mock_get
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            result = asyncio.run(provider.list_models())

        assert len(result) == 2
        assert result[0]["name"] == "llama3:8b"
        assert result[1]["name"] == "qwen3.5:27b"

    def test_list_models_connection_error(self) -> None:
        """list_models raises ConnectionError when server unreachable."""
        provider = OllamaProvider(base_url="http://localhost:11434")

        async def mock_get(*args: Any, **kwargs: Any) -> httpx.Response:
            raise httpx.ConnectError("Connection refused")

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = mock_get
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            with pytest.raises(ConnectionError, match="Cannot reach Ollama"):
                asyncio.run(provider.list_models())


class TestOllamaProviderInit:
    """Test OllamaProvider initialization."""

    def test_default_base_url(self) -> None:
        """Default base URL is http://localhost:11434."""
        with patch.dict("os.environ", {}, clear=False):
            # Remove OLLAMA_BASE_URL if set
            import os

            os.environ.pop("OLLAMA_BASE_URL", None)
            provider = OllamaProvider()
        assert provider._base_url == "http://localhost:11434"

    def test_custom_base_url(self) -> None:
        """Custom base URL is used when provided."""
        provider = OllamaProvider(base_url="http://custom:9999")
        assert provider._base_url == "http://custom:9999"

    def test_env_var_override(self) -> None:
        """OLLAMA_BASE_URL environment variable overrides default."""
        with patch.dict("os.environ", {"OLLAMA_BASE_URL": "http://env:8888"}):
            provider = OllamaProvider()
        assert provider._base_url == "http://env:8888"


class TestAdaptiveNumCtx:
    """num_ctx is sized to the prompt, not the model's (possibly huge) default —
    so a 262144-context model doesn't allocate a KV cache that spills VRAM to CPU."""

    def test_tiny_prompt_uses_floor_not_model_default(self) -> None:
        import asyncio

        provider = OllamaProvider()
        provider.get_context_window = AsyncMock(return_value=262144)  # huge default
        ctx = asyncio.run(provider._adaptive_num_ctx("qwen3.6:27b", "short prompt", 800))
        assert ctx == 4096  # floor — nowhere near 262144

    def test_large_prompt_grows_but_caps_at_model_max(self) -> None:
        import asyncio

        provider = OllamaProvider()
        provider.get_context_window = AsyncMock(return_value=8192)
        big = "x" * 400_000  # ~100k token estimate, far over the model max
        ctx = asyncio.run(provider._adaptive_num_ctx("small-ctx:7b", big, 8192))
        assert ctx == 8192  # capped at the model's max context

    def test_scales_with_prompt_when_under_model_max(self) -> None:
        import asyncio

        provider = OllamaProvider()
        provider.get_context_window = AsyncMock(return_value=262144)
        big = "x" * 200_000  # ~65k token estimate
        ctx = asyncio.run(provider._adaptive_num_ctx("qwen3.6:27b", big, 8192))
        assert 60_000 < ctx < 262_144  # sized to need, well under the default

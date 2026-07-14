# pyright: strict
"""Property and unit tests for OllamaProvider.

Feature: local-inference
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Callable
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from distill.commands._json import ExitCode, map_exception_to_exit_code
from distill.llm.errors import ProviderBusyTimeoutError, describe_provider_error
from distill.llm.providers.ollama import (
    _STRUCTURED_JSON_CALL_TYPES,
    OllamaProvider,
    _describe_ollama_error,
)
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
# Streaming mock: OllamaProvider.call() uses client.stream() + aiter_lines()
# ---------------------------------------------------------------------------

_STREAM_REQUEST = httpx.Request("POST", "http://localhost:11434/api/chat")


class _FakeStreamResponse:
    """Stand-in for the httpx streaming response yielded by client.stream()."""

    def __init__(
        self,
        frames: list[dict[str, Any]],
        *,
        status_code: int = 200,
        stall_exc: Exception | None = None,
    ) -> None:
        self.status_code = status_code
        self._frames = frames
        self._stall_exc = stall_exc

    async def aiter_lines(self) -> AsyncIterator[str]:
        for frame in self._frames:
            yield json.dumps(frame)
        if self._stall_exc is not None:
            # Model went silent mid-generation: the per-read idle timeout fires.
            raise self._stall_exc

    async def aread(self) -> bytes:
        return b""

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}",
                request=_STREAM_REQUEST,
                response=httpx.Response(self.status_code, request=_STREAM_REQUEST),
            )


class _FakeStream:
    """Async context manager returned by the fake client's stream()."""

    def __init__(self, response: _FakeStreamResponse) -> None:
        self._response = response

    async def __aenter__(self) -> _FakeStreamResponse:
        return self._response

    async def __aexit__(self, *exc: object) -> None:
        return None


class _FakeStreamClient:
    """Stand-in for httpx.AsyncClient whose stream() emits NDJSON frames."""

    def __init__(
        self,
        frames: list[dict[str, Any]],
        *,
        status_code: int = 200,
        stall_exc: Exception | None = None,
        captured: dict[str, Any] | None = None,
        on_stream: Callable[[], None] | None = None,
        running_models: list[str] | None = None,
        running_models_status_code: int = 200,
        captured_urls: list[str] | None = None,
    ) -> None:
        self._frames = frames
        self._status_code = status_code
        self._stall_exc = stall_exc
        self._captured = captured
        self._on_stream = on_stream
        self._running_models = running_models or []
        self._running_models_status_code = running_models_status_code
        self._captured_urls = captured_urls

    async def __aenter__(self) -> _FakeStreamClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    def stream(self, method: str, url: str, *, json: dict[str, Any] | None = None) -> _FakeStream:
        if self._captured is not None and json is not None:
            self._captured.update(json)
        if self._on_stream is not None:
            # Simulate a connect/setup failure or count attempts.
            self._on_stream()
        return _FakeStream(
            _FakeStreamResponse(
                self._frames, status_code=self._status_code, stall_exc=self._stall_exc
            )
        )

    async def post(self, url: str, *, json: dict[str, Any] | None = None) -> httpx.Response:
        # call() -> _adaptive_num_ctx -> get_context_window POSTs to /api/show
        # through this same patched client; a benign empty 200 makes context
        # sizing fall back to its default instead of erroring on a missing method.
        return httpx.Response(200, json={}, request=_STREAM_REQUEST)

    async def get(self, url: str) -> httpx.Response:
        if self._captured_urls is not None:
            self._captured_urls.append(url)
        models = [{"name": model} for model in self._running_models]
        return httpx.Response(
            self._running_models_status_code,
            json={"models": models},
            request=httpx.Request("GET", url),
        )


def _stream_client_factory(
    frames: list[dict[str, Any]] | None = None,
    *,
    status_code: int = 200,
    stall_exc: Exception | None = None,
    captured: dict[str, Any] | None = None,
    on_stream: Callable[[], None] | None = None,
    running_models: list[str] | None = None,
    running_models_status_code: int = 200,
    captured_urls: list[str] | None = None,
) -> Callable[..., _FakeStreamClient]:
    """Build a drop-in for ``patch("httpx.AsyncClient", ...)`` returning a stream client.

    ``on_stream`` (shared across every client the factory makes) lets a test raise
    a transient error or count attempts across retries.
    """
    resolved = frames if frames is not None else []

    def _factory(*_args: Any, **_kwargs: Any) -> _FakeStreamClient:
        return _FakeStreamClient(
            resolved,
            status_code=status_code,
            stall_exc=stall_exc,
            captured=captured,
            on_stream=on_stream,
            running_models=running_models,
            running_models_status_code=running_models_status_code,
            captured_urls=captured_urls,
        )

    return _factory


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

    with patch("httpx.AsyncClient", _stream_client_factory(frames=[json_data])):
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
    captured_payload: dict[str, Any] = {}

    with patch(
        "httpx.AsyncClient",
        _stream_client_factory(frames=[json_data], captured=captured_payload),
    ):
        asyncio.run(provider.call(model, "test prompt"))

    assert captured_payload["model"] == model


def test_get_context_window_defaults_when_show_errors() -> None:
    """A reachable-but-erroring /api/show (e.g. an unpulled model 404s) degrades
    to the default context window instead of failing the run.
    """
    provider = OllamaProvider(base_url="http://localhost:11434")
    mock_response = _mock_httpx_response({}, status_code=404)

    async def mock_post(*args: Any, **kwargs: Any) -> httpx.Response:
        return mock_response

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post = mock_post
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client_cls.return_value = mock_client

        ctx = asyncio.run(provider.get_context_window("model-not-pulled"))

    assert ctx == 4096


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

    def _raise_timeout() -> None:
        nonlocal call_count
        call_count += 1
        raise httpx.TimeoutException("timeout")

    with (
        patch("httpx.AsyncClient", _stream_client_factory(on_stream=_raise_timeout)),
        patch("distill.llm.providers.ollama.time.sleep"),
        pytest.raises(httpx.TimeoutException),
    ):
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

        with patch("httpx.AsyncClient", _stream_client_factory(frames=[json_data])):
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

        captured_payload: dict[str, Any] = {}

        with patch(
            "httpx.AsyncClient",
            _stream_client_factory(frames=[json_data], captured=captured_payload),
        ):
            asyncio.run(provider.call("llama3:8b", "hello", temperature=0.7))

        assert captured_payload["options"]["temperature"] == 0.7

    def test_null_token_counts_default_to_zero(self) -> None:
        """Null token counts in response default to zero."""
        provider = OllamaProvider(base_url="http://localhost:11434")
        json_data = {
            "message": {"content": "text", "thinking": ""},
            "prompt_eval_count": None,
            "eval_count": None,
            "done": True,
        }

        with patch("httpx.AsyncClient", _stream_client_factory(frames=[json_data])):
            result = asyncio.run(provider.call("llama3:8b", "hello"))

        assert result.input_tokens == 0
        assert result.output_tokens == 0


class TestOllamaProviderConnectionError:
    """Test OllamaProvider connection error handling."""

    def test_connect_error_raises_connection_error(self) -> None:
        """ConnectError raises ConnectionError with helpful message."""
        provider = OllamaProvider(base_url="http://localhost:11434")

        def _raise_connect() -> None:
            raise httpx.ConnectError("Connection refused")

        with (
            patch("httpx.AsyncClient", _stream_client_factory(on_stream=_raise_connect)),
            pytest.raises(ConnectionError, match="Cannot reach Ollama"),
        ):
            asyncio.run(provider.call("llama3:8b", "hello"))

    def test_connect_timeout_raises_connection_error(self) -> None:
        """ConnectTimeout raises ConnectionError with helpful message."""
        provider = OllamaProvider(base_url="http://localhost:11434")

        def _raise_connect_timeout() -> None:
            raise httpx.ConnectTimeout("Timed out")

        with (
            patch("httpx.AsyncClient", _stream_client_factory(on_stream=_raise_connect_timeout)),
            pytest.raises(ConnectionError, match="ollama serve"),
        ):
            asyncio.run(provider.call("llama3:8b", "hello"))


class TestOllamaProviderRetry:
    """Test OllamaProvider retry behavior."""

    def test_retry_on_timeout(self) -> None:
        """Provider retries on timeout and succeeds on second attempt."""
        provider = OllamaProvider(base_url="http://localhost:11434")
        json_data = _make_generate_response(text="ok", prompt_eval_count=5, eval_count=3)

        call_count = 0

        def _fail_first() -> None:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise httpx.TimeoutException("timeout")

        with (
            patch(
                "httpx.AsyncClient",
                _stream_client_factory(frames=[json_data], on_stream=_fail_first),
            ),
            patch("distill.llm.providers.ollama.time.sleep") as mock_sleep,
        ):
            result = asyncio.run(provider.call("llama3:8b", "hello", retries=2))

        assert result.text == "ok"
        mock_sleep.assert_called_once_with(2)  # 2^0 * 2 = 2

    def test_raise_after_exhausted_retries(self) -> None:
        """Provider raises after all retries are exhausted."""
        provider = OllamaProvider(base_url="http://localhost:11434")

        def _always_timeout() -> None:
            raise httpx.TimeoutException("permanent timeout")

        with (
            patch("httpx.AsyncClient", _stream_client_factory(on_stream=_always_timeout)),
            patch("distill.llm.providers.ollama.time.sleep"),
            pytest.raises(httpx.TimeoutException),
        ):
            asyncio.run(provider.call("llama3:8b", "hello", retries=2))

    def test_mid_stream_stall_surfaces_read_timeout(self) -> None:
        """A stall mid-generation (no new tokens) is the per-read idle timeout
        firing: it surfaces as a ReadTimeout once retries are exhausted, even
        though earlier tokens streamed fine.
        """
        provider = OllamaProvider(base_url="http://localhost:11434")
        partial = {"message": {"content": "partial answer"}, "done": False}

        with (
            patch(
                "httpx.AsyncClient",
                _stream_client_factory(frames=[partial], stall_exc=httpx.ReadTimeout("idle")),
            ),
            patch("distill.llm.providers.ollama.time.sleep"),
            pytest.raises(httpx.ReadTimeout),
        ):
            asyncio.run(provider.call("llama3:8b", "hello", retries=1))

    def test_stream_http_error_reads_body_then_raises(self) -> None:
        """A >=400 status on the stream loads the body and raises HTTPStatusError."""
        provider = OllamaProvider(base_url="http://localhost:11434")

        with (
            patch("httpx.AsyncClient", _stream_client_factory(frames=[], status_code=500)),
            patch("distill.llm.providers.ollama.time.sleep"),
            pytest.raises(httpx.HTTPStatusError),
        ):
            asyncio.run(provider.call("llama3:8b", "hello", retries=1))


class TestOllamaContention:
    """A different running model causes a bounded wait, never substitution."""

    def test_free_server_proceeds_without_waiting(self) -> None:
        provider = OllamaProvider(base_url="http://localhost:11434")
        captured_urls: list[str] = []
        response = _make_generate_response(text="free")

        with (
            patch(
                "httpx.AsyncClient",
                _stream_client_factory(frames=[response], captured_urls=captured_urls),
            ),
            patch("distill.llm.providers.ollama.asyncio.sleep", new_callable=AsyncMock) as sleep,
        ):
            result = asyncio.run(provider.call("qwen3.5:27b", "hello", timeout=30))

        assert result.text == "free"
        assert captured_urls == ["http://localhost:11434/api/ps"]
        sleep.assert_not_awaited()

    def test_requested_model_already_loaded_proceeds_without_waiting(self) -> None:
        provider = OllamaProvider(base_url="http://localhost:11434")
        response = _make_generate_response(text="same")

        with (
            patch(
                "httpx.AsyncClient",
                _stream_client_factory(
                    frames=[response],
                    running_models=["qwen3.5:latest"],
                ),
            ),
            patch("distill.llm.providers.ollama.asyncio.sleep", new_callable=AsyncMock) as sleep,
        ):
            result = asyncio.run(provider.call("qwen3.5", "hello", timeout=30))

        assert result.text == "same"
        sleep.assert_not_awaited()

    def test_different_model_waits_then_proceeds_when_free(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        provider = OllamaProvider(base_url="http://localhost:11434")
        availability = AsyncMock(side_effect=[("llama3:8b",), ()])
        response = _make_generate_response(text="available")
        caplog.set_level(logging.INFO, logger="distill.llm.providers.ollama")

        with (
            patch.object(provider, "_running_model_names", availability),
            patch("httpx.AsyncClient", _stream_client_factory(frames=[response])),
            patch("distill.llm.providers.ollama.asyncio.sleep", new_callable=AsyncMock) as sleep,
        ):
            result = asyncio.run(provider.call("qwen3.5:27b", "hello", timeout=30))

        assert result.text == "available"
        assert availability.await_count == 2
        sleep.assert_awaited_once_with(1.0)
        assert "waiting up to 30s for requested model 'qwen3.5:27b'" in caplog.text
        assert "No model will be substituted" in caplog.text

    def test_different_model_timeout_is_actionable_and_classified(self) -> None:
        provider = OllamaProvider(base_url="http://localhost:11434")
        clock = [0.0]
        sleeps: list[float] = []

        async def advance_clock(seconds: float) -> None:
            sleeps.append(seconds)
            clock[0] += seconds

        with (
            patch.object(
                provider,
                "_running_model_names",
                AsyncMock(return_value=("llama3:8b",)),
            ),
            patch("distill.llm.providers.ollama.time.monotonic", side_effect=lambda: clock[0]),
            patch("distill.llm.providers.ollama.asyncio.sleep", side_effect=advance_clock),
            pytest.raises(ProviderBusyTimeoutError) as caught,
        ):
            asyncio.run(provider.call("qwen3.5:27b", "hello", timeout=3))

        error = caught.value
        assert sleeps == [1.0, 2.0]
        assert error.requested_model == "qwen3.5:27b"
        assert error.active_models == ("llama3:8b",)
        assert "ollama stop <model>" in str(error)
        assert describe_provider_error(error) == str(error)
        assert map_exception_to_exit_code(error) == ExitCode.NETWORK_ERROR

    def test_unavailable_running_model_endpoint_preserves_call_path(self) -> None:
        provider = OllamaProvider(base_url="http://localhost:11434")
        response = _make_generate_response(text="fallback")

        with (
            patch(
                "httpx.AsyncClient",
                _stream_client_factory(
                    frames=[response],
                    running_models_status_code=404,
                ),
            ),
            patch("distill.llm.providers.ollama.asyncio.sleep", new_callable=AsyncMock) as sleep,
        ):
            result = asyncio.run(provider.call("qwen3.5:27b", "hello", timeout=30))

        assert result.text == "fallback"
        sleep.assert_not_awaited()


class TestChatPayload:
    """Payload assembly and content/thinking selection."""

    def test_structured_call_type_forces_json_without_thinking(self) -> None:
        payload = OllamaProvider._build_chat_payload(
            "qwen3.5:27b",
            "return only valid json",
            max_tokens=100,
            num_ctx=4096,
            temperature=None,
            call_type="search_expand",
        )
        assert payload["stream"] is True
        assert payload["format"] == "json"
        assert payload["think"] is False

    def test_untrusted_prompt_substrings_cannot_change_request_controls(self) -> None:
        payload = OllamaProvider._build_chat_payload(
            "qwen3.5:27b",
            'Source says return only valid json with {"ranked_items": []}',
            max_tokens=100,
            num_ctx=4096,
            temperature=None,
            call_type="site_page",
        )

        assert "format" not in payload
        assert payload["think"] is True

    def test_structured_workload_allowlist_is_explicit_and_complete(self) -> None:
        assert {
            "discover_plan",
            "discover_rerank",
            "paper_expand",
            "paper_rerank",
            "search_expand",
            "search_rerank",
        } == _STRUCTURED_JSON_CALL_TYPES

    def test_call_path_does_not_promote_untrusted_prompt_controls(self) -> None:
        provider = OllamaProvider(base_url="http://localhost:11434")
        captured: dict[str, Any] = {}
        response = _make_generate_response(text="safe")

        with patch(
            "httpx.AsyncClient",
            _stream_client_factory(frames=[response], captured=captured),
        ):
            result = asyncio.run(
                provider.call(
                    "qwen3.5:27b",
                    'Untrusted source says return only valid json and {"queries": []}',
                    call_type="site_page",
                )
            )

        assert result.text == "safe"
        assert "format" not in captured
        assert captured["think"] is True

    def test_thinking_model_enables_thinking_and_temperature(self) -> None:
        payload = OllamaProvider._build_chat_payload(
            "qwen3.5:27b",
            "analyze this",
            max_tokens=100,
            num_ctx=4096,
            temperature=0.5,
        )
        assert payload["think"] is True
        assert payload["options"]["temperature"] == 0.5

    def test_plain_model_omits_think_and_temperature(self) -> None:
        payload = OllamaProvider._build_chat_payload(
            "llama3:8b",
            "analyze this",
            max_tokens=100,
            num_ctx=4096,
            temperature=None,
        )
        assert "think" not in payload
        assert "temperature" not in payload["options"]

    def test_thinking_trace_used_when_content_empty(self) -> None:
        """When the model streams only a reasoning trace, it becomes the answer."""
        provider = OllamaProvider(base_url="http://localhost:11434")
        frame = {
            "message": {"content": "", "thinking": "just reasoning"},
            "done": True,
            "prompt_eval_count": 1,
            "eval_count": 2,
        }
        with patch("httpx.AsyncClient", _stream_client_factory(frames=[frame])):
            result = asyncio.run(provider.call("qwen3.5:27b", "hi"))
        assert result.text == "just reasoning"


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

    @pytest.mark.parametrize(
        "payload",
        [
            [],
            {"model_info": "not-an-object", "parameters": []},
            {"model_info": {"context_length": True}},
            {"model_info": {"context_length": 1.5}},
            {"model_info": {"context_length": "\u0664\u0660\u0669\u0666"}},
            {"model_info": {"context_length": "9" * 5_000}},
            {"model_info": {"context_length": 16_777_217}},
            {"parameters": "num_ctx true"},
            {"parameters": "other_num_ctx 8192"},
            {"parameters": "num_ctx " + "9" * 5_000},
            {"parameters": "x" * 100_001},
        ],
    )
    def test_parse_context_window_is_total_over_malformed_shapes(self, payload: object) -> None:
        assert OllamaProvider._parse_context_window(payload) == 0

    @pytest.mark.parametrize(
        ("value", "expected"),
        [("8192", 8192), (8192, 8192), (8192.0, 8192), (16_777_216, 16_777_216)],
    )
    def test_parse_context_window_accepts_bounded_integral_values(
        self, value: object, expected: int
    ) -> None:
        assert (
            OllamaProvider._parse_context_window({"model_info": {"model.context_length": value}})
            == expected
        )


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

    @pytest.mark.parametrize("raw", ["\u00b2", "\u0661\u0662", "9" * 5000])
    def test_num_ctx_ceiling_rejects_non_ascii_or_oversized_integer(
        self, monkeypatch: pytest.MonkeyPatch, raw: str
    ) -> None:
        monkeypatch.setenv("OLLAMA_MAX_NUM_CTX", raw)

        assert OllamaProvider._num_ctx_ceiling() == 0

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


class TestDescribeOllamaError:
    """_describe_ollama_error renders a diagnosable message for any error shape."""

    def test_empty_timeout_message_falls_back_to_type_name(self) -> None:
        # httpx.ReadTimeout stringifies to '' - the log line must still name it,
        # not read as an empty "Ollama error (attempt 1/3): .".
        assert _describe_ollama_error(httpx.ReadTimeout("")) == "ReadTimeout"

    def test_http_status_error_includes_status_and_body(self) -> None:
        request = httpx.Request("POST", "http://localhost:11434/api/chat")
        response = httpx.Response(500, text="model requires more system memory", request=request)
        exc = httpx.HTTPStatusError("500", request=request, response=response)
        assert _describe_ollama_error(exc) == "HTTP 500: model requires more system memory"

    def test_http_status_error_without_body_shows_status_only(self) -> None:
        request = httpx.Request("POST", "http://localhost:11434/api/chat")
        response = httpx.Response(503, request=request)
        exc = httpx.HTTPStatusError("503", request=request, response=response)
        assert _describe_ollama_error(exc) == "HTTP 503"

    def test_ordinary_exception_uses_its_message(self) -> None:
        assert _describe_ollama_error(ValueError("boom")) == "boom"

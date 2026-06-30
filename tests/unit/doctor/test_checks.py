"""Focused doctor check boundary tests."""

from __future__ import annotations

import asyncio
import sys
import types
from typing import Any

import pytest

from distill.config import DistillConfig
from distill.doctor import checks
from distill.llm.router import RETIRED_MODELS, RETIREMENT_DATE


def test_check_retired_models_reports_exact_field_and_replacement() -> None:
    retired, replacement = next(iter(RETIRED_MODELS.items()))
    config = DistillConfig(xai_analysis_model=retired)

    warnings = checks.check_retired_models(config)

    assert warnings == [
        (
            f"xai_analysis_model uses retired model '{retired}' "
            f"(retiring {RETIREMENT_DATE}); replace with '{replacement}'"
        )
    ]


def test_doctor_validate_key_rejects_unknown_provider() -> None:
    with pytest.raises(ValueError, match="unknown provider: unknown"):
        checks.doctor_validate_key("unknown", DistillConfig())


def test_doctor_validate_xai_key_success_uses_configured_analysis_model(monkeypatch) -> None:
    calls: list[dict[str, Any]] = []

    class _Completions:
        @staticmethod
        def create(**kwargs) -> object:
            calls.append(kwargs)
            return object()

    class _OpenAI:
        def __init__(self, *, api_key: str, base_url: str | None = None) -> None:
            self.api_key = api_key
            self.base_url = base_url
            self.chat = types.SimpleNamespace(completions=_Completions())

    monkeypatch.setitem(sys.modules, "openai", types.SimpleNamespace(OpenAI=_OpenAI))

    status, detail = checks.doctor_validate_key(
        "xai",
        DistillConfig(xai_api_key="test-key", xai_analysis_model="grok-4.3"),
    )

    assert (status, detail) == ("ok", "grok-4.3")
    assert calls[0]["model"] == "grok-4.3"
    assert calls[0]["max_completion_tokens"] == 5


def test_doctor_validate_gemini_key_success(monkeypatch) -> None:
    class _Models:
        @staticmethod
        def generate_content(*, model: str, contents: str) -> object:
            assert model == "gemini-3.5-flash"
            assert contents == "hi"
            return object()

    class _Client:
        def __init__(self, *, api_key: str) -> None:
            self.api_key = api_key
            self.models = _Models()

    monkeypatch.setitem(
        sys.modules,
        "google",
        types.SimpleNamespace(genai=types.SimpleNamespace(Client=_Client)),
    )

    assert checks.doctor_validate_key(
        "gemini",
        DistillConfig(gemini_api_key="test-key"),
    ) == ("ok", "Deep Research")


def test_doctor_validate_gemini_key_auth_rejection(monkeypatch) -> None:
    class _AuthError(Exception):
        code = 403

    class _Models:
        @staticmethod
        def generate_content(*, model: str, contents: str) -> object:
            raise _AuthError("forbidden")

    class _Client:
        def __init__(self, *, api_key: str) -> None:
            self.api_key = api_key
            self.models = _Models()

    monkeypatch.setitem(
        sys.modules,
        "google",
        types.SimpleNamespace(genai=types.SimpleNamespace(Client=_Client)),
    )

    status, detail = checks.doctor_validate_key(
        "gemini",
        DistillConfig(gemini_api_key="test-key"),
    )

    assert status == "invalid"
    assert detail == "forbidden"


def test_doctor_validate_openai_key_success(monkeypatch) -> None:
    calls: list[dict[str, Any]] = []

    class _Completions:
        @staticmethod
        def create(**kwargs) -> object:
            calls.append(kwargs)
            return object()

    class _OpenAI:
        def __init__(self, *, api_key: str, base_url: str | None = None) -> None:
            self.api_key = api_key
            self.base_url = base_url
            self.chat = types.SimpleNamespace(completions=_Completions())

    monkeypatch.setitem(sys.modules, "openai", types.SimpleNamespace(OpenAI=_OpenAI))

    status, detail = checks.doctor_validate_key(
        "openai",
        DistillConfig(openai_api_key="test-key"),
    )

    assert (status, detail) == ("ok", "optional")
    assert calls[0]["model"] == "gpt-4o-mini"
    assert calls[0]["max_tokens"] == 5


def test_check_ollama_status_uses_running_loop_fallback(monkeypatch) -> None:
    class _Loop:
        @staticmethod
        def run_until_complete(coroutine) -> list[dict[str, str]]:
            coroutine.close()
            return [{"name": "qwen3.5:27b"}, {"name": ""}, {}]

    class _Provider:
        @staticmethod
        async def list_models() -> list[dict[str, str]]:
            return [{"name": "unused"}]

    def _raise_runtime(coroutine):
        coroutine.close()
        raise RuntimeError("loop already running")

    monkeypatch.setitem(
        sys.modules,
        "distill.llm.providers.ollama",
        types.SimpleNamespace(OllamaProvider=lambda: _Provider()),
    )
    monkeypatch.setattr(asyncio, "run", _raise_runtime)
    monkeypatch.setattr(asyncio, "get_event_loop", lambda: _Loop())

    assert checks.check_ollama_status() == ("running", ["qwen3.5:27b"])


def test_check_ollama_status_unavailable_on_provider_error(monkeypatch) -> None:
    class _Provider:
        @staticmethod
        async def list_models() -> list[dict[str, str]]:
            raise ConnectionError("offline")

    monkeypatch.setitem(
        sys.modules,
        "distill.llm.providers.ollama",
        types.SimpleNamespace(OllamaProvider=lambda: _Provider()),
    )

    assert checks.check_ollama_status() == ("unavailable", [])


def test_check_lmstudio_status_running_and_unavailable(monkeypatch) -> None:
    class _Response:
        status_code = 200

    class _Client:
        def __init__(self, *, timeout: int) -> None:
            self.timeout = timeout

        def __enter__(self) -> _Client:
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        @staticmethod
        def get(url: str) -> _Response:
            assert url == "http://lmstudio.test/v1/models"
            return _Response()

    monkeypatch.setenv("LMSTUDIO_BASE_URL", "http://lmstudio.test/v1")
    monkeypatch.setitem(sys.modules, "httpx", types.SimpleNamespace(Client=_Client))

    assert checks.check_lmstudio_status() == "running"

    class _UnavailableResponse:
        status_code = 500

    class _UnavailableClient(_Client):
        @staticmethod
        def get(url: str) -> _UnavailableResponse:
            return _UnavailableResponse()

    monkeypatch.setitem(sys.modules, "httpx", types.SimpleNamespace(Client=_UnavailableClient))

    assert checks.check_lmstudio_status() == "unavailable"

    class _FailingClient(_Client):
        @staticmethod
        def get(url: str) -> _Response:
            raise OSError("offline")

    monkeypatch.setitem(sys.modules, "httpx", types.SimpleNamespace(Client=_FailingClient))

    assert checks.check_lmstudio_status() == "unavailable"

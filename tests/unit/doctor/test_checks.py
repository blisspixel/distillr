"""Focused doctor check boundary tests."""

from __future__ import annotations

import asyncio
import sys
import types
from pathlib import Path
from typing import Any

import pytest

from distill.config import DistillConfig
from distill.doctor import checks
from distill.llm.router import RETIRED_MODELS, RETIREMENT_DATE
from distill.pipeline.costs import CostTracker


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

    with pytest.raises(ValueError, match="unknown provider: unknown"):
        checks.doctor_validate_key("unknown", DistillConfig(), live=False)


def test_nested_doctor_key_sessions_reuse_the_outer_tracker(tmp_path: Path) -> None:
    config = DistillConfig(distill_output_dir=tmp_path)

    with (
        checks.doctor_key_validation_session(config) as outer,
        checks.doctor_key_validation_session(config) as inner,
    ):
        assert inner is outer


def test_no_metered_skips_live_key_validation_before_client_or_network_work(
    monkeypatch,
) -> None:
    calls: list[str] = []

    class _ForbiddenClient:
        def __init__(self, *args, **kwargs) -> None:
            del args, kwargs
            calls.append("client")
            raise AssertionError("provider client must not be constructed")

    def _forbidden_post(*args, **kwargs) -> None:
        del args, kwargs
        calls.append("post")
        raise AssertionError("provider network must not be called")

    monkeypatch.setitem(sys.modules, "openai", types.SimpleNamespace(OpenAI=_ForbiddenClient))
    monkeypatch.setitem(
        sys.modules,
        "google",
        types.SimpleNamespace(genai=types.SimpleNamespace(Client=_ForbiddenClient)),
    )
    monkeypatch.setitem(sys.modules, "httpx", types.SimpleNamespace(post=_forbidden_post))

    config = DistillConfig(
        xai_api_key="xai-key",
        gemini_api_key="gemini-key",
        anthropic_api_key="anthropic-key",
        openai_api_key="openai-key",
        distill_cost_mode="no-metered",
    )

    for provider in ("xai", "gemini", "anthropic", "openai"):
        status, detail = checks.doctor_validate_key(provider, config)
        assert status == "skipped"
        assert "Route blocked by no-metered cost policy" in detail
        assert provider in detail

    assert calls == []


def test_no_metered_preserves_missing_key_status_without_live_validation() -> None:
    config = DistillConfig(
        xai_api_key="",
        gemini_api_key="",
        anthropic_api_key="",
        openai_api_key="",
        distill_cost_mode="no-metered",
    )

    assert checks.doctor_validate_key("xai", config) == ("missing", "")
    for provider in ("gemini", "anthropic", "openai"):
        assert checks.doctor_validate_key(provider, config) == ("not_set", "")


def test_doctor_validate_xai_key_success_uses_configured_analysis_model(
    monkeypatch,
    tmp_path: Path,
) -> None:
    calls: list[dict[str, Any]] = []
    saves: list[tuple[Path, str, CostTracker]] = []

    class _Completions:
        @staticmethod
        def create(**kwargs) -> object:
            calls.append(kwargs)
            return types.SimpleNamespace(
                usage=types.SimpleNamespace(prompt_tokens=2, completion_tokens=1),
            )

    class _OpenAI:
        def __init__(self, *, api_key: str, base_url: str | None = None) -> None:
            self.api_key = api_key
            self.base_url = base_url
            self.chat = types.SimpleNamespace(completions=_Completions())

    monkeypatch.setitem(sys.modules, "openai", types.SimpleNamespace(OpenAI=_OpenAI))
    monkeypatch.setattr(
        checks,
        "save_run_log",
        lambda directory, command, tracker, **_kwargs: saves.append((directory, command, tracker)),
    )

    status, detail = checks.doctor_validate_key(
        "xai",
        DistillConfig(
            xai_api_key="test-key",
            xai_analysis_model="grok-4.3",
            distill_output_dir=tmp_path,
        ),
    )

    assert (status, detail) == ("ok", "grok-4.3")
    assert calls[0]["model"] == "grok-4.3"
    assert calls[0]["max_completion_tokens"] == 5
    assert [(directory, command) for directory, command, _tracker in saves] == [
        (tmp_path, "doctor")
    ]
    assert saves[0][2].entries[0].prompt_tokens == 2
    assert saves[0][2].entries[0].completion_tokens == 1
    assert saves[0][2].entries[0].usage_source == "reported"


def test_doctor_key_probe_budget_refuses_before_provider_contact(
    monkeypatch,
    tmp_path: Path,
) -> None:
    class _ForbiddenClient:
        def __init__(self, *args, **kwargs) -> None:
            del args, kwargs
            raise AssertionError("budget refusal must happen before client construction")

    monkeypatch.setitem(sys.modules, "openai", types.SimpleNamespace(OpenAI=_ForbiddenClient))

    status, detail = checks.doctor_validate_key(
        "xai",
        DistillConfig(
            xai_api_key="test-key",
            xai_analysis_model="grok-4.3",
            distill_output_dir=tmp_path,
            distill_cost_workflow_budgets="doctor=0.000001",
        ),
    )

    assert status == "skipped"
    assert "projected" in detail.lower()


@pytest.mark.parametrize(
    ("provider", "key_field"),
    (
        ("gemini", "gemini_api_key"),
        ("anthropic", "anthropic_api_key"),
        ("openai", "openai_api_key"),
    ),
)
def test_each_optional_doctor_probe_honors_workflow_budget_before_contact(
    provider: str,
    key_field: str,
    tmp_path: Path,
) -> None:
    config = DistillConfig(
        **{
            key_field: "test-key",
            "distill_output_dir": tmp_path,
            "distill_cost_workflow_budgets": "doctor=0.000001",
        }
    )

    status, detail = checks.doctor_validate_key(provider, config)

    assert status == "skipped"
    assert "projected" in detail.lower()


def test_doctor_key_validation_session_persists_failures_once(
    monkeypatch,
    tmp_path: Path,
) -> None:
    saves: list[CostTracker] = []

    class _NetworkError(Exception):
        """Synthetic transport failure raised by the local test double."""

    class _Completions:
        @staticmethod
        def create(**_kwargs) -> object:
            raise _NetworkError("offline")

    class _OpenAI:
        def __init__(self, **_kwargs) -> None:
            self.chat = types.SimpleNamespace(completions=_Completions())

    monkeypatch.setitem(sys.modules, "openai", types.SimpleNamespace(OpenAI=_OpenAI))
    monkeypatch.setattr(
        checks,
        "save_run_log",
        lambda _directory, _command, tracker, **_kwargs: saves.append(tracker),
    )
    config = DistillConfig(
        xai_api_key="test-key",
        openai_api_key="test-key",
        distill_output_dir=tmp_path,
    )

    with checks.doctor_key_validation_session(config):
        assert checks.doctor_validate_key("xai", config)[0] == "unknown"
        assert checks.doctor_validate_key("openai", config)[0] == "unknown"

    assert len(saves) == 1
    assert len(saves[0].entries) == 2
    assert {entry.provider_name for entry in saves[0].entries} == {"xai", "openai"}
    assert {entry.outcome for entry in saves[0].entries} == {"error"}
    assert {entry.usage_source for entry in saves[0].entries} == {"conservative"}


@pytest.mark.parametrize("provider", ("xai", "gemini", "anthropic", "openai"))
def test_doctor_probe_preserves_process_interruptions(
    provider: str,
    monkeypatch,
) -> None:
    class _Completions:
        @staticmethod
        def create(**_kwargs) -> object:
            raise KeyboardInterrupt

    class _OpenAI:
        def __init__(self, **_kwargs) -> None:
            self.chat = types.SimpleNamespace(completions=_Completions())

    class _Models:
        @staticmethod
        def generate_content(**_kwargs) -> object:
            raise KeyboardInterrupt

    class _Gemini:
        def __init__(self, **_kwargs) -> None:
            self.models = _Models()

    monkeypatch.setitem(sys.modules, "openai", types.SimpleNamespace(OpenAI=_OpenAI))
    monkeypatch.setitem(
        sys.modules,
        "google",
        types.SimpleNamespace(genai=types.SimpleNamespace(Client=_Gemini)),
    )
    monkeypatch.setitem(
        sys.modules,
        "httpx",
        types.SimpleNamespace(
            post=lambda *_args, **_kwargs: (_ for _ in ()).throw(KeyboardInterrupt)
        ),
    )
    config = DistillConfig(
        xai_api_key="test-key",
        gemini_api_key="test-key",
        anthropic_api_key="test-key",
        openai_api_key="test-key",
    )
    tracker = CostTracker()

    with pytest.raises(KeyboardInterrupt):
        checks._doctor_validate_key(provider, config, tracker)

    assert len(tracker.entries) == 1
    assert tracker.entries[0].error_type == "KeyboardInterrupt"


@pytest.mark.parametrize(
    "response",
    (
        types.SimpleNamespace(json=lambda: (_ for _ in ()).throw(ValueError("bad json"))),
        types.SimpleNamespace(json=lambda: []),
        types.SimpleNamespace(json=lambda: {"usage": "malformed"}),
    ),
)
def test_anthropic_probe_counts_reject_malformed_payloads(response: object) -> None:
    assert checks._anthropic_probe_counts(response) == (None, None)


def test_doctor_validate_gemini_key_success(monkeypatch, tmp_path: Path) -> None:
    calls: list[dict[str, object]] = []

    class _Models:
        @staticmethod
        def generate_content(*, model: str, contents: str, config: object) -> object:
            assert model == "gemini-3.5-flash"
            assert contents == "hi"
            calls.append({"config": config})
            return types.SimpleNamespace(
                usage_metadata=types.SimpleNamespace(
                    prompt_token_count=2,
                    candidates_token_count=1,
                ),
            )

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
        DistillConfig(gemini_api_key="test-key", distill_output_dir=tmp_path),
    ) == ("ok", "Deep Research")
    assert calls == [{"config": {"max_output_tokens": 5}}]


def test_doctor_validate_gemini_key_auth_rejection(monkeypatch, tmp_path: Path) -> None:
    class _AuthError(Exception):
        code = 403

    class _Models:
        @staticmethod
        def generate_content(*, model: str, contents: str, config: object) -> object:
            del model, contents, config
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
        DistillConfig(gemini_api_key="test-key", distill_output_dir=tmp_path),
    )

    assert status == "invalid"
    assert detail == "forbidden"


def test_doctor_validate_anthropic_key_success(monkeypatch, tmp_path: Path) -> None:
    calls: list[dict[str, object]] = []

    class _Response:
        @staticmethod
        def raise_for_status() -> None:
            return None

        @staticmethod
        def json() -> dict[str, object]:
            return {"usage": {"input_tokens": 2, "output_tokens": 1}}

    def _post(url: str, **kwargs) -> _Response:
        kwargs["url"] = url
        calls.append(kwargs)
        return _Response()

    monkeypatch.setitem(sys.modules, "httpx", types.SimpleNamespace(post=_post))

    status, detail = checks.doctor_validate_key(
        "anthropic",
        DistillConfig(anthropic_api_key="test-key", distill_output_dir=tmp_path),
    )

    assert (status, detail) == ("ok", "claude-sonnet-5")
    assert calls[0]["headers"] == {
        "x-api-key": "test-key",
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    assert calls[0]["json"] == {
        "model": "claude-sonnet-5",
        "max_tokens": 1,
        "messages": [{"role": "user", "content": "hi"}],
        "output_config": {"effort": "low"},
    }


def test_doctor_validate_anthropic_key_auth_rejection(monkeypatch, tmp_path: Path) -> None:
    class _AuthError(Exception):
        def __init__(self) -> None:
            self.response = types.SimpleNamespace(status_code=401)
            super().__init__("unauthorized")

    class _Response:
        @staticmethod
        def raise_for_status() -> None:
            raise _AuthError()

    monkeypatch.setitem(
        sys.modules,
        "httpx",
        types.SimpleNamespace(post=lambda *_args, **_kw: _Response()),
    )

    status, detail = checks.doctor_validate_key(
        "anthropic",
        DistillConfig(anthropic_api_key="test-key", distill_output_dir=tmp_path),
    )

    assert status == "invalid"
    assert detail == "unauthorized"


def test_doctor_validate_openai_key_success(monkeypatch, tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []

    class _Completions:
        @staticmethod
        def create(**kwargs) -> object:
            calls.append(kwargs)
            return types.SimpleNamespace(
                usage=types.SimpleNamespace(prompt_tokens=2, completion_tokens=1),
            )

    class _OpenAI:
        def __init__(self, *, api_key: str, base_url: str | None = None) -> None:
            self.api_key = api_key
            self.base_url = base_url
            self.chat = types.SimpleNamespace(completions=_Completions())

    monkeypatch.setitem(sys.modules, "openai", types.SimpleNamespace(OpenAI=_OpenAI))

    status, detail = checks.doctor_validate_key(
        "openai",
        DistillConfig(openai_api_key="test-key", distill_output_dir=tmp_path),
    )

    assert (status, detail) == ("ok", "optional")
    assert calls[0]["model"] == "gpt-4.1-mini"
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

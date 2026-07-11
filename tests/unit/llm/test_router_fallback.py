"""Tests for the opt-in local fallback in distill.llm.router.call."""

from __future__ import annotations

import pytest

from distill.llm import router
from distill.llm.cost_policy import CostPolicyError
from distill.llm.errors import ProviderBusyTimeoutError
from distill.llm.router import LLM_Response, RouterConfig, _fallback_target


class _CreditError(Exception):
    def __init__(self) -> None:
        super().__init__("used all available credits")
        self.status_code = 403


class _FakeProvider:
    """Async provider stub: either raises or returns a fixed response."""

    def __init__(self, *, fail: bool, label: str) -> None:
        self.fail = fail
        self.label = label

    async def call(self, model_id, prompt, **kwargs):
        if self.fail:
            raise _CreditError()
        return LLM_Response(
            text=f"{self.label}:{model_id}", input_tokens=1, output_tokens=2, model=model_id
        )


def _config(tmp_path, **kw) -> RouterConfig:
    return RouterConfig(xai_api_key="k", ops_dir=str(tmp_path), **kw)


def test_fallback_target_requires_both_provider_and_model(tmp_path):
    exc = _CreditError()
    assert _fallback_target(_config(tmp_path), "xai", exc) is None
    assert _fallback_target(_config(tmp_path, fallback_provider="ollama"), "xai", exc) is None
    cfg = _config(tmp_path, fallback_provider="ollama", fallback_model="m")
    assert _fallback_target(cfg, "xai", exc) == ("ollama", "m")


def test_fallback_target_skips_non_credit_errors(tmp_path):
    cfg = _config(tmp_path, fallback_provider="ollama", fallback_model="m")
    assert _fallback_target(cfg, "xai", ValueError("bug")) is None


def test_fallback_target_skips_same_provider(tmp_path):
    cfg = _config(tmp_path, fallback_provider="xai", fallback_model="m")
    assert _fallback_target(cfg, "xai", _CreditError()) is None


def test_call_falls_back_to_local_on_credit_error(tmp_path, monkeypatch):
    cfg = _config(tmp_path, fallback_provider="ollama", fallback_model="qwen3.5:27b")

    def fake_get_provider(name, config):
        return _FakeProvider(fail=(name == "xai"), label=name)

    monkeypatch.setattr(router, "_get_provider", fake_get_provider)
    resp = router.call(cfg, "analysis", "prompt")
    assert resp.text.startswith("ollama:")
    assert resp.model == "qwen3.5:27b"


def test_no_metered_blocks_cloud_fallback_before_provider_construction(tmp_path, monkeypatch):
    cfg = _config(
        tmp_path,
        provider="ollama",
        cost_mode="no-metered",
        fallback_provider="xai",
        fallback_model="grok-4.3",
    )
    constructed: list[str] = []

    def fake_get_provider(name, config):
        del config
        constructed.append(name)
        if name != "ollama":
            raise AssertionError("blocked cloud fallback must not be constructed")
        return _FakeProvider(fail=True, label=name)

    monkeypatch.setattr(router, "_get_provider", fake_get_provider)

    with pytest.raises(CostPolicyError, match="Route blocked by no-metered cost policy"):
        router.call(cfg, "analysis", "prompt")

    assert constructed == ["ollama"]


def test_paid_ok_allows_configured_cloud_fallback(tmp_path, monkeypatch):
    cfg = _config(
        tmp_path,
        provider="ollama",
        cost_mode="paid-ok",
        fallback_provider="xai",
        fallback_model="grok-4.3",
    )
    constructed: list[str] = []

    def fake_get_provider(name, config):
        del config
        constructed.append(name)
        return _FakeProvider(fail=name == "ollama", label=name)

    monkeypatch.setattr(router, "_get_provider", fake_get_provider)

    response = router.call(cfg, "analysis", "prompt")

    assert response.text == "xai:grok-4.3"
    assert constructed == ["ollama", "xai"]


def test_call_raises_original_when_no_fallback(tmp_path, monkeypatch):
    cfg = _config(tmp_path)  # no fallback configured

    monkeypatch.setattr(
        router, "_get_provider", lambda name, config: _FakeProvider(fail=True, label=name)
    )
    with pytest.raises(_CreditError):
        router.call(cfg, "analysis", "prompt")


def test_call_raises_original_when_fallback_also_fails(tmp_path, monkeypatch):
    cfg = _config(tmp_path, fallback_provider="ollama", fallback_model="m")

    monkeypatch.setattr(
        router, "_get_provider", lambda name, config: _FakeProvider(fail=True, label=name)
    )
    with pytest.raises(_CreditError):
        router.call(cfg, "analysis", "prompt")


def test_call_surfaces_retryable_busy_error_from_local_fallback(tmp_path, monkeypatch):
    cfg = _config(tmp_path, fallback_provider="ollama", fallback_model="qwen2.5:14b")
    busy = ProviderBusyTimeoutError(
        provider="Ollama",
        requested_model="qwen2.5:14b",
        active_models=("qwen2.5-coder:32b",),
        timeout_seconds=120,
    )

    class _BusyFallbackProvider:
        async def call(self, model_id, prompt, **kwargs):
            del model_id, prompt, kwargs
            raise busy

    def fake_get_provider(name, config):
        del config
        if name == "xai":
            return _FakeProvider(fail=True, label=name)
        return _BusyFallbackProvider()

    monkeypatch.setattr(router, "_get_provider", fake_get_provider)

    with pytest.raises(ProviderBusyTimeoutError) as raised:
        router.call(cfg, "analysis", "prompt")

    assert raised.value is busy

"""Shared fixtures for the command-layer tests."""

import pytest


@pytest.fixture(autouse=True)
def _model_available(monkeypatch):
    # Command gates now ask the router "is a model configured for this workload?"
    # (cloud key OR local provider) instead of reading config.xai_api_key. Default
    # a keyless local provider so commands proceed under test the way they did when
    # a test set xai_api_key="test-key" -- env-isolated (ollama needs no key, so
    # this is independent of any ambient .env cloud key). Tests of the no-model
    # path override the provider (e.g. DISTILL_PROVIDER=anthropic, not implemented).
    monkeypatch.setenv("DISTILL_PROVIDER", "ollama")

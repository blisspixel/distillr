"""Shared fixtures for the MCP-tool tests."""

import pytest


@pytest.fixture(autouse=True)
def _model_available(monkeypatch):
    # MCP model-using tools now gate on the router ("is a model configured for
    # this workload?", cloud key OR local provider) instead of config.xai_api_key.
    # Default a keyless local provider so the tools proceed under test the way they
    # did when a test set xai_api_key="test-key" -- env-isolated (ollama needs no
    # key). The no-model error tests override the provider to a not-implemented one.
    # ollama/lmstudio now require an explicit configured model at validation time,
    # so pin one here (matching tests/unit/commands/conftest.py) or model_available()
    # fails closed and the model-gated tools return early before their real work.
    monkeypatch.setenv("DISTILL_PROVIDER", "ollama")
    monkeypatch.setenv("DISTILL_MODEL", "qwen3.5:27b")

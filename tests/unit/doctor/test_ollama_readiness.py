"""Local setup must not confuse an installed model with permission to infer."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import httpx
import pytest
from typer.testing import CliRunner

from distill import cli
from distill.commands import doctor as doctor_command
from distill.commands import init as init_command
from distill.config import DistillConfig
from distill.doctor.checks import check_ollama_model_readiness
from distill.doctor.hardware import HardwareProfile
from distill.llm.providers.ollama import OllamaProvider


@pytest.mark.parametrize(
    ("status", "ready"),
    [
        ({"cloud": {"disabled": True, "source": "env"}}, True),
        ({"cloud": {"disabled": False, "source": "env"}}, False),
        ({"cloud": {"disabled": "true", "source": "env"}}, False),
        ({}, False),
    ],
)
def test_doctor_and_init_share_exact_model_proof(tmp_path, monkeypatch, status, ready):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DISTILL_PROVIDER", "ollama")
    monkeypatch.setenv("DISTILL_MODEL", "selected-alias")
    monkeypatch.setenv("DISTILL_COST_MODE", "no-metered")
    paths = []
    checked_models = []

    def handler(request):
        paths.append(request.url.path)
        if request.url.path == "/api/status":
            return httpx.Response(200, json=status)
        assert request.url.path == "/api/show", "readiness must never submit inference"
        checked_models.append(json.loads(request.content)["model"])
        return httpx.Response(
            200,
            json={
                "details": {"format": "gguf"},
                "model_info": {"general.architecture": "llama"},
            },
        )

    client_type = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: client_type(transport=httpx.MockTransport(handler), **kwargs),
    )
    config = DistillConfig(xai_api_key="", distill_cost_mode="no-metered")
    monkeypatch.setattr(
        "distill.doctor.hardware.detect_hardware",
        lambda: HardwareProfile("none", "", 0, 16, False),
    )
    monkeypatch.setattr(doctor_command, "get_config", lambda: config)
    monkeypatch.setattr(
        doctor_command, "_doctor_validate_key", lambda *args, **kwargs: ("not_set", "")
    )
    monkeypatch.setattr(
        doctor_command, "_check_ollama_status", lambda: ("running", ["other", "selected-alias"])
    )
    monkeypatch.setattr(doctor_command, "_check_lmstudio_models", lambda: ("unavailable", []))
    monkeypatch.setattr(init_command, "chromium_status", lambda: "installed")
    monkeypatch.setattr(
        init_command,
        "_local_model_inventory",
        lambda provider: ("running", ["other", "selected-alias"]),
    )

    runner = CliRunner()
    doctor_result = runner.invoke(cli.app, ["doctor", "--json"])
    assert doctor_result.exit_code == 0, doctor_result.output
    doctor = json.loads(doctor_result.stdout)["data"]
    assert doctor["ready"] is ready
    assert doctor["local_inference"]["configured_model_ready"] is ready
    assert doctor["local_inference"]["ollama_models"] == ["other", "selected-alias"]

    init_result = runner.invoke(cli.app, ["--json", "init", "--provider", "local", "--yes"])
    assert init_result.exit_code == (0 if ready else 1), init_result.output
    init = json.loads(init_result.stdout)["data"]
    assert init["ready"] is ready
    assert init["local_model_ready"] is ready
    assert init["local_reachable"] is True
    if ready:
        assert checked_models == ["selected-alias", "selected-alias"]
    else:
        assert checked_models == []
        assert any("local-only" in warning for warning in doctor["warnings"])
        assert any("local-only" in blocker for blocker in init["blocking"])
        assert not any("not installed" in blocker for blocker in init["blocking"])
        human_result = runner.invoke(cli.app, ["doctor"])
        assert human_result.exit_code == 0, human_result.output
        assert "not ready" in human_result.output
        assert "local-only" in human_result.output
        assert "Local ready:" not in human_result.output
    assert set(paths) <= {"/api/status", "/api/show"}


@pytest.mark.parametrize("model", ["", " "])
def test_empty_model_refuses_before_proof(monkeypatch, model):
    proof = AsyncMock()
    monkeypatch.setattr(OllamaProvider, "require_local", proof)
    status, detail = check_ollama_model_readiness(model)
    assert status == "blocked"
    assert "exact installed" in detail
    proof.assert_not_called()


def test_remote_endpoint_refuses_before_proof(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "https://hosted.example")
    proof = AsyncMock()
    monkeypatch.setattr(OllamaProvider, "require_local", proof)
    assert check_ollama_model_readiness("selected-alias")[0] == "blocked"
    proof.assert_not_called()


def test_unexpected_proof_failure_is_blocked_without_leaking_details(monkeypatch):
    monkeypatch.setattr(
        OllamaProvider, "require_local", AsyncMock(side_effect=RuntimeError("private details"))
    )
    status, detail = check_ollama_model_readiness("selected-alias")
    assert status == "blocked"
    assert "RuntimeError" in detail
    assert "private details" not in detail

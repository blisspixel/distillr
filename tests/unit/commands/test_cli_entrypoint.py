"""Tests for the installed CLI entrypoint wrapper."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from distill import cli
from distill.commands._json import ExitCode, set_json_active
from distill.llm.cost_policy import CostPolicyError
from distill.llm.errors import ProviderBusyTimeoutError
from distill.llm.run_context import update_current_run
from distill.pipeline.costs import BudgetExceededError, ProjectedBudgetExceededError


class _FailingApp:
    def __init__(self, exc: Exception) -> None:
        self.exc = exc
        self.pretty_exceptions_enable = True

    def __call__(self) -> None:
        raise self.exc


class _InstrumentedApp:
    def __init__(self, ops_dir: Path) -> None:
        self.ops_dir = ops_dir
        self.pretty_exceptions_enable = True

    def __call__(self) -> None:
        update_current_run(command="doctor", ops_dir=self.ops_dir)


def test_main_records_one_content_free_command_phase(monkeypatch, tmp_path):
    fake_app = _InstrumentedApp(tmp_path / ".distill")
    monkeypatch.setattr(cli, "app", fake_app)

    cli.main()

    rows = [
        json.loads(line)
        for line in (tmp_path / ".distill" / "phase_telemetry.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert len(rows) == 1
    assert rows[0]["command"] == "doctor"
    assert rows[0]["invocation_type"] == "cli"
    assert rows[0]["outcome"] == "success"
    assert rows[0]["run_id"]


def test_main_prints_clean_provider_error_and_documented_exit(monkeypatch):
    exc = RuntimeError("invalid api key")
    exc.status_code = 401
    fake_app = _FailingApp(exc)
    printed: list[str] = []

    monkeypatch.setattr(cli, "app", fake_app)
    monkeypatch.setattr(cli.console, "print", lambda message: printed.append(str(message)))

    with pytest.raises(SystemExit) as raised:
        cli.main()

    assert raised.value.code == int(ExitCode.CONFIG_ERROR)
    assert fake_app.pretty_exceptions_enable is False
    assert printed
    assert "API key" in printed[0]


def test_main_prints_clean_budget_error_and_documented_exit(monkeypatch):
    fake_app = _FailingApp(BudgetExceededError(0.61, 0.5))
    printed: list[str] = []

    monkeypatch.setattr(cli, "app", fake_app)
    monkeypatch.setattr(cli.console, "print", lambda message: printed.append(str(message)))

    with pytest.raises(SystemExit) as raised:
        cli.main()

    assert raised.value.code == int(ExitCode.BUDGET_EXCEEDED)
    assert fake_app.pretty_exceptions_enable is False
    assert printed
    assert "Budget exceeded" in printed[0]


def test_main_prints_clean_cost_policy_error_and_documented_exit(monkeypatch):
    fake_app = _FailingApp(CostPolicyError("Route blocked by no-metered cost policy."))
    printed: list[str] = []

    monkeypatch.setattr(cli, "app", fake_app)
    monkeypatch.setattr(cli.console, "print", lambda message: printed.append(str(message)))

    with pytest.raises(SystemExit) as raised:
        cli.main()

    assert raised.value.code == int(ExitCode.CONFIG_ERROR)
    assert fake_app.pretty_exceptions_enable is False
    assert printed
    assert "Route blocked by no-metered cost policy" in printed[0]


def test_main_emits_budget_error_json(monkeypatch, capsys):
    fake_app = _FailingApp(BudgetExceededError(0.61, 0.5))
    monkeypatch.setattr(cli, "app", fake_app)

    set_json_active(True)
    try:
        with pytest.raises(SystemExit) as raised:
            cli.main()
        captured = capsys.readouterr()
    finally:
        set_json_active(False)

    assert raised.value.code == int(ExitCode.BUDGET_EXCEEDED)
    payload = json.loads(captured.out)
    assert payload["status"] == "error"
    assert payload["data"]["reason"] == "budget_exceeded"
    assert payload["data"]["spent_usd"] == 0.61
    assert payload["data"]["budget_usd"] == 0.5


def test_main_emits_projected_budget_error_json(monkeypatch, capsys):
    fake_app = _FailingApp(ProjectedBudgetExceededError(0.12, 0.05))
    monkeypatch.setattr(cli, "app", fake_app)

    set_json_active(True)
    try:
        with pytest.raises(SystemExit) as raised:
            cli.main()
        captured = capsys.readouterr()
    finally:
        set_json_active(False)

    assert raised.value.code == int(ExitCode.BUDGET_EXCEEDED)
    payload = json.loads(captured.out)
    assert payload["status"] == "error"
    assert payload["data"]["reason"] == "budget_exceeded"
    assert payload["data"]["projected"] is True
    assert payload["data"]["projected_usd"] == 0.12
    assert payload["data"]["budget_usd"] == 0.05


def test_main_emits_cost_policy_error_json(monkeypatch, capsys):
    fake_app = _FailingApp(CostPolicyError("Route blocked by no-metered cost policy."))
    monkeypatch.setattr(cli, "app", fake_app)

    set_json_active(True)
    try:
        with pytest.raises(SystemExit) as raised:
            cli.main()
        captured = capsys.readouterr()
    finally:
        set_json_active(False)

    assert raised.value.code == int(ExitCode.CONFIG_ERROR)
    payload = json.loads(captured.out)
    assert payload["status"] == "error"
    assert payload["data"]["reason"] == "cost_policy_blocked"
    assert "Route blocked by no-metered cost policy" in payload["error"]


def test_main_emits_provider_busy_error_json(monkeypatch, capsys):
    fake_app = _FailingApp(
        ProviderBusyTimeoutError(
            provider="Ollama",
            requested_model="qwen2.5:14b",
            active_models=("qwen2.5-coder:32b",),
            timeout_seconds=120,
        )
    )
    monkeypatch.setattr(cli, "app", fake_app)

    set_json_active(True)
    try:
        with pytest.raises(SystemExit) as raised:
            cli.main()
        captured = capsys.readouterr()
    finally:
        set_json_active(False)

    assert raised.value.code == int(ExitCode.NETWORK_ERROR)
    payload = json.loads(captured.out)
    assert payload["status"] == "error"
    assert payload["data"] == {
        "code": "provider_busy",
        "retryable": True,
        "terminal": False,
        "provider": "Ollama",
        "requested_model": "qwen2.5:14b",
        "active_models": ["qwen2.5-coder:32b"],
        "waited_seconds": 120,
    }
    assert captured.err == ""


def test_main_reraises_unrecognized_errors(monkeypatch):
    fake_app = _FailingApp(ValueError("unexpected bug"))
    monkeypatch.setattr(cli, "app", fake_app)

    with pytest.raises(ValueError, match="unexpected bug"):
        cli.main()

    assert fake_app.pretty_exceptions_enable is False

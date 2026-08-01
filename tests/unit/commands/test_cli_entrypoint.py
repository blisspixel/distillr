"""Tests for the installed CLI entrypoint wrapper."""

from __future__ import annotations

import json
import runpy
from pathlib import Path

import pytest

from distill import cli
from distill.commands._json import ExitCode, set_json_active
from distill.llm.cost_policy import CostPolicyError
from distill.llm.errors import ProviderBusyTimeoutError
from distill.llm.run_context import update_current_run
from distill.pipeline.costs import (
    PROFILE_RECEIPT_ENV,
    BudgetExceededError,
    ProjectedBudgetExceededError,
)


def test_python_module_entrypoint_calls_cli_main(monkeypatch):
    calls: list[bool] = []
    monkeypatch.setattr(cli, "main", lambda: calls.append(True))

    runpy.run_module("distill", run_name="__main__")

    assert calls == [True]


class _FailingApp:
    def __init__(self, exc: Exception) -> None:
        self.exc = exc
        self.pretty_exceptions_enable = True

    def __call__(self) -> None:
        raise self.exc


class _InstrumentedApp:
    def __init__(self, ops_dir: Path, command: str = "doctor") -> None:
        self.ops_dir = ops_dir
        self.command = command
        self.pretty_exceptions_enable = True

    def __call__(self) -> None:
        update_current_run(command=self.command, ops_dir=self.ops_dir)


class _InstrumentedExitApp(_InstrumentedApp):
    def __init__(self, ops_dir: Path, code: object, command: str = "open") -> None:
        super().__init__(ops_dir, command=command)
        self.code = code

    def __call__(self) -> None:
        super().__call__()
        raise SystemExit(self.code)


class _InstrumentedFailingApp(_InstrumentedApp):
    def __init__(self, ops_dir: Path, exc: Exception, command: str = "doctor") -> None:
        super().__init__(ops_dir, command=command)
        self.exc = exc

    def __call__(self) -> None:
        super().__call__()
        raise self.exc


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


@pytest.mark.parametrize(
    ("code", "expected_outcome"),
    [
        (None, "success"),
        (ExitCode.SUCCESS, "success"),
        (ExitCode.RUNTIME_ERROR, "error"),
        (ExitCode.USAGE_ERROR, "usage_error"),
        (ExitCode.CONFIG_ERROR, "config_error"),
        (ExitCode.NETWORK_ERROR, "network_error"),
        (ExitCode.NOT_FOUND, "not_found"),
        (ExitCode.BUDGET_EXCEEDED, "budget_exceeded"),
        (99, "error"),
        ("invalid-status", "error"),
    ],
)
def test_main_records_semantic_system_exit_outcome(
    monkeypatch,
    tmp_path: Path,
    code: object,
    expected_outcome: str,
) -> None:
    ops_dir = tmp_path / ".distill"
    fake_app = _InstrumentedExitApp(ops_dir, code)
    monkeypatch.setattr(cli, "app", fake_app)

    with pytest.raises(SystemExit) as raised:
        cli.main()

    assert raised.value.code == code
    row = json.loads((ops_dir / "phase_telemetry.jsonl").read_text(encoding="utf-8"))
    assert row["outcome"] == expected_outcome
    assert row["error_type"] == ("" if code in (None, ExitCode.SUCCESS) else "SystemExit")


@pytest.mark.parametrize(
    ("exc", "expected_outcome"),
    [
        (CostPolicyError("Route blocked by no-metered cost policy."), "refused"),
        (BudgetExceededError(0.61, 0.5), "budget_exceeded"),
        (
            ProviderBusyTimeoutError(
                provider="Ollama",
                requested_model="qwen2.5:14b",
                active_models=("qwen2.5-coder:32b",),
                timeout_seconds=120,
            ),
            "network_error",
        ),
    ],
)
def test_main_preserves_explicit_and_mapped_exception_outcomes(
    monkeypatch,
    tmp_path: Path,
    exc: Exception,
    expected_outcome: str,
) -> None:
    ops_dir = tmp_path / ".distill"
    fake_app = _InstrumentedFailingApp(ops_dir, exc)
    monkeypatch.setattr(cli, "app", fake_app)
    monkeypatch.setattr(cli.console, "print", lambda *_args, **_kwargs: None)

    with pytest.raises(SystemExit):
        cli.main()

    row = json.loads((ops_dir / "phase_telemetry.jsonl").read_text(encoding="utf-8"))
    assert row["outcome"] == expected_outcome


def test_main_writes_zero_usage_receipt_for_successful_profile_latest_child(monkeypatch, tmp_path):
    receipt_id = "c" * 64
    fake_app = _InstrumentedApp(tmp_path / ".distill", command="latest")
    monkeypatch.setattr(cli, "app", fake_app)
    monkeypatch.setenv(PROFILE_RECEIPT_ENV, receipt_id)

    cli.main()

    rows = [
        json.loads(line)
        for line in (tmp_path / ".distill" / "cost_log.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert len(rows) == 1
    assert rows[0]["command"] == "latest"
    assert rows[0]["profile_receipt_id"] == receipt_id
    assert rows[0]["profile_receipt_cost_usd"] == 0


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
    assert payload["data"]["phase"] == "gate.budget"
    assert payload["data"]["action"] == "cli"
    assert payload["data"]["limit"]["kind"] == "budget"
    assert payload["data"]["run_id"]


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
    assert payload["data"]["phase"] == "gate.cost_policy"
    assert payload["data"]["action"] == "cli"
    assert payload["data"]["limit"]["kind"] == "cost_mode"
    assert payload["data"]["run_id"]


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


def test_main_escapes_provider_controlled_rich_markup(monkeypatch):
    fake_app = _FailingApp(
        ProviderBusyTimeoutError(
            provider="Ollama",
            requested_model="safe:latest",
            active_models=("[bold red]untrusted[/bold red]",),
            timeout_seconds=1,
        )
    )
    rendered: list[str] = []
    monkeypatch.setattr(cli, "app", fake_app)
    monkeypatch.setattr(cli.console, "print", lambda value: rendered.append(str(value)))

    with pytest.raises(SystemExit) as raised:
        cli.main()

    assert raised.value.code == int(ExitCode.NETWORK_ERROR)
    assert "\\[bold red]untrusted\\[/bold red]" in rendered[0]


def test_main_reraises_unrecognized_errors(monkeypatch):
    fake_app = _FailingApp(ValueError("unexpected bug"))
    monkeypatch.setattr(cli, "app", fake_app)

    with pytest.raises(ValueError, match="unexpected bug"):
        cli.main()

    assert fake_app.pretty_exceptions_enable is False

"""Tests for the installed CLI entrypoint wrapper."""

from __future__ import annotations

import json

import pytest

from distill import cli
from distill.commands._json import ExitCode, set_json_active
from distill.pipeline.costs import BudgetExceededError


class _FailingApp:
    def __init__(self, exc: Exception) -> None:
        self.exc = exc
        self.pretty_exceptions_enable = True

    def __call__(self) -> None:
        raise self.exc


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


def test_main_reraises_unrecognized_errors(monkeypatch):
    fake_app = _FailingApp(ValueError("unexpected bug"))
    monkeypatch.setattr(cli, "app", fake_app)

    with pytest.raises(ValueError, match="unexpected bug"):
        cli.main()

    assert fake_app.pretty_exceptions_enable is False

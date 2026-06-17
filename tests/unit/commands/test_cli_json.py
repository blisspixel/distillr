"""Tests for --json CLI flag integration.

Covers:
- Task 10.3: Unit tests for --json output
- Task 11.2: Property test for exit code 0 on success
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from distill.cli import app

runner = CliRunner()


def test_doctor_key_auth_rejected_distinguishes_auth_from_transient() -> None:
    # Only a 401/403 means the key is dead. Transient errors (timeout, 5xx,
    # offline) must NOT be classified as a rejection -- doing so falsely told
    # users with valid keys that the provider rejected them.
    from distill.doctor.checks import _doctor_key_auth_rejected

    auth = RuntimeError("unauthorized")
    auth.status_code = 401  # type: ignore[attr-defined]
    assert _doctor_key_auth_rejected(auth) is True

    forbidden = RuntimeError("forbidden")  # google-genai shape uses .code
    forbidden.code = 403  # type: ignore[attr-defined]
    assert _doctor_key_auth_rejected(forbidden) is True

    transient = RuntimeError("service unavailable")
    transient.status_code = 503  # type: ignore[attr-defined]
    assert _doctor_key_auth_rejected(transient) is False

    assert _doctor_key_auth_rejected(RuntimeError("offline, no status")) is False


@pytest.fixture
def mock_config(tmp_path):
    from distill.config import DistillConfig

    config = DistillConfig(
        xai_api_key="test",
        distill_output_dir=tmp_path / "library",
    )
    config.library_dir.mkdir(parents=True, exist_ok=True)
    return config


@pytest.fixture(autouse=True)
def _offline_key_validation():
    """Keep doctor's live API-key validation off the network in unit tests.

    Both doctor paths now live-validate keys via ``_doctor_validate_key``;
    default it to a healthy offline result so tests never make real provider
    calls. Individual tests re-patch it to exercise invalid-key handling.
    """

    def _fake(provider, config):
        if provider == "xai":
            return ("ok", "grok-4.3")
        return ("not_set", "")

    with patch("distill.commands.doctor._doctor_validate_key", side_effect=_fake):
        yield


class TestJsonCosts:
    """Test distill costs --json produces valid JSON."""

    def test_costs_json_no_history(self, mock_config):
        """costs --json with no cost log returns valid JSON."""
        with patch("distill.commands.maintain.get_config", return_value=mock_config):
            result = runner.invoke(app, ["--json", "costs"])

        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["status"] == "ok"
        assert parsed["data"]["runs"] == []
        assert "message" in parsed["data"]

    def test_costs_json_with_history(self, mock_config):
        """costs --json with cost entries returns valid JSON with runs."""
        log_file = mock_config.library_dir / "cost_log.jsonl"
        entry = {
            "timestamp": "2025-01-15T10:00:00",
            "command": "learn",
            "full_videos": 3,
            "shorts": 0,
            "actual_cost": 0.1234,
            "total_input_tokens": 5000,
            "total_output_tokens": 2000,
            "elapsed_seconds": 45,
        }
        log_file.write_text(json.dumps(entry) + "\n", encoding="utf-8")

        with patch("distill.commands.maintain.get_config", return_value=mock_config):
            result = runner.invoke(app, ["--json", "costs"])

        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["status"] == "ok"
        assert len(parsed["data"]["runs"]) == 1
        assert parsed["data"]["total_cost"] == 0.1234

    def test_costs_json_no_ansi(self, mock_config):
        """costs --json output contains no ANSI escape codes."""
        with patch("distill.commands.maintain.get_config", return_value=mock_config):
            result = runner.invoke(app, ["--json", "costs"])

        assert "\x1b" not in result.output


class TestJsonDoctor:
    """Test distill doctor --json produces valid JSON."""

    def test_doctor_json_output(self, mock_config):
        """doctor --json returns valid JSON with checks and warnings."""
        with patch("distill.commands.doctor.get_config", return_value=mock_config):
            result = runner.invoke(app, ["--json", "doctor"])

        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["status"] == "ok"
        assert "checks" in parsed["data"]
        assert "warnings" in parsed["data"]

    def test_doctor_command_local_json_output(self, mock_config):
        """`distill doctor --json` matches the global JSON flag shape."""
        with patch("distill.commands.doctor.get_config", return_value=mock_config):
            result = runner.invoke(app, ["doctor", "--json"])

        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["status"] == "ok"
        assert "checks" in parsed["data"]
        assert "warnings" in parsed["data"]

    def test_doctor_json_no_ansi(self, mock_config):
        """doctor --json output contains no ANSI escape codes."""
        with patch("distill.commands.doctor.get_config", return_value=mock_config):
            result = runner.invoke(app, ["--json", "doctor"])

        assert "\x1b" not in result.output

    def test_doctor_json_has_api_key_status(self, mock_config):
        """doctor --json reports live-validated API key status, not presence."""
        with patch("distill.commands.doctor.get_config", return_value=mock_config):
            result = runner.invoke(app, ["--json", "doctor"])

        parsed = json.loads(result.output)
        checks = parsed["data"]["checks"]
        assert "xai_api_key" in checks
        # Values reflect live validity, not mere presence.
        assert checks["xai_api_key"] in {"ok", "invalid", "missing"}
        assert checks["gemini_api_key"] in {"ok", "invalid", "not_set"}
        assert checks["openai_api_key"] in {"ok", "invalid", "not_set"}

    def test_doctor_json_flags_invalid_key(self, mock_config):
        """A present-but-rejected key reports 'invalid' + a warning, not a false-green.

        Regression guard: the --json path used to report presence only ("set"),
        so a revoked/expired key looked healthy while reports failed.
        """

        def _fake(provider, config):
            if provider == "xai":
                return ("ok", "grok-4.3")
            if provider == "gemini":
                return ("invalid", "400 API_KEY_INVALID")
            return ("not_set", "")

        with (
            patch("distill.commands.doctor.get_config", return_value=mock_config),
            patch("distill.commands.doctor._doctor_validate_key", side_effect=_fake),
        ):
            result = runner.invoke(app, ["--json", "doctor"])

        assert result.exit_code == 0
        parsed = json.loads(result.output)
        checks = parsed["data"]["checks"]
        assert checks["gemini_api_key"] == "invalid"
        assert checks["xai_api_key"] == "ok"
        assert any("GEMINI_API_KEY" in w for w in parsed["data"]["warnings"])

    def test_doctor_json_ready_verdict_and_browser(self, mock_config):
        """--json doctor carries a top-level `ready` verdict and a browser check."""

        def _ok(provider, config):
            return ("ok", "grok-4.3") if provider == "xai" else ("not_set", "")

        with (
            patch("distill.commands.doctor.get_config", return_value=mock_config),
            patch("distill.commands.doctor._doctor_validate_key", side_effect=_ok),
            patch("distill.commands.init.chromium_status", return_value="installed"),
        ):
            result = runner.invoke(app, ["--json", "doctor"])

        assert result.exit_code == 0
        data = json.loads(result.output)["data"]
        assert data["ready"] is True  # a working cloud key
        assert data["checks"]["browser"] == "installed"

    def test_doctor_json_not_ready_without_provider(self, mock_config):
        """`ready` is False with no validating cloud key and no local server."""

        def _missing(provider, config):
            return ("missing", "") if provider == "xai" else ("not_set", "")

        with (
            patch("distill.commands.doctor.get_config", return_value=mock_config),
            patch("distill.commands.doctor._doctor_validate_key", side_effect=_missing),
            patch("distill.commands.init.chromium_status", return_value="missing"),
            patch("distill.commands.doctor._check_ollama_status", return_value=("unavailable", [])),
            patch("distill.commands.doctor._check_lmstudio_status", return_value="unavailable"),
        ):
            result = runner.invoke(app, ["--json", "doctor"])

        data = json.loads(result.output)["data"]
        assert data["ready"] is False


class TestJsonAlerts:
    """Test distill alerts --json produces valid JSON."""

    def test_alerts_json_no_alerts(self, mock_config):
        """alerts --json with no alerts returns valid JSON."""
        with patch("distill.commands.maintain.get_config", return_value=mock_config):
            result = runner.invoke(app, ["--json", "alerts"])

        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["status"] == "ok"
        assert "\x1b" not in result.output

    def test_alerts_json_with_alerts(self, mock_config):
        """alerts --json with alerts returns content."""
        alerts_file = mock_config.library_dir / "watch_alerts.md"
        alerts_file.write_text("# Alerts\n- New video detected", encoding="utf-8")

        with patch("distill.commands.maintain.get_config", return_value=mock_config):
            result = runner.invoke(app, ["--json", "alerts"])

        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["status"] == "ok"
        assert "New video detected" in parsed["data"]["alerts"]


class TestJsonHealth:
    """Test distill health --json produces valid JSON."""

    def test_health_json_empty_library(self, mock_config):
        """health --json returns an envelope even when there are no topics."""
        with patch("distill.commands.doctor.get_config", return_value=mock_config):
            result = runner.invoke(app, ["--json", "health"])

        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["status"] == "ok"
        assert parsed["data"]["scope"] == "all"
        assert parsed["data"]["topics"] == []
        assert parsed["data"]["healthy"] is False
        assert parsed["data"]["message"] == "No topics found to audit"


class TestJsonErrorPaths:
    """Test that error paths produce JSON with error key."""

    def test_json_error_envelope_structure(self):
        """JsonEnvelope.fail produces correct structure."""
        from distill.commands._json import JsonEnvelope

        envelope = JsonEnvelope.fail("Something went wrong")
        parsed = json.loads(envelope.to_json())
        assert parsed["status"] == "error"
        assert parsed["error"] == "Something went wrong"
        assert "\x1b" not in envelope.to_json()


class TestExitCodes:
    """Property 8: Successful commands return exit code 0.

    **Validates: Requirements 4.1**
    """

    def test_successful_alerts_returns_zero(self, mock_config):
        """Successful alerts command returns exit code 0."""
        with patch("distill.commands.maintain.get_config", return_value=mock_config):
            result = runner.invoke(app, ["alerts"])

        assert result.exit_code == 0

    def test_successful_costs_returns_zero(self, mock_config):
        """Successful costs command returns exit code 0."""
        with patch("distill.commands.maintain.get_config", return_value=mock_config):
            result = runner.invoke(app, ["costs"])

        assert result.exit_code == 0

    def test_successful_doctor_returns_zero(self, mock_config):
        """Successful doctor command returns exit code 0."""
        with patch("distill.commands.doctor.get_config", return_value=mock_config):
            result = runner.invoke(app, ["--json", "doctor"])

        assert result.exit_code == 0

    def test_successful_json_alerts_returns_zero(self, mock_config):
        """Successful alerts --json command returns exit code 0."""
        with patch("distill.commands.maintain.get_config", return_value=mock_config):
            result = runner.invoke(app, ["--json", "alerts"])

        assert result.exit_code == 0

    def test_successful_json_costs_returns_zero(self, mock_config):
        """Successful costs --json command returns exit code 0."""
        with patch("distill.commands.maintain.get_config", return_value=mock_config):
            result = runner.invoke(app, ["--json", "costs"])

        assert result.exit_code == 0

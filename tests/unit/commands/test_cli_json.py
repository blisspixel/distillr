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


@pytest.fixture
def mock_config(tmp_path):
    from distill.config import DistillConfig

    config = DistillConfig(
        xai_api_key="test",
        distill_output_dir=tmp_path / "library",
    )
    config.library_dir.mkdir(parents=True, exist_ok=True)
    return config


class TestJsonCosts:
    """Test distill costs --json produces valid JSON."""

    def test_costs_json_no_history(self, mock_config):
        """costs --json with no cost log returns valid JSON."""
        with patch("distill._cli_impl.get_config", return_value=mock_config):
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

        with patch("distill._cli_impl.get_config", return_value=mock_config):
            result = runner.invoke(app, ["--json", "costs"])

        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["status"] == "ok"
        assert len(parsed["data"]["runs"]) == 1
        assert parsed["data"]["total_cost"] == 0.1234

    def test_costs_json_no_ansi(self, mock_config):
        """costs --json output contains no ANSI escape codes."""
        with patch("distill._cli_impl.get_config", return_value=mock_config):
            result = runner.invoke(app, ["--json", "costs"])

        assert "\x1b" not in result.output


class TestJsonDoctor:
    """Test distill doctor --json produces valid JSON."""

    def test_doctor_json_output(self, mock_config):
        """doctor --json returns valid JSON with checks and warnings."""
        with patch("distill._cli_impl.get_config", return_value=mock_config):
            result = runner.invoke(app, ["--json", "doctor"])

        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["status"] == "ok"
        assert "checks" in parsed["data"]
        assert "warnings" in parsed["data"]

    def test_doctor_json_no_ansi(self, mock_config):
        """doctor --json output contains no ANSI escape codes."""
        with patch("distill._cli_impl.get_config", return_value=mock_config):
            result = runner.invoke(app, ["--json", "doctor"])

        assert "\x1b" not in result.output

    def test_doctor_json_has_api_key_status(self, mock_config):
        """doctor --json reports API key status."""
        with patch("distill._cli_impl.get_config", return_value=mock_config):
            result = runner.invoke(app, ["--json", "doctor"])

        parsed = json.loads(result.output)
        checks = parsed["data"]["checks"]
        assert "xai_api_key" in checks


class TestJsonAlerts:
    """Test distill alerts --json produces valid JSON."""

    def test_alerts_json_no_alerts(self, mock_config):
        """alerts --json with no alerts returns valid JSON."""
        with patch("distill._cli_impl.get_config", return_value=mock_config):
            result = runner.invoke(app, ["--json", "alerts"])

        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["status"] == "ok"
        assert "\x1b" not in result.output

    def test_alerts_json_with_alerts(self, mock_config):
        """alerts --json with alerts returns content."""
        alerts_file = mock_config.library_dir / "watch_alerts.md"
        alerts_file.write_text("# Alerts\n- New video detected", encoding="utf-8")

        with patch("distill._cli_impl.get_config", return_value=mock_config):
            result = runner.invoke(app, ["--json", "alerts"])

        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["status"] == "ok"
        assert "New video detected" in parsed["data"]["alerts"]


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
        with patch("distill._cli_impl.get_config", return_value=mock_config):
            result = runner.invoke(app, ["alerts"])

        assert result.exit_code == 0

    def test_successful_costs_returns_zero(self, mock_config):
        """Successful costs command returns exit code 0."""
        with patch("distill._cli_impl.get_config", return_value=mock_config):
            result = runner.invoke(app, ["costs"])

        assert result.exit_code == 0

    def test_successful_doctor_returns_zero(self, mock_config):
        """Successful doctor command returns exit code 0."""
        with patch("distill._cli_impl.get_config", return_value=mock_config):
            result = runner.invoke(app, ["--json", "doctor"])

        assert result.exit_code == 0

    def test_successful_json_alerts_returns_zero(self, mock_config):
        """Successful alerts --json command returns exit code 0."""
        with patch("distill._cli_impl.get_config", return_value=mock_config):
            result = runner.invoke(app, ["--json", "alerts"])

        assert result.exit_code == 0

    def test_successful_json_costs_returns_zero(self, mock_config):
        """Successful costs --json command returns exit code 0."""
        with patch("distill._cli_impl.get_config", return_value=mock_config):
            result = runner.invoke(app, ["--json", "costs"])

        assert result.exit_code == 0

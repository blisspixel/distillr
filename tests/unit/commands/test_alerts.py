"""Tests for the distill alerts command."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from distill.cli import app
from distill.config import DistillConfig

runner = CliRunner()


@pytest.fixture
def mock_config(tmp_path):
    config = DistillConfig(
        xai_api_key="test",
        distill_output_dir=tmp_path / "library",
    )
    config.library_dir.mkdir(parents=True, exist_ok=True)
    return config


class TestAlertsCommand:
    def test_no_alerts(self, mock_config):
        with patch("distill._cli_impl.get_config", return_value=mock_config):
            result = runner.invoke(app, ["alerts"])
        assert result.exit_code == 0

    def test_with_alerts(self, mock_config):
        # Create a watch_alerts.md file
        alerts_file = mock_config.library_dir / "watch_alerts.md"
        alerts_file.write_text("# Watch Alerts\n- New video on AI channel", encoding="utf-8")

        with patch("distill._cli_impl.get_config", return_value=mock_config):
            result = runner.invoke(app, ["alerts"])
        assert result.exit_code == 0

    def test_json_no_alerts(self, mock_config):
        with patch("distill._cli_impl.get_config", return_value=mock_config):
            result = runner.invoke(app, ["--json", "alerts"])
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["status"] == "ok"
        assert parsed["data"]["message"] == "No watch alerts found."

    def test_json_with_alerts(self, mock_config):
        alerts_file = mock_config.library_dir / "watch_alerts.md"
        alerts_file.write_text("# Alerts\n- Something new", encoding="utf-8")

        with patch("distill._cli_impl.get_config", return_value=mock_config):
            result = runner.invoke(app, ["--json", "alerts"])
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["status"] == "ok"
        assert "Something new" in parsed["data"]["alerts"]


class TestAlertsMcpResource:
    """Test the watch-alerts MCP resource response."""

    def test_mcp_resource_no_alerts(self, mock_config):
        """MCP resource returns clear message when no alerts exist."""
        with patch("distill.mcp.server._config", return_value=mock_config):
            from distill.mcp.resources import get_watch_alerts

            result = get_watch_alerts()
        assert "No watch alerts found" in result

    def test_mcp_resource_with_alerts(self, mock_config):
        """MCP resource returns alert content when alerts exist."""
        mock_config.library_dir.mkdir(parents=True, exist_ok=True)
        alerts_file = mock_config.library_dir / "watch_alerts.md"
        alerts_file.write_text("# Watch Alerts\n- Channel X has new content", encoding="utf-8")

        with patch("distill.mcp.server._config", return_value=mock_config):
            from distill.mcp.resources import get_watch_alerts

            result = get_watch_alerts()
        assert "Channel X has new content" in result

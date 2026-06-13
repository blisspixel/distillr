"""Tests for --json CLI flag integration."""

from __future__ import annotations

import json
from unittest.mock import patch

from typer.testing import CliRunner

from distill.cli import app

runner = CliRunner()


class TestJsonFlag:
    def test_json_flag_on_alerts_command(self, tmp_path):
        """Test --json flag produces valid JSON output."""
        from distill.config import DistillConfig

        config = DistillConfig(
            xai_api_key="test",
            distill_output_dir=tmp_path / "library",
        )
        config.library_dir.mkdir(parents=True, exist_ok=True)

        with patch("distill.commands.maintain.get_config", return_value=config):
            result = runner.invoke(app, ["--json", "alerts"])

        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["status"] == "ok"
        assert "\x1b" not in result.output  # No ANSI codes

    def test_json_flag_accepted_globally(self):
        """Test that --json is accepted as a global option."""
        result = runner.invoke(app, ["--json", "--help"])
        # --help should still work with --json
        assert result.exit_code == 0


class TestExitCodes:
    def test_successful_command_returns_zero(self, tmp_path):
        """Property 8: Successful commands return exit code 0."""
        from distill.config import DistillConfig

        config = DistillConfig(
            xai_api_key="test",
            distill_output_dir=tmp_path / "library",
        )
        config.library_dir.mkdir(parents=True, exist_ok=True)

        with patch("distill.commands.maintain.get_config", return_value=config):
            result = runner.invoke(app, ["alerts"])

        assert result.exit_code == 0

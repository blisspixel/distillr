"""Unit tests for `distill open --vault` command options.

Feature: living-wiki-0-7
Tests: --vault, --vault with DISTILL_VAULT_EDITOR, error cases
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import typer


class TestOpenVault:
    """Tests for open --vault command behavior."""

    def test_vault_calls_webbrowser_open(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """--vault uses webbrowser.open() when no DISTILL_VAULT_EDITOR is set."""
        library_dir = tmp_path / "library"
        library_dir.mkdir()

        mock_config = MagicMock()
        mock_config.library_dir = library_dir

        monkeypatch.delenv("DISTILL_VAULT_EDITOR", raising=False)

        with (
            patch("distill._cli_impl.get_config", return_value=mock_config),
            patch("distill._cli_impl.webbrowser.open") as mock_open,
            patch("distill._cli_impl.console"),
        ):
            from distill._cli_impl import open_cmd

            open_cmd(topic=None, channel=None, what="output", vault=True, path="")

            mock_open.assert_called_once_with(str(library_dir))

    def test_vault_with_editor_env_var(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """--vault uses DISTILL_VAULT_EDITOR when set."""
        library_dir = tmp_path / "library"
        library_dir.mkdir()

        mock_config = MagicMock()
        mock_config.library_dir = library_dir

        monkeypatch.setenv("DISTILL_VAULT_EDITOR", "obsidian")

        with (
            patch("distill._cli_impl.get_config", return_value=mock_config),
            patch("shutil.which", return_value="/usr/bin/obsidian"),
            patch("subprocess.run") as mock_run,
            patch("distill._cli_impl.console"),
        ):
            from distill._cli_impl import open_cmd

            open_cmd(topic=None, channel=None, what="output", vault=True, path="")

            mock_run.assert_called_once_with(["obsidian", str(library_dir)])

    def test_vault_missing_library_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """--vault exits with error when library dir doesn't exist."""
        library_dir = tmp_path / "nonexistent"

        mock_config = MagicMock()
        mock_config.library_dir = library_dir

        monkeypatch.delenv("DISTILL_VAULT_EDITOR", raising=False)

        with (
            patch("distill._cli_impl.get_config", return_value=mock_config),
            patch("distill._cli_impl.console"),
        ):
            from distill._cli_impl import open_cmd

            with pytest.raises(typer.Exit):
                open_cmd(topic=None, channel=None, what="output", vault=True, path="")

    def test_vault_with_path_option(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """--vault --path opens a subdirectory within library."""
        library_dir = tmp_path / "library"
        library_dir.mkdir()
        subdir = library_dir / "topics" / "ai-agents"
        subdir.mkdir(parents=True)

        mock_config = MagicMock()
        mock_config.library_dir = library_dir

        monkeypatch.delenv("DISTILL_VAULT_EDITOR", raising=False)

        with (
            patch("distill._cli_impl.get_config", return_value=mock_config),
            patch("distill._cli_impl.webbrowser.open") as mock_open,
            patch("distill._cli_impl.console"),
        ):
            from distill._cli_impl import open_cmd

            open_cmd(topic=None, channel=None, what="output", vault=True, path="topics/ai-agents")

            mock_open.assert_called_once_with(str(subdir))

    def test_vault_with_missing_subdirectory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """--vault --path exits with error when subdirectory doesn't exist."""
        library_dir = tmp_path / "library"
        library_dir.mkdir()

        mock_config = MagicMock()
        mock_config.library_dir = library_dir

        monkeypatch.delenv("DISTILL_VAULT_EDITOR", raising=False)

        with (
            patch("distill._cli_impl.get_config", return_value=mock_config),
            patch("distill._cli_impl.console"),
        ):
            from distill._cli_impl import open_cmd

            with pytest.raises(typer.Exit):
                open_cmd(
                    topic=None, channel=None, what="output", vault=True, path="nonexistent/path"
                )

    def test_vault_editor_not_found(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """--vault exits with error when DISTILL_VAULT_EDITOR program not found."""
        library_dir = tmp_path / "library"
        library_dir.mkdir()

        mock_config = MagicMock()
        mock_config.library_dir = library_dir

        monkeypatch.setenv("DISTILL_VAULT_EDITOR", "nonexistent-editor")

        with (
            patch("distill._cli_impl.get_config", return_value=mock_config),
            patch("shutil.which", return_value=None),
            patch("distill._cli_impl.console"),
        ):
            from distill._cli_impl import open_cmd

            with pytest.raises(typer.Exit):
                open_cmd(topic=None, channel=None, what="output", vault=True, path="")

"""Per-user env files load after the working directory and never clobber process env."""

from __future__ import annotations

import os
from pathlib import Path

from distill.env_files import (
    existing_env_files,
    home_distill_env_path,
    is_distill_checkout,
    load_distill_dotenv,
    writable_env_path,
    xdg_env_path,
)


def test_checkout_detection(tmp_path: Path) -> None:
    assert is_distill_checkout(tmp_path) is False
    (tmp_path / "pyproject.toml").write_text("name = 'distillr'\n", encoding="utf-8")
    assert is_distill_checkout(tmp_path) is True
    (tmp_path / "pyproject.toml").write_text('name = "other"\n', encoding="utf-8")
    assert is_distill_checkout(tmp_path) is False


def test_unreadable_pyproject_is_not_a_checkout(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").mkdir()
    assert is_distill_checkout(tmp_path) is False


def test_user_paths_follow_xdg_and_isolated_home(monkeypatch) -> None:
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    home = home_distill_env_path()
    assert home.parent.name == ".distill"
    assert home.name == ".env"
    # The suite fixture replaces Path.home, so both helpers stay under that root.
    assert home == Path.home() / ".distill" / ".env"
    assert xdg_env_path() == home.parent.parent / ".config" / "distill" / ".env"


def test_writable_path_is_cwd_in_a_checkout_and_xdg_elsewhere(tmp_path: Path, monkeypatch) -> None:
    checkout = tmp_path / "checkout"
    other = tmp_path / "other"
    checkout.mkdir()
    other.mkdir()
    (checkout / "pyproject.toml").write_text('name = "distillr"\n', encoding="utf-8")

    monkeypatch.chdir(checkout)
    assert writable_env_path() == checkout / ".env"
    monkeypatch.chdir(other)
    assert writable_env_path() == xdg_env_path()


def test_load_order_is_process_then_cwd_then_user(tmp_path: Path, monkeypatch) -> None:
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    (cwd / ".env").write_text("DISTILL_FROM_CWD=cwd\nSHARED=cwd\n", encoding="utf-8")
    user = xdg_env_path()
    user.parent.mkdir(parents=True, exist_ok=True)
    user.write_text(
        "DISTILL_FROM_USER=user\nSHARED=user\nDISTILL_FROM_CWD=user\n",
        encoding="utf-8",
    )
    legacy = home_distill_env_path()
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text("DISTILL_FROM_LEGACY=legacy\nSHARED=legacy\n", encoding="utf-8")
    monkeypatch.setenv("SHARED", "process")
    monkeypatch.delenv("DISTILL_FROM_CWD", raising=False)
    monkeypatch.delenv("DISTILL_FROM_USER", raising=False)
    monkeypatch.delenv("DISTILL_FROM_LEGACY", raising=False)

    load_distill_dotenv()

    assert os.environ["SHARED"] == "process"
    assert os.environ["DISTILL_FROM_CWD"] == "cwd"
    assert os.environ["DISTILL_FROM_USER"] == "user"
    assert os.environ["DISTILL_FROM_LEGACY"] == "legacy"
    assert existing_env_files() == [cwd / ".env", user, legacy]

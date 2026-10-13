# pyright: strict
"""Working-directory and per-user env files.

Process environment wins, then ``./.env``, then the user file. A checkout
(``pyproject.toml`` names distillr) still writes ``./.env``. Everywhere else,
setup writes the XDG config file so a later command in another directory sees
the same provider.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

__all__ = [
    "existing_env_files",
    "home_distill_env_path",
    "is_distill_checkout",
    "load_distill_dotenv",
    "user_env_paths",
    "writable_env_path",
    "xdg_env_path",
]


def is_distill_checkout(cwd: Path | None = None) -> bool:
    """True when *cwd* is a distillr source checkout."""

    root = cwd or Path.cwd()
    pyproject = root / "pyproject.toml"
    try:
        text = pyproject.read_text(encoding="utf-8")
    except OSError:
        return False
    return 'name = "distillr"' in text or "name = 'distillr'" in text


def xdg_env_path() -> Path:
    """Per-user env file under ``$XDG_CONFIG_HOME/distill/.env``."""

    raw = os.environ.get("XDG_CONFIG_HOME", "").strip()
    base = Path(raw) if raw else Path.home() / ".config"
    return base / "distill" / ".env"


def home_distill_env_path() -> Path:
    """Legacy per-user env file next to the default library."""

    return Path.home() / ".distill" / ".env"


def user_env_paths() -> list[Path]:
    """User env files in load order, after the working-directory file."""

    return [xdg_env_path(), home_distill_env_path()]


def writable_env_path() -> Path:
    """Where ``init`` and ``provider set`` persist new assignments."""

    if is_distill_checkout():
        return Path.cwd() / ".env"
    return xdg_env_path()


def load_distill_dotenv() -> None:
    """Load cwd ``.env``, then user files, without clobbering existing env."""

    cwd_env = Path.cwd() / ".env"
    if cwd_env.is_file():
        load_dotenv(dotenv_path=cwd_env, override=False)
    for path in user_env_paths():
        if path.is_file():
            load_dotenv(dotenv_path=path, override=False)


def existing_env_files() -> list[Path]:
    """Env files that exist now, cwd first, then user files."""

    found: list[Path] = []
    cwd_env = Path.cwd() / ".env"
    if cwd_env.is_file():
        found.append(cwd_env)
    for path in user_env_paths():
        if path.is_file() and path not in found:
            found.append(path)
    return found

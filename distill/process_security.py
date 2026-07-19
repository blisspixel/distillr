"""Shared security boundaries for child-process execution."""

# pyright: strict

from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from pathlib import Path

_WINDOWS_DEFAULT_EXTENSIONS = (".COM", ".EXE")
_EXACT_SECRET_NAMES = frozenset(
    {
        "ANTHROPIC_API_KEY",
        "AZURE_OPENAI_API_KEY",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "AZURE_CLIENT_SECRET",
        "DISTILL_WORKER_CLAIM_TOKEN",
        "GEMINI_API_KEY",
        "GH_TOKEN",
        "GITHUB_TOKEN",
        "GOOGLE_API_KEY",
        "GOOGLE_APPLICATION_CREDENTIALS",
        "HF_TOKEN",
        "HUGGING_FACE_HUB_TOKEN",
        "OPENAI_API_KEY",
        "XAI_API_KEY",
    }
)
_UNSAFE_PACKAGE_OVERRIDE_NAMES = frozenset(
    {
        "NODE_OPTIONS",
        "NODE_PATH",
        "PLAYWRIGHT_BROWSERS_PATH",
        "PLAYWRIGHT_NODEJS_PATH",
    }
)


def _windows_candidate_names(name: str, raw_extensions: str) -> tuple[str, ...]:
    """Return deduplicated executable candidates from an allowlisted PATHEXT."""

    extensions: list[str] = []
    for extension in raw_extensions.split(os.pathsep):
        normalized = extension.strip().upper()
        if normalized and not normalized.startswith("."):
            normalized = f".{normalized}"
        if normalized in _WINDOWS_DEFAULT_EXTENSIONS and normalized not in extensions:
            extensions.append(normalized)
    return tuple(f"{name}{extension}" for extension in extensions)


def _candidate_names(name: str, env: Mapping[str, str]) -> tuple[str, ...]:
    if os.name != "nt" or Path(name).suffix:
        return (name,)
    raw_extensions = env.get("PATHEXT", os.pathsep.join(_WINDOWS_DEFAULT_EXTENSIONS))
    return _windows_candidate_names(name, raw_extensions)


def _usable_executable(path: Path) -> Path | None:
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    if not resolved.is_file():
        return None
    if os.name != "nt" and not os.access(resolved, os.X_OK):
        return None
    return resolved


def _search_directory(raw_directory: str, working_directory: Path) -> Path | None:
    if not raw_directory:
        return None
    directory = Path(raw_directory.strip('"'))
    if not directory.is_absolute():
        return None
    try:
        resolved = directory.resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    return None if resolved == working_directory else resolved


def _absolute_executable(name: str) -> str | None:
    path = Path(name)
    if not path.is_absolute():
        return None
    resolved = _usable_executable(path)
    return str(resolved) if resolved is not None else None


def resolve_executable(
    name: str,
    *,
    env: Mapping[str, str] | None = None,
) -> str | None:
    """Return an absolute executable path without searching the current directory.

    Relative PATH entries and the resolved working directory are ignored. This
    avoids Windows current-directory image selection and gives subprocesses one
    exact executable identity instead of a second implicit search operation.
    """

    if not name or Path(name).name != name:
        return _absolute_executable(name)

    environment = os.environ if env is None else env
    try:
        working_directory = Path.cwd().resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    candidate_names = _candidate_names(name, environment)
    for raw_directory in os.get_exec_path(environment):
        resolved_directory = _search_directory(raw_directory, working_directory)
        if resolved_directory is None:
            continue
        for candidate_name in candidate_names:
            resolved = _usable_executable(resolved_directory / candidate_name)
            if (
                resolved is not None
                and resolved.parent != working_directory
                and (os.name != "nt" or resolved.parent == resolved_directory)
            ):
                return str(resolved)
    return None


def sanitized_package_env(source: Mapping[str, str] | None = None) -> dict[str, str]:
    """Copy an environment without package-loader injection or credentials."""

    original = os.environ if source is None else source
    sanitized = {
        key: value
        for key, value in original.items()
        if key.upper() not in _EXACT_SECRET_NAMES
        and not key.upper().endswith(("_API_KEY", "_PASSWORD", "_SECRET", "_TOKEN"))
        and not key.upper().startswith("PYTHON")
        and key.upper() not in _UNSAFE_PACKAGE_OVERRIDE_NAMES
    }
    sanitized["PYTHONSAFEPATH"] = "1"
    sanitized["PYTHONNOUSERSITE"] = "1"
    return sanitized


def unsafe_package_overrides(source: Mapping[str, str] | None = None) -> tuple[str, ...]:
    """Return ambient variables that can replace or inject package child code."""

    original = os.environ if source is None else source
    return tuple(
        sorted(
            key.upper()
            for key in original
            if key.upper() in _UNSAFE_PACKAGE_OVERRIDE_NAMES and original[key]
        )
    )


def package_install_context() -> tuple[str, dict[str, str]]:
    """Return a trusted Python-adjacent cwd and sanitized package environment."""

    return str(Path(sys.executable).resolve().parent), sanitized_package_env()

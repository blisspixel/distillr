"""Installed package version helper."""

# pyright: strict

from __future__ import annotations

from importlib.metadata import version

__all__ = ["get_version"]


def get_version() -> str:
    """Get package version from metadata."""
    for dist in ("distillr", "distill"):
        try:
            value = version(dist)
        except Exception:
            continue
        if value:
            return value
    return "dev"

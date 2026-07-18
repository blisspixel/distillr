# pyright: strict
"""Side-effect-free classification for CLI targets."""

from __future__ import annotations

from pathlib import PureWindowsPath
from urllib.parse import urlparse


def is_http_url(value: str) -> bool:
    """Return whether *value* declares an HTTP or HTTPS URL."""

    return urlparse(value).scheme.lower() in {"http", "https"}


def is_remote_filesystem_path(value: str) -> bool:
    """Return whether *value* is a UNC or Windows device path."""

    if not value or "\x00" in value:
        return False
    normalized = value.replace("/", "\\")
    if normalized.startswith("\\\\"):
        return True
    windows_path = PureWindowsPath(value)
    return windows_path.drive.startswith("\\\\") or windows_path.root.startswith("\\\\")


def require_local_filesystem_target(value: str) -> None:
    """Reject remote filesystem forms before callers perform path I/O."""

    if "\x00" in value:
        raise ValueError("target contains a null byte")
    if is_remote_filesystem_path(value):
        raise ValueError("remote filesystem targets are not supported")

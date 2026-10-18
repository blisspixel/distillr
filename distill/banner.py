"""A static ANSI wordmark for successful setup and upgrades."""

from __future__ import annotations

import os
from pathlib import Path

from rich.console import Console

from distill.library.confined_state import atomic_write_confined_text, read_confined_state_text

BANNER_ART = "D I S T I L L"


def _is_banner_enabled() -> bool:
    return os.environ.get("DISTILL_BANNER", "").strip().lower() not in {"off", "false", "0", "no"}


def show_banner(console: Console, art: str = BANNER_ART) -> bool:
    """Show an explicit static signature only on a capable terminal."""
    if (
        not _is_banner_enabled()
        or not console.is_terminal
        or not console.color_system
        or "NO_COLOR" in os.environ
        or os.environ.get("TERM") == "dumb"
        or os.environ.get("CI", "").lower() in {"true", "1", "yes"}
    ):
        return False
    console.print(art, style="cyan", markup=False, highlight=False)
    return True


def show_signature(console: Console, root: Path, version: str) -> bool:
    """Remember one successful setup or upgrade signature per version."""
    marker = root / ".distill" / "signature-version"
    previous = read_confined_state_text(marker, root, max_bytes=256) if root.exists() else None
    if previous == version or not show_banner(console):
        return False
    root.mkdir(parents=True, exist_ok=True)
    atomic_write_confined_text(marker, version, root)
    return True

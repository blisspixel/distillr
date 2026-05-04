"""Structured logging configuration for the Distill CLI.

Call ``configure_logging()`` once at CLI startup (from the ``--debug``
callback in ``cli.py``) to set up console and file handlers on the
``distill`` logger hierarchy.
"""

from __future__ import annotations

import logging
from pathlib import Path

__all__ = ["configure_logging"]

_CONFIGURED = False


def configure_logging(debug: bool = False, ops_dir: Path | None = None) -> None:
    """Configure structured logging for the CLI.

    Parameters
    ----------
    debug:
        When *True*, the console handler emits DEBUG+ messages.
        When *False* (default), only WARNING+ reach the console.
    ops_dir:
        If provided, a file handler writes DEBUG+ messages to
        ``<ops_dir>/distill.log``.  Typically ``library/.distill/``.
    """
    global _CONFIGURED
    if _CONFIGURED:
        # Reconfigure levels on subsequent calls (e.g. --debug parsed late).
        root = logging.getLogger("distill")
        root.setLevel(logging.DEBUG if debug else logging.WARNING)
        for handler in root.handlers:
            if isinstance(handler, logging.StreamHandler) and not isinstance(
                handler, logging.FileHandler
            ):
                handler.setLevel(logging.DEBUG if debug else logging.WARNING)
        return

    root = logging.getLogger("distill")
    root.setLevel(logging.DEBUG)

    # Console handler — WARNING+ by default, DEBUG with --debug
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG if debug else logging.WARNING)
    console_handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)-8s %(name)s — %(message)s",
            datefmt="%H:%M:%S",
        )
    )
    root.addHandler(console_handler)

    # File handler — always DEBUG, writes to ops_dir
    if ops_dir:
        ops_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(ops_dir / "distill.log", encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)-8s %(name)s — %(message)s",
            )
        )
        root.addHandler(file_handler)

    _CONFIGURED = True

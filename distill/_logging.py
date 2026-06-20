"""Structured logging configuration for the Distill CLI.

Call ``configure_logging()`` at CLI startup to set up or retarget console and
file handlers on the ``distill`` logger hierarchy.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

__all__ = ["configure_logging"]

_CONSOLE_MARKER = "_distill_console_handler"
_FILE_MARKER = "_distill_file_handler"
_FORMAT = "%(asctime)s %(levelname)-8s %(name)s - %(message)s"


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
    root = logging.getLogger("distill")
    root.setLevel(logging.DEBUG)
    _configure_console_handler(root, debug=debug)
    _configure_file_handler(root, ops_dir=ops_dir)


def _configure_console_handler(root: logging.Logger, *, debug: bool) -> None:
    level = logging.DEBUG if debug else logging.WARNING
    handler = _find_console_handler(root)
    if handler is None:
        handler = logging.StreamHandler(sys.stderr)
        setattr(handler, _CONSOLE_MARKER, True)
        root.addHandler(handler)

    # Reused processes and test runners replace stdout/stderr per invocation.
    handler.stream = sys.stderr
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter(_FORMAT, datefmt="%H:%M:%S"))


def _configure_file_handler(root: logging.Logger, *, ops_dir: Path | None) -> None:
    handlers = _find_file_handlers(root)
    if ops_dir is None:
        for handler in handlers:
            root.removeHandler(handler)
            handler.close()
        return

    ops_dir.mkdir(parents=True, exist_ok=True)
    target = (ops_dir / "distill.log").resolve()
    active: logging.FileHandler | None = None
    for handler in handlers:
        handler_path = Path(handler.baseFilename).resolve()
        if active is None and handler_path == target:
            active = handler
            continue
        root.removeHandler(handler)
        handler.close()

    if active is None:
        active = logging.FileHandler(target, encoding="utf-8")
        setattr(active, _FILE_MARKER, True)
        root.addHandler(active)

    active.setLevel(logging.DEBUG)
    active.setFormatter(logging.Formatter(_FORMAT))


def _find_console_handler(root: logging.Logger) -> logging.StreamHandler | None:
    for handler in root.handlers:
        if getattr(handler, _CONSOLE_MARKER, False) and isinstance(handler, logging.StreamHandler):
            return handler
    for handler in root.handlers:
        if isinstance(handler, logging.StreamHandler) and not isinstance(
            handler, logging.FileHandler
        ):
            setattr(handler, _CONSOLE_MARKER, True)
            return handler
    return None


def _find_file_handlers(root: logging.Logger) -> list[logging.FileHandler]:
    handlers = [handler for handler in root.handlers if isinstance(handler, logging.FileHandler)]
    for handler in handlers:
        setattr(handler, _FILE_MARKER, True)
    return handlers

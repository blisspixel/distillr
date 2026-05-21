"""Process-startup hooks that must run before any rich/typer/Console import.

The Distill CLI prints non-ASCII glyphs in some banners (e.g. preflight warning
markers, table separators). On a default Windows console with cp1252, those
crash with ``UnicodeEncodeError`` before the user sees any output. This module
reconfigures stdout/stderr to UTF-8 *at import time* so any code that imports
``distill.cli_shared`` (which imports this module first) gets safe stdio.

Importing this module is the side effect — there is no public API to call.
``ensure_utf8_stdio`` is exported only so tests can exercise it directly.
"""

from __future__ import annotations

import contextlib
import sys


def ensure_utf8_stdio() -> None:
    """Reconfigure stdout/stderr to UTF-8 with replacement on encoding error.

    Also enables line buffering on both streams. Without this, long-running
    operations whose only output goes through buffered stdout (e.g. Whisper
    transcription of multi-minute audio under a non-TTY harness like CI,
    subprocess invocations, or the agent task runner) appear silent for
    minutes, which can cause supervisors that watch for stdout activity to
    kill the process as hung.

    Idempotent and silent: a no-op when streams lack ``reconfigure`` (pytest
    capsys, redirected pipes on some platforms) or when the underlying buffer
    rejects the change (rare; e.g. a stream already locked by another process).
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        with contextlib.suppress(OSError, ValueError):
            reconfigure(encoding="utf-8", errors="replace", line_buffering=True)


ensure_utf8_stdio()

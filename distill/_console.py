"""The shared Rich consoles for the whole CLI.

Foundational module: it imports nothing from ``distill`` except ``_bootstrap``
(stdio setup), so every layer -- commands, pipeline, ingestors, concepts -- can
import the *same* console object without violating the import-direction
contracts. That single-object sharing is load-bearing: because every module
prints through one console, ``--json`` mode can redirect *all* human output to
stderr at once (see :func:`route_human_output_to_stderr`), leaving stdout
carrying only the machine-readable JSON envelope.

Two consoles:

- ``console`` -- human-facing output. Writes to stdout by default; ``--json``
  redirects it to stderr so diagnostics never corrupt the JSON on stdout.
- ``err_console`` -- always stderr, for output that must reach the terminal
  even while stdout is reserved (rare; most callers use ``console``).
"""

from __future__ import annotations

from rich.console import Console

# Side-effect import: reconfigures stdout/stderr to UTF-8 *before* the Console
# objects below are constructed, so a cp1252 Windows console can render the
# CLI's non-ASCII glyphs. Must stay first. Mirrors the guard _helpers.py had.
from distill import _bootstrap  # noqa: F401  -- imported for stdio side effect

__all__ = ["console", "err_console", "is_quiet", "set_json_mode", "set_verbosity"]

# The one shared human-output console. Modules import THIS object (not their own
# Console()) so a single redirect governs every print.
console = Console()

# Always-stderr console for the few callers that must write to the terminal
# while stdout is reserved for structured output.
err_console = Console(stderr=True)
_quiet = False


def set_verbosity(*, quiet: bool = False) -> None:
    """Set process-local human-output verbosity for the shared console."""
    global _quiet
    _quiet = quiet
    console.quiet = quiet


def is_quiet() -> bool:
    """Return whether the shared human console is currently quiet."""
    return _quiet


def set_json_mode(enabled: bool) -> None:
    """Point the shared ``console`` at stderr (JSON mode) or stdout (normal).

    In ``--json`` mode the command writes its JSON envelope straight to stdout,
    so every human/progress/diagnostic ``console.print`` must go elsewhere --
    stderr -- to keep stdout clean for the machine. Idempotent, and called on
    *every* invocation (not just JSON ones) so a reused process -- a test
    runner, the MCP server -- resets the stream rather than leaking a prior
    JSON-mode redirect into a later human-mode call.

    Toggles Rich's dynamic ``stderr`` flag rather than pinning ``console.file``
    to a captured stream: pinning would freeze a transient stdout/stderr (e.g. a
    test runner's buffer) and later raise "I/O operation on closed file". With
    ``_file`` cleared, Rich resolves the live ``sys.stdout``/``sys.stderr`` at
    each write.
    """
    console._file = None  # drop any pinned stream; resolve the live one per write
    console.stderr = enabled

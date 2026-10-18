# pyright: strict
"""Shared key-readiness rows for the human doctor view."""

from rich.console import Console
from rich.markup import escape

from distill.commands._diagnostics import print_diagnostic


def print_key_row(
    console: Console, key: str, status: str, detail: str, *, missing: str = "not set (optional)"
) -> None:
    state, style = "--", "dim"
    if status == "ok":
        state, style = "OK", "green"
        message = detail
    elif status == "not_set":
        message = missing
    elif status == "skipped":
        style = "yellow"
        message = "live validation skipped by no-metered policy"
    elif status == "unknown":
        style = "yellow"
        message = f"could not verify: {detail[:45]}"
    else:
        state, style = "XX", "red"
        message = detail[:60]
    print_diagnostic(
        console, f"  [{style}]{state}[/{style}]  {key:<18}  [{style}]{escape(message)}[/{style}]"
    )

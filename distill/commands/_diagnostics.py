# pyright: strict
"""Hanging diagnostic rows with state words and terminal theme colors."""

from __future__ import annotations

import re

from rich.console import Console
from rich.table import Table
from rich.text import Text

_ROW = re.compile(r"^(\s*(?:OK|--|XX)\s+)(.+?)(\s{2,})(.+)$")


def print_diagnostic(console: Console, message: str) -> None:
    text = Text.from_markup(message)
    match = _ROW.match(text.plain)
    if match is None:
        console.print(text)
        return
    label = text[: match.end(2)]
    details = text[match.start(4) :]
    width = max(1, min(72, console.width))
    table = Table.grid(padding=(0, 2), expand=True)
    table.width = width
    table.add_column(width=min(24, max(1, width - 20)), no_wrap=True)
    table.add_column(ratio=1, overflow="fold")
    table.add_row(label, details)
    console.print(table)

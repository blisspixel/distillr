# pyright: strict
"""Shared appearance controls and metadata for live and exported dashboards."""

from __future__ import annotations

import json
from html import escape
from pathlib import Path

from distill.web.theme import ThemeCollection, load_themes


def theme_metadata(collection: ThemeCollection | None = None) -> str:
    return escape(json.dumps((collection or load_themes()).to_row()))


def appearance_controls(collection: ThemeCollection | None = None, *, token: str = "") -> str:
    collection = collection or load_themes()
    selects: list[str] = []
    for variant in ("dark", "light"):
        options = "".join(
            f'<option value="{theme.slug}">{escape(theme.name)}</option>'
            for theme in collection.themes
            if theme.variant == variant
        )
        selects.append(
            f'<label>{variant.title()} theme<select data-theme-slot="{variant}">{options}</select></label>'
        )
    cards = "".join(
        f'<button type="button" class="theme-card" data-theme="{theme.slug}" data-theme-choice="{theme.slug}">'
        f"<span>{escape(theme.name)}</span><small>Research text</small>"
        '<span class="theme-chips"><i class="chip-success">OK</i><i class="chip-warning">Attention</i><i class="chip-error">Error</i><i class="chip-info">Info</i></span></button>'
        for theme in collection.themes
    )
    import_control = (
        f'<button type="button" data-theme-refresh>Refresh themes</button>'
        f'<label>Import TOML theme<input type="file" accept=".toml" data-theme-file data-theme-token="{escape(token)}"></label>'
        if token
        else ""
    )
    return (
        '<details class="appearance"><summary>Appearance</summary>'
        '<label>Appearance mode<select data-appearance><option value="dark">Dark</option><option value="light">Light</option><option value="system">System</option></select></label>'
        + "".join(selects)
        + '<div class="theme-cards" aria-label="Theme previews">'
        + cards
        + "</div>"
        + import_control
        + '<p data-theme-notice role="status" aria-live="polite"></p></details>'
    )


def standalone_scripts() -> str:
    static = Path(__file__).parent / "static"
    return (static / "theme-init.js").read_text(encoding="utf-8")

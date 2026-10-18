# pyright: strict
"""Strict data themes shared by the live UI and standalone dashboard export."""

from __future__ import annotations

import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Literal, cast

from distill.env_files import xdg_env_path
from distill.library.confined import read_confined_text
from distill.web.theme_colors import color, contrast, distinct_statuses, mix, repair_contrast

THEME_MAX_BYTES = 16 * 1024
BUILTIN_THEMES = Path(__file__).parent / "themes"
_REQUIRED = {
    "bg",
    "surface",
    "text",
    "muted",
    "accent",
    "success",
    "warning",
    "error",
    "info",
    "selection",
}
_OPTIONAL = {"surface-raised", "border", "on-accent", "focus", "rule"}
_TEXT_ROLES = ("accent", "success", "warning", "error", "info")


def validate_slug(value: str) -> str:
    if (
        len(value) > 64
        or re.fullmatch(r"[a-z0-9_][a-z0-9._+\-]*", value, re.ASCII) is None
        or value in {".", ".."}
    ):
        raise ValueError("theme slug must use 1 to 64 ASCII letters, digits, or ._+-")
    return value


def user_themes_dir() -> Path:
    return xdg_env_path().parent / "themes"


def _object(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("theme tables must be objects")
    raw = cast(dict[object, object], value)
    if any(not isinstance(key, str) for key in raw):
        raise ValueError("theme keys must be strings")
    return {str(key): item for key, item in raw.items()}


def _text(data: dict[str, object], key: str, limit: int, default: str = "") -> str:
    value = data.get(key, default)
    if not isinstance(value, str) or len(value) > limit or any(ord(c) < 32 for c in value):
        raise ValueError(f"invalid theme {key}")
    return value


@dataclass(frozen=True)
class Theme:
    name: str
    slug: str
    variant: Literal["dark", "light"]
    colors: Mapping[str, str]
    author: str = ""
    source: str = ""
    license: str = ""
    repairs: tuple[str, ...] = ()

    def to_row(self) -> dict[str, object]:
        return {
            "name": self.name,
            "slug": self.slug,
            "variant": self.variant,
            "colors": dict(self.colors),
            "author": self.author,
            "source": self.source,
            "license": self.license,
            "repairs": list(self.repairs),
        }


def parse_theme(content: str) -> Theme:
    if len(content.encode("utf-8")) > THEME_MAX_BYTES:
        raise ValueError("theme exceeds the 16 KB limit")
    data = _object(tomllib.loads(content))
    if set(data) - {"name", "slug", "variant", "author", "source", "license", "colors"}:
        raise ValueError("unknown theme fields")
    name = _text(data, "name", 64)
    slug = validate_slug(_text(data, "slug", 64))
    variant = _text(data, "variant", 5)
    if not name or variant not in {"dark", "light"}:
        raise ValueError("theme requires a name and dark or light variant")
    raw = _object(data.get("colors"))
    if set(raw) - _REQUIRED - {"optional"} or not set(raw) >= _REQUIRED:
        raise ValueError("theme colors require exactly the documented roles")
    colors = {key: color(raw[key]) for key in _REQUIRED}
    optional = _object(raw.get("optional", {}))
    if set(optional) - _OPTIONAL:
        raise ValueError("unknown optional theme colors")
    colors.update({key: color(value) for key, value in optional.items()})
    repairs = _validate_colors(colors)
    return Theme(
        name,
        slug,
        "dark" if variant == "dark" else "light",
        MappingProxyType(colors),
        _text(data, "author", 128),
        _text(data, "source", 2048),
        _text(data, "license", 128),
        repairs,
    )


def _validate_colors(colors: dict[str, str]) -> tuple[str, ...]:
    backgrounds = (colors["bg"], colors["surface"])
    for role in ("text", "muted"):
        for background in (*backgrounds, colors["selection"]):
            ratio = contrast(colors[role], background)
            if ratio < 4.5:
                raise ValueError(f"{role} is {ratio:.2f}:1 on a text surface (needs 4.5)")
    repairs: list[str] = []
    for role in _TEXT_ROLES:
        repaired = repair_contrast(colors[role], backgrounds, 4.5)
        if repaired != colors[role]:
            repairs.append(f"{role}: {colors[role]} to {repaired} (OKLCH lightness)")
            colors[role] = repaired
    if not distinct_statuses(colors["success"], colors["error"]):
        raise ValueError("success and error hues or lightness must remain distinct")
    colors.setdefault("surface-raised", mix(colors["surface"], colors["text"], 0.06))
    colors.setdefault("focus", colors["accent"])
    colors.setdefault("border", mix(colors["bg"], colors["text"], 0.5))
    colors.setdefault("rule", colors["border"])
    colors.setdefault("on-accent", max(backgrounds, key=lambda bg: contrast(colors["accent"], bg)))
    for role in ("focus", "border"):
        repaired = repair_contrast(colors[role], backgrounds, 3)
        if repaired != colors[role]:
            repairs.append(f"{role}: {colors[role]} to {repaired} (OKLCH lightness)")
            colors[role] = repaired
    if contrast(colors["on-accent"], colors["accent"]) < 4.5:
        raise ValueError("on-accent text needs 4.5:1 contrast")
    return tuple(repairs)


@dataclass(frozen=True)
class ThemeCollection:
    themes: tuple[Theme, ...]
    notices: tuple[str, ...] = ()

    def to_row(self) -> dict[str, object]:
        return {"themes": [theme.to_row() for theme in self.themes], "notices": list(self.notices)}


def _theme_text(path: Path, directory: Path, *, builtin: bool) -> str | None:
    if not builtin:
        return read_confined_text(path, directory, max_bytes=THEME_MAX_BYTES)
    # Installed package assets may share an inode with the installer's cache.
    # Mutable user palettes retain the confined single-link read above.
    try:
        with path.open("rb") as stream:
            content = stream.read(THEME_MAX_BYTES + 1)
        return content.decode("utf-8") if len(content) <= THEME_MAX_BYTES else None
    except (OSError, UnicodeError):
        return None


def load_themes() -> ThemeCollection:
    themes: dict[str, Theme] = {}
    notices: list[str] = []
    for directory, builtin in ((BUILTIN_THEMES, True), (user_themes_dir(), False)):
        for path in sorted(directory.glob("*.toml")):
            try:
                content = _theme_text(path, directory, builtin=builtin)
                if content is None:
                    raise ValueError("unsafe, unreadable, or oversized theme file")
                theme = parse_theme(content)
                if path.stem != theme.slug:
                    raise ValueError("theme filename must match its declared slug")
                if theme.slug in themes:
                    raise ValueError("theme slug already belongs to another theme")
                themes[theme.slug] = theme
            except ValueError as exc:
                if builtin:
                    raise ValueError(f"Invalid built-in theme {path.name}: {exc}") from exc
                notices.append(
                    f'Theme "{path.name}" not loaded: {exc}. Using the house fallback when needed.'
                )
    return ThemeCollection(tuple(themes.values()), tuple(notices))


def theme_css(collection: ThemeCollection | None = None) -> str:
    collection = collection or load_themes()
    blocks: list[str] = []
    for theme in collection.themes:
        colors = dict(theme.colors)
        aliases = {
            "panel": "surface",
            "ink": "text",
            "line": "rule",
            "accent2": "focus",
            "danger": "error",
        }
        colors.update({alias: colors[role] for alias, role in aliases.items()})
        declarations = ";".join(f"--{key}:{value}" for key, value in sorted(colors.items()))
        declarations += ";--accent-light:var(--surface);--accent2-light:var(--surface)"
        blocks.append(f'[data-theme="{theme.slug}"]{{color-scheme:{theme.variant};{declarations}}}')
    return "\n".join(blocks)


def dashboard_styles(collection: ThemeCollection | None = None) -> str:
    static = Path(__file__).parent / "static"
    return "\n".join(
        (
            theme_css(collection),
            (static / "style.css").read_text(encoding="utf-8"),
            (static / "export.css").read_text(encoding="utf-8"),
        )
    )

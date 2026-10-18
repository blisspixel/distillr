# pyright: strict
"""Manage strict, non-executable dashboard theme data."""

from __future__ import annotations

import zipfile

import typer

from distill._console import console
from distill.commands._json import ExitCode, emit_json, exit_with_refusal, json_mode_active
from distill.ingestors.net import NetworkError
from distill.web.theme import load_themes
from distill.web.theme_install import install_theme, remove_theme, update_themes

theme_app = typer.Typer(help="List, install, update, or remove dashboard color themes.")


@theme_app.command("list")
def list_themes() -> None:
    collection = load_themes()
    if json_mode_active():
        emit_json(collection.to_row())
        return
    for theme in collection.themes:
        console.print(f"{theme.slug:28} {theme.variant:5}  {theme.name}", markup=False)
        for repair in theme.repairs:
            console.print(f"  Repair: {repair}", markup=False)
    for notice in collection.notices:
        console.print(notice, markup=False)


@theme_app.command("install")
def install(
    target: str = typer.Argument(help="TOML file or HTTPS GitHub theme repository"),
) -> None:
    try:
        report = install_theme(target)
    except (OSError, ValueError, zipfile.BadZipFile, NetworkError) as exc:
        exit_with_refusal(
            f"Theme not installed: {exc}",
            code=ExitCode.RUNTIME_ERROR,
            reason="theme_install_refused",
            action="theme install",
        )
    if json_mode_active():
        emit_json({"installed": list(report.installed), "ignored": list(report.ignored)})
        return
    console.print("Installed: " + ", ".join(report.installed), markup=False)
    for ignored in report.ignored:
        console.print(f"Ignored non-theme or linked file: {ignored}", markup=False)


@theme_app.command("update")
def update() -> None:
    try:
        reports = update_themes()
    except (OSError, ValueError, zipfile.BadZipFile, NetworkError) as exc:
        exit_with_refusal(
            f"Theme update refused: {exc}",
            code=ExitCode.RUNTIME_ERROR,
            reason="theme_update_refused",
            action="theme update",
        )
    if json_mode_active():
        emit_json({"updated": [list(report.installed) for report in reports]})
        return
    for report in reports:
        console.print("Updated: " + ", ".join(report.installed), markup=False)
    if not reports:
        console.print("No repository-installed themes to update.")


@theme_app.command("remove")
def remove(slug: str) -> None:
    try:
        remove_theme(slug)
    except (OSError, ValueError) as exc:
        exit_with_refusal(
            f"Theme removal refused: {exc}",
            code=ExitCode.RUNTIME_ERROR,
            reason="theme_remove_refused",
            action="theme remove",
        )
    if json_mode_active():
        emit_json({"removed": slug})
        return
    console.print(f"Removed user theme: {slug}", markup=False)

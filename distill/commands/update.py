"""``distill update`` -- self-update to the latest published distillr.

Detects how distillr was installed (uv tool / pipx / pip / source checkout) and
runs the right upgrade, or with ``--check`` just reports whether a newer release
exists. Registered onto the app from ``distill.cli`` (mirroring ``ingest`` /
``audit``). All logic lives in :mod:`distill.update`; this is the thin Typer +
presentation layer.
"""

from __future__ import annotations

import typer

from distill._console import console
from distill.commands._json import emit_json, json_mode_active

__all__ = ["register", "update_cmd"]


def _report_check(current: str, latest: str | None, method: str, newer: bool) -> None:
    if json_mode_active():
        emit_json(
            {
                "current": current,
                "latest": latest,
                "update_available": newer,
                "install_method": method,
            }
        )
        return
    console.print(f"  Installed: [bold]{current}[/bold]")
    console.print(f"  Latest:    [bold]{latest or 'unknown (offline?)'}[/bold]")
    console.print(f"  Install:   {method}")
    if newer:
        console.print("\n  [yellow]Update available.[/yellow] Run [bold]distill update[/bold].")
    elif latest:
        console.print("\n  [green]You're on the latest release.[/green]")


def _report_source(current: str, method: str) -> None:
    msg = (
        "Source/editable install -- update with `git pull` then `uv sync` (or `pip install -e .`)."
    )
    if json_mode_active():
        emit_json({"current": current, "install_method": method, "message": msg})
        return
    console.print(f"  [cyan]{msg}[/cyan]")


def _report_already_latest(current: str, latest: str | None) -> None:
    if json_mode_active():
        emit_json(
            {"current": current, "latest": latest, "upgraded": False, "reason": "already-latest"}
        )
        return
    console.print(f"  [green]Already on the latest release ({current}).[/green]")


def _do_upgrade(current: str, latest: str | None, method: str) -> None:
    from distill.update import run_self_update, upgrade_command

    cmd = upgrade_command(method)
    cmd_str = " ".join(cmd) if cmd else method
    if not json_mode_active():
        console.print(f"  Upgrading via [dim]{cmd_str}[/dim] ...")

    ok, detail, was_noop = run_self_update()

    if json_mode_active():
        emit_json(
            {
                "current": current,
                "latest": latest,
                "upgraded": ok and not was_noop,
                "new_version": detail if ok else None,
                "error": None if ok else detail,
                "install_method": method,
            }
        )
        if not ok:
            raise typer.Exit(1)
        return

    if not ok:
        console.print(f"  [red]Update failed:[/red] {detail}")
        console.print(f"  [dim]Try manually: {cmd_str}[/dim]")
        raise typer.Exit(1)
    if was_noop:
        console.print(f"  [green]Already at the latest release ({detail}).[/green]")
    else:
        console.print(f"  [green]Updated to {detail}.[/green] Restart any running distill session.")


def update_cmd(
    check: bool = typer.Option(
        False, "--check", help="Report whether a newer release exists, without upgrading."
    ),
) -> None:
    """Update distillr to the latest published version (or --check for status)."""
    from distill.update import (
        METHOD_SOURCE,
        detect_install_method,
        fetch_latest_version,
        get_installed_version,
        latest_is_newer,
    )

    current = get_installed_version() or "unknown"
    method = detect_install_method()
    latest = fetch_latest_version()
    newer = latest_is_newer(current, latest)

    if check:
        _report_check(current, latest, method, newer)
    elif method == METHOD_SOURCE:
        _report_source(current, method)
    elif not newer and latest:
        _report_already_latest(current, latest)
    else:
        _do_upgrade(current, latest, method)


def register(app: typer.Typer) -> None:
    """Attach the ``update`` command to the app (called from distill.cli)."""
    app.command(name="update", rich_help_panel="Maintain")(update_cmd)

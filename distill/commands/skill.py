# pyright: strict
"""Agent Skill lifecycle commands."""

from __future__ import annotations

import shlex
from pathlib import Path
from typing import NoReturn, cast

import typer
from rich.table import Table

from distill._console import console
from distill.agent_skills import (
    CLIENTS,
    SCOPES,
    SkillBundle,
    SkillBundleError,
    SkillInstallError,
    apply_install,
    export_skill,
    inspect_install,
    load_bundled_skill,
    native_client_guidance,
    remove_install,
    resolve_install_target,
)
from distill.commands._json import ExitCode, emit_json, json_mode_active

__all__ = ["skill_app"]

skill_app = typer.Typer(
    help="Inspect, install, update, remove, or export the bundled Agent Skill.",
    no_args_is_help=True,
)


def _bundle() -> SkillBundle:
    try:
        return load_bundled_skill()
    except SkillBundleError as exc:
        _exit_skill_error(exc, reason="skill_bundle_invalid", code=ExitCode.CONFIG_ERROR)


def _target(client: str, scope: str, project_root: Path | None) -> Path:
    try:
        return resolve_install_target(client, scope, project_root=project_root)
    except SkillInstallError as exc:
        _exit_skill_error(exc, reason="skill_target_invalid", code=ExitCode.USAGE_ERROR)


def _exit_skill_error(
    exc: Exception,
    *,
    reason: str,
    code: ExitCode = ExitCode.RUNTIME_ERROR,
) -> NoReturn:
    from distill.commands._json import emit_json_refusal, phase_for_exit_code

    if json_mode_active():
        emit_json_refusal(
            reason=reason,
            error=str(exc),
            phase=phase_for_exit_code(code),
            action="skill",
            limit={"kind": "skill_install"},
        )
    else:
        console.print(f"[red]{exc}[/red]")
    raise typer.Exit(int(code))


def _status_payload(
    bundle: SkillBundle,
    client: str,
    scope: str,
    project_root: Path | None,
) -> dict[str, object]:
    destination = _target(client, scope, project_root)
    status = inspect_install(bundle, destination, client=client, scope=scope)
    return {
        "client": client,
        "native": native_client_guidance(client, scope),
        "direct_install": status.as_dict(),
    }


def _approval_command(
    action: str,
    client: str,
    scope: str,
    project_root: Path | None,
) -> str:
    arguments = [
        "distill",
        "skill",
        action,
        "--client",
        client.strip().lower(),
        "--scope",
        scope.strip().lower(),
    ]
    if project_root is not None:
        arguments.extend(("--project-root", str(project_root)))
    arguments.append("--yes")
    return shlex.join(arguments)


@skill_app.command(name="doctor")
def skill_doctor_cmd(
    client: str = typer.Option(
        "all",
        "--client",
        help="Client to inspect: all, portable, codex, claude, gemini, grok, antigravity.",
    ),
    scope: str = typer.Option(
        "project",
        "--scope",
        help="Direct install scope: project or user.",
    ),
    project_root: Path | None = typer.Option(
        None,
        "--project-root",
        help="Project root for project-scoped direct install inspection.",
    ),
) -> None:
    """Verify the wheel bundle and report native plus direct-install readiness."""

    bundle = _bundle()
    normalized_client = client.strip().lower()
    normalized_scope = scope.strip().lower()
    if normalized_client != "all" and normalized_client not in CLIENTS:
        _exit_skill_error(
            SkillInstallError(f"Unknown client '{client}'. Choose: all, {', '.join(CLIENTS)}"),
            reason="skill_target_invalid",
            code=ExitCode.USAGE_ERROR,
        )
    if normalized_scope not in SCOPES:
        _exit_skill_error(
            SkillInstallError(f"Unknown scope '{scope}'. Choose: {', '.join(SCOPES)}"),
            reason="skill_target_invalid",
            code=ExitCode.USAGE_ERROR,
        )
    selected = CLIENTS if normalized_client == "all" else (normalized_client,)
    rows = [
        _status_payload(bundle, selected_client, normalized_scope, project_root)
        for selected_client in selected
    ]
    data = {
        "bundle": bundle.as_dict(),
        "clients": rows,
        "billing": (
            "Skill presence and client login do not prove included-plan or no-metered usage. "
            "Active-session worker results remain host-managed."
        ),
    }
    if json_mode_active():
        emit_json(data)
        return

    console.print(
        f"Bundled [bold]{bundle.name}[/bold] {bundle.version} verified "
        f"({len(bundle.files)} files, {bundle.bundle_sha256[:12]}...)."
    )
    table = Table(title=f"Agent Skill readiness ({normalized_scope} scope)")
    table.add_column("Client")
    table.add_column("CLI")
    table.add_column("Direct target")
    table.add_column("State")
    for row in rows:
        native_value = row["native"]
        direct_value = row["direct_install"]
        assert isinstance(native_value, dict)
        assert isinstance(direct_value, dict)
        native = cast(dict[str, object], native_value)
        direct = cast(dict[str, object], direct_value)
        binary_state = (
            "n/a"
            if native.get("binary") is None
            else ("found" if native.get("binary_found") is True else "missing")
        )
        table.add_row(
            str(row["client"]),
            binary_state,
            str(direct["destination"]),
            str(direct["state"]),
        )
    console.print(table)
    console.print(
        "[yellow]Client presence does not prove included-plan billing. "
        "Active-session workers remain host-managed.[/yellow]"
    )


@skill_app.command(name="install")
def skill_install_cmd(
    client: str = typer.Option(
        "portable",
        "--client",
        help="Direct-discovery target: portable, codex, claude, gemini, grok, antigravity.",
    ),
    scope: str = typer.Option("project", "--scope", help="Install scope: project or user."),
    project_root: Path | None = typer.Option(
        None,
        "--project-root",
        help="Project root for a project-scoped install.",
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Apply the displayed install, adoption, or clean managed update.",
    ),
) -> None:
    """Preview or apply a verified direct skill installation."""

    client = client.strip().lower()
    scope = scope.strip().lower()
    bundle = _bundle()
    destination = _target(client, scope, project_root)
    status = inspect_install(bundle, destination, client=client, scope=scope)
    if status.action == "refuse":
        _exit_skill_error(
            SkillInstallError(status.detail or f"Cannot install over state: {status.state}"),
            reason="skill_install_conflict",
        )
    if not yes:
        data = {
            "approved": False,
            "changed": False,
            "plan": status.as_dict(),
            "next": (
                _approval_command("install", client, scope, project_root)
                if status.action != "none"
                else None
            ),
        }
        if json_mode_active():
            emit_json(data)
        elif status.action == "none":
            console.print(f"[green]{bundle.name} is already current at {destination}.[/green]")
        else:
            console.print(
                f"Plan: {status.action} [bold]{bundle.name}[/bold] at {destination}. "
                "No files changed. Add --yes to apply."
            )
        return
    try:
        installed = apply_install(
            bundle,
            destination,
            client=client,
            scope=scope,
        )
    except SkillInstallError as exc:
        _exit_skill_error(exc, reason="skill_install_failed")
    data = {
        "approved": True,
        "changed": status.action != "none",
        "previous_state": status.state,
        "install": installed.as_dict(),
    }
    if json_mode_active():
        emit_json(data)
        return
    console.print(f"[green]{bundle.name} {bundle.version} is current at {destination}.[/green]")


@skill_app.command(name="uninstall")
def skill_uninstall_cmd(
    client: str = typer.Option(
        "portable",
        "--client",
        help="Direct-discovery target: portable, codex, claude, gemini, grok, antigravity.",
    ),
    scope: str = typer.Option("project", "--scope", help="Install scope: project or user."),
    project_root: Path | None = typer.Option(
        None,
        "--project-root",
        help="Project root for a project-scoped install.",
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Remove the clean Distill-managed direct installation.",
    ),
) -> None:
    """Preview or remove only a clean Distill-managed direct installation."""

    client = client.strip().lower()
    scope = scope.strip().lower()
    bundle = _bundle()
    destination = _target(client, scope, project_root)
    status = inspect_install(bundle, destination, client=client, scope=scope)
    removable = status.state in {"current", "update-available"} and status.managed and status.safe
    if status.state != "absent" and not removable:
        _exit_skill_error(
            SkillInstallError(
                status.detail or "Refusing to remove an unmanaged or modified installation"
            ),
            reason="skill_uninstall_conflict",
        )
    if not yes:
        data = {
            "approved": False,
            "changed": False,
            "plan": {
                **status.as_dict(),
                "action": "none" if status.state == "absent" else "remove",
            },
            "next": (
                None
                if status.state == "absent"
                else _approval_command("uninstall", client, scope, project_root)
            ),
        }
        if json_mode_active():
            emit_json(data)
        elif status.state == "absent":
            console.print(f"No direct {bundle.name} installation exists at {destination}.")
        else:
            console.print(
                f"Plan: remove the clean managed install at {destination}. "
                "No files changed. Add --yes to apply."
            )
        return
    try:
        removed = remove_install(
            bundle,
            destination,
            client=client,
            scope=scope,
        )
    except SkillInstallError as exc:
        _exit_skill_error(exc, reason="skill_uninstall_failed")
    data = {
        "approved": True,
        "changed": status.state != "absent",
        "previous_state": status.state,
        "install": removed.as_dict(),
    }
    if json_mode_active():
        emit_json(data)
        return
    if status.state == "absent":
        console.print(f"No direct {bundle.name} installation exists at {destination}.")
    else:
        console.print(f"Removed the managed {bundle.name} installation from {destination}.")


@skill_app.command(name="export")
def skill_export_cmd(
    output: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Destination .skill or .zip path. Defaults to the current directory.",
    ),
    overwrite: bool = typer.Option(
        False,
        "--overwrite",
        help="Replace existing regular archive and checksum files.",
    ),
) -> None:
    """Export a deterministic Agent Skill archive and SHA-256 sidecar."""

    bundle = _bundle()
    destination = output or Path.cwd() / f"{bundle.name}-{bundle.version}.skill"
    try:
        result = export_skill(bundle, destination, overwrite=overwrite)
    except SkillInstallError as exc:
        _exit_skill_error(exc, reason="skill_export_failed")
    if json_mode_active():
        emit_json(result)
        return
    console.print(f"Exported {result['path']}")
    console.print(f"SHA-256: {result['sha256']}")
    console.print(f"Checksum: {result['checksum_path']}")

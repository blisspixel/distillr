# pyright: strict
"""Host-session worker commands for deferred AgentProvider tasks."""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any, NoReturn, cast

import typer
from rich.table import Table

from distill._console import console
from distill.commands._helpers import get_config
from distill.commands._json import ExitCode, emit_json, json_mode_active
from distill.worker import (
    AgentTaskQueue,
    WorkerTaskConflict,
    WorkerTaskError,
    WorkerTaskInvalid,
    WorkerTaskNotFound,
)

__all__ = ["worker_app"]

worker_app = typer.Typer(
    help="Claim and complete deferred tasks from the active agent session.",
    no_args_is_help=True,
)


def _queue() -> AgentTaskQueue:
    return AgentTaskQueue(get_config().library_dir / ".distill")


@worker_app.command(name="list")
def worker_list_cmd() -> None:
    """List deferred tasks without printing their prompt contents."""

    rows = cast(list[dict[str, Any]], _worker_call(lambda queue: queue.list_tasks()))
    if json_mode_active():
        emit_json({"tasks": rows, "count": len(rows)})
        return
    if not rows:
        console.print("No deferred worker tasks.")
        return
    table = Table(title="Deferred worker tasks")
    table.add_column("Task")
    table.add_column("Workload")
    table.add_column("Status")
    table.add_column("Host")
    table.add_column("Lease")
    for row in rows:
        claim = row.get("claim")
        claim_data = cast(dict[str, object], claim) if isinstance(claim, dict) else {}
        lease = str(claim_data.get("lease_expires_at", ""))
        if claim_data.get("lease_expired") is True:
            lease = f"expired {lease}"
        table.add_row(
            str(row.get("task_id", "?")),
            str(row.get("workload", "?")),
            str(row.get("status", "invalid")),
            str(claim_data.get("host", "")),
            lease,
        )
    console.print(table)


@worker_app.command(name="claim")
def worker_claim_cmd(
    host: str = typer.Option(
        ...,
        "--host",
        help="Active host session, such as codex, claude, grok, or antigravity.",
    ),
    worker_id: str = typer.Option(
        "interactive",
        "--worker-id",
        help="Stable label for this worker session.",
    ),
    workload: str = typer.Option(
        "",
        "--workload",
        help="Claim only tasks with this workload tag.",
    ),
    lease_seconds: int = typer.Option(
        3600,
        "--lease-seconds",
        min=60,
        max=604_800,
        help="Informational claim lease between 60 seconds and 7 days.",
    ),
) -> None:
    """Claim one pending task and create a scratch-only workspace."""

    result = _worker_call(
        lambda queue: queue.claim(
            host=host,
            worker_id=worker_id,
            workload=workload,
            lease_seconds=lease_seconds,
        )
    )
    if result is None:
        data = {"claimed": False, "reason": "no_pending_tasks"}
        if json_mode_active():
            emit_json(data)
        else:
            console.print("No eligible unclaimed worker tasks.")
        return
    if json_mode_active():
        emit_json(result)
        return
    console.print(f"Claimed task [bold]{result['task_id']}[/bold] ({result['workload']}).")
    console.print(f"Read: {result['prompt_path']}")
    console.print(f"Write only: {result['result_path']}")
    console.print(
        "Set DISTILL_WORKER_CLAIM_TOKEN to the returned token, then submit "
        "without placing the token in process arguments."
    )
    console.print(
        "[yellow]Billing is host-managed. Distill has not proved this session "
        "is no-metered.[/yellow]"
    )
    console.print(f"Claim token: {result['claim_token']}")


@worker_app.command(name="submit")
def worker_submit_cmd(
    task_id: str = typer.Argument(help="Twelve-character task id returned by worker claim."),
    model: str = typer.Option(
        "",
        "--model",
        help="Host model label when known.",
    ),
    input_tokens: int | None = typer.Option(
        None,
        "--input-tokens",
        min=0,
        help="Host-reported input tokens. Supply with --output-tokens.",
    ),
    output_tokens: int | None = typer.Option(
        None,
        "--output-tokens",
        min=0,
        help="Host-reported output tokens. Supply with --input-tokens.",
    ),
) -> None:
    """Validate and publish the result.md from a claimed workspace."""

    claim_token = _worker_claim_token()
    result = _worker_call(
        lambda queue: queue.submit(
            task_id,
            claim_token=claim_token,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
    )
    if json_mode_active():
        emit_json(result)
        return
    console.print(f"Submitted task [bold]{result['task_id']}[/bold].")
    console.print(f"Published result: {result['published_result_path']}")
    console.print(f"Receipt: {result['submission_receipt_path']}")


@worker_app.command(name="abandon")
def worker_abandon_cmd(
    task_id: str = typer.Argument(help="Twelve-character task id returned by worker claim."),
    reason: str = typer.Option(
        ...,
        "--reason",
        help="Short reason recorded in the abandonment receipt.",
    ),
) -> None:
    """Release a claim without publishing its scratch result."""

    claim_token = _worker_claim_token()
    result = _worker_call(
        lambda queue: queue.abandon(
            task_id,
            claim_token=claim_token,
            reason=reason,
        )
    )
    if json_mode_active():
        emit_json(result)
        return
    console.print(f"Released task [bold]{result['task_id']}[/bold].")
    console.print(f"Receipt: {result['abandonment_receipt_path']}")


@worker_app.command(name="release-expired")
def worker_release_expired_cmd(
    task_id: str = typer.Argument(help="Task id whose expired claim should be released."),
    yes: bool = typer.Option(
        False,
        "--yes",
        help="Release the expired claim. Without this, show the requested action only.",
    ),
) -> None:
    """Release a stale claim after its recorded lease has expired."""

    if not yes:
        data = {
            "released": False,
            "approved": False,
            "task_id": task_id,
            "next": f"distill worker release-expired {task_id} --yes",
        }
        if json_mode_active():
            emit_json(data)
        else:
            console.print("No claim was released. Add --yes after checking worker list.")
        return
    result = _worker_call(lambda queue: queue.release_expired(task_id))
    if json_mode_active():
        emit_json(result)
        return
    console.print(f"Released expired claim for task [bold]{result['task_id']}[/bold].")
    console.print(f"Receipt: {result['release_receipt_path']}")


def _worker_call(action: Callable[[AgentTaskQueue], Any]) -> Any:
    try:
        return action(_queue())
    except WorkerTaskError as exc:
        _exit_worker_error(exc)


def _worker_claim_token() -> str:
    """Read the worker bearer token without accepting it in process arguments."""

    token = os.environ.get("DISTILL_WORKER_CLAIM_TOKEN", "")
    if not token:
        _exit_worker_error(
            WorkerTaskInvalid("Set DISTILL_WORKER_CLAIM_TOKEN before submit or abandon.")
        )
    return token


def _exit_worker_error(exc: WorkerTaskError) -> NoReturn:
    if isinstance(exc, WorkerTaskNotFound):
        code = ExitCode.NOT_FOUND
        reason = "worker_task_not_found"
    elif isinstance(exc, WorkerTaskInvalid):
        code = ExitCode.CONFIG_ERROR
        reason = "worker_task_invalid"
    elif isinstance(exc, WorkerTaskConflict):
        code = ExitCode.RUNTIME_ERROR
        reason = "worker_task_conflict"
    else:
        code = ExitCode.RUNTIME_ERROR
        reason = "worker_task_error"
    if json_mode_active():
        emit_json({"reason": reason}, error=str(exc))
    else:
        console.print(f"[red]{exc}[/red]")
    raise typer.Exit(int(code))

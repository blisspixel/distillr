"""Private editorial CLI with explicit routes and durable budget visibility."""

from __future__ import annotations

from pathlib import Path

import typer

from distill._console import console
from distill.commands._json import ExitCode, emit_json, json_mode_active
from distill.editorial.budget import WeeklyLedger
from distill.editorial.perspective import init_perspective, load_perspective
from distill.editorial.routing import select_routes
from distill.editorial.sources import collect_sources, save_receipts
from distill.editorial.workflow import build_article
from distill.llm.router import RouterConfig
from distill.pipeline.budget import BudgetExceededError

editorial_app = typer.Typer(
    help="Research and write private, budgeted, receipt-backed blog drafts."
)
_PERSPECTIVE = Path("private/perspective.toml")
_WORKSPACE = Path("private/editorial")


def _show(data: object) -> None:
    if json_mode_active():
        emit_json(data=data)
    else:
        console.print(data, markup=False)


def _error(exc: Exception) -> None:
    from distill.llm.providers.openrouter import OpenRouterRequestError

    code = (
        ExitCode.BUDGET_EXCEEDED if isinstance(exc, BudgetExceededError) else ExitCode.CONFIG_ERROR
    )
    # Provider exceptions can include request data. Only local budget/config
    # errors have an operator-facing message here.
    message = (
        str(exc)
        if isinstance(
            exc, (BudgetExceededError, ValueError, FileNotFoundError, OpenRouterRequestError)
        )
        else type(exc).__name__
    )
    if json_mode_active():
        emit_json(error=message)
    else:
        console.print(message, markup=False)
    raise typer.Exit(int(code))


@editorial_app.command("init")
def editorial_init(
    perspective: Path = typer.Option(
        _PERSPECTIVE, "--perspective", help="Private author TOML file to create."
    ),
) -> None:
    """Create a generic private perspective. No API calls and no overwrite."""
    try:
        _show({"perspective": str(init_perspective(perspective)), "metered_enabled": False})
    except (OSError, ValueError) as exc:
        _error(exc)


@editorial_app.command("preview")
def editorial_preview(
    perspective: Path = typer.Option(_PERSPECTIVE, "--perspective"),
    workspace: Path = typer.Option(
        _WORKSPACE, "--workspace", help="Shared private workspace and weekly ledger."
    ),
) -> None:
    """Show source scope, route readiness and budget without model calls."""
    try:
        brief = load_perspective(perspective)
        base = RouterConfig()
        try:
            routes, reason = select_routes(brief, base)
            selected = {role: list(config.resolve("report")) for role, config in routes.items()}
        except ValueError as exc:
            selected, reason = {}, str(exc)
        _show(
            {
                "topics": brief.topics,
                "sources": brief.sources.model_dump(),
                "routes": selected,
                "route_status": reason,
                "budget": WeeklyLedger(workspace / "budget.jsonl").status(brief.budget.weekly_usd),
                "per_run_usd": brief.budget.per_run_usd,
                "ready": bool(selected),
            }
        )
    except Exception as exc:
        _error(exc)


@editorial_app.command("run")
def editorial_run(
    perspective: Path = typer.Option(_PERSPECTIVE, "--perspective"),
    workspace: Path = typer.Option(_WORKSPACE, "--workspace"),
    paid_only: bool = typer.Option(
        False,
        "--paid-only",
        help="Validate the configured paid routes; still requires metered opt-in and budget.",
    ),
    retonr: Path | None = typer.Option(
        None, "--retonr", help="Optional native Retonr binary for its supported candidate check."
    ),
    receipt_dir: Path | None = typer.Option(
        None,
        "--receipt-dir",
        help="Use explicitly supplied recent receipt JSON files instead of fetching sources.",
    ),
) -> None:
    """Capture news and produce reviewed Markdown and DOCX. Never publish."""
    try:
        brief = load_perspective(perspective)
        directory = build_article(
            brief,
            workspace,
            RouterConfig(),
            paid_only=paid_only,
            receipt_dir=receipt_dir,
            retonr_executable=retonr,
            progress=None
            if json_mode_active()
            else lambda message: console.print(message, markup=False),
        )
        _show(
            {
                "status": "ready_for_review",
                "markdown": str(directory / "article.md"),
                "docx": str(directory / "article.docx"),
                "manifest": str(directory / "manifest.json"),
            }
        )
    except Exception as exc:
        _error(exc)


@editorial_app.command("capture")
def editorial_capture(
    destination: Path = typer.Argument(
        help="New private directory for current receipt JSON files."
    ),
    perspective: Path = typer.Option(_PERSPECTIVE, "--perspective"),
) -> None:
    """Fetch a reviewable source packet without making model calls."""
    try:
        brief = load_perspective(perspective)
        destination.mkdir(parents=True, exist_ok=False)
        sources, failures = collect_sources(brief.sources)
        save_receipts(destination, sources)
        _show({"receipts": str(destination), "source_count": len(sources), "failures": failures})
    except Exception as exc:
        _error(exc)


def register(app: typer.Typer) -> None:
    app.add_typer(editorial_app, name="editorial", rich_help_panel="Research")

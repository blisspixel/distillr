# pyright: strict
"""``distill provider`` -- show, list, and set the analysis route."""

from __future__ import annotations

import os
from typing import NoReturn

import typer
from rich.markup import escape
from rich.table import Table

from distill._console import console
from distill.commands._helpers import isatty, tty_prompt
from distill.commands._json import ExitCode, emit_json, json_mode_active
from distill.commands.init import env_file_path, set_env_var
from distill.llm.provider_catalog import (
    PROVIDER_HELP,
    ROUTABLE_PROVIDERS,
    default_model_for_provider,
    known_models_for_provider,
    normalize_provider_name,
    price_summary,
    validate_provider_route,
)
from distill.llm.router import RouterConfig

__all__ = ["provider_app", "register"]

provider_app = typer.Typer(
    help="Show, list, or set the analysis provider and model.",
    invoke_without_command=True,
    no_args_is_help=False,
)


def register(app: typer.Typer) -> None:
    """Attach provider commands under Maintain."""
    app.add_typer(provider_app, name="provider", rich_help_panel="Maintain")


@provider_app.callback(invoke_without_command=True)
def provider_root(ctx: typer.Context) -> None:
    """Show the active analysis route when no subcommand is given."""
    if ctx.invoked_subcommand is None:
        provider_show_cmd()


@provider_app.command("show")
def provider_show_cmd() -> None:
    """Show the active analysis provider and model route.

    Examples:
      distill provider
      distill provider show
      distill --json provider show
    """
    payload = _current_route_payload()
    if json_mode_active():
        emit_json(payload)
        return

    console.print(
        f"  Provider  [bold]{escape(str(payload['provider']))}[/bold]  "
        f"[dim]{escape(str(payload['provider_help']))}[/dim]"
    )
    console.print(f"  Model     [bold]{escape(str(payload['model']))}[/bold]")
    if payload.get("price"):
        console.print(f"  Pricing   [dim]{escape(str(payload['price']))}[/dim]")
    console.print(f"  Cost mode [dim]{escape(str(payload['cost_mode']))}[/dim]")
    console.print(f"  Env file  [dim]{escape(str(payload['env_file']))}[/dim]")
    console.print()
    console.print("[dim]Change default:[/dim]  distill provider set <provider> [model]")
    console.print(
        "[dim]One run only:[/dim]  distill --provider <provider> --model <model> <command>"
    )


@provider_app.command("list")
def provider_list_cmd(
    provider: str | None = typer.Argument(
        None,
        help="Optional provider to list models for (xai, gemini, anthropic, ...).",
    ),
) -> None:
    """List routable providers and known cloud models.

    Examples:
      distill provider list
      distill provider list gemini
      distill --json provider list
    """
    if provider:
        try:
            name = normalize_provider_name(provider)
        except ValueError as exc:
            _exit_usage(str(exc))
        models = known_models_for_provider(name)
        payload: dict[str, object] = {
            "provider": name,
            "help": PROVIDER_HELP[name],
            "default_model": default_model_for_provider(name),
            "models": [{"id": model_id, "price": price_summary(model_id)} for model_id in models],
            "note": _list_note(name),
        }
        if json_mode_active():
            emit_json(payload)
            return
        console.print(f"[bold]{escape(name)}[/bold]  [dim]{escape(PROVIDER_HELP[name])}[/dim]")
        if models:
            table = Table(show_header=True, header_style="bold")
            table.add_column("Model")
            table.add_column("Price (standard paid)")
            preferred = default_model_for_provider(name)
            for model_id in models:
                label = model_id
                if model_id == preferred:
                    label = f"{model_id}  (recommended)"
                table.add_row(label, price_summary(model_id))
            console.print(table)
        else:
            console.print(f"  [dim]{_list_note(name)}[/dim]")
        return

    providers_payload = [
        {
            "id": name,
            "help": PROVIDER_HELP[name],
            "default_model": default_model_for_provider(name),
            "models": known_models_for_provider(name),
            "note": _list_note(name),
        }
        for name in ROUTABLE_PROVIDERS
    ]
    if json_mode_active():
        emit_json({"providers": providers_payload})
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("Provider")
    table.add_column("Default model")
    table.add_column("Notes")
    for row in providers_payload:
        default = str(row["default_model"] or "-")
        table.add_row(str(row["id"]), default, str(row["help"]))
    console.print(table)
    console.print()
    console.print("[dim]Models for one provider:[/dim]  distill provider list gemini")
    console.print("[dim]Set default route:[/dim]     distill provider set gemini gemini-3.6-flash")


@provider_app.command("set")
def provider_set_cmd(
    provider: str | None = typer.Argument(
        None,
        help="Provider id: xai, gemini, anthropic, ollama, lmstudio, agent.",
    ),
    model: str | None = typer.Argument(
        None,
        help="Model id. Optional for cloud providers that have a catalog default.",
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Accept interactive defaults without prompting (non-TTY safe).",
    ),
) -> None:
    """Persist DISTILL_PROVIDER and DISTILL_MODEL in the working-directory .env.

    Interactive when run on a TTY without arguments. Non-interactive shells must
    pass an explicit provider (and a model for local or agent routes).

    Examples:
      distill provider set gemini gemini-3.6-flash
      distill provider set gemini
      distill provider set ollama qwen3.5:27b
      distill provider set
    """
    try:
        chosen_provider, chosen_model = _resolve_set_selection(
            provider=provider,
            model=model,
            yes=yes,
        )
    except ValueError as exc:
        _exit_usage(str(exc))

    env_path = env_file_path()
    try:
        set_env_var(env_path, "DISTILL_PROVIDER", chosen_provider)
        set_env_var(env_path, "DISTILL_MODEL", chosen_model)
    except (OSError, ValueError) as exc:
        message = f"Could not update {env_path}: {exc}"
        if json_mode_active():
            emit_json(
                {"reason": "env_file_error", "env_file": str(env_path)},
                error=message,
            )
        else:
            console.print(f"[red]{message}[/red]")
        raise typer.Exit(int(ExitCode.RUNTIME_ERROR)) from exc

    os.environ["DISTILL_PROVIDER"] = chosen_provider
    os.environ["DISTILL_MODEL"] = chosen_model

    price = _catalog_price(chosen_model)
    payload = {
        "provider": chosen_provider,
        "model": chosen_model,
        "price": price,
        "env_file": str(env_path),
        "provider_help": PROVIDER_HELP[chosen_provider],
    }

    if json_mode_active():
        emit_json(payload)
        return

    console.print(
        f"  [green]Set[/green] DISTILL_PROVIDER={escape(chosen_provider)}  "
        f"DISTILL_MODEL={escape(chosen_model)}"
    )
    console.print(f"  [dim]Wrote[/dim] {escape(str(env_path))}")
    if price:
        console.print(f"  [dim]Pricing[/dim] {escape(price)}")
    console.print()
    console.print("[dim]Check readiness:[/dim]  distill --cost-mode paid-ok doctor")
    console.print(
        "[dim]One-run override:[/dim]  distill --provider "
        f"{escape(chosen_provider)} --model {escape(chosen_model)} <command>"
    )


def _catalog_price(model_id: str) -> str:
    from distill.llm.cost import PRICING

    if model_id in PRICING:
        return price_summary(model_id)
    return ""


def _current_route_payload() -> dict[str, object]:
    config = RouterConfig()
    provider_name, model_id = config.resolve("analysis")
    help_text = PROVIDER_HELP.get(provider_name, "custom or unrecognized provider")
    return {
        "provider": provider_name,
        "model": model_id,
        "provider_help": help_text,
        "price": _catalog_price(model_id),
        "cost_mode": config.cost_mode,
        "env_file": str(env_file_path()),
    }


def _list_note(provider: str) -> str:
    if provider in {"ollama", "lmstudio"}:
        return "Use an exact model id from the local inventory (see distill doctor)."
    if provider == "agent":
        return "Host-managed deferred work; not a live cloud API route."
    return "Catalog models from Distill pricing; any API-valid id is also accepted."


def _resolve_set_selection(
    *,
    provider: str | None,
    model: str | None,
    yes: bool,
) -> tuple[str, str]:
    interactive = isatty() and not yes
    chosen_provider = (provider or "").strip()
    chosen_model = (model or "").strip()

    if not chosen_provider:
        if not interactive:
            raise ValueError(
                "Provider is required without a TTY. "
                "Example: distill provider set gemini gemini-3.6-flash"
            )
        chosen_provider = _prompt_provider()

    name = normalize_provider_name(chosen_provider)

    if not chosen_model:
        default = default_model_for_provider(name)
        if default and (yes or not interactive):
            chosen_model = default
        elif interactive:
            chosen_model = _prompt_model(name, default=default)
        else:
            raise ValueError(
                f"Model is required for provider '{name}'. "
                f"Example: distill provider set {name} <model-id>"
            )

    if not chosen_model:
        raise ValueError(
            f"Model is required for provider '{name}'. "
            f"Example: distill provider set {name} <model-id>"
        )

    return validate_provider_route(name, chosen_model)


def _prompt_provider() -> str:
    console.print("[bold]Provider[/bold]")
    for index, name in enumerate(ROUTABLE_PROVIDERS, start=1):
        console.print(f"  {index}. {name:<10}  [dim]{escape(PROVIDER_HELP[name])}[/dim]")
    answer = tty_prompt(
        "Choose provider number or name",
        default="1",
        non_tty_default="",
    ).strip()
    if not answer:
        raise ValueError("No provider selected.")
    if answer.isdigit():
        index = int(answer)
        if 1 <= index <= len(ROUTABLE_PROVIDERS):
            return ROUTABLE_PROVIDERS[index - 1]
        raise ValueError(f"Provider choice out of range: {answer}")
    return answer


def _prompt_model(provider: str, *, default: str) -> str:
    models = known_models_for_provider(provider)
    if models:
        console.print(f"[bold]Model ({escape(provider)})[/bold]")
        for index, model_id in enumerate(models, start=1):
            marker = "  (recommended)" if model_id == default else ""
            console.print(
                f"  {index}. {model_id:<28}  [dim]{escape(price_summary(model_id))}{marker}[/dim]"
            )
        console.print("  Or type an exact API model id not listed above.")
        answer = tty_prompt(
            "Choose model number or id",
            default="1" if default else "",
            non_tty_default=default,
        ).strip()
        if not answer:
            return default
        if answer.isdigit():
            index = int(answer)
            if 1 <= index <= len(models):
                return models[index - 1]
            raise ValueError(f"Model choice out of range: {answer}")
        return answer

    answer = tty_prompt(
        f"Exact model id for {provider}",
        default=default,
        non_tty_default=default,
    ).strip()
    if not answer:
        raise ValueError(f"Model is required for provider '{provider}'.")
    return answer


def _exit_usage(message: str) -> NoReturn:
    if json_mode_active():
        emit_json({"reason": "usage_error"}, error=message)
    else:
        console.print(f"[red]{message}[/red]")
    raise typer.Exit(int(ExitCode.USAGE_ERROR))

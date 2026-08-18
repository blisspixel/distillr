# pyright: strict
"""``distill roles`` -- name the local models this machine should use when.

One machine usually holds several models that are not interchangeable: a
mixture-of-experts model that decodes fastest, a smaller one that reasons, one
that will engage with material a safety-tuned model refuses. Roles let an
operator name them once and select one per run with ``--role``.

A role only changes which model reads the source. Prompts, the verify gate, and
receipt discipline are identical across every role, because the charter refuses
any mode that buys speed with fidelity.
"""

from __future__ import annotations

import typer
from rich.markup import escape

from distill._console import console
from distill.commands._json import ExitCode, emit_json, json_mode_active
from distill.commands.init import env_file_path, set_env_var
from distill.llm.model_roles import (
    ROLES,
    RoleCandidate,
    resolve_role_model,
    role_env_var,
    suggest_roles,
)

__all__ = ["register", "roles_app"]

roles_app = typer.Typer(
    help="Name the local model to use for each role (fast, standard, deep, unfiltered).",
    invoke_without_command=True,
    no_args_is_help=False,
)

# The unfiltered role earns its keep on ordinary research a safety-tuned model
# balks at: art history that discusses the nude, security and malware analysis,
# drug policy, extremism studies, forensic and clinical material. A refusal in
# the middle of a corpus is worse than a wrong answer, because the synthesis
# never mentions the hole it left.
_UNFILTERED_NOTE = (
    "no candidate matched. Nothing the server reports distinguishes a "
    "refusal-free model, so assign one yourself if you need it."
)


def _installed_candidates() -> list[RoleCandidate]:
    """Installed completion-capable models, with server capabilities and speed.

    Capabilities decide the deep role, so they must come from the server rather
    than be assumed: whether a model can produce a reasoning trace is exactly
    the fact a name cannot tell you.
    """
    import asyncio

    from distill.commands.bench import stored_decode_rates
    from distill.commands.eval import _ollama_model_sizes  # pyright: ignore[reportPrivateUsage]

    sizes = _ollama_model_sizes()
    if not sizes:
        return []
    rates = stored_decode_rates()
    capabilities = _capabilities_for(sorted(sizes))
    del asyncio
    return [
        RoleCandidate(
            name=name,
            size_gb=size_gb,
            capabilities=capabilities.get(name, frozenset()),
            decode_tokens_per_second=rates.get(name, 0.0),
        )
        for name, size_gb in sorted(sizes.items(), key=lambda kv: kv[1])
    ]


def _capabilities_for(models: list[str]) -> dict[str, frozenset[str]]:
    """Server-declared capabilities per model; empty when unreachable."""
    import asyncio

    from distill.llm.providers.ollama import OllamaProvider

    async def gather() -> dict[str, frozenset[str]]:
        provider = OllamaProvider()
        return {name: await provider._show.capabilities(name) for name in models}  # pyright: ignore[reportPrivateUsage]

    try:
        return asyncio.run(gather())
    except Exception:
        # Capability discovery only refines the suggestion; never fail the view.
        return {}


@roles_app.callback()
def roles_root(ctx: typer.Context) -> None:
    """Show each role, what it points at, and what this machine suggests."""
    if ctx.invoked_subcommand is not None:
        return

    assigned = {role: resolve_role_model(role) for role in ROLES}
    suggestions = {a.role: a for a in suggest_roles(_installed_candidates())}

    if json_mode_active():
        emit_json(
            {
                "roles": [
                    {
                        "role": role,
                        "model": assigned[role],
                        "configured": bool(assigned[role]),
                        "suggested": getattr(suggestions.get(role), "model", ""),
                        "suggested_reason": getattr(suggestions.get(role), "reason", ""),
                        "env_var": role_env_var(role),
                    }
                    for role in ROLES
                ]
            }
        )
        return

    console.print()
    console.print("  [bold]Local model roles[/bold]")
    console.print(f"  [dim]{'-' * 66}[/dim]")
    for role in ROLES:
        model = assigned[role]
        shown = f"[green]{escape(model)}[/green]" if model else "[dim]not set[/dim]"
        console.print(f"  {role:<12}{shown}")
        suggestion = suggestions.get(role)
        if role == "unfiltered" and not model and suggestion is None:
            console.print(f"              [dim]{_UNFILTERED_NOTE}[/dim]")
        elif suggestion is not None and suggestion.model != model:
            console.print(
                f"              [dim]suggested: {escape(suggestion.model)} "
                f"- {suggestion.reason}[/dim]"
            )
    console.print()
    console.print("  [dim]Set one:   distill roles set deep qwen3.8:27b[/dim]")
    console.print('  [dim]Use one:   distill --role deep papers "..." --topic t[/dim]')
    console.print(
        "  [dim]Roles pick which model reads the source. They never change the "
        "prompts or the verify gate.[/dim]"
    )
    console.print(
        "  [dim]Faster is not better. Only `distill eval` ranks these on the "
        "quality of the analysis.[/dim]"
    )
    console.print(
        "  [dim]Unfiltered candidates are matched on name only - edit the list "
        "with DISTILL_UNFILTERED_HINTS.[/dim]"
    )


@roles_app.command("set")
def roles_set(
    role: str = typer.Argument(..., help="fast | standard | deep | unfiltered"),
    model: str = typer.Argument(..., help="Exact installed model id"),
) -> None:
    """Pin a model to a role, persisted to .env."""
    requested = role.strip().lower()
    if requested not in ROLES:
        console.print(f"[red]Unknown role '{escape(role)}'.[/red] Choose: {', '.join(ROLES)}.")
        raise typer.Exit(ExitCode.USAGE_ERROR)

    target = model.strip()
    installed = {c.name for c in _installed_candidates()}
    if installed and target not in installed:
        # Warn rather than refuse: the model may live on another provider, or be
        # pulled later. Silently accepting a typo is the worse failure.
        console.print(
            f"[yellow]'{escape(target)}' is not among this machine's installed "
            f"completion-capable models.[/yellow] Pinning it anyway; run "
            f"`distill doctor` to confirm before relying on it."
        )

    env_path = env_file_path()
    set_env_var(env_path, role_env_var(requested), target)
    console.print(f"  Set {role_env_var(requested)}={escape(target)} in {env_path}")
    console.print(f"  [dim]Use it:  distill --role {requested} <command>[/dim]")


def register(app: typer.Typer) -> None:
    """Attach role commands under Maintain."""
    app.add_typer(roles_app, name="roles", rich_help_panel="Maintain")

# pyright: strict
"""Adapter + local-route reporting for `distill doctor`.

Presentation helpers extracted from distill.commands.doctor to keep that module
under the module-size cap. These render (or emit JSON for) the CLI adapter
readiness report, portable local-service route availability evidence, and the
Local Inference section. The `doctor(...)` command imports them back.
"""

from __future__ import annotations

from rich.markup import escape

from distill._console import console
from distill.config import DistillConfig
from distill.llm.cost_policy import LOCAL_PROVIDER_NAMES

__all__ = [
    "_doctor_adapter_report",
    "_doctor_adapter_support_statement",
    "_doctor_local_inference_section",
    "_local_route_availability_report",
]


def _doctor_adapter_report(*, json_output: bool) -> None:
    """Print or emit read-only CLI adapter readiness."""

    from distill.commands._json import JsonEnvelope
    from distill.doctor.adapters import adapter_doctor_report

    report = adapter_doctor_report()
    if json_output:
        import sys

        sys.stdout.write(JsonEnvelope.success(report.to_dict()).to_json() + "\n")
        return

    console.print("\n  [bold]CLI Adapter Doctor[/bold]")
    console.print("  [dim]Read-only checks. No adapter workloads were run.[/dim]")
    console.print(
        f"  [dim]Scratch manifest contract: {report.manifest_contract['schema_version']}[/dim]"
    )
    for probe in report.adapters:
        status = "READY" if probe.no_metered_eligible else "BLOCKED"
        color = "green" if probe.no_metered_eligible else "yellow"
        console.print(
            f"  [{color}]{status}[/{color}] {probe.name} "
            f"[dim]({probe.route_class}; {probe.binary})[/dim]"
        )
        if probe.version:
            console.print(f"    version: {probe.version}")
        _doctor_adapter_support_statement(probe.support_statement_detail)
        if probe.auth_mode:
            console.print(f"    auth: {probe.auth_mode}")
        if probe.config_files_found:
            console.print(f"    config files: {', '.join(probe.config_files_found)}")
        if probe.auth_evidence:
            console.print(f"    auth evidence: {', '.join(probe.auth_evidence)}")
        if probe.env_blockers_present:
            console.print(f"    env blockers: {', '.join(probe.env_blockers_present)}")
        if probe.missing_flags:
            console.print(f"    missing flags: {', '.join(probe.missing_flags)}")
        if probe.blocked_reasons:
            console.print(f"    blocked: {'; '.join(probe.blocked_reasons)}")


def _doctor_adapter_support_statement(detail: dict[str, object]) -> None:
    if not detail:
        return
    console.print(
        "    support statement: "
        f"{detail.get('status')} "
        f"(checked {detail.get('checked_on')}, "
        f"no-metered current={detail.get('no_metered_current')})"
    )


def _local_route_availability_report(
    *,
    ollama_status: str,
    ollama_models: tuple[str, ...],
    lmstudio_status: str,
    lmstudio_models: tuple[str, ...],
) -> list[dict[str, object]]:
    """Return portable local-service availability evidence for doctor JSON."""

    import time

    from distill.eval.route_availability import (
        local_service_route_availability_signal,
        route_availability_decision,
    )

    checked_at = int(time.time())
    signals = [
        local_service_route_availability_signal(
            provider="ollama",
            status=ollama_status,
            checked_at=checked_at,
            models=ollama_models,
        ),
        local_service_route_availability_signal(
            provider="lmstudio",
            status=lmstudio_status,
            checked_at=checked_at,
            models=lmstudio_models,
        ),
    ]
    signals.extend(
        local_service_route_availability_signal(
            provider="ollama",
            status=ollama_status,
            checked_at=checked_at,
            models=ollama_models,
            model=model,
        )
        for model in ollama_models
    )
    signals.extend(
        local_service_route_availability_signal(
            provider="lmstudio",
            status=lmstudio_status,
            checked_at=checked_at,
            models=lmstudio_models,
            model=model,
        )
        for model in lmstudio_models
    )
    return [
        {
            "signal": signal.to_dict(),
            "decision": route_availability_decision(signal, now=checked_at).to_dict(),
        }
        for signal in signals
    ]


def _doctor_local_inference_section(  # noqa: C901
    config: DistillConfig,
    accent: str,
    *,
    key_statuses: dict[str, str] | None = None,
    key_details: dict[str, str] | None = None,
) -> None:
    """Display the Local Inference section in distill doctor output."""
    from distill.commands.doctor import (
        _configured_analysis_readiness,
        _local_model_inventory,
        _router_config,
    )
    from distill.doctor.hardware import detect_hardware
    from distill.doctor.recommendations import recommend_models

    if key_statuses is None:
        key_statuses = {
            "xai": "ok" if config.xai_api_key.get_secret_value().strip() else "not_set",
            "gemini": "ok" if config.gemini_api_key.get_secret_value().strip() else "not_set",
            "anthropic": (
                "ok" if config.anthropic_api_key.get_secret_value().strip() else "not_set"
            ),
            "openai": "ok" if config.openai_api_key.get_secret_value().strip() else "not_set",
        }
    if key_details is None:
        route_provider, route_model = _router_config(config).resolve("analysis")
        key_details = {route_provider: route_model}

    console.print()
    console.print("  [bold]Local Inference[/bold]")
    console.print(f"  [dim]{'-' * 50}[/dim]")

    # Hardware detection
    profile = detect_hardware()
    if profile.gpu_type == "nvidia":
        console.print(
            f"  GPU:        [green]{profile.gpu_name}[/green]  "
            f"[dim]({profile.vram_gb:.0f} GB VRAM)[/dim]"
        )
    elif profile.gpu_type == "apple_silicon":
        console.print(
            f"  GPU:        [green]{profile.gpu_name}[/green]  "
            f"[dim]({profile.vram_gb:.0f} GB unified)[/dim]"
        )
    else:
        console.print("  GPU:        [dim]none detected[/dim]")

    console.print(f"  RAM:        [dim]{profile.system_ram_gb:.0f} GB[/dim]")
    if profile.is_container:
        console.print("  Container:  [yellow]yes[/yellow]")

    # Ollama server status
    ollama_status, ollama_models = _local_model_inventory(config, "ollama")
    if ollama_status == "running":
        console.print(
            f"  Ollama:     [green]running[/green]  [dim]({len(ollama_models)} model(s))[/dim]"
        )
        if ollama_models:
            for m in ollama_models[:5]:
                console.print(f"              [dim]- {escape(m)}[/dim]")
            if len(ollama_models) > 5:
                console.print(f"              [dim]  ... and {len(ollama_models) - 5} more[/dim]")
    elif ollama_status in {"blocked", "untrusted"}:
        console.print("  Ollama:     [yellow]not probed (non-loopback endpoint)[/yellow]")
    else:
        console.print("  Ollama:     [dim]not running[/dim]")

    # LM Studio server status
    lmstudio_status, lmstudio_models = _local_model_inventory(config, "lmstudio")
    if lmstudio_status == "running":
        console.print(
            f"  LM Studio:  [green]running[/green]  [dim]({len(lmstudio_models)} model(s))[/dim]"
        )
        for model in lmstudio_models[:5]:
            console.print(f"              [dim]  {escape(model)}[/dim]")
    elif lmstudio_status in {"blocked", "untrusted"}:
        console.print("  LM Studio:  [yellow]not probed (non-loopback endpoint)[/yellow]")
    else:
        console.print("  LM Studio:  [dim]not running[/dim]")

    route_provider, route_model, route_ready = _configured_analysis_readiness(
        config,
        key_statuses=key_statuses,
        key_details=key_details,
        ollama_status=ollama_status,
        ollama_models=tuple(ollama_models),
        lmstudio_status=lmstudio_status,
        lmstudio_models=tuple(lmstudio_models),
    )
    local_model_ready = route_ready and route_provider in LOCAL_PROVIDER_NAMES
    if route_provider:
        status = "[green]ready[/green]" if route_ready else "[yellow]not ready[/yellow]"
        console.print(f"  Configured: {escape(route_provider)} / {escape(route_model)}  ({status})")

    # Model recommendations
    recommendations = recommend_models(profile)
    if recommendations:
        console.print()
        console.print("  [bold]Recommended Models[/bold]")
        console.print(f"  [dim]{'-' * 50}[/dim]")
        ollama_model_names = {m.split(":")[0] if ":" in m else m for m in ollama_models}
        for rec in recommendations:
            rec_base = rec.model_name.split(":")[0] if ":" in rec.model_name else rec.model_name
            if rec_base in ollama_model_names or rec.model_name in ollama_models:
                status_icon = "[green]✓[/green]"
            else:
                status_icon = "[yellow]↓[/yellow]"
            console.print(
                f"  {status_icon} {rec.model_name}  "
                f"[dim]ctx={rec.context_window:,} - {rec.reason}[/dim]"
            )
            if rec_base not in ollama_model_names and rec.model_name not in ollama_models:
                console.print(f"     [dim]ollama pull {rec.model_name}[/dim]")

    # Next step: a concrete first command tailored to what's actually configured.
    console.print()
    console.print("  [bold]Next step[/bold]")
    console.print(f"  [dim]{'-' * 50}[/dim]")
    if route_ready and route_provider not in LOCAL_PROVIDER_NAMES:
        console.print(
            '  Configured cloud route ready:  [cyan]distill --cost-mode paid-ok papers "agent memory" '
            "--limit 5 --preview[/cyan]"
        )
        if ollama_models:
            console.print(
                f"  Compare local vs cloud (local is free):  "
                f"[cyan]distill eval --models grok-4.3,{escape(ollama_models[0])}[/cyan]"
            )
    elif local_model_ready:
        console.print(
            "  Local ready, no API key:  [cyan]distill --cost-mode no-metered papers "
            '"agent memory" --limit 5 --preview[/cyan]'
        )
        console.print("  [dim]Add XAI_API_KEY to .env to also use cloud models.[/dim]")
    elif ollama_models or lmstudio_models:
        example_model = ollama_models[0] if ollama_models else lmstudio_models[0]
        example_provider = "ollama" if ollama_models else "lmstudio"
        console.print(
            "  Model available but routing is not ready: set "
            f"DISTILL_PROVIDER={example_provider} and DISTILL_MODEL={escape(example_model)}, "
            "then re-run `distill doctor`."
        )
    else:
        console.print(
            "  Not set up yet:  [cyan]distill --cost-mode no-metered init[/cyan]  "
            "[dim](guided: writes .env, validates your key, installs the browser)[/dim]"
        )
        console.print(
            "  [dim]Or by hand: add XAI_API_KEY to .env for cloud, "
            "or `ollama pull qwen3.5:27b` to run local.[/dim]"
        )

# pyright: strict
"""The `distill eval` command + its local-model helpers, extracted from _logic.

Model cost x quality comparison over frozen fixtures (the arbiter of "is a local
model good enough to switch to"). The Ollama size/selection helpers live here too
-- they are only used by this command now that doctor moved out. Registered via
register() from distill.cli.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from pathlib import Path

import typer

from distill._console import console
from distill.cli_shared import require_api_key as _require_api_key
from distill.commands._helpers import (
    budgeted_cost_tracker,
    enforce_projected_workflow_budget,
    get_config,
    run_preflight,
)
from distill.commands._helpers import tty_confirm as _tty_confirm
from distill.doctor.hardware import HardwareProfile
from distill.jsonl import append_jsonl_lines
from distill.library.paths import atomic_write_text
from distill.llm.cost_policy import evaluate_route_cost_policy
from distill.llm.providers._ollama_registry import model_can_complete

__all__ = ["eval_cmd", "register"]

logger = logging.getLogger(__name__)

# Headroom left for the OS when weights share system memory.
_OS_RESERVE_GB = 8.0
_OS_RESERVE_SHARE = 0.25


def _append_results_log(path: Path, lines: Iterable[str]) -> None:
    """Durably append one complete eval result batch under the JSONL lock."""

    append_jsonl_lines(path, lines, durable=True)


def _ollama_model_sizes() -> dict[str, float]:
    """Map completion-capable Ollama model name -> on-disk size in GB.

    Returns ``{}`` when Ollama is unreachable, non-loopback, or unreadable.
    Embedding-only models are excluded: they are installed and sized like any
    other model but cannot serve the chat completion an eval workload needs.
    """
    import asyncio

    from distill.llm.cost_policy import classify_provider

    if classify_provider("ollama") != "local":
        return {}
    try:
        from distill.llm.providers.ollama import OllamaProvider

        provider = OllamaProvider()
        try:
            models_data = asyncio.run(provider.list_models())
        except RuntimeError:
            loop = asyncio.get_event_loop()
            models_data = loop.run_until_complete(provider.list_models())
        return {
            str(m.get("name", "")): float(m.get("size", 0) or 0) / 1e9
            for m in models_data
            if m.get("name") and model_can_complete(m)
        }
    except Exception:
        # Silence here previously made a registry-parse regression look exactly
        # like "no local models installed", which disables the local eval gate.
        logger.warning("Ollama model discovery failed; treating as no local models", exc_info=True)
        return {}


def local_memory_budget_gb(profile: HardwareProfile) -> float:
    """GB available to hold model weights on this machine.

    A dedicated VRAM ceiling is the budget when one was actually measured.
    Otherwise weights live in system RAM -- true for CPU-only machines, for
    Apple unified memory, and for an integrated GPU whose reported VRAM is a
    BIOS carve-out rather than a limit. Reserve headroom for the OS and the
    rest of the working set, because a model that swaps is worse than a
    smaller one that does not.
    """
    if profile.vram_capacity_gb > 0:
        return profile.vram_capacity_gb
    if profile.system_ram_gb <= 0:
        return 0.0
    return profile.system_ram_gb - min(_OS_RESERVE_GB, profile.system_ram_gb * _OS_RESERVE_SHARE)


def _best_local_model() -> str | None:
    """Largest installed model that fits this machine's memory budget.

    Largest-that-fits, not smallest: the size ordering is a fit statement, not
    a quality claim -- `distill eval` is the arbiter of whether a model is good
    enough. Reading `vram_gb` here instead of `vram_capacity_gb` was a real bug:
    an integrated GPU reports a 2GB carve-out, nothing fit it, and selection
    silently fell back to the smallest installed model.
    """
    sizes = _ollama_model_sizes()
    if not sizes:
        return None
    from distill.doctor.hardware import detect_hardware

    budget = local_memory_budget_gb(detect_hardware())
    fitting = {name: gb for name, gb in sizes.items() if gb <= budget}
    if fitting:
        return max(fitting, key=lambda name: fitting[name])
    # Nothing fits the budget: the smallest is the only one with a chance.
    return min(sizes, key=lambda name: sizes[name])


def eval_cmd(  # noqa: C901 — CLI: option parse + estimate + run + report + results log
    workload: str = typer.Option(
        "all", "--workload", "-w", help="paper | video | site | ask | all"
    ),
    models: str = typer.Option(
        "auto",
        "--models",
        "-m",
        help="Comma-separated model ids to compare. 'auto' = grok-4.6 with an XAI key, "
        "else a fitting local Ollama model.",
    ),
    anchor: str = typer.Option(
        "auto",
        "--anchor",
        help="Reference model the others are compared against. 'auto' = grok-4.6 with an "
        "XAI key, else the first listed model.",
    ),
    judge: str = typer.Option(
        "auto",
        "--judge",
        help="Neutral model that gates migrations (faithfulness veto + pairwise vs the anchor); "
        "'auto' picks a cross-family model, else none -> fail closed on switches",
    ),
    threshold: float = typer.Option(
        0.90,
        "--threshold",
        help="Advisory composite reference shown in the report (x the anchor's mean). "
        "NOT a gate - the model judges decide the switch",
    ),
    report: bool = typer.Option(
        False, "--report", help="Write the cost x quality table to .distill/eval/<workload>_<ts>.md"
    ),
    no_cache: bool = typer.Option(
        False, "--no-cache", help="Ignore the eval cache and re-run every (model, fixture)"
    ),
    allow_oversized: bool = typer.Option(
        False,
        "--allow-oversized",
        help="Run local models whose weights exceed GPU VRAM (default: skip them - they spill to CPU)",
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the pre-run cost confirmation"),
):
    """Compare models on cost x quality over frozen fixtures; recommend the cheapest that clears the bar.

    A migration is gated by model judges, never the gameable deterministic
    composite: a candidate must pass the faithfulness veto (graded absolutely
    against the source) AND have the pairwise judge confirm it at par with the
    anchor; with no neutral judge the eval fails closed (stay on the incumbent).
    The composite is shown for diagnosis only. It recommends; it never switches
    your configured model. To go cheaper than the grok-4.6 cloud default, eval a
    local model (e.g. `--models grok-4.6,qwen3.5:27b` with Ollama running).
    """
    from datetime import datetime

    from distill.eval import (
        WORKLOADS,
        UnpricedEvalRouteError,
        console_lines,
        estimate_eval_cost,
        judge_shares_family,
        load_fixtures,
        render_markdown,
        results_log_lines,
        run_model_eval,
        summarize,
    )
    from distill.eval.harness import provider_for_model
    from distill.pipeline.costs import save_run_log

    run_preflight()
    valid = (*WORKLOADS, "all")
    if workload not in valid:
        console.print(f"[red]Unknown --workload '{workload}'.[/red] Choose: {', '.join(valid)}.")
        raise typer.Exit(1)

    config = get_config()
    # Adaptive defaults: cloud (grok-4.6) when an XAI key exists AND the active
    # cost policy actually permits a metered route, else a fitting local model.
    # Without the policy check, `--cost-mode no-metered eval` selected grok-4.6
    # as model and anchor, quoted a spend estimate for it, then failed every
    # fixture on the route block and still exited 0 -- a green run full of zeros
    # on exactly the cost mode the docs recommend.
    cloud_ok = (
        bool(config.xai_api_key)
        and evaluate_route_cost_policy(
            cost_mode=config.distill_cost_mode,
            provider="xai",
            workload="eval",
        ).allowed
    )
    best_local = _best_local_model()
    if models == "auto":
        models = "grok-4.6" if cloud_ok else (best_local or "")
    model_list = [m.strip() for m in models.split(",") if m.strip()]
    if not model_list:
        console.print(
            "[red]No models to eval.[/red] With an XAI key: --models grok-4.6,qwen3.5:27b. "
            "For local-only: install an Ollama model (see `distill doctor`) or pass --models <name>."
        )
        raise typer.Exit(1)
    if anchor == "auto":
        anchor = "grok-4.6" if cloud_ok else model_list[0]
    if judge == "auto":
        # A migration verdict must come from a judge that is neither the anchor's
        # family (no incumbent grading its own replacement — biased against
        # switching) nor a candidate (a model grading itself — biased toward
        # itself, which would let a hallucinating candidate vouch for its own
        # output and defeat the faithfulness veto). Prefer a different-family
        # cloud model, else a different-family local model that isn't a candidate;
        # else none -> the eval fails closed on migrations (honest "can't certify"
        # beats a biased verdict).
        def _neutral(cand: str) -> bool:
            return bool(cand) and not judge_shares_family(cand, anchor) and cand not in model_list

        if cloud_ok and _neutral("grok-4.6"):
            judge = "grok-4.6"
        elif best_local is not None and _neutral(best_local):
            judge = best_local
        else:
            judge = ""

    # The anchor must be in the run so candidates have something to compare against.
    if anchor not in model_list:
        model_list.insert(0, anchor)

    # GPU-adaptive guard (portable: NVIDIA/AMD VRAM, Apple unified memory, or
    # gracefully skipped when none is detected). Cloud models are never affected.
    from distill.doctor.hardware import detect_hardware

    local_models = [m for m in model_list if provider_for_model(m) in ("ollama", "lmstudio")]
    profile = detect_hardware()
    # Only a dedicated-VRAM measurement is a real capacity ceiling. Unified
    # memory and an integrated GPU's BIOS carve-out are not: a 780M reports 2GB
    # and still runs an 18GB model out of shared system RAM, so gating on that
    # figure would disqualify every model the machine can actually run.
    vram = profile.vram_capacity_gb
    if vram > 0 and local_models:
        sizes = _ollama_model_sizes()
        oversized = [m for m in local_models if sizes.get(m, 0.0) > vram and m != anchor]
        for m in oversized:
            console.print(
                f"[yellow]{m} (~{sizes[m]:.0f}GB) exceeds your {vram:.0f}GB VRAM - it would "
                f"spill to CPU.[/yellow]"
            )
        if oversized and not allow_oversized:
            model_list = [m for m in model_list if m not in oversized]
            console.print(
                "[dim]Skipped the above (pass --allow-oversized to run them anyway).[/dim]"
            )
    elif local_models and not profile.has_gpu:
        # Say "CPU" only when no accelerator was found. Claiming it whenever the
        # VRAM probe came up empty told every AMD/Intel owner their GPU-served
        # run would be slow on CPU.
        console.print(
            "[dim]No GPU detected - local models will run on CPU (slow); "
            "cloud models are unaffected.[/dim]"
        )
    elif local_models and not profile.vram_is_dedicated:
        console.print(
            f"[dim]{profile.gpu_name or profile.gpu_type} detected; memory is shared with the "
            "system, so model size is not capped here.[/dim]"
        )

    needs_xai = provider_for_model(judge) == "xai" or any(
        provider_for_model(m) == "xai" for m in model_list
    )
    if needs_xai:
        _require_api_key(config.xai_api_key, "XAI_API_KEY required for grok models / the judge")

    fixtures = load_fixtures(workload)
    if not fixtures:
        console.print(f"[yellow]No fixtures for workload '{workload}'.[/yellow]")
        raise typer.Exit(1)

    try:
        est = estimate_eval_cost(fixtures, model_list, anchor=anchor, judge_model=judge)
    except UnpricedEvalRouteError as exc:
        from distill.commands._json import ExitCode, emit_json, json_mode_active

        if json_mode_active():
            emit_json({"reason": "external_cost_unavailable"}, error=str(exc))
        else:
            console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=ExitCode.CONFIG_ERROR) from exc
    judge_label = judge or "none (no neutral judge available)"
    console.print(
        f"[bold]Model eval[/bold]: {len(model_list)} model(s) x {len(fixtures)} fixture(s) "
        f"({workload}). Anchor: {anchor}. Judge: {judge_label}."
    )
    console.print(f"[dim]Estimated spend ~${est:.2f}.[/dim]")
    enforce_projected_workflow_budget(config, "eval", est)
    if not judge:
        console.print(
            "[yellow]No neutral judge available[/yellow] - only the anchor's own family is "
            "configured, and the incumbent can't impartially judge its own replacement. The "
            "faithfulness check gates migrations, so without it the eval will recommend staying "
            "on the anchor. Add a cross-family key (e.g. GEMINI_API_KEY) or pass "
            "--judge <model from another family> to certify a switch."
        )
    elif judge_shares_family(judge, anchor):
        console.print(
            "[yellow]The --judge you chose shares the anchor's family[/yellow], so the head-to-head "
            "is self-preference-biased toward the anchor and won't reliably certify a migration. "
            "Pass a different-family --judge for an impartial verdict."
        )
    if not yes and not _tty_confirm("Run the eval?", default=True):
        console.print("[yellow]Aborted.[/yellow]")
        raise typer.Exit(0)

    tracker = budgeted_cost_tracker(config, "eval")
    cache_dir = None if no_cache else (config.library_dir / ".distill" / "eval_cache")
    rows = run_model_eval(
        workload, model_list, anchor=anchor, judge_model=judge, tracker=tracker, cache_dir=cache_dir
    )
    summary = summarize(rows, anchor=anchor, threshold=threshold)
    console.print()
    for line in console_lines(summary):
        console.print(line)

    # Append-only results log for drift tracking over time.
    now = datetime.now()
    out_dir = config.library_dir / ".distill" / "eval"
    out_dir.mkdir(parents=True, exist_ok=True)
    _append_results_log(
        out_dir / "results.jsonl",
        results_log_lines(rows, now_iso=now.isoformat(), anchor=anchor, judge_model=judge),
    )

    if report:
        path = out_dir / f"{workload}_{now.strftime('%Y%m%dT%H%M%S')}.md"
        atomic_write_text(path, render_markdown(summary, now_iso=now.isoformat(), rows=rows))
        console.print(f"\n[dim]Report written to {path}[/dim]")

    save_run_log(
        config.library_dir,
        "eval",
        tracker,
        estimated_cost=est,
    )
    console.print(f"[dim]Eval spend: {tracker.format_cost()}[/dim]")


def register(app: typer.Typer) -> None:
    """Attach the eval command to the app (called from distill.cli)."""
    app.command(name="eval", rich_help_panel="Maintain")(eval_cmd)

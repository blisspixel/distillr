# pyright: strict
"""Doctor + health commands, extracted from the _logic monolith.

`distill doctor` is the environment/key/dependency diagnostic; `distill health`
is the fast corpus-health console view (the report-producing version is
`distill audit`). The pure check/probe helpers live in distill.doctor.checks;
this module is the command + presentation layer. Registered via register() from
distill.cli (mirroring view/maintain/update/init).
"""

from __future__ import annotations

import importlib
import importlib.metadata as importlib_metadata
import importlib.util as importlib_util
import os
from pathlib import Path
from typing import Protocol, cast

import typer

from distill._console import console
from distill._version import get_version as _get_version
from distill.commands._doctor_data import corpus_library_stats as _corpus_library_stats
from distill.commands._helpers import _complete_topics, get_config
from distill.config import DistillConfig
from distill.doctor.checks import (
    check_lmstudio_status,
    check_ollama_status,
    check_retired_models,
    doctor_key_validation_session,
    doctor_validate_key,
)
from distill.library import Library
from distill.pipeline.dashboard_data import (
    collect_corpus_health_warnings as _collect_corpus_health_warnings,
)
from distill.preflight import (
    YTDLP_STALE_DAYS,
    invalidate_preflight_cache,
    update_ytdlp,
    ytdlp_age_days,
)

__all__ = ["doctor", "health", "register"]

_check_lmstudio_status = check_lmstudio_status
_check_ollama_status = check_ollama_status
_doctor_validate_key = doctor_validate_key


def _configured_metered_api_keys(config: DistillConfig) -> list[str]:
    keys: list[str] = []
    if config.xai_api_key.get_secret_value().strip():
        keys.append("XAI_API_KEY")
    if config.gemini_api_key.get_secret_value().strip():
        keys.append("GEMINI_API_KEY")
    if config.anthropic_api_key.get_secret_value().strip():
        keys.append("ANTHROPIC_API_KEY")
    if config.openai_api_key.get_secret_value().strip():
        keys.append("OPENAI_API_KEY")
    return keys


def _cost_mode_warnings(config: DistillConfig) -> list[str]:
    if config.distill_cost_mode != "auto":
        return []
    keys = _configured_metered_api_keys(config)
    if not keys:
        return []
    return [
        "Cost mode is auto and metered API keys are configured: "
        f"{', '.join(keys)}. Commands may use API-billed routes; pass "
        "`--cost-mode no-metered` or set `DISTILL_COST_MODE=no-metered` to fail closed."
    ]


class _CTranslate2Module(Protocol):
    def get_cuda_device_count(self) -> int: ...

    def get_supported_compute_types(self, device: str) -> set[str]: ...


def doctor(  # noqa: C901 - legacy, will refactor
    ctx: typer.Context,
    update: bool = typer.Option(
        False,
        "--update",
        help="Upgrade yt-dlp via pip if it is older than the freshness threshold",
    ),
    links: bool = typer.Option(
        False,
        "--links",
        help="Check wiki-link integrity across the corpus",
    ),
    fix: bool = typer.Option(
        False,
        "--fix",
        help="Fix broken wiki-links (requires --links)",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Output doctor or link-check results as JSON",
    ),
    adapters: bool = typer.Option(
        False,
        "--adapters",
        help="Check candidate CLI adapter readiness without running workloads",
    ),
    migrate_links: bool = typer.Option(
        False,
        "--migrate-links",
        help="Scan for legacy-named artifacts and print dry-run migration plan",
    ),
    migrate_frontmatter: bool = typer.Option(
        False,
        "--migrate-frontmatter",
        help="Rewrite pre-0.8.1 ``confidence:`` frontmatter to ``synthesis_scope:`` (dry-run)",
    ),
    apply: bool = typer.Option(
        False,
        "--apply",
        help="Execute the migration plan (requires --migrate-links or --migrate-frontmatter)",
    ),
):
    """Check API keys, tools, and library health."""
    from distill.commands._json import JsonEnvelope

    json_mode = ctx.obj.get("json", False) if ctx.obj else False

    _ACCENT = "rgb(100,149,237)"
    config = get_config()

    if adapters:
        _doctor_adapter_report(json_output=json_output or json_mode)
        return

    # --- Link integrity check mode ---
    if links:
        from distill.library.links import check_links, fix_broken_links

        library_dir = config.library_dir
        if not library_dir.exists():
            console.print("[red]Error: library directory does not exist.[/red]")
            raise typer.Exit(1)

        result = check_links(library_dir)

        if json_output or json_mode:
            import sys

            envelope = JsonEnvelope.success(result.to_dict())
            sys.stdout.write(envelope.to_json() + "\n")
        else:
            console.print("\n  [bold]Link Integrity Check[/bold]")
            console.print(f"  Files scanned: {result.files_scanned}")
            console.print(f"  Total links:   {result.total_links}")
            console.print(f"  Broken links:  {len(result.broken_links)}")
            if result.broken_links:
                console.print()
                for bl in result.broken_links[:20]:
                    console.print(
                        f"  [red]✗[/red] {bl.source_file}:{bl.line_number} → {bl.link_text}"
                    )
                if len(result.broken_links) > 20:
                    console.print(f"  [dim]... and {len(result.broken_links) - 20} more[/dim]")

        if fix:
            if not result.broken_links:
                if not (json_output or json_mode):
                    console.print("  [green]Nothing to fix.[/green]")
            else:
                fixed_count = fix_broken_links(library_dir, result.broken_links)
                if not (json_output or json_mode):
                    console.print(f"\n  [green]Fixed {fixed_count} broken link(s).[/green]")

        return

    # --- Migration mode ---
    if migrate_links:
        from distill.library.migration import apply_migration, scan_legacy_artifacts

        library_dir = config.library_dir
        if not library_dir.exists():
            console.print("[red]Error: library directory does not exist.[/red]")
            raise typer.Exit(1)

        actions = scan_legacy_artifacts(library_dir)

        if not actions:
            console.print("  [green]Nothing to migrate - no legacy artifacts found.[/green]")
            return

        if not apply:
            # Dry-run: print proposed changes
            console.print("\n  [bold]Migration Plan (dry-run):[/bold]")
            for action in actions:
                console.print(f"  RENAME: {action.source_path.relative_to(library_dir)}")
                console.print(f"       → {action.target_path.relative_to(library_dir)}")
            console.print(
                f"\n  Summary: {len(actions)} rename(s) proposed. Use --apply to execute."
            )
        else:
            # Execute migration
            migration_result = apply_migration(actions, library_dir=library_dir)
            console.print("\n  [bold]Migration Complete[/bold]")
            console.print(f"  Files renamed:      {migration_result.files_renamed}")
            console.print(f"  Links updated:      {migration_result.links_updated}")
            console.print(f"  Conflicts skipped:  {migration_result.conflicts_skipped}")
            if migration_result.errors:
                console.print(f"  Errors:             {len(migration_result.errors)}")
                for err in migration_result.errors:
                    console.print(f"    [red]•[/red] {err}")

        return

    # --- Frontmatter field rename mode (confidence -> synthesis_scope) ---
    if migrate_frontmatter:
        from distill.library.migration import (
            apply_frontmatter_field_migration,
            scan_confidence_field,
        )

        library_dir = config.library_dir
        if not library_dir.exists():
            console.print("[red]Error: library directory does not exist.[/red]")
            raise typer.Exit(1)

        actions = scan_confidence_field(library_dir)

        if not actions:
            console.print(
                "  [green]Nothing to migrate - no ``confidence:`` frontmatter found.[/green]"
            )
            return

        if not apply:
            console.print("\n  [bold]Frontmatter Migration Plan (dry-run):[/bold]")
            for action in actions[:20]:
                console.print(
                    f"  REWRITE: {action.path.relative_to(library_dir)} "
                    f"({action.old_field} -> {action.new_field}, value={action.value!r})"
                )
            if len(actions) > 20:
                console.print(f"  [dim]... and {len(actions) - 20} more[/dim]")
            console.print(
                f"\n  Summary: {len(actions)} file(s) need rewriting. Use --apply to execute."
            )
        else:
            result = apply_frontmatter_field_migration(actions)
            console.print("\n  [bold]Frontmatter Migration Complete[/bold]")
            console.print(f"  Files rewritten: {result.files_rewritten}")
            console.print(f"  Files skipped:   {result.files_skipped}")
            if result.errors:
                console.print(f"  Errors:          {len(result.errors)}")
                for err in result.errors:
                    console.print(f"    [red]•[/red] {err}")

        return

    # --- Validate flag combinations ---
    if fix and not links:
        console.print("[red]Error: --fix requires --links[/red]")
        raise typer.Exit(1)
    if apply and not (migrate_links or migrate_frontmatter):
        console.print("[red]Error: --apply requires --migrate-links or --migrate-frontmatter[/red]")
        raise typer.Exit(1)

    if json_mode or json_output:
        # JSON mode: collect health data and return structured output
        checks: dict[str, str] = {}
        warnings_list: list[str] = []

        # API keys -- live-validated, not presence-only. A revoked/expired key
        # is present but dead; reporting it as "set" is a false-green that the
        # human doctor path (which makes a live call) would never produce.
        with doctor_key_validation_session(config):
            xai_status, xai_detail = _doctor_validate_key("xai", config)
            gem_status, gem_detail = _doctor_validate_key("gemini", config)
            ant_status, ant_detail = _doctor_validate_key("anthropic", config)
            oai_status, oai_detail = _doctor_validate_key("openai", config)
        checks["xai_api_key"] = xai_status  # ok | invalid | missing | skipped
        checks["gemini_api_key"] = gem_status  # ok | invalid | not_set | skipped
        checks["anthropic_api_key"] = ant_status  # ok | invalid | not_set | skipped
        checks["openai_api_key"] = oai_status  # ok | invalid | not_set | skipped
        checks["cost_mode"] = config.distill_cost_mode
        if xai_status == "invalid":
            warnings_list.append(f"XAI_API_KEY rejected by provider: {xai_detail[:80]}")
        if gem_status == "invalid":
            warnings_list.append(f"GEMINI_API_KEY rejected by provider: {gem_detail[:80]}")
        if ant_status == "invalid":
            warnings_list.append(f"ANTHROPIC_API_KEY rejected by provider: {ant_detail[:80]}")
        if oai_status == "invalid":
            warnings_list.append(f"OPENAI_API_KEY rejected by provider: {oai_detail[:80]}")
        warnings_list.extend(_cost_mode_warnings(config))

        # yt-dlp
        try:
            importlib_metadata.version("yt-dlp")  # raises if not installed
            checks["yt_dlp"] = importlib_metadata.version("yt-dlp")
        except Exception:
            checks["yt_dlp"] = "not_found"

        # Library stats
        lib = Library(config)
        topics, total_ch, _total_vids, _scan_vids = _corpus_library_stats(config, lib)
        checks["topics"] = str(len(topics))
        checks["channels"] = str(total_ch)

        # Retired models
        retired_warnings = check_retired_models(config)
        warnings_list.extend(retired_warnings)

        # Local inference
        from distill.doctor.hardware import detect_hardware
        from distill.doctor.recommendations import recommend_models as _recommend

        profile = detect_hardware()
        ollama_status, ollama_models = _check_ollama_status()
        lmstudio_status = _check_lmstudio_status()
        recommendations = _recommend(profile)
        local_route_availability = _local_route_availability_report(
            ollama_status=ollama_status,
            ollama_models=tuple(ollama_models),
            lmstudio_status=lmstudio_status,
        )

        # Browser capture readiness (the #1 silent ingest failure for YouTube/web).
        # Reuses init's cheap executable-path probe rather than launching a browser.
        from distill.commands.init import chromium_status

        checks["browser"] = chromium_status()  # installed | missing | unknown

        local_inference = {
            "gpu_type": profile.gpu_type,
            "gpu_name": profile.gpu_name,
            "vram_gb": profile.vram_gb,
            "system_ram_gb": profile.system_ram_gb,
            "is_container": profile.is_container,
            "ollama_status": ollama_status,
            "ollama_models": ollama_models,
            "lmstudio_status": lmstudio_status,
            "route_availability": local_route_availability,
            "recommended_models": [
                {
                    "model_name": r.model_name,
                    "context_window": r.context_window,
                    "reason": r.reason,
                }
                for r in recommendations
            ],
        }

        # Top-level readiness verdict: can this environment analyze a source at
        # all? Provider-ready = a working cloud key OR a running local server.
        # Browser is reported separately (papers / local-file ingest need no
        # browser), so a missing browser does not by itself mean "not ready".
        ready = (
            checks["xai_api_key"] == "ok"
            or ollama_status == "running"
            or lmstudio_status == "running"
        )

        envelope = JsonEnvelope.success(
            {
                "ready": ready,
                "checks": checks,
                "warnings": warnings_list,
                "local_inference": local_inference,
            }
        )
        import sys

        sys.stdout.write(envelope.to_json() + "\n")
        return

    update_succeeded = False
    if update:
        console.print("[dim]Upgrading yt-dlp via pip...[/dim]")
        ok, detail, was_noop = update_ytdlp()
        if ok:
            update_succeeded = True
            if was_noop:
                console.print(
                    f"  [green]OK[/green]  yt-dlp [bold]v{detail}[/bold] "
                    "is already the latest published release"
                )
            else:
                console.print(f"  [green]OK[/green]  yt-dlp upgraded to [bold]v{detail}[/bold]")
            invalidate_preflight_cache(config.library_dir)
        else:
            console.print(f"  [red]XX[/red]  yt-dlp upgrade failed: [red]{detail}[/red]")
        console.print()

    console.print()
    console.print("  [bold]API Keys[/bold]")
    console.print(f"  [dim]{'-' * 50}[/dim]")

    # XAI/Grok -- required. Live-validated via the shared helper so this human
    # view and the --json view can never disagree about a key's health.
    with doctor_key_validation_session(config):
        xai_status, xai_detail = _doctor_validate_key("xai", config)
        gem_status, gem_detail = _doctor_validate_key("gemini", config)
        ant_status, ant_detail = _doctor_validate_key("anthropic", config)
        oai_status, oai_detail = _doctor_validate_key("openai", config)

    if xai_status == "ok":
        console.print(f"  [green]OK[/green]  XAI_API_KEY       [dim]{xai_detail}[/dim]")
    elif xai_status == "missing":
        console.print("  [red]XX[/red]  XAI_API_KEY       [red]NOT SET (required)[/red]")
    elif xai_status == "skipped":
        console.print(
            "  [yellow]--[/yellow]  XAI_API_KEY       "
            "[yellow]live validation skipped by no-metered policy[/yellow]"
        )
    elif xai_status == "unknown":
        console.print(
            f"  [yellow]--[/yellow]  XAI_API_KEY       [yellow]could not verify: {xai_detail:.45}[/yellow]"
        )
    else:
        console.print(f"  [red]XX[/red]  XAI_API_KEY       [red]{xai_detail:.60}[/red]")

    # Gemini -- needed for reports
    if gem_status == "ok":
        console.print("  [green]OK[/green]  GEMINI_API_KEY    [dim]Deep Research[/dim]")
    elif gem_status == "not_set":
        console.print(
            "  [yellow]--[/yellow]  GEMINI_API_KEY    [dim]not set (needed for reports)[/dim]"
        )
    elif gem_status == "skipped":
        console.print(
            "  [yellow]--[/yellow]  GEMINI_API_KEY    "
            "[yellow]live validation skipped by no-metered policy[/yellow]"
        )
    elif gem_status == "unknown":
        console.print(
            f"  [yellow]--[/yellow]  GEMINI_API_KEY    [yellow]could not verify: {gem_detail:.45}[/yellow]"
        )
    else:
        console.print(f"  [red]XX[/red]  GEMINI_API_KEY    [red]{gem_detail:.60}[/red]")

    # Anthropic -- optional metered analysis route
    if ant_status == "ok":
        console.print("  [green]OK[/green]  ANTHROPIC_API_KEY [dim]claude-sonnet-5[/dim]")
    elif ant_status == "not_set":
        console.print("  [dim]--  ANTHROPIC_API_KEY not set (optional)[/dim]")
    elif ant_status == "skipped":
        console.print(
            "  [yellow]--[/yellow]  ANTHROPIC_API_KEY "
            "[yellow]live validation skipped by no-metered policy[/yellow]"
        )
    elif ant_status == "unknown":
        console.print(
            f"  [yellow]--[/yellow]  ANTHROPIC_API_KEY [yellow]could not verify: {ant_detail:.45}[/yellow]"
        )
    else:
        console.print(f"  [red]XX[/red]  ANTHROPIC_API_KEY [red]{ant_detail:.60}[/red]")

    # OpenAI -- optional
    if oai_status == "ok":
        console.print("  [green]OK[/green]  OPENAI_API_KEY    [dim]optional[/dim]")
    elif oai_status == "not_set":
        console.print("  [dim]--  OPENAI_API_KEY    not set (optional)[/dim]")
    elif oai_status == "skipped":
        console.print(
            "  [yellow]--[/yellow]  OPENAI_API_KEY    "
            "[yellow]live validation skipped by no-metered policy[/yellow]"
        )
    elif oai_status == "unknown":
        console.print(
            f"  [yellow]--[/yellow]  OPENAI_API_KEY    [yellow]could not verify: {oai_detail:.45}[/yellow]"
        )
    else:
        console.print(f"  [red]XX[/red]  OPENAI_API_KEY    [red]{oai_detail:.60}[/red]")

    # Tools
    console.print()
    console.print("  [bold]Tools[/bold]")
    console.print(f"  [dim]{'-' * 50}[/dim]")

    try:
        if importlib_util.find_spec("yt_dlp") is None:
            raise importlib_metadata.PackageNotFoundError("yt-dlp")
        ytdlp_version = importlib_metadata.version("yt-dlp")
        age = ytdlp_age_days()
        if update_succeeded and (age is None or age > YTDLP_STALE_DAYS):
            # Suppress the "X days old; run --update" nag right after a successful
            # upgrade attempt; pypi simply hasn't shipped a newer release yet.
            age_label = "  [dim](latest available release)[/dim]"
        elif age is None:
            age_label = ""
        elif age > YTDLP_STALE_DAYS:
            age_label = f"  [yellow]({age}d old; run `distill doctor --update`)[/yellow]"
        else:
            age_label = f"  [dim]({age}d old)[/dim]"
        console.print(
            f"  [green]OK[/green]  yt-dlp            [dim]v{ytdlp_version}[/dim]{age_label}"
        )
    except Exception:
        console.print("  [red]XX[/red]  yt-dlp            [red]not found[/red]")

    # Playwright
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            browser.close()
        console.print("  [green]OK[/green]  playwright        [dim]browser search[/dim]")
    except Exception:
        console.print(
            "  [yellow]--[/yellow]  playwright        [dim]not available (fallback search used)[/dim]"
        )

    # Scribe
    if config.scribe_path and Path(config.scribe_path).exists():
        console.print(f"  [green]OK[/green]  scribe            [dim]{config.scribe_path}[/dim]")
    elif config.scribe_path:
        console.print(
            f"  [red]XX[/red]  scribe            [red]not found at {config.scribe_path}[/red]"
        )
    else:
        console.print("  [dim]--  scribe            not set (optional transcript fallback)[/dim]")

    # Transcription providers (Whisper for sources without native captions:
    # X-native video, podcasts, conference talks, generic audio/video files).
    # YouTube continues to use yt-dlp captions; these checks are only
    # relevant for sources outside that path.
    console.print()
    console.print("  [bold]Transcription[/bold]")
    console.print(f"  [dim]{'-' * 50}[/dim]")

    fw_installed = False
    try:
        fw_version = importlib_metadata.version("faster-whisper")
        fw_installed = True
        console.print(
            f"  [green]OK[/green]  faster-whisper    [dim]v{fw_version} (local provider)[/dim]"
        )
    except importlib_metadata.PackageNotFoundError:
        console.print(
            "  [dim]--  faster-whisper    not installed "
            "(pip install faster-whisper for local GPU/CPU transcription)[/dim]"
        )
    except Exception as exc:
        console.print(f"  [yellow]--[/yellow]  faster-whisper    [yellow]{exc!s:.60}[/yellow]")

    if fw_installed:
        try:
            ct2 = cast(_CTranslate2Module, importlib.import_module("ctranslate2"))
            cuda_count = ct2.get_cuda_device_count()
            if cuda_count > 0:
                compute_types = ct2.get_supported_compute_types("cuda")
                preferred = "float16" if "float16" in compute_types else next(iter(compute_types))
                console.print(
                    f"  [green]OK[/green]  CUDA device       "
                    f"[dim]{cuda_count} device(s), compute={preferred}[/dim]"
                )
            else:
                console.print(
                    "  [yellow]--[/yellow]  CUDA device       "
                    "[dim]none detected; local Whisper will run on CPU (slower)[/dim]"
                )
        except Exception as exc:
            console.print(f"  [yellow]--[/yellow]  CUDA device       [yellow]{exc!s:.60}[/yellow]")

        # Peek HF cache for already-downloaded Whisper models so users
        # know whether the first run will incur a ~3GB download.
        hf_cache = Path(os.environ.get("HF_HOME") or Path.home() / ".cache" / "huggingface")
        cached_models: list[str] = []
        if hf_cache.exists():
            hub_dir = hf_cache / "hub"
            if hub_dir.exists():
                for entry in hub_dir.iterdir():
                    name = entry.name
                    if name.startswith("models--") and "whisper" in name.lower():
                        cached_models.append(name.replace("models--", "").replace("--", "/"))
        if cached_models:
            console.print(
                f"  [green]OK[/green]  whisper models    [dim]{', '.join(cached_models[:3])}[/dim]"
            )
        else:
            console.print(
                "  [dim]--  whisper models    none cached "
                "(first transcription will download ~3GB for large-v3)[/dim]"
            )

    # Routing surface: which providers transcribe.py will pick from
    # today, in order. Helps debug "why did this go to cloud?" surprises.
    providers: list[str] = []
    if fw_installed:
        providers.append("local (faster-whisper large-v3)")
    if config.xai_api_key:
        providers.append("cloud (xai-grok-stt $0.10/hr)")
    if config.openai_api_key:
        providers.append("cloud (openai whisper-1 $0.36/hr)")
    if providers:
        routing = " -> ".join(providers)
    else:
        routing = (
            "[red]no provider available[/red] -- install faster-whisper, "
            "or set XAI_API_KEY / OPENAI_API_KEY"
        )
    console.print(f"  [dim]Provider routing: {routing}[/dim]")

    # Verification: the entailment tier (optional extra). The deterministic
    # numeric tier is always on; this shows whether prose claims also get
    # checked (docs/design/entailment-tier.md).
    console.print()
    console.print("  [bold]Verification[/bold]")
    console.print(f"  [dim]{'-' * 50}[/dim]")
    console.print("  [green]OK[/green]  numeric tier      [dim]deterministic, always on[/dim]")
    from distill.pipeline.verify_entailment import entailment_available

    if entailment_available():
        console.print(
            "  [green]OK[/green]  entailment tier   "
            "[dim]transformers installed; HHEM loads on first verified write[/dim]"
        )
    else:
        console.print(
            "  [dim]--  entailment tier   not installed "
            r"(pip install distillr\[entailment] to check prose claims locally)[/dim]"
        )

    # Library
    console.print()
    console.print("  [bold]Library[/bold]")
    console.print(f"  [dim]{'-' * 50}[/dim]")

    lib = Library(config)
    topics, total_ch, total_vids, scan_vids = _corpus_library_stats(config, lib)
    watchlist = lib.get_watchlist()
    topic_watchlist = lib.get_topic_watchlist()

    console.print(f"  Topics:     [{_ACCENT}]{len(topics)}[/{_ACCENT}]")
    console.print(f"  Channels:   [{_ACCENT}]{total_ch}[/{_ACCENT}]")
    vid_detail = f"[{_ACCENT}]{total_vids}[/{_ACCENT}]"
    if scan_vids:
        vid_detail += f"  [dim]({scan_vids} scan, {total_vids - scan_vids} full)[/dim]"
    console.print(f"  Videos:     {vid_detail}")
    if watchlist:
        w_with_instr = sum(1 for e in watchlist if e.active_instructions)
        watch_detail = f"[{_ACCENT}]{len(watchlist)}[/{_ACCENT}]"
        if w_with_instr:
            watch_detail += f"  [dim]({w_with_instr} with custom instructions)[/dim]"
        console.print(f"  Watching:   {watch_detail}")
    if topic_watchlist:
        console.print(f"  TopicWatch: [{_ACCENT}]{len(topic_watchlist)}[/{_ACCENT}]")

    # Disk usage
    lib_dir = config.library_dir
    if lib_dir.exists():
        total_size = sum(f.stat().st_size for f in lib_dir.rglob("*") if f.is_file())
        if total_size > 1024 * 1024:
            console.print(f"  Disk:       [dim]{total_size / 1024 / 1024:.1f} MB[/dim]")
        else:
            console.print(f"  Disk:       [dim]{total_size / 1024:.0f} KB[/dim]")

    # Config
    console.print()
    console.print("  [bold]Config[/bold]")
    console.print(f"  [dim]{'-' * 50}[/dim]")
    console.print(
        f"  Lookback:   [dim]{config.distill_default_months} month{'s' if config.distill_default_months != 1 else ''}[/dim]"
    )
    console.print(f"  Cost mode:  [dim]{config.distill_cost_mode}[/dim]")
    for warning in _cost_mode_warnings(config):
        console.print(f"  [yellow]![/yellow] {warning}")
    console.print(f"  Library:    [dim]{config.library_dir}[/dim]")
    console.print(f"  Version:    [dim]v{_get_version()}[/dim]")

    # Retired models
    retired_warnings = check_retired_models(config)
    if retired_warnings:
        console.print()
        console.print("  [bold]Retired Models[/bold]")
        console.print(f"  [dim]{'-' * 50}[/dim]")
        for warning in retired_warnings:
            console.print(f"  [yellow]⚠[/yellow]  {warning}")

    # Local Inference
    _doctor_local_inference_section(config, _ACCENT)

    console.print()


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
    return [
        {
            "signal": signal.to_dict(),
            "decision": route_availability_decision(signal, now=checked_at).to_dict(),
        }
        for signal in signals
    ]


def _doctor_local_inference_section(config: DistillConfig, accent: str) -> None:  # noqa: C901
    """Display the Local Inference section in distill doctor output."""
    from distill.doctor.hardware import detect_hardware
    from distill.doctor.recommendations import recommend_models

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
    ollama_status, ollama_models = _check_ollama_status()
    if ollama_status == "running":
        console.print(
            f"  Ollama:     [green]running[/green]  [dim]({len(ollama_models)} model(s))[/dim]"
        )
        if ollama_models:
            for m in ollama_models[:5]:
                console.print(f"              [dim]• {m}[/dim]")
            if len(ollama_models) > 5:
                console.print(f"              [dim]  ... and {len(ollama_models) - 5} more[/dim]")
    else:
        console.print("  Ollama:     [dim]not running[/dim]")

    # LM Studio server status
    lmstudio_status = _check_lmstudio_status()
    if lmstudio_status == "running":
        console.print("  LM Studio:  [green]running[/green]")
    else:
        console.print("  LM Studio:  [dim]not running[/dim]")

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
    if get_config().xai_api_key:
        console.print('  Cloud ready:  [cyan]distill papers "agent memory" --limit 5[/cyan]')
        if ollama_models:
            console.print(
                f"  Compare local vs cloud (local is free):  "
                f"[cyan]distill eval --models grok-4.3,{ollama_models[0]}[/cyan]"
            )
    elif ollama_models:
        console.print(
            f"  Local ready, no API key:  [cyan]distill eval --models {ollama_models[0]}[/cyan]"
        )
        console.print("  [dim]Add XAI_API_KEY to .env to also use cloud models.[/dim]")
    else:
        console.print(
            "  Not set up yet:  [cyan]distill init[/cyan]  "
            "[dim](guided: writes .env, validates your key, installs the browser)[/dim]"
        )
        console.print(
            "  [dim]Or by hand: add XAI_API_KEY to .env for cloud, "
            "or `ollama pull qwen3.5:27b` to run local.[/dim]"
        )


def health(  # noqa: C901 -- straight-line walk over topics + warning categories
    topic: str = typer.Argument(
        "all",
        help="Topic to audit, or 'all' for the full library",
        autocompletion=_complete_topics,
    ),
):
    """Audit corpus quality signals like stale syntheses and thin artifacts."""
    from distill.commands._json import emit_json, json_mode_active
    from distill.concepts.contradictions import ContestedConcept, find_contested

    config = get_config()
    lib = Library(config)
    topics = lib.get_topics() if topic == "all" else [topic]
    warnings = _collect_corpus_health_warnings(config, lib, topics, limit=50)

    contested_by_topic: dict[str, list[ContestedConcept]] = {}
    for t in topics:
        topic_dir = config.topic_dir(t)
        if topic_dir.exists():
            contested = find_contested(topic_dir)
            if contested:
                contested_by_topic[t] = contested

    if json_mode_active():
        emit_json(
            {
                "scope": topic,
                "topics": topics,
                "healthy": bool(topics) and not warnings and not contested_by_topic,
                "warnings": warnings,
                "contested_concepts": {
                    t: [item.to_dict() for item in items]
                    for t, items in sorted(contested_by_topic.items())
                },
                "message": "" if topics else "No topics found to audit",
            }
        )
        return

    console.print()
    console.print("[bold]Corpus Health[/bold]")
    console.print(f"  [dim]scope: {topic}[/dim]")
    console.print()

    if not topics:
        console.print("  [yellow]No topics found to audit[/yellow]")
        return

    if not warnings and not contested_by_topic:
        console.print("  [green]No obvious corpus health issues detected[/green]")
        return

    for item in warnings:
        console.print(f"  [yellow]-[/yellow] {item}")

    if contested_by_topic:
        console.print()
        console.print(
            "  [bold]Contested concepts[/bold] (both helpful and harmful evidence present):"
        )
        for t, items in sorted(contested_by_topic.items()):
            console.print(f"  [dim]{t}:[/dim]")
            for c in items[:10]:  # cap per-topic to keep output readable
                label = "entity" if c.is_entity else "concept"
                console.print(
                    f"    [yellow]-[/yellow] {c.name} ({label}, {c.helpful_count} helpful / "
                    f"{c.harmful_count} harmful across {c.source_count} sources)"
                )
            if len(items) > 10:
                console.print(f"    [dim]... and {len(items) - 10} more[/dim]")

    console.print()
    console.print(
        "  [dim]Use distill reanalyze / distill resynthesize / distill topic-watch run to refresh weak artifacts[/dim]"
    )


def register(app_: typer.Typer) -> None:
    """Attach the doctor + health commands to the app (called from distill.cli)."""
    app_.command(rich_help_panel="Maintain")(doctor)
    app_.command(rich_help_panel="Maintain")(health)

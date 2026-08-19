# pyright: strict
"""``distill bench`` -- measure local model speed on this machine.

Speed only. Whether a model is *good enough* is a semantic judgment and belongs
to ``distill eval``, which grades output against its source with a model judge.
Nothing here ranks answer quality: a deterministic number that looks like a
quality score is exactly the proxy the project charter forbids.

What this does answer is the question a local user cannot answer today: how long
will this run take on my box, and which installed model is worth pointing it at?
"""

from __future__ import annotations

import asyncio
import json
import platform
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import typer

from distill._console import console
from distill.commands._helpers import get_config, run_preflight
from distill.commands._json import emit_json, json_mode_active
from distill.jsonl import append_jsonl_lines
from distill.pipeline.duration_estimates import (
    SpeedCalibration,
    estimate_stage_duration,
    format_duration,
)
from distill.pipeline.speed_probe import (
    ModelSpeed,
    build_probe_prompt,
    release_model,
    speed_from_response,
)

__all__ = ["bench_cmd", "register"]

# Large enough that fixed per-request overhead is amortized: a 20-token probe
# measured 65 tok/s prefill where 2,812 tokens measured 188 on the same model.
_PREFILL_TOKENS = 1024
_DECODE_TOKENS = 64
_PROBE_TIMEOUT_SECONDS = 900
_MAX_RESULT_ROW_BYTES = 64 * 1024


@dataclass(frozen=True)
class _Row:
    speed: ModelSpeed
    calibration: SpeedCalibration


def _calibration_for(speed: ModelSpeed) -> SpeedCalibration:
    return SpeedCalibration(
        model=speed.model,
        provider=speed.provider,
        prefill_tokens_per_second=speed.prefill_tokens_per_second,
        decode_tokens_per_second=speed.decode_tokens_per_second,
        cold_load_seconds=speed.cold_load_seconds,
        basis="probe",
        samples={"prefill": 1, "decode": 1},
    )


async def _probe_one(provider_name: str, model: str) -> ModelSpeed:
    """Warm-up, then one measured call whose response carries both rates."""
    from distill.llm.providers.ollama import OllamaProvider

    provider = OllamaProvider()
    try:
        # Both calls must size the context identically. The window is derived
        # from prompt length, and changing it forces a full weight reload -- so
        # warming up on a short prompt and measuring on a long one reloads
        # between them and charges the reload to the model's inference time.
        warmup = await provider.call(
            model,
            build_probe_prompt(_PREFILL_TOKENS),
            max_tokens=_DECODE_TOKENS,
            timeout=_PROBE_TIMEOUT_SECONDS,
            call_type="bench",
        )
        measured = await provider.call(
            model,
            build_probe_prompt(_PREFILL_TOKENS),
            max_tokens=_DECODE_TOKENS,
            timeout=_PROBE_TIMEOUT_SECONDS,
            call_type="bench",
        )
    except Exception as exc:  # one bad model must not end the sweep
        await release_model(provider._base_url, model)  # pyright: ignore[reportPrivateUsage]
        return ModelSpeed(
            model=model, provider=provider_name, outcome="error", error=str(exc)[:200]
        )
    # Hold exactly one model at a time. A model left resident competes for
    # memory with the next one measured, which reads as that model being slower.
    await release_model(provider._base_url, model)  # pyright: ignore[reportPrivateUsage]
    return speed_from_response(model, provider_name, warmup=warmup, measured=measured)


def _machine_facts() -> dict[str, object]:
    """Machine identity for comparing runs, with nothing personally identifying.

    Deliberately excludes hostname, username, filesystem paths, and the raw
    provider model details blob, which has been observed to carry an absolute
    path containing a username.
    """
    from distill.doctor.hardware import detect_hardware
    from distill.update import get_installed_version

    profile = detect_hardware()
    return {
        "gpu_type": profile.gpu_type,
        "gpu_name": profile.gpu_name,
        "vram_gb": profile.vram_gb,
        "vram_is_dedicated": profile.vram_is_dedicated,
        "system_ram_gb": profile.system_ram_gb,
        "operating_system": platform.system(),
        "platform_release": platform.release(),
        "architecture": platform.machine(),
        "distill_version": get_installed_version() or "",
    }


def _row_payload(speed: ModelSpeed, machine: dict[str, object]) -> dict[str, object]:
    # Comparability contract: two rows may only be compared when model,
    # quantization, num_ctx, provider and provider version all match. Recording
    # them is what lets `compare` refuse an apples-to-oranges ratio later.
    return {
        "schema_version": "bench-result.v1",
        "machine": machine,
        "provider": speed.provider,
        "model": speed.model,
        "prefill_tokens": speed.prefill_tokens,
        "prefill_seconds": round(speed.prefill_seconds, 4),
        "prefill_tokens_per_second": round(speed.prefill_tokens_per_second, 2),
        "decode_tokens": speed.decode_tokens,
        "decode_seconds": round(speed.decode_seconds, 4),
        "decode_tokens_per_second": round(speed.decode_tokens_per_second, 2),
        "load_plus_queue_seconds": round(speed.cold_load_seconds, 2),
        "num_ctx": speed.num_ctx,
        "reloaded_during_measure": speed.reloaded_during_measure,
        "outcome": speed.outcome,
        "error": speed.error,
    }


def _results_path(library_dir: Path) -> Path:
    return library_dir / ".distill" / "bench" / "results.jsonl"


def bench_cmd(
    models: str = typer.Option(
        "installed",
        "--models",
        "-m",
        help="installed (default) or a comma-separated list of local model ids",
    ),
    json_out: bool = typer.Option(False, "--json", help="Emit machine-readable results"),
) -> None:
    """Measure local model speed on this machine: prefill, decode, and cold load.

    Speed only. To judge whether a model is good enough, run distill eval.
    """
    run_preflight()
    config = get_config()

    from distill.commands.eval import _ollama_model_sizes  # pyright: ignore[reportPrivateUsage]

    sizes = _ollama_model_sizes()
    targets = (
        sorted(sizes, key=lambda name: sizes[name])
        if models == "installed"
        else [name.strip() for name in models.split(",") if name.strip()]
    )
    if not targets:
        console.print(
            "[yellow]No completion-capable local models found.[/yellow] "
            "Start Ollama and pull one, then re-run. See distill doctor."
        )
        raise typer.Exit(1)

    machine = _machine_facts()
    if not json_out:
        console.print()
        console.print("  [bold]Local model speed[/bold]")
        console.print(f"  [dim]{'-' * 66}[/dim]")
        console.print(
            f"  [dim]{machine['gpu_name'] or machine['gpu_type']} - "
            f"{machine['system_ram_gb']} GB RAM - {machine['operating_system']}[/dim]"
        )
        console.print(
            f"  [dim]Probe: {_PREFILL_TOKENS}-token prefill (cache-defeated) plus "
            f"{_DECODE_TOKENS}-token decode[/dim]"
        )
        console.print()

    rows: list[_Row] = []
    for index, model in enumerate(targets, start=1):
        if not json_out:
            console.print(f"  [{index}/{len(targets)}] measuring {model} ...")
        speed = asyncio.run(_probe_one("ollama", model))
        rows.append(_Row(speed=speed, calibration=_calibration_for(speed)))

    path = _results_path(config.library_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    append_jsonl_lines(
        path,
        [json.dumps(_row_payload(row.speed, machine), sort_keys=True) for row in rows],
        durable=True,
    )

    if json_out or json_mode_active():
        emit_json(
            {
                "machine": machine,
                "models": [_row_payload(row.speed, machine) for row in rows],
                "results_path": str(path),
            }
        )
        return

    console.print()
    header = f"  {'model':<32}{'load':>8}{'prefill':>13}{'decode':>13}{'20K/3K paper':>15}"
    console.print(f"[bold]{header}[/bold]")
    for row in rows:
        speed = row.speed
        if not speed.usable:
            note = speed.error[:38] if speed.error else "reloaded mid-probe; re-run"
            console.print(f"  {speed.model:<32}{'-':>8}{'-':>13}{'-':>13}  [yellow]{note}[/yellow]")
            continue
        paper = estimate_stage_duration("paper", row.calibration)
        console.print(
            f"  {speed.model:<32}"
            f"{format_duration(speed.cold_load_seconds):>8}"
            f"{speed.prefill_tokens_per_second:>9.1f} t/s"
            f"{speed.decode_tokens_per_second:>9.1f} t/s"
            f"{format_duration(paper.expected_seconds):>15}"
        )
    console.print()
    console.print(f"  [dim]Stored: {path}[/dim]")
    console.print("  [dim]Speed only. To judge quality, run distill eval.[/dim]")


def register(app: typer.Typer) -> None:
    """Attach the bench command to the app (called from distill.cli)."""
    app.command(name="bench", rich_help_panel="Maintain")(bench_cmd)


def stored_decode_rates() -> dict[str, float]:
    """Best measured decode rate per model from this machine's bench history.

    Returns ``{}`` when nothing has been measured, so callers fall back to a
    structural ordering rather than treating absence as zero speed.
    """
    from distill.jsonl import bounded_jsonl_lines

    try:
        config = get_config()
    except Exception:
        return {}
    path = _results_path(config.library_dir)
    if not path.exists():
        return {}
    rates: dict[str, float] = {}
    try:
        with path.open("rb") as handle:
            for payload in bounded_jsonl_lines(handle, max_row_bytes=_MAX_RESULT_ROW_BYTES):
                if payload is None:
                    continue  # oversized row: skip rather than fail the caller
                try:
                    parsed: object = json.loads(payload)
                except ValueError:
                    continue
                if not isinstance(parsed, dict):
                    continue
                row = cast(dict[str, object], parsed)
                model = str(row.get("model", ""))
                rate = row.get("decode_tokens_per_second")
                if not model or isinstance(rate, bool) or not isinstance(rate, (int, float)):
                    continue
                if rate <= 0:
                    continue
                rates[model] = max(rates.get(model, 0.0), float(rate))
    except OSError:
        return {}
    return rates

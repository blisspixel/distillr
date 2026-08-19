# pyright: strict
"""Wall-clock estimates for local routes, measured rather than modeled.

The dollar estimator has a legitimate cold-start default: a price list is a real
external fact, so an uncalibrated run can still be priced from the registry.
Speed has no such fact. Tokens per second is a property of *this* silicon, this
model, and this quantization, and nothing outside the machine can supply it.

So this module deliberately has **no default rate**. Too few samples means
``calibrated=False`` and callers print "unknown". That is the honest output, and
it is the specific failure the deleted ``estimate_throughput()`` committed: it
returned a hardcoded 60/35/25 per GPU tier and 0.0 for every other machine,
which on a laptop measured at 24.5 tok/s was both fabricated and backwards.

Two rates, never one. Prefill and decode differ by several times on the same
model -- 30.3 vs 24.5 tok/s on one machine here, 12.6 vs 3.1 on another -- so a
single blended rate misestimates a 20K-input paper by tens of minutes.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from distill.jsonl import JsonlIntegrityError, read_jsonl_objects_strict
from distill.llm.cost_policy import metered_api_spend_notice
from distill.pipeline.cost_estimates import _STAGE_TOKENS  # pyright: ignore[reportPrivateUsage]

__all__ = [
    "DurationEstimate",
    "SpeedCalibration",
    "estimate_stage_duration",
    "estimate_workflow_duration",
    "format_duration",
    "format_run_projection",
    "load_speed_calibration",
]

_BENCH_MAX_FILE_BYTES = 1_048_576
_BENCH_MAX_ROW_BYTES = 64 * 1024
_BENCH_MAX_ROWS = 2_000

# Bands are wider when the only evidence is production telemetry, because real
# prompts vary in length and a growing KV cache slows decode as context fills.
_PROBE_BAND = (0.8, 1.4)
_TELEMETRY_BAND = (0.7, 1.6)


def format_duration(seconds: float) -> str:
    """Render seconds as a compact, human-scannable duration."""
    if not math.isfinite(seconds) or seconds < 0:
        return "unknown"
    total = round(seconds)
    if total < 60:
        return f"{total}s"
    minutes, secs = divmod(total, 60)
    if minutes < 60:
        return f"{minutes}m{secs:02d}s" if secs else f"{minutes}m"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes:02d}m" if minutes else f"{hours}h"


@dataclass(frozen=True)
class SpeedCalibration:
    """Measured per-model inference rates for one machine.

    ``0.0`` means "not measured", never "instant". Both rates must be positive
    before any duration may be derived.
    """

    model: str = ""
    provider: str = ""
    prefill_tokens_per_second: float = 0.0
    decode_tokens_per_second: float = 0.0
    cold_load_seconds: float = 0.0
    basis: str = "uncalibrated"  # "probe" | "telemetry" | "mixed" | "uncalibrated"
    samples: dict[str, int] = field(default_factory=lambda: {"prefill": 0, "decode": 0})
    measured_at: str = ""

    @property
    def calibrated(self) -> bool:
        """True only when both phases have a usable measured rate."""
        return self.prefill_tokens_per_second > 0 and self.decode_tokens_per_second > 0

    @property
    def sample_count(self) -> int:
        return sum(self.samples.values())


@dataclass(frozen=True)
class DurationEstimate:
    """A projected wall-clock duration, or an explicit unknown."""

    expected_seconds: float = 0.0
    low_seconds: float = 0.0
    high_seconds: float = 0.0
    calibrated: bool = False
    basis: str = "uncalibrated"
    samples: int = 0
    model: str = ""

    def format(self) -> str:
        """One line suitable for a pre-run confirmation."""
        if not self.calibrated:
            target = f" for {self.model}" if self.model else ""
            return f"unknown (no local speed measurement{target})"
        band = f"{format_duration(self.low_seconds)}-{format_duration(self.high_seconds)}"
        return f"~{format_duration(self.expected_seconds)} (est; {band}, {self.samples} sample(s))"


def _estimate(
    seconds: float,
    calibration: SpeedCalibration,
) -> DurationEstimate:
    low, high = _PROBE_BAND if calibration.basis == "probe" else _TELEMETRY_BAND
    return DurationEstimate(
        expected_seconds=seconds,
        low_seconds=seconds * low,
        high_seconds=seconds * high,
        calibrated=True,
        basis=calibration.basis,
        samples=calibration.sample_count,
        model=calibration.model,
    )


def _uncalibrated(calibration: SpeedCalibration) -> DurationEstimate:
    return DurationEstimate(basis="uncalibrated", model=calibration.model)


def stage_seconds(
    input_tokens: int,
    output_tokens: int,
    calibration: SpeedCalibration,
) -> float:
    """Seconds to prefill ``input_tokens`` then decode ``output_tokens``."""
    return (
        input_tokens / calibration.prefill_tokens_per_second
        + output_tokens / calibration.decode_tokens_per_second
    )


def estimate_stage_duration(stage: str, calibration: SpeedCalibration) -> DurationEstimate:
    """Projected duration for one pipeline stage on this machine.

    Stage token volumes come from the cost estimator's table, so dollars and
    duration can never disagree about how big a paper is.
    """
    if stage not in _STAGE_TOKENS or not calibration.calibrated:
        return _uncalibrated(calibration)
    input_tokens, output_tokens = _STAGE_TOKENS[stage]
    return _estimate(stage_seconds(input_tokens, output_tokens, calibration), calibration)


def _finite_positive(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        return None
    return number


def _finite_non_negative(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return 0.0
    number = float(value)
    if not math.isfinite(number) or number < 0:
        return 0.0
    return number


def load_speed_calibration(
    library_dir: Path,
    *,
    model: str,
    provider: str,
) -> SpeedCalibration:
    """Latest successful ``distill bench`` row for this model on this library.

    Missing, unreadable, or mismatched rows return an uncalibrated object. That
    is the honest outcome: Distill will not invent a tokens-per-second number.
    """
    blank = SpeedCalibration(model=model, provider=provider)
    if not model or not provider:
        return blank
    path = library_dir / ".distill" / "bench" / "results.jsonl"
    try:
        rows = read_jsonl_objects_strict(
            path,
            max_file_bytes=_BENCH_MAX_FILE_BYTES,
            max_row_bytes=_BENCH_MAX_ROW_BYTES,
            max_rows=_BENCH_MAX_ROWS,
            confinement_root=library_dir,
        )
    except (JsonlIntegrityError, OSError, ValueError):
        return blank
    for row in reversed(rows):
        if row.get("outcome") != "success":
            continue
        if str(row.get("model") or "") != model:
            continue
        if str(row.get("provider") or "") != provider:
            continue
        prefill = _finite_positive(row.get("prefill_tokens_per_second"))
        decode = _finite_positive(row.get("decode_tokens_per_second"))
        if prefill is None or decode is None:
            continue
        return SpeedCalibration(
            model=model,
            provider=provider,
            prefill_tokens_per_second=prefill,
            decode_tokens_per_second=decode,
            cold_load_seconds=_finite_non_negative(row.get("load_plus_queue_seconds")),
            basis="probe",
            samples={"prefill": 1, "decode": 1},
        )
    return blank


def format_run_projection(
    *,
    cost_usd: float,
    duration: DurationEstimate,
    local: bool,
) -> str:
    """One pre-run line: dollars always, wall clock when time is the budget."""
    cost = f"${cost_usd:.2f}"
    if not local:
        return f"Projected spend {cost} on a metered cloud API. {metered_api_spend_notice()}"
    if duration.calibrated:
        where = f" on {duration.model}" if duration.model else ""
        return (
            f"Projected spend {cost} · {duration.format()}{where}. "
            "On a local route, wall clock is the budget; hours are expected."
        )
    return (
        f"Projected spend {cost} · {duration.format()}. "
        "Run `distill bench` once so Distill can estimate duration on this machine."
    )


def estimate_workflow_duration(
    stage_counts: Mapping[str, int],
    calibration: SpeedCalibration,
    *,
    serialized: bool = True,
) -> DurationEstimate:
    """Projected duration for a whole run: how many of each stage.

    ``serialized`` must stay True for local routes no matter what ``--workers``
    says. A local runtime serializes requests for a loaded model, and Distill's
    own contention wait blocks a second model rather than running it alongside,
    so dividing by a worker count would promise a speedup the machine cannot
    deliver.
    """
    if not calibration.calibrated:
        return _uncalibrated(calibration)
    total = 0.0
    for stage, count in stage_counts.items():
        if count <= 0 or stage not in _STAGE_TOKENS:
            continue
        input_tokens, output_tokens = _STAGE_TOKENS[stage]
        total += stage_seconds(input_tokens, output_tokens, calibration) * count
    if total <= 0:
        return _uncalibrated(calibration)
    if calibration.cold_load_seconds > 0:
        total += calibration.cold_load_seconds  # paid once per run
    del serialized  # documented invariant: never divide by a worker count
    return _estimate(total, calibration)

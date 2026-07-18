# pyright: strict
"""Per-prompt telemetry — JSONL logging and top-N query.

Every LLM call through the router emits a ``Telemetry_Record`` to
``<ops_dir>/telemetry.jsonl``.  The ``top_n_by_tokens`` helper enables the
"biggest prompts" view for cost optimisation.
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import asdict, dataclass, fields
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from distill.jsonl import append_jsonl_line, bounded_jsonl_lines
from distill.parsing import strict_json_loads

logger = logging.getLogger(__name__)

MAX_TELEMETRY_ROW_BYTES = 1024 * 1024


def _valid_token_count(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _valid_elapsed_seconds(value: object) -> bool:
    return (
        isinstance(value, int | float)
        and not isinstance(value, bool)
        and math.isfinite(float(value))
        and value >= 0
    )


@dataclass
class Telemetry_Record:
    """Per-prompt telemetry entry."""

    model: str
    workload_tag: str
    input_tokens: int
    output_tokens: int
    elapsed_seconds: float
    outcome: str  # "success" or error type string
    call_type: str = ""
    error_type: str = ""
    run_id: str = ""  # UUID per top-level CLI command or MCP invocation
    timestamp: str = ""  # ISO 8601, set at write time
    # New fields (0.6) — default empty for backward compat
    provider_type: str = ""  # "local" or "cloud"
    provider_name: str = ""  # "ollama", "lmstudio", "xai", etc.
    tokens_per_second: float = 0.0  # output_tokens / elapsed_seconds for local
    usage_source: str = "unknown"  # reported, conservative, unavailable, or legacy unknown


@dataclass(frozen=True, slots=True)
class TelemetryScan:
    """Validated provider history summary with bounded retained rows."""

    top_records: tuple[Telemetry_Record, ...] = ()
    local_total_seconds: float = 0.0
    local_total_tokens: int = 0
    local_records_count: int = 0
    cloud_records_count: int = 0
    total_tokens_per_second: float = 0.0
    malformed_rows: int = 0
    unreadable: bool = False


@dataclass(slots=True)
class _TelemetryTotals:
    local_seconds: float = 0.0
    local_tokens: int = 0
    local_records: int = 0
    cloud_records: int = 0
    tokens_per_second: float = 0.0

    def add(self, record: Telemetry_Record) -> bool:
        if record.provider_type != "local":
            self.cloud_records += 1
            return True
        next_seconds = self.local_seconds + float(record.elapsed_seconds)
        next_tokens_per_second = self.tokens_per_second
        if record.tokens_per_second > 0:
            next_tokens_per_second += float(record.tokens_per_second)
        if not math.isfinite(next_seconds) or not math.isfinite(next_tokens_per_second):
            return False
        self.local_records += 1
        self.local_seconds = next_seconds
        self.local_tokens += record.input_tokens + record.output_tokens
        self.tokens_per_second = next_tokens_per_second
        return True


_FIELD_NAMES = frozenset(field.name for field in fields(Telemetry_Record))
_TEXT_FIELDS = (
    "model",
    "workload_tag",
    "outcome",
    "call_type",
    "error_type",
    "run_id",
    "timestamp",
    "provider_type",
    "provider_name",
    "usage_source",
)


def write_record(ops_dir: str, record: Telemetry_Record) -> None:
    """Append *record* as a JSON line to ``<ops_dir>/telemetry.jsonl``.

    Auto-creates *ops_dir* on first write. Logs diagnostic detail and continues
    without blocking the LLM call if telemetry cannot be persisted.
    """
    if not ops_dir:
        return
    path = Path(ops_dir) / "telemetry.jsonl"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        record.timestamp = datetime.now(UTC).isoformat()
        append_jsonl_line(path, json.dumps(asdict(record), allow_nan=False))
    except Exception as exc:
        logger.debug("Failed to write telemetry to %s: %s", path, exc, exc_info=True)


def _parse_record(raw: bytes) -> Telemetry_Record:
    loaded = strict_json_loads(raw)
    if not isinstance(loaded, dict):
        raise ValueError("provider telemetry row is not an object")
    data = cast("dict[str, object]", loaded)
    filtered = {key: value for key, value in data.items() if key in _FIELD_NAMES}
    try:
        record = Telemetry_Record(**filtered)  # type: ignore[arg-type]
    except TypeError as exc:
        raise ValueError("provider telemetry row has an invalid shape") from exc
    if any(not isinstance(getattr(record, field_name), str) for field_name in _TEXT_FIELDS):
        raise ValueError("provider telemetry text field is invalid")
    if not (
        _valid_token_count(record.input_tokens)
        and _valid_token_count(record.output_tokens)
        and _valid_elapsed_seconds(record.elapsed_seconds)
        and _valid_elapsed_seconds(record.tokens_per_second)
    ):
        raise ValueError("provider telemetry measurement is invalid")
    return record


def _empty_scan(*, unreadable: bool = False) -> TelemetryScan:
    return TelemetryScan(unreadable=unreadable)


def scan_telemetry(ops_dir: str | Path, n: int = 10) -> TelemetryScan:
    """Stream and validate provider history while retaining at most *n* ranked rows."""

    path = Path(ops_dir) / "telemetry.jsonl"
    top_records: list[Telemetry_Record] = []
    totals = _TelemetryTotals()
    malformed_rows = 0
    retained_limit = max(0, n)
    try:
        with path.open("rb") as stream:
            for raw in bounded_jsonl_lines(stream, max_row_bytes=MAX_TELEMETRY_ROW_BYTES):
                if raw is None:
                    malformed_rows += 1
                    continue
                if not raw.strip():
                    continue
                try:
                    record = _parse_record(raw)
                except (RecursionError, ValueError):
                    malformed_rows += 1
                    continue
                if not totals.add(record):
                    malformed_rows += 1
                    continue
                if retained_limit:
                    top_records.append(record)
                    top_records.sort(
                        key=lambda candidate: candidate.input_tokens + candidate.output_tokens,
                        reverse=True,
                    )
                    del top_records[retained_limit:]
    except FileNotFoundError:
        return _empty_scan()
    except OSError as exc:
        logger.debug("Failed to read provider telemetry from %s: %s", path, exc)
        return _empty_scan(unreadable=True)

    if malformed_rows:
        suffix = "row" if malformed_rows == 1 else "rows"
        logger.debug(
            "Skipped %d malformed provider telemetry %s in %s",
            malformed_rows,
            suffix,
            path,
        )
    return TelemetryScan(
        top_records=tuple(top_records),
        local_total_seconds=totals.local_seconds,
        local_total_tokens=totals.local_tokens,
        local_records_count=totals.local_records,
        cloud_records_count=totals.cloud_records,
        total_tokens_per_second=totals.tokens_per_second,
        malformed_rows=malformed_rows,
    )


def top_n_by_tokens(ops_dir: str, n: int = 10) -> list[Telemetry_Record]:
    """Return the top *n* valid records by total token usage."""

    if n <= 0:
        return []
    return list(scan_telemetry(ops_dir, n=n).top_records)

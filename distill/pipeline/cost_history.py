"""Historical cost-log analytics used by reporting surfaces."""

# pyright: strict

from __future__ import annotations

import math
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any, BinaryIO, TypedDict, cast

from distill.jsonl import bounded_jsonl_lines
from distill.library.confined import read_confined_bytes, validate_confined_path
from distill.parsing import strict_json_loads

__all__ = [
    "CostHistoryCoverage",
    "CostLogScan",
    "cost_history_integrity_message",
    "estimator_accuracy",
    "find_confined_cost_log",
    "project_cost_log_row",
    "projected_next_run_cost",
    "read_confined_cost_log_rows",
    "read_cost_log_rows",
    "scan_confined_cost_log",
    "scan_cost_log",
    "select_cost_log_path",
]

_MAX_COST_LOG_BYTES = 16 * 1024 * 1024
_MAX_COST_LOG_ROWS = 10_000
_MAX_COST_LOG_ROW_BYTES = 1024 * 1024
_PUBLIC_COST_FIELDS = (
    "timestamp",
    "run_id",
    "command",
    "full_videos",
    "shorts",
    "grok_calls",
    "gemini_queries",
    "gemini_query_outcomes",
    "total_input_tokens",
    "total_output_tokens",
    "conservative_usage_calls",
    "actual_cost",
    "estimated_cost",
    "elapsed_seconds",
    "profile_receipt_id",
    "profile_receipt_cost_usd",
    "profile_receipt_tracker_id",
    "by_call_type",
    "by_model",
    "by_provider",
    "by_route_class",
    "usage_ledger",
    # Scope markers the writer stamps precisely to disqualify a confident total.
    # Omitting them stripped them from every projected row, so MCP consumers
    # summed ``actual_cost`` and published a clean "$0.00" for runs whose
    # external cost is explicitly unknown (host-managed or remote-local routes).
    # The CLI reads raw rows and reports the scope correctly; the projection has
    # to carry them so the MCP surfaces can do the same.
    "external_cost_status",
    "actual_cost_scope",
)


class CostHistoryCoverage(TypedDict):
    """Machine-readable completeness evidence for one ledger scan."""

    complete: bool
    valid_rows: int
    retained_rows: int
    malformed_rows: int
    omitted_valid_rows: int
    invalid_timestamp_rows: int
    read_error: bool


@dataclass(frozen=True, slots=True)
class CostLogScan:
    """Strict cost-ledger rows plus explicit evidence coverage."""

    rows: tuple[dict[str, Any], ...] = ()
    valid_rows: int = 0
    malformed_rows: int = 0
    omitted_valid_rows: int = 0
    invalid_timestamp_rows: int = 0
    unreadable: bool = False

    @property
    def complete(self) -> bool:
        return not (
            self.malformed_rows
            or self.omitted_valid_rows
            or self.invalid_timestamp_rows
            or self.unreadable
        )

    def coverage(self) -> CostHistoryCoverage:
        return {
            "complete": self.complete,
            "valid_rows": self.valid_rows,
            "retained_rows": len(self.rows),
            "malformed_rows": self.malformed_rows,
            "omitted_valid_rows": self.omitted_valid_rows,
            "invalid_timestamp_rows": self.invalid_timestamp_rows,
            "read_error": self.unreadable,
        }


def cost_history_integrity_message(path: Path | str, scan: CostLogScan) -> str:
    """Describe incomplete ledger evidence without claiming partial totals.

    ``path`` may be a filesystem path or an already agent-safe display label
    (for example a library-relative POSIX string). Callers that surface this
    message to untrusted MCP clients should pass a confined display label.
    """

    reasons: list[str] = []
    if scan.unreadable:
        reasons.append("the file could not be read safely")
    if scan.malformed_rows:
        label = "row" if scan.malformed_rows == 1 else "rows"
        reasons.append(f"{scan.malformed_rows} malformed {label}")
    if scan.omitted_valid_rows:
        label = "row is" if scan.omitted_valid_rows == 1 else "rows are"
        reasons.append(f"{scan.omitted_valid_rows} valid {label} outside the retained window")
    if scan.invalid_timestamp_rows:
        label = "row" if scan.invalid_timestamp_rows == 1 else "rows"
        reasons.append(f"{scan.invalid_timestamp_rows} {label} without a valid timestamp")
    detail = "; ".join(reasons) or "coverage could not be proven"
    return f"Cost history is incomplete at {path}: {detail}."


def _valid_nonnegative_cost(value: object, *, allow_none: bool) -> bool:
    if value is None:
        return allow_none
    if isinstance(value, bool) or not isinstance(value, int | float):
        return False
    try:
        cost = float(value)
    except OverflowError:
        return False
    return math.isfinite(cost) and cost >= 0


def _has_valid_monetary_values(row: dict[str, Any]) -> bool:
    return _valid_nonnegative_cost(row.get("actual_cost"), allow_none=False) and (
        "estimated_cost" not in row
        or _valid_nonnegative_cost(row.get("estimated_cost"), allow_none=True)
    )


def _has_valid_timestamp(row: dict[str, Any]) -> bool:
    value = row.get("timestamp")
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (OverflowError, ValueError):
        return False
    return True


def _scan_cost_stream(stream: BinaryIO, *, limit: int) -> CostLogScan:
    rows: deque[dict[str, Any]] = deque(maxlen=limit)
    valid_rows = 0
    malformed_rows = 0
    omitted_valid_rows = 0
    invalid_timestamp_rows = 0
    for raw in bounded_jsonl_lines(stream, max_row_bytes=_MAX_COST_LOG_ROW_BYTES):
        if raw is None:
            malformed_rows += 1
            continue
        if not raw.strip():
            continue
        try:
            loaded = strict_json_loads(raw)
        except (RecursionError, ValueError):
            malformed_rows += 1
            continue
        if not isinstance(loaded, dict):
            malformed_rows += 1
            continue
        row = cast(dict[str, Any], loaded)
        if not _has_valid_monetary_values(row):
            malformed_rows += 1
            continue
        valid_rows += 1
        if not _has_valid_timestamp(row):
            invalid_timestamp_rows += 1
        if len(rows) == limit:
            omitted_valid_rows += 1
        rows.append(row)
    return CostLogScan(
        rows=tuple(rows),
        valid_rows=valid_rows,
        malformed_rows=malformed_rows,
        omitted_valid_rows=omitted_valid_rows,
        invalid_timestamp_rows=invalid_timestamp_rows,
    )


def _unreadable_scan() -> CostLogScan:
    return CostLogScan(unreadable=True)


def scan_confined_cost_log(
    path: Path,
    root: Path,
    *,
    limit: int = _MAX_COST_LOG_ROWS,
) -> CostLogScan:
    """Read one bounded no-follow cost ledger with explicit coverage."""

    if limit < 1:
        raise ValueError("cost ledger row limit must be positive")
    try:
        content = read_confined_bytes(path, root, max_bytes=_MAX_COST_LOG_BYTES)
        if content is None:
            try:
                path.lstat()
            except FileNotFoundError:
                return CostLogScan()
            return _unreadable_scan()
    except OSError:
        return _unreadable_scan()
    return _scan_cost_stream(BytesIO(content), limit=min(limit, _MAX_COST_LOG_ROWS))


def read_confined_cost_log_rows(
    path: Path,
    root: Path,
    *,
    limit: int = _MAX_COST_LOG_ROWS,
) -> list[dict[str, object]]:
    """Read strict object rows through the no-follow cost-log boundary."""

    if limit <= 0:
        return []
    scan = scan_confined_cost_log(path, root)
    return [cast("dict[str, object]", row) for row in scan.rows[-min(limit, _MAX_COST_LOG_ROWS) :]]


def find_confined_cost_log(library_dir: Path) -> Path | None:
    """Select the current or legacy cost log only when it is a confined file."""

    for path in (
        library_dir / ".distill" / "cost_log.jsonl",
        library_dir / "cost_log.jsonl",
    ):
        if validate_confined_path(path, library_dir, expect_directory=False) is not None:
            return path
    return None


def select_cost_log_path(library_dir: Path) -> Path | None:
    """Select the newest ledger candidate without hiding an unsafe path."""

    for path in (
        library_dir / ".distill" / "cost_log.jsonl",
        library_dir / "cost_log.jsonl",
    ):
        try:
            path.lstat()
        except FileNotFoundError:
            continue
        except OSError:
            return path
        return path
    return None


def project_cost_log_row(row: Mapping[str, object]) -> dict[str, object]:
    """Project one ledger row onto the stable public cost-resource surface."""

    return {field: row[field] for field in _PUBLIC_COST_FIELDS if field in row}


def scan_cost_log(path: Path, *, limit: int = _MAX_COST_LOG_ROWS) -> CostLogScan:
    """Stream one local cost ledger with bounded retained rows and no writes."""

    if limit < 1:
        raise ValueError("cost ledger row limit must be positive")
    try:
        with path.open("rb") as stream:
            return _scan_cost_stream(stream, limit=min(limit, _MAX_COST_LOG_ROWS))
    except FileNotFoundError:
        return CostLogScan()
    except OSError:
        return _unreadable_scan()


def read_cost_log_rows(
    path: Path,
    *,
    limit: int = _MAX_COST_LOG_ROWS,
    root: Path | None = None,
) -> list[dict[str, Any]]:
    """Read the newest bounded, strict JSON object rows from a cost ledger."""

    if limit <= 0:
        return []
    scan = scan_confined_cost_log(path, root) if root is not None else scan_cost_log(path)
    return list(scan.rows[-min(limit, _MAX_COST_LOG_ROWS) :])


def _positive_finite_cost(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    try:
        cost = float(value)
    except OverflowError:
        return None
    return cost if math.isfinite(cost) and cost > 0 else None


def _median(values: list[float]) -> float | None:
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2:
        return ordered[mid]
    midpoint = ordered[mid - 1] / 2.0 + ordered[mid] / 2.0
    return midpoint if math.isfinite(midpoint) else None


def _finite_percentage_difference(estimated: float, actual: float) -> float | None:
    """Return signed percentage error only when the derived metric is representable."""

    value = (estimated / actual - 1.0) * 100.0
    return value if math.isfinite(value) else None


def _finite_mean(values: list[float]) -> float | None:
    """Average finite values without overflowing a representable mean."""

    if not values:
        return None
    count = len(values)
    try:
        mean = math.fsum(value / count for value in values)
    except OverflowError:
        return None
    return mean if math.isfinite(mean) else None


def estimator_accuracy(entries: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Summarize estimate accuracy for runs that record estimate and spend."""
    signed_pct: list[float] = []
    for row in entries:
        if str(row.get("command", "")).endswith("_preview"):
            continue
        estimated = _positive_finite_cost(row.get("estimated_cost"))
        actual = _positive_finite_cost(row.get("actual_cost"))
        if estimated is None or actual is None:
            continue
        percentage = _finite_percentage_difference(estimated, actual)
        if percentage is None:
            return None
        signed_pct.append(percentage)
    if not signed_pct:
        return None
    recent = signed_pct[-10:]
    median_abs = _median([abs(value) for value in signed_pct])
    median_signed = _median(signed_pct)
    recent_median_abs = _median([abs(value) for value in recent])
    if median_abs is None or median_signed is None or recent_median_abs is None:
        return None
    return {
        "runs_compared": len(signed_pct),
        "median_abs_pct_error": round(median_abs, 1),
        "median_signed_pct_error": round(median_signed, 1),
        "recent10_median_abs_pct_error": round(recent_median_abs, 1),
    }


def projected_next_run_cost(entries: list[dict[str, Any]]) -> float | None:
    """Average up to five recent positive costs from non-preview runs."""
    costs: list[float] = []
    for row in reversed(entries):
        if str(row.get("command", "")).endswith("_preview"):
            continue
        actual = _positive_finite_cost(row.get("actual_cost"))
        if actual is not None:
            costs.append(actual)
        if len(costs) >= 5:
            break
    if not costs:
        return 0.0
    return _finite_mean(costs)

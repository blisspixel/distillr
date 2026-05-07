# pyright: strict
"""Per-prompt telemetry — JSONL logging and top-N query.

Every LLM call through the router emits a ``Telemetry_Record`` to
``<ops_dir>/telemetry.jsonl``.  The ``top_n_by_tokens`` helper enables the
"biggest prompts" view for cost optimisation.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, fields
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


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


def write_record(ops_dir: str, record: Telemetry_Record) -> None:
    """Append *record* as a JSON line to ``<ops_dir>/telemetry.jsonl``.

    Auto-creates *ops_dir* on first write.  Logs a warning and continues
    (never blocks the LLM call) if the path is not writable.
    """
    if not ops_dir:
        return
    path = Path(ops_dir) / "telemetry.jsonl"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        record.timestamp = datetime.now(timezone.utc).isoformat()
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(record)) + "\n")
    except OSError as exc:
        logger.warning("Failed to write telemetry to %s: %s", path, exc)


def top_n_by_tokens(ops_dir: str, n: int = 10) -> list[Telemetry_Record]:
    """Return the top *n* records by total token usage (input + output).

    Skips malformed JSONL lines gracefully.
    """
    path = Path(ops_dir) / "telemetry.jsonl"
    if not path.exists():
        return []

    field_names: set[str] = {f.name for f in fields(Telemetry_Record)}
    records: list[Telemetry_Record] = []

    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            data: dict[str, object] = json.loads(line)
            # Only pass keys that are valid Telemetry_Record fields
            filtered: dict[str, object] = {k: v for k, v in data.items() if k in field_names}
            records.append(Telemetry_Record(**filtered))  # type: ignore[arg-type]
        except (json.JSONDecodeError, TypeError):
            continue

    records.sort(
        key=lambda r: r.input_tokens + r.output_tokens,
        reverse=True,
    )
    return records[:n]

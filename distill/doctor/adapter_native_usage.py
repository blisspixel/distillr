"""Strict native-usage boundary for future CLI adapter wrappers."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from distill.doctor.adapter_manifest import AdapterUsage

ADAPTER_NATIVE_USAGE_SCHEMA_VERSION = "adapter-native-usage.v1"
ADAPTER_NATIVE_USAGE_REQUIRED_FIELDS: tuple[str, ...] = (
    "schema_version",
    "adapter",
    "source",
    "usage",
)

_ADAPTER_NAMES = frozenset(
    {
        "codex",
        "claude",
        "grok",
        "gemini-cli",
        "antigravity",
        "copilot",
        "ollama",
        "lmstudio",
    }
)


class AdapterNativeUsageError(ValueError):
    """Raised when adapter native usage cannot be accepted."""


class AdapterNativeUsageRecord(BaseModel):
    """Parsed native usage record produced by an adapter wrapper."""

    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal["adapter-native-usage.v1"]
    adapter: str
    source: Literal["cli-json", "usage-file", "stdout-json", "stderr-json", "wrapper"]
    usage: AdapterUsage
    model: str = ""
    request_id: str = ""
    stop_reason: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("adapter")
    @classmethod
    def _known_adapter(cls, value: str) -> str:
        if value not in _ADAPTER_NAMES:
            raise ValueError(f"unknown adapter: {value}")
        return value

    @field_validator("model", "request_id", "stop_reason")
    @classmethod
    def _strip_text(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def _require_usage_signal(self) -> Self:
        if not self.usage.has_signal:
            raise ValueError("adapter native usage must include token counts or metadata")
        return self

    def to_adapter_usage(self) -> AdapterUsage:
        """Return manifest-compatible usage with usage-signal provenance."""

        native = dict(self.usage.native)
        native.setdefault(
            "distill_usage_signal",
            {
                "schema_version": self.schema_version,
                "source": self.source,
                "model": self.model,
                "request_id": self.request_id,
                "stop_reason": self.stop_reason,
                "metadata": self.metadata,
            },
        )
        return AdapterUsage(
            input_tokens=self.usage.input_tokens,
            output_tokens=self.usage.output_tokens,
            native=native,
        )

    def to_dict(self) -> dict[str, Any]:
        """Return a stable JSON-serializable representation."""

        return self.model_dump(mode="json")


def codex_jsonl_native_usage(
    jsonl: str,
    *,
    model: str = "",
    request_id: str = "",
    stop_reason: str = "complete",
) -> AdapterNativeUsageRecord:
    """Collect native usage from Codex `exec --json` JSONL output."""

    event_count = 0
    usage_events: list[dict[str, Any]] = []
    thread_id = request_id.strip()
    saw_failed_turn = False
    for line_number, line in enumerate(jsonl.splitlines(), start=1):
        event = _parse_codex_jsonl_event(line, line_number)
        if event is None:
            continue
        event_count += 1
        event_type = event.get("type")
        if event_type == "thread.started" and not thread_id:
            thread_id = _optional_text(event.get("thread_id"))
        if event_type == "turn.failed":
            saw_failed_turn = True
        if event_type == "turn.completed":
            usage = event.get("usage")
            if not isinstance(usage, Mapping):
                raise AdapterNativeUsageError(
                    f"codex JSONL turn.completed usage must be an object: {line_number}"
                )
            usage_events.append(dict(usage))

    if not usage_events:
        raise AdapterNativeUsageError("codex JSONL usage not found")
    if saw_failed_turn and stop_reason == "complete":
        stop_reason = "failed"

    cached_input_tokens = _sum_optional_usage_field(usage_events, "cached_input_tokens")
    reasoning_output_tokens = _sum_optional_usage_field(usage_events, "reasoning_output_tokens")
    return AdapterNativeUsageRecord(
        schema_version=ADAPTER_NATIVE_USAGE_SCHEMA_VERSION,
        adapter="codex",
        source="stdout-json",
        usage=AdapterUsage(
            input_tokens=_sum_optional_usage_field(usage_events, "input_tokens"),
            output_tokens=_sum_optional_usage_field(usage_events, "output_tokens"),
            native={
                "adapter_format": "codex-jsonl",
                "event_count": event_count,
                "usage_event_count": len(usage_events),
                "cached_input_tokens": cached_input_tokens,
                "reasoning_output_tokens": reasoning_output_tokens,
                "raw_usage_events": usage_events,
            },
        ),
        model=model,
        request_id=thread_id,
        stop_reason=stop_reason,
    )


def adapter_native_usage_contract() -> dict[str, Any]:
    """Return the native usage contract for doctor reports and docs."""

    return {
        "schema_version": ADAPTER_NATIVE_USAGE_SCHEMA_VERSION,
        "required_fields": list(ADAPTER_NATIVE_USAGE_REQUIRED_FIELDS),
        "adapters": sorted(_ADAPTER_NAMES),
        "sources": ["cli-json", "usage-file", "stdout-json", "stderr-json", "wrapper"],
        "requires_signal": True,
        "manifest_usage_shape": {
            "input_tokens": "integer|null",
            "output_tokens": "integer|null",
            "native": "object",
        },
    }


def validate_adapter_native_usage(payload: Mapping[str, Any]) -> AdapterNativeUsageRecord:
    """Parse and validate a native usage record."""

    return AdapterNativeUsageRecord.model_validate(dict(payload))


def load_adapter_native_usage(
    path: Path,
    *,
    scratch_root: Path | None = None,
) -> AdapterNativeUsageRecord:
    """Load a JSON or YAML native usage record from scratch."""

    usage_path = _resolve_usage_path(path, scratch_root=scratch_root)
    text = usage_path.read_text(encoding="utf-8")
    if usage_path.suffix.lower() in {".yaml", ".yml"}:
        payload = yaml.safe_load(text)
    else:
        payload = json.loads(text)
    if not isinstance(payload, Mapping):
        raise AdapterNativeUsageError("adapter native usage must be a mapping")
    return validate_adapter_native_usage(payload)


def _resolve_usage_path(path: Path, *, scratch_root: Path | None) -> Path:
    if scratch_root is None:
        return path
    if path.is_absolute():
        raise AdapterNativeUsageError(f"adapter native usage path must be scratch relative: {path}")
    root = scratch_root.resolve()
    candidate = (root / path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise AdapterNativeUsageError(
            f"adapter native usage path escapes scratch workspace: {path}"
        ) from exc
    return candidate


def _parse_codex_jsonl_event(line: str, line_number: int) -> Mapping[str, Any] | None:
    text = line.strip()
    if not text:
        return None
    try:
        event = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AdapterNativeUsageError(
            f"codex JSONL usage line is invalid JSON: {line_number}"
        ) from exc
    if not isinstance(event, Mapping):
        raise AdapterNativeUsageError(f"codex JSONL usage line must be an object: {line_number}")
    return event


def _sum_optional_usage_field(usages: list[dict[str, Any]], key: str) -> int | None:
    total = 0
    found = False
    for usage in usages:
        if key not in usage or usage[key] is None:
            continue
        value = usage[key]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise AdapterNativeUsageError(
                f"codex JSONL usage field {key} must be a non-negative integer"
            )
        total += value
        found = True
    return total if found else None


def _optional_text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""

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


def claude_json_native_usage(
    json_output: str,
    *,
    model: str = "",
    request_id: str = "",
    stop_reason: str = "complete",
) -> AdapterNativeUsageRecord:
    """Collect native usage from Claude Code JSON or stream JSON output."""

    events = _parse_claude_json_events(json_output)
    usage_events = _claude_top_level_usage_events(events)
    if not usage_events:
        usage_events = _claude_message_usage_events(events)
    if not usage_events:
        raise AdapterNativeUsageError("claude JSON usage not found")

    result_events = _events_with_type(events, "result")
    metadata_events = result_events or events
    session_id = request_id.strip() or _first_text(metadata_events, "session_id")
    model_name = model.strip() or _first_text(metadata_events, "model") or _message_model(events)
    final_stop_reason = _claude_stop_reason(metadata_events, stop_reason=stop_reason)
    native: dict[str, Any] = {
        "adapter_format": "claude-json",
        "event_count": len(events),
        "usage_event_count": len(usage_events),
        "cache_creation_input_tokens": _sum_optional_usage_field(
            usage_events,
            "cache_creation_input_tokens",
            label="claude JSON",
        ),
        "cache_read_input_tokens": _sum_optional_usage_field(
            usage_events,
            "cache_read_input_tokens",
            label="claude JSON",
        ),
        "raw_usage_events": usage_events,
    }
    for key in ("duration_ms", "duration_api_ms", "num_turns"):
        value = _sum_optional_usage_field(metadata_events, key, label="claude JSON")
        if value is not None:
            native[key] = value
    total_cost = _sum_optional_number_field(metadata_events, "total_cost_usd", "claude JSON")
    if total_cost is not None:
        native["total_cost_usd"] = total_cost
    subtypes = tuple(
        subtype for event in metadata_events if (subtype := _optional_text(event.get("subtype")))
    )
    if subtypes:
        native["result_subtypes"] = subtypes

    return AdapterNativeUsageRecord(
        schema_version=ADAPTER_NATIVE_USAGE_SCHEMA_VERSION,
        adapter="claude",
        source="stdout-json",
        usage=AdapterUsage(
            input_tokens=_sum_optional_usage_field(
                usage_events,
                "input_tokens",
                label="claude JSON",
            ),
            output_tokens=_sum_optional_usage_field(
                usage_events,
                "output_tokens",
                label="claude JSON",
            ),
            native=native,
        ),
        model=model_name,
        request_id=session_id,
        stop_reason=final_stop_reason,
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


def _parse_claude_json_events(json_output: str) -> list[dict[str, Any]]:
    text = json_output.strip()
    if not text:
        raise AdapterNativeUsageError("claude JSON output is empty")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return _parse_claude_jsonl_events(text)
    if not isinstance(payload, Mapping):
        raise AdapterNativeUsageError("claude JSON output must be an object or JSONL objects")
    return [dict(payload)]


def _parse_claude_jsonl_events(text: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            event = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise AdapterNativeUsageError(
                f"claude JSON usage line is invalid JSON: {line_number}"
            ) from exc
        if not isinstance(event, Mapping):
            raise AdapterNativeUsageError(
                f"claude JSON usage line must be an object: {line_number}"
            )
        events.append(dict(event))
    if not events:
        raise AdapterNativeUsageError("claude JSON output is empty")
    return events


def _claude_top_level_usage_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    usage_events: list[dict[str, Any]] = []
    for event in events:
        if "usage" not in event or event["usage"] is None:
            continue
        if not isinstance(event["usage"], Mapping):
            raise AdapterNativeUsageError("claude JSON usage must be an object")
        usage_events.append(dict(event["usage"]))
    return usage_events


def _claude_message_usage_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    usage_events: list[dict[str, Any]] = []
    for event in events:
        message = event.get("message")
        if not isinstance(message, Mapping):
            continue
        usage = message.get("usage")
        if usage is None:
            continue
        if not isinstance(usage, Mapping):
            raise AdapterNativeUsageError("claude JSON message usage must be an object")
        usage_events.append(dict(usage))
    return usage_events


def _events_with_type(events: list[dict[str, Any]], event_type: str) -> list[dict[str, Any]]:
    return [event for event in events if _optional_text(event.get("type")) == event_type]


def _first_text(events: list[dict[str, Any]], key: str) -> str:
    for event in events:
        value = _optional_text(event.get(key))
        if value:
            return value
    return ""


def _message_model(events: list[dict[str, Any]]) -> str:
    for event in events:
        message = event.get("message")
        if not isinstance(message, Mapping):
            continue
        model = _optional_text(message.get("model"))
        if model:
            return model
    return ""


def _claude_stop_reason(events: list[dict[str, Any]], *, stop_reason: str) -> str:
    explicit = stop_reason.strip()
    if explicit != "complete":
        return explicit
    if any(event.get("is_error") is True for event in events):
        return "failed"
    return _first_text(events, "stop_reason") or explicit


def _sum_optional_usage_field(
    usages: list[dict[str, Any]],
    key: str,
    *,
    label: str = "codex JSONL",
) -> int | None:
    total = 0
    found = False
    for usage in usages:
        if key not in usage or usage[key] is None:
            continue
        value = usage[key]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise AdapterNativeUsageError(
                f"{label} usage field {key} must be a non-negative integer"
            )
        total += value
        found = True
    return total if found else None


def _sum_optional_number_field(
    events: list[dict[str, Any]],
    key: str,
    label: str,
) -> float | None:
    total = 0.0
    found = False
    for event in events:
        if key not in event or event[key] is None:
            continue
        value = event[key]
        if isinstance(value, bool) or not isinstance(value, int | float) or value < 0:
            raise AdapterNativeUsageError(f"{label} field {key} must be a non-negative number")
        total += float(value)
        found = True
    return total if found else None


def _optional_text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _get_first_positive_int(d: dict[str, Any], *keys: str) -> int | None:
    """Return first non-negative int value for any of the keys, or None."""
    for k in keys:
        if k in d and d[k] is not None:
            v = d[k]
            if isinstance(v, bool) or not isinstance(v, int) or v < 0:
                raise AdapterNativeUsageError(
                    f"gemini-cli JSON usage field {k} must be a non-negative integer"
                )
            return v
    return None


# --- Grok, Gemini CLI, Antigravity native usage parsers (0.19 plan-quota wiring) ---
# These follow the same strict structural contract as codex/claude.
# Formats are derived from typical CLI JSON/JSONL usage events for the respective
# adapters (refine on official support statements + real capture). All paths are
# rule-owned (parse + aggregate); no semantic judgment.


def grok_json_native_usage(
    json_output: str,
    *,
    model: str = "",
    request_id: str = "",
    stop_reason: str = "complete",
) -> AdapterNativeUsageRecord:
    """Collect native usage from Grok CLI JSON or JSONL output.

    Expected shapes (tolerated):
    - Top-level: {"usage": {"input_tokens": N, "output_tokens": N}, ...}
    - Or message-wrapped usage events.
    """
    events = _parse_generic_json_events(json_output)
    usage_events = _generic_usage_events(events, usage_key="usage")
    if not usage_events:
        usage_events = _generic_usage_events(events, usage_key="message")
    if not usage_events:
        raise AdapterNativeUsageError("grok JSON usage not found")

    session_id = (
        request_id.strip() or _first_text(events, "request_id") or _first_text(events, "id")
    )
    model_name = model.strip() or _first_text(events, "model")

    return AdapterNativeUsageRecord(
        schema_version=ADAPTER_NATIVE_USAGE_SCHEMA_VERSION,
        adapter="grok",
        source="stdout-json",
        usage=AdapterUsage(
            input_tokens=_sum_optional_usage_field(usage_events, "input_tokens", label="grok JSON"),
            output_tokens=_sum_optional_usage_field(
                usage_events, "output_tokens", label="grok JSON"
            ),
            native={
                "adapter_format": "grok-json",
                "event_count": len(events),
                "usage_event_count": len(usage_events),
                "raw_usage_events": usage_events,
            },
        ),
        model=model_name,
        request_id=session_id,
        stop_reason=stop_reason,
    )


def gemini_cli_json_native_usage(
    json_output: str,
    *,
    model: str = "",
    request_id: str = "",
    stop_reason: str = "complete",
) -> AdapterNativeUsageRecord:
    """Collect native usage from Gemini CLI / Antigravity-style JSON output.

    Tolerates usageMetadata style or direct usage:
    - {"usageMetadata": {"promptTokenCount": N, "candidatesTokenCount": N}}
    - Or {"usage": {"input_tokens" or "prompt_tokens", "output_tokens" or "completion_tokens"}}
    """
    events = _parse_generic_json_events(json_output)
    usage_events: list[dict[str, Any]] = []
    for e in events:
        if "usageMetadata" in e and isinstance(e["usageMetadata"], Mapping):
            um = _normalize_gemini_usage_metadata(dict(e["usageMetadata"]))
            usage_events.append(um)
        elif "usage" in e and isinstance(e["usage"], Mapping):
            usage_events.append(dict(e["usage"]))

    if not usage_events and events and isinstance(events[0], Mapping) and "usage" in events[0]:
        usage_events = [dict(events[0]["usage"])]
    if not usage_events:
        raise AdapterNativeUsageError("gemini-cli JSON usage not found")

    model_name = model.strip() or _first_text(events, "model")
    sid = (
        request_id.strip() or _first_text(events, "request_id") or _first_text(events, "session_id")
    )

    input_toks = _get_first_positive_int(
        usage_events[0], "input_tokens", "prompt_tokens", "promptTokenCount"
    )
    output_toks = _get_first_positive_int(
        usage_events[0], "output_tokens", "completion_tokens", "candidatesTokenCount"
    )

    # if not in first, try sum from list
    if input_toks is None:
        input_toks = _sum_optional_usage_field(
            usage_events, "input_tokens", label="gemini-cli JSON"
        )
    if output_toks is None:
        output_toks = _sum_optional_usage_field(
            usage_events, "output_tokens", label="gemini-cli JSON"
        )

    return AdapterNativeUsageRecord(
        schema_version=ADAPTER_NATIVE_USAGE_SCHEMA_VERSION,
        adapter="gemini-cli",
        source="stdout-json",
        usage=AdapterUsage(
            input_tokens=input_toks,
            output_tokens=output_toks,
            native={
                "adapter_format": "gemini-cli-json",
                "event_count": len(events),
                "usage_event_count": len(usage_events),
                "raw_usage_events": usage_events,
            },
        ),
        model=model_name,
        request_id=sid,
        stop_reason=stop_reason,
    )


def antigravity_json_native_usage(
    json_output: str,
    *,
    model: str = "",
    request_id: str = "",
    stop_reason: str = "complete",
) -> AdapterNativeUsageRecord:
    """Collect native usage forcing adapter='antigravity' (reuses tolerant normalizer)."""
    rec = gemini_cli_json_native_usage(
        json_output, model=model, request_id=request_id, stop_reason=stop_reason
    )
    return AdapterNativeUsageRecord(
        schema_version=rec.schema_version,
        adapter="antigravity",
        source=rec.source,
        usage=rec.usage,
        model=rec.model,
        request_id=rec.request_id,
        stop_reason=rec.stop_reason,
        metadata=getattr(rec, "metadata", {}),
    )


def _parse_generic_json_events(text: str) -> list[dict[str, Any]]:
    """Best-effort JSON or JSONL event list (shared helper for new adapters)."""
    events: list[dict[str, Any]] = []
    stripped = text.strip()
    if not stripped:
        return events
    # Try as single JSON first
    try:
        obj = json.loads(stripped)
    except json.JSONDecodeError:
        obj = None
    if isinstance(obj, list):
        return [dict(e) for e in obj if isinstance(e, Mapping)]
    if isinstance(obj, Mapping):
        return [dict(obj)]
    # JSONL fallback
    for _line_number, line in enumerate(stripped.splitlines(), start=1):
        s = line.strip()
        if not s:
            continue
        try:
            e = json.loads(s)
            if isinstance(e, Mapping):
                events.append(dict(e))
        except json.JSONDecodeError:
            # tolerant; ignore noise lines
            continue
    return events


def _generic_usage_events(
    events: list[dict[str, Any]], *, usage_key: str = "usage"
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for e in events:
        if usage_key in e and isinstance(e[usage_key], Mapping):
            out.append(dict(e[usage_key]))
        # also accept direct on event for top level
        if "input_tokens" in e or "prompt_tokens" in e:
            out.append(dict(e))
    return out


def _normalize_gemini_usage_metadata(um: dict[str, Any]) -> dict[str, Any]:
    """Normalize Gemini usageMetadata keys to our internal input/output_tokens."""
    if "promptTokenCount" in um or "input_tokens" not in um:
        um.setdefault("input_tokens", um.get("promptTokenCount"))
    if "candidatesTokenCount" in um or "output_tokens" not in um:
        um.setdefault("output_tokens", um.get("candidatesTokenCount"))
    return um

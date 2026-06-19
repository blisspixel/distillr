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

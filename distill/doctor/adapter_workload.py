"""Strict workload-package boundary for future CLI adapter runs."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Any, Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ADAPTER_WORKLOAD_SCHEMA_VERSION = "adapter-workload.v1"
ADAPTER_WORKLOADS: tuple[str, ...] = (
    "profile-enrichment",
    "corpus-qa",
    "candidate-classification",
    "synthesis-planning",
)
ADAPTER_WORKLOAD_PATH_FIELDS: tuple[str, ...] = (
    "prompt_path",
    "source_paths",
    "output_schema_path",
    "result_manifest_path",
    "allowed_write_paths",
)

_WORKLOAD_PATH_RE = re.compile(r"^[A-Za-z]:")


class AdapterWorkloadError(ValueError):
    """Raised when an adapter workload package cannot be accepted."""


class AdapterWorkloadPackage(BaseModel):
    """Parsed `adapter-workload.v1` package for a future adapter attempt."""

    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal["adapter-workload.v1"]
    workload: Literal[
        "profile-enrichment",
        "corpus-qa",
        "candidate-classification",
        "synthesis-planning",
    ]
    command_class: Literal["read-only", "scratch-write"] = "read-only"
    prompt_path: str
    source_paths: list[str]
    output_schema_path: str | None = None
    result_manifest_path: str = "adapter-result.json"
    allowed_write_paths: list[str] = Field(default_factory=list)
    cost_mode: Literal["auto", "no-metered", "paid-ok"] = "no-metered"
    max_seconds: int = 120
    output_limit: int = 4000
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("prompt_path", "result_manifest_path")
    @classmethod
    def _safe_single_path(cls, value: str) -> str:
        return _normalize_workload_path(value)

    @field_validator("output_schema_path")
    @classmethod
    def _safe_optional_path(cls, value: str | None) -> str | None:
        return _normalize_workload_path(value) if value is not None else None

    @field_validator("source_paths", "allowed_write_paths")
    @classmethod
    def _safe_path_list(cls, values: list[str]) -> list[str]:
        return [_normalize_workload_path(value) for value in values]

    @field_validator("max_seconds", "output_limit")
    @classmethod
    def _positive_limits(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("limits must be positive")
        return value

    @model_validator(mode="after")
    def _enforce_shape(self) -> Self:
        if not self.source_paths:
            raise ValueError("adapter workloads must include at least one source path")
        if self.command_class == "read-only" and self.allowed_write_paths:
            raise ValueError("read-only adapter workloads cannot declare write paths")
        return self

    def to_dict(self) -> dict[str, Any]:
        """Return a stable JSON-serializable representation."""

        return self.model_dump(mode="json")


def adapter_workload_contract() -> dict[str, Any]:
    """Return the workload-package contract for docs and future doctor reports."""

    return {
        "schema_version": ADAPTER_WORKLOAD_SCHEMA_VERSION,
        "workloads": list(ADAPTER_WORKLOADS),
        "path_fields": list(ADAPTER_WORKLOAD_PATH_FIELDS),
        "command_classes": ["read-only", "scratch-write"],
        "cost_modes": ["auto", "no-metered", "paid-ok"],
        "paths_are_scratch_relative": True,
        "read_only_declares_no_write_paths": True,
    }


def validate_adapter_workload_package(payload: Mapping[str, Any]) -> AdapterWorkloadPackage:
    """Parse and validate a candidate adapter workload package."""

    return AdapterWorkloadPackage.model_validate(dict(payload))


def load_adapter_workload_package(path: Path) -> AdapterWorkloadPackage:
    """Load a JSON or YAML adapter workload package from disk."""

    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in {".yaml", ".yml"}:
        payload = yaml.safe_load(text)
    else:
        payload = json.loads(text)
    if not isinstance(payload, Mapping):
        raise AdapterWorkloadError("adapter workload package must be a mapping")
    return validate_adapter_workload_package(payload)


def _normalize_workload_path(value: str) -> str:
    text = value.strip().replace("\\", "/")
    if not text:
        raise ValueError("adapter workload paths must be non-empty")
    if "\x00" in text:
        raise ValueError("adapter workload paths cannot contain NUL")
    if _WORKLOAD_PATH_RE.match(text):
        raise ValueError(f"adapter workload path must be relative: {value!r}")
    if any(part in {"", ".", ".."} for part in text.split("/")):
        raise ValueError(f"adapter workload path must not traverse directories: {value!r}")
    path = PurePosixPath(text)
    if path.is_absolute():
        raise ValueError(f"adapter workload path must be relative: {value!r}")
    return path.as_posix()

"""Strict workload-package boundary for future CLI adapter runs."""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Any, Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from distill.library.confined import read_confined_text
from distill.parsing import strict_json_loads

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
_ADAPTER_WORKLOAD_MAX_BYTES = 1024 * 1024
_ADAPTER_WORKLOAD_MAX_SECONDS = 3600
_ADAPTER_WORKLOAD_MAX_OUTPUT_CHARS = 1_000_000


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

    @field_validator("max_seconds")
    @classmethod
    def _bounded_seconds(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("limits must be positive")
        if value > _ADAPTER_WORKLOAD_MAX_SECONDS:
            raise ValueError(f"max_seconds cannot exceed {_ADAPTER_WORKLOAD_MAX_SECONDS:,}")
        return value

    @field_validator("output_limit")
    @classmethod
    def _bounded_output(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("limits must be positive")
        if value > _ADAPTER_WORKLOAD_MAX_OUTPUT_CHARS:
            raise ValueError(
                f"output_limit cannot exceed {_ADAPTER_WORKLOAD_MAX_OUTPUT_CHARS:,} characters"
            )
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


def load_adapter_workload_package(
    path: Path,
    *,
    scratch_root: Path | None = None,
) -> AdapterWorkloadPackage:
    """Load a JSON or YAML adapter workload package from disk."""

    root = scratch_root.resolve() if scratch_root is not None else path.parent.resolve()
    candidate = (
        path
        if path.is_absolute()
        else root / (path if scratch_root is not None else Path(path.name))
    )
    text = read_confined_text(candidate, root, max_bytes=_ADAPTER_WORKLOAD_MAX_BYTES)
    if text is None:
        raise AdapterWorkloadError(
            "adapter workload must be a confined private regular UTF-8 file "
            f"no larger than {_ADAPTER_WORKLOAD_MAX_BYTES:,} bytes"
        )
    try:
        if candidate.suffix.lower() in {".yaml", ".yml"}:
            payload = yaml.safe_load(text)
        else:
            payload = strict_json_loads(text)
    except (RecursionError, ValueError, yaml.YAMLError) as exc:
        raise AdapterWorkloadError("adapter workload is invalid structured data") from exc
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

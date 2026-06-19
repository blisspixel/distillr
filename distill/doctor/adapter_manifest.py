"""Strict result-manifest boundary for external CLI adapters."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ADAPTER_RESULT_SCHEMA_VERSION = "adapter-result.v1"
ADAPTER_MANIFEST_REQUIRED_FIELDS: tuple[str, ...] = (
    "schema_version",
    "adapter",
    "adapter_version",
    "auth_class",
    "command_class",
    "prompt_hash",
    "source_hash",
    "elapsed_ms",
    "usage",
    "stop_reason",
    "files_read",
    "files_written",
    "output",
    "policy",
)
ADAPTER_MANIFEST_PATH_FIELDS: tuple[str, ...] = ("files_read", "files_written")

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
_NO_METERED_AUTH_CLASSES = frozenset({"local", "included-plan"})
_QUOTA_STOP_REASONS = frozenset({"quota", "rate-limit"})
_ENV_NAME_RE = re.compile(r"^[A-Z_][A-Z0-9_]*$")


class AdapterManifestError(ValueError):
    """Raised when a manifest path cannot be accepted."""


class AdapterUsage(BaseModel):
    """Native usage signal recorded by an external adapter run."""

    model_config = ConfigDict(extra="forbid", strict=True)

    input_tokens: int | None
    output_tokens: int | None
    native: dict[str, Any]

    @field_validator("input_tokens", "output_tokens")
    @classmethod
    def _non_negative_token_count(cls, value: int | None) -> int | None:
        if value is not None and value < 0:
            raise ValueError("token counts must be non-negative")
        return value

    @property
    def has_signal(self) -> bool:
        """True when the adapter recorded at least one usage signal."""

        return self.input_tokens is not None or self.output_tokens is not None or bool(self.native)


class AdapterQuotaStop(BaseModel):
    """Structured quota or rate-limit stop from an external adapter run."""

    model_config = ConfigDict(extra="forbid", strict=True)

    reached: bool
    reason: str = ""
    retry_after_seconds: int | None = None
    provider_code: str = ""
    native: dict[str, Any] = Field(default_factory=dict)

    @field_validator("reason", "provider_code")
    @classmethod
    def _strip_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("retry_after_seconds")
    @classmethod
    def _non_negative_retry_after(cls, value: int | None) -> int | None:
        if value is not None and value < 0:
            raise ValueError("retry_after_seconds must be non-negative")
        return value

    @model_validator(mode="after")
    def _require_reason_when_reached(self) -> Self:
        if self.reached and not self.reason:
            raise ValueError("quota_stop.reason is required when quota was reached")
        return self


class AdapterPolicy(BaseModel):
    """Cost-policy state attached to an adapter result."""

    model_config = ConfigDict(extra="forbid", strict=True)

    cost_mode: Literal["auto", "no-metered", "paid-ok"]
    blocked_api_key_env: list[str]
    metered_allowed: bool

    @field_validator("blocked_api_key_env")
    @classmethod
    def _valid_env_names(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for value in values:
            env_name = value.strip()
            if not _ENV_NAME_RE.fullmatch(env_name):
                raise ValueError(f"invalid environment variable name: {value!r}")
            normalized.append(env_name)
        return sorted(set(normalized))


class AdapterResultManifest(BaseModel):
    """Parsed `adapter-result.v1` manifest from a scratch adapter run."""

    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal["adapter-result.v1"]
    adapter: str
    adapter_version: str
    auth_class: Literal["local", "included-plan", "metered-api", "unknown"]
    command_class: Literal["read-only", "scratch-write"]
    model: str = ""
    prompt_hash: str
    source_hash: str
    elapsed_ms: int
    usage: AdapterUsage
    stop_reason: str
    files_read: list[str]
    files_written: list[str]
    output: dict[str, Any] | str
    policy: AdapterPolicy
    quota_stop: AdapterQuotaStop | None = None
    citations: list[str] = Field(default_factory=list)
    receipts: list[str] = Field(default_factory=list)

    @field_validator("adapter", "adapter_version", "prompt_hash", "source_hash", "stop_reason")
    @classmethod
    def _non_empty_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("value must be non-empty")
        return normalized

    @field_validator("model")
    @classmethod
    def _strip_model(cls, value: str) -> str:
        return value.strip()

    @field_validator("adapter")
    @classmethod
    def _known_adapter(cls, value: str) -> str:
        if value not in _ADAPTER_NAMES:
            raise ValueError(f"unknown adapter: {value}")
        return value

    @field_validator("elapsed_ms")
    @classmethod
    def _non_negative_elapsed(cls, value: int) -> int:
        if value < 0:
            raise ValueError("elapsed_ms must be non-negative")
        return value

    @field_validator("files_read", "files_written")
    @classmethod
    def _safe_manifest_paths(cls, values: list[str]) -> list[str]:
        return [_normalize_manifest_path(value) for value in values]

    @field_validator("citations", "receipts")
    @classmethod
    def _non_empty_list_values(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for value in values:
            text = value.strip()
            if not text:
                raise ValueError("list values must be non-empty")
            normalized.append(text)
        return normalized

    @model_validator(mode="after")
    def _enforce_policy(self) -> Self:
        if not self.usage.has_signal:
            raise ValueError("usage must include token counts or native usage metadata")
        if self.command_class == "scratch-write" and not self.files_written:
            raise ValueError("scratch-write manifests must record files_written")
        quota_stop_reason = _is_quota_stop_reason(self.stop_reason)
        if quota_stop_reason and (self.quota_stop is None or not self.quota_stop.reached):
            raise ValueError("quota or rate-limit stop_reason requires quota_stop.reached")
        if self.quota_stop is not None and self.quota_stop.reached and not quota_stop_reason:
            raise ValueError("quota_stop.reached requires quota or rate-limit stop_reason")
        if self.policy.cost_mode == "no-metered":
            if self.auth_class not in _NO_METERED_AUTH_CLASSES:
                raise ValueError("no-metered adapter results require local or included-plan auth")
            if self.policy.metered_allowed:
                raise ValueError("no-metered adapter results cannot allow metered usage")
            if self.policy.blocked_api_key_env:
                raise ValueError("no-metered adapter results cannot carry API-key blockers")
        return self

    def resolve_written_paths(self, scratch_root: Path) -> tuple[Path, ...]:
        """Resolve declared written paths and ensure they stay under scratch_root."""

        root = scratch_root.resolve()
        resolved: list[Path] = []
        for rel_path in self.files_written:
            candidate = (root / rel_path).resolve()
            try:
                candidate.relative_to(root)
            except ValueError as exc:
                raise AdapterManifestError(
                    f"manifest write path escapes scratch workspace: {rel_path}"
                ) from exc
            resolved.append(candidate)
        return tuple(resolved)

    def to_dict(self) -> dict[str, Any]:
        """Return a stable JSON-serializable representation."""

        return self.model_dump(mode="json")


@dataclass(frozen=True)
class AdapterWorkspaceWriteCheck:
    """Before/after scratch workspace write check for an adapter run."""

    declared_files: tuple[str, ...]
    new_files: tuple[str, ...]
    missing_files: tuple[str, ...]
    unexpected_files: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.missing_files and not self.unexpected_files

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "declared_files": list(self.declared_files),
            "new_files": list(self.new_files),
            "missing_files": list(self.missing_files),
            "unexpected_files": list(self.unexpected_files),
        }


def adapter_result_manifest_contract() -> dict[str, Any]:
    """Return the current manifest contract for doctor reports and docs."""

    return {
        "schema_version": ADAPTER_RESULT_SCHEMA_VERSION,
        "required_fields": list(ADAPTER_MANIFEST_REQUIRED_FIELDS),
        "optional_fields": ["model", "citations", "receipts", "quota_stop"],
        "path_fields": list(ADAPTER_MANIFEST_PATH_FIELDS),
        "auth_classes": ["local", "included-plan", "metered-api", "unknown"],
        "command_classes": ["read-only", "scratch-write"],
        "no_metered_auth_classes": sorted(_NO_METERED_AUTH_CLASSES),
        "quota_stop": {
            "required_when_stop_reason": ["quota", "rate_limit", "rate-limit"],
            "fields": [
                "reached",
                "reason",
                "retry_after_seconds",
                "provider_code",
                "native",
            ],
        },
        "workspace_write_check": {
            "uses_before_snapshot": True,
            "flags_missing_declared_files": True,
            "flags_unexpected_new_files": True,
        },
    }


def validate_adapter_result_manifest(
    payload: Mapping[str, Any],
    *,
    scratch_root: Path | None = None,
) -> AdapterResultManifest:
    """Parse and validate a candidate adapter result manifest."""

    manifest = AdapterResultManifest.model_validate(dict(payload))
    if scratch_root is not None:
        manifest.resolve_written_paths(scratch_root)
    return manifest


def load_adapter_result_manifest(
    path: Path,
    *,
    scratch_root: Path | None = None,
) -> AdapterResultManifest:
    """Load a JSON or YAML adapter result manifest from disk."""

    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in {".yaml", ".yml"}:
        payload = yaml.safe_load(text)
    else:
        payload = json.loads(text)
    if not isinstance(payload, Mapping):
        raise AdapterManifestError("adapter manifest must be a mapping")
    return validate_adapter_result_manifest(payload, scratch_root=scratch_root)


def snapshot_scratch_files(scratch_root: Path) -> frozenset[str]:
    """Return safe, relative file paths currently present under scratch_root."""

    root = scratch_root.resolve()
    if not root.exists():
        return frozenset()
    files: set[str] = set()
    for path in root.rglob("*"):
        if path.is_file():
            files.add(_relative_scratch_path(root, path))
    return frozenset(files)


def check_adapter_workspace_writes(
    manifest: AdapterResultManifest,
    scratch_root: Path,
    *,
    before_files: set[str] | frozenset[str] | tuple[str, ...] = (),
    allowed_new_files: tuple[str, ...] = (),
) -> AdapterWorkspaceWriteCheck:
    """Compare a manifest with before/after scratch file snapshots."""

    manifest.resolve_written_paths(scratch_root)
    before = {_normalize_manifest_path(path) for path in before_files}
    allowed = {_normalize_manifest_path(path) for path in allowed_new_files}
    after = set(snapshot_scratch_files(scratch_root))
    declared = set(manifest.files_written)
    new_files = after - before
    return AdapterWorkspaceWriteCheck(
        declared_files=tuple(sorted(declared)),
        new_files=tuple(sorted(new_files)),
        missing_files=tuple(sorted(path for path in declared if path not in after)),
        unexpected_files=tuple(sorted(new_files - declared - allowed)),
    )


def _normalize_manifest_path(value: str) -> str:
    text = value.strip().replace("\\", "/")
    if not text:
        raise ValueError("manifest paths must be non-empty")
    if "\x00" in text:
        raise ValueError("manifest paths cannot contain NUL")
    if re.match(r"^[A-Za-z]:", text):
        raise ValueError(f"manifest path must be relative: {value!r}")
    path = PurePosixPath(text)
    if path.is_absolute():
        raise ValueError(f"manifest path must be relative: {value!r}")
    if any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"manifest path must not traverse directories: {value!r}")
    return path.as_posix()


def _is_quota_stop_reason(value: str) -> bool:
    return value.strip().lower().replace("_", "-") in _QUOTA_STOP_REASONS


def _relative_scratch_path(root: Path, path: Path) -> str:
    try:
        path.resolve().relative_to(root)
    except ValueError as exc:
        raise AdapterManifestError(f"scratch file escapes workspace: {path}") from exc
    return path.relative_to(root).as_posix()

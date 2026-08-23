"""Native writer for strict adapter-result manifests from captured CLI output."""

from __future__ import annotations

import hashlib
import json
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from distill.doctor.adapter_manifest import (
    ADAPTER_RESULT_SCHEMA_VERSION,
    AdapterQuotaStop,
    AdapterResultManifest,
    AdapterUsage,
    validate_adapter_result_manifest,
)
from distill.doctor.adapter_native_usage import load_adapter_native_usage
from distill.doctor.adapter_workload import AdapterWorkloadPackage
from distill.library.confined import read_confined_bytes, read_confined_text
from distill.library.paths import atomic_replace_text

__all__ = [
    "AdapterResultWriteSpec",
    "write_adapter_result_manifest",
]

_ADAPTER_RESULT_FILE_MAX_BYTES = 4 * 1024 * 1024
_ADAPTER_INPUT_FILE_MAX_BYTES = 64 * 1024 * 1024
_ADAPTER_INPUT_TOTAL_MAX_BYTES = 256 * 1024 * 1024
_ADAPTER_MANIFEST_MAX_BYTES = 1024 * 1024


@dataclass(frozen=True)
class AdapterResultWriteSpec:
    """Inputs needed to write an `adapter-result.v1` manifest after a CLI run."""

    adapter: str
    adapter_version: str
    auth_class: Literal["local", "included-plan", "metered-api", "unknown"]
    scratch_root: Path
    workload: AdapterWorkloadPackage
    result_text_path: Path = Path("result.txt")
    native_usage_path: Path | None = None
    model: str = ""
    elapsed_ms: int = 0
    usage: AdapterUsage | None = None
    stop_reason: str = "complete"
    quota_stop: AdapterQuotaStop | None = None
    blocked_api_key_env: tuple[str, ...] = ()
    blocked_metered_routes: tuple[str, ...] = ()
    metered_allowed: bool = False
    files_read: tuple[str, ...] = ()
    files_written: tuple[str, ...] = ()
    output: dict[str, Any] | str | None = None
    citations: tuple[str, ...] = ()
    receipts: tuple[str, ...] = ()
    native: dict[str, Any] = field(default_factory=dict)


def write_adapter_result_manifest(spec: AdapterResultWriteSpec) -> AdapterResultManifest:
    """Write and return a validated adapter result manifest for captured output."""

    root = spec.scratch_root.resolve()
    result_path = _resolve_scratch_path(root, spec.result_text_path)
    output = spec.output if spec.output is not None else _read_result_text(root, result_path, spec)
    _validate_output_limit(output, spec.workload.output_limit)
    usage = _usage_from_spec(spec, root)
    payload = {
        "schema_version": ADAPTER_RESULT_SCHEMA_VERSION,
        "adapter": spec.adapter,
        "adapter_version": spec.adapter_version,
        "auth_class": spec.auth_class,
        "command_class": spec.workload.command_class,
        "model": spec.model,
        "prompt_hash": _hash_file(root, spec.workload.prompt_path),
        "source_hash": _hash_sources(root, spec.workload.source_paths),
        "elapsed_ms": spec.elapsed_ms,
        "usage": usage.model_dump(mode="json"),
        "stop_reason": spec.stop_reason,
        "files_read": _files_read(spec),
        "files_written": list(spec.files_written),
        "output": output,
        "policy": {
            "cost_mode": spec.workload.cost_mode,
            "blocked_api_key_env": list(spec.blocked_api_key_env),
            "blocked_metered_routes": list(spec.blocked_metered_routes),
            "metered_allowed": spec.metered_allowed,
        },
        "citations": list(spec.citations),
        "receipts": list(spec.receipts),
    }
    if spec.quota_stop is not None:
        payload["quota_stop"] = spec.quota_stop.model_dump(mode="json")

    manifest = validate_adapter_result_manifest(payload, scratch_root=root)
    manifest_path = _resolve_scratch_path(root, Path(spec.workload.result_manifest_path))
    _write_bounded_json(
        manifest_path,
        manifest.to_dict(),
        max_bytes=_ADAPTER_MANIFEST_MAX_BYTES,
        label="adapter manifest",
    )
    return manifest


def _files_read(spec: AdapterResultWriteSpec) -> list[str]:
    files = [
        spec.workload.prompt_path,
        *spec.workload.source_paths,
    ]
    if spec.workload.output_schema_path:
        files.append(spec.workload.output_schema_path)
    files.extend(spec.files_read)
    return sorted(set(files))


def _usage_from_spec(spec: AdapterResultWriteSpec, root: Path) -> AdapterUsage:
    if spec.usage is not None:
        return spec.usage
    if spec.native_usage_path is not None:
        record = load_adapter_native_usage(
            spec.native_usage_path,
            scratch_root=root,
        )
        if record.adapter != spec.adapter:
            raise ValueError(
                "adapter native usage adapter mismatch: "
                f"expected {spec.adapter}, got {record.adapter}"
            )
        return record.to_adapter_usage()
    return AdapterUsage(
        input_tokens=None,
        output_tokens=None,
        native=dict(spec.native),
    )


def _hash_file(root: Path, rel_path: str) -> str:
    path = _resolve_scratch_path(root, Path(rel_path))
    content = read_confined_bytes(path, root, max_bytes=_ADAPTER_INPUT_FILE_MAX_BYTES)
    if content is None:
        raise ValueError(
            "adapter input must be a confined private regular file "
            f"no larger than {_ADAPTER_INPUT_FILE_MAX_BYTES:,} bytes: {rel_path}"
        )
    digest = hashlib.sha256()
    digest.update(content)
    return f"sha256:{digest.hexdigest()}"


def _hash_sources(root: Path, rel_paths: list[str]) -> str:
    digest = hashlib.sha256()
    total_bytes = 0
    for rel_path in sorted(rel_paths):
        path = _resolve_scratch_path(root, Path(rel_path))
        content = read_confined_bytes(path, root, max_bytes=_ADAPTER_INPUT_FILE_MAX_BYTES)
        if content is None:
            raise ValueError(
                "adapter source must be a confined private regular file "
                f"no larger than {_ADAPTER_INPUT_FILE_MAX_BYTES:,} bytes: {rel_path}"
            )
        total_bytes += len(content)
        if total_bytes > _ADAPTER_INPUT_TOTAL_MAX_BYTES:
            raise ValueError(
                "adapter sources exceed the "
                f"{_ADAPTER_INPUT_TOTAL_MAX_BYTES:,}-byte aggregate limit"
            )
        digest.update(rel_path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(content)
        digest.update(b"\0")
    return f"sha256:{digest.hexdigest()}"


def _resolve_scratch_path(root: Path, path: Path) -> Path:
    if (
        path.is_absolute()
        or path.drive
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError(f"adapter result path escapes scratch workspace: {path}")
    candidate = root.joinpath(*path.parts)
    current = root
    for index, part in enumerate(path.parts):
        current /= part
        try:
            file_stat = current.lstat()
        except FileNotFoundError:
            break
        except OSError as exc:
            raise ValueError(f"adapter result path cannot be inspected safely: {path}") from exc
        if _is_link_like(current, file_stat):
            raise ValueError(f"adapter result path contains a linked component: {path}")
        if index < len(path.parts) - 1 and not stat.S_ISDIR(file_stat.st_mode):
            raise ValueError(f"adapter result path contains a non-directory component: {path}")
    return candidate


def _read_result_text(root: Path, path: Path, spec: AdapterResultWriteSpec) -> str:
    byte_limit = min(_ADAPTER_RESULT_FILE_MAX_BYTES, spec.workload.output_limit * 4)
    output = read_confined_text(path, root, max_bytes=byte_limit)
    if output is None:
        raise ValueError(
            "adapter result must be a confined private regular UTF-8 file "
            f"within the {spec.workload.output_limit:,}-character output limit"
        )
    return output


def _validate_output_limit(output: dict[str, Any] | str, limit: int) -> None:
    serialized = (
        output
        if isinstance(output, str)
        else json.dumps(
            output,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        )
    )
    if len(serialized) > limit:
        raise ValueError(f"adapter result exceeds the {limit:,}-character output limit")


def _write_bounded_json(path: Path, value: object, *, max_bytes: int, label: str) -> None:
    content = (
        json.dumps(
            value,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    )
    if len(content.encode("utf-8")) > max_bytes:
        raise ValueError(f"{label} exceeds the {max_bytes:,}-byte limit")
    atomic_replace_text(path, content)


def _is_link_like(path: Path, file_stat: object) -> bool:
    mode = getattr(file_stat, "st_mode", 0)
    attributes = getattr(file_stat, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    is_junction = getattr(path, "is_junction", None)
    return bool(
        stat.S_ISLNK(mode)
        or (reparse_flag and attributes & reparse_flag)
        or (callable(is_junction) and is_junction())
    )

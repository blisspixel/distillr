"""Native writer for strict adapter-result manifests from captured CLI output."""

from __future__ import annotations

import hashlib
import json
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

__all__ = [
    "AdapterResultWriteSpec",
    "write_adapter_result_manifest",
]


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
    output = spec.output if spec.output is not None else result_path.read_text(encoding="utf-8")
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
    manifest_path.write_text(
        json.dumps(manifest.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
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
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return f"sha256:{digest.hexdigest()}"


def _hash_sources(root: Path, rel_paths: list[str]) -> str:
    digest = hashlib.sha256()
    for rel_path in sorted(rel_paths):
        path = _resolve_scratch_path(root, Path(rel_path))
        digest.update(rel_path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return f"sha256:{digest.hexdigest()}"


def _resolve_scratch_path(root: Path, path: Path) -> Path:
    candidate = (root / path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"adapter result path escapes scratch workspace: {path}") from exc
    return candidate

"""Adapter-specific capture helpers for future CLI adapter runs."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from distill.doctor.adapter_manifest import AdapterQuotaStop, AdapterResultManifest
from distill.doctor.adapter_native_usage import codex_jsonl_native_usage
from distill.doctor.adapter_result_writer import (
    AdapterResultWriteSpec,
    write_adapter_result_manifest,
)
from distill.doctor.adapter_workload import AdapterWorkloadPackage

__all__ = [
    "CodexCaptureWriteSpec",
    "write_codex_captured_result",
]


@dataclass(frozen=True)
class CodexCaptureWriteSpec:
    """Captured Codex outputs needed to write adapter manifests."""

    adapter_version: str
    auth_class: Literal["local", "included-plan", "metered-api", "unknown"]
    scratch_root: Path
    workload: AdapterWorkloadPackage
    stdout_jsonl: str
    result_text_path: Path = Path("result.txt")
    native_usage_path: Path = Path("native-usage.json")
    model: str = ""
    elapsed_ms: int = 0
    stop_reason: str = "complete"
    quota_stop: AdapterQuotaStop | None = None
    blocked_api_key_env: tuple[str, ...] = ()
    metered_allowed: bool = False
    citations: tuple[str, ...] = ()
    receipts: tuple[str, ...] = ()


def write_codex_captured_result(spec: CodexCaptureWriteSpec) -> AdapterResultManifest:
    """Write native usage and result manifests from captured Codex output."""

    root = spec.scratch_root.resolve()
    usage_record = codex_jsonl_native_usage(
        spec.stdout_jsonl,
        model=spec.model,
        stop_reason=spec.stop_reason,
    )
    native_usage_path = _write_native_usage_file(root, spec.native_usage_path, usage_record)
    return write_adapter_result_manifest(
        AdapterResultWriteSpec(
            adapter="codex",
            adapter_version=spec.adapter_version,
            auth_class=spec.auth_class,
            scratch_root=root,
            workload=spec.workload,
            result_text_path=spec.result_text_path,
            native_usage_path=native_usage_path,
            model=spec.model,
            elapsed_ms=spec.elapsed_ms,
            stop_reason=spec.stop_reason,
            quota_stop=spec.quota_stop,
            blocked_api_key_env=spec.blocked_api_key_env,
            metered_allowed=spec.metered_allowed,
            citations=spec.citations,
            receipts=spec.receipts,
        )
    )


def _write_native_usage_file(root: Path, path: Path, usage_record) -> Path:
    usage_path = _resolve_scratch_path(root, path)
    usage_path.parent.mkdir(parents=True, exist_ok=True)
    usage_path.write_text(
        json.dumps(usage_record.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return usage_path.relative_to(root)


def _resolve_scratch_path(root: Path, path: Path) -> Path:
    if path.is_absolute():
        raise ValueError(f"adapter capture path must be scratch relative: {path}")
    candidate = (root / path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"adapter capture path escapes scratch workspace: {path}") from exc
    return candidate

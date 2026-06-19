"""Adapter-specific capture helpers for future CLI adapter runs."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from distill.doctor.adapter_manifest import AdapterQuotaStop, AdapterResultManifest
from distill.doctor.adapter_native_usage import (
    claude_json_native_usage,
    codex_jsonl_native_usage,
)
from distill.doctor.adapter_result_writer import (
    AdapterResultWriteSpec,
    write_adapter_result_manifest,
)
from distill.doctor.adapter_workload import AdapterWorkloadPackage

__all__ = [
    "ClaudeCaptureWriteSpec",
    "CodexCaptureWriteSpec",
    "StdoutCaptureWriteSpec",
    "write_claude_captured_result",
    "write_codex_captured_result",
    "write_stdout_captured_result",
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


@dataclass(frozen=True)
class ClaudeCaptureWriteSpec:
    """Captured Claude JSON output needed to write adapter manifests."""

    adapter_version: str
    auth_class: Literal["local", "included-plan", "metered-api", "unknown"]
    scratch_root: Path
    workload: AdapterWorkloadPackage
    stdout_json: str
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


@dataclass(frozen=True)
class StdoutCaptureWriteSpec:
    """Captured stdout and native usage needed to write adapter manifests."""

    adapter: str
    adapter_version: str
    auth_class: Literal["local", "included-plan", "metered-api", "unknown"]
    scratch_root: Path
    workload: AdapterWorkloadPackage
    stdout_text: str
    native_usage_path: Path = Path("native-usage.json")
    result_text_path: Path = Path("result.txt")
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


def write_claude_captured_result(spec: ClaudeCaptureWriteSpec) -> AdapterResultManifest:
    """Write native usage and result manifests from captured Claude JSON output."""

    root = spec.scratch_root.resolve()
    output = _claude_result_output(spec.stdout_json)
    result_text_path = _write_result_text_file(
        root,
        spec.result_text_path,
        _result_output_text(output),
    )
    usage_record = claude_json_native_usage(
        spec.stdout_json,
        model=spec.model,
        stop_reason=spec.stop_reason,
    )
    native_usage_path = _write_native_usage_file(root, spec.native_usage_path, usage_record)
    return write_adapter_result_manifest(
        AdapterResultWriteSpec(
            adapter="claude",
            adapter_version=spec.adapter_version,
            auth_class=spec.auth_class,
            scratch_root=root,
            workload=spec.workload,
            result_text_path=result_text_path,
            native_usage_path=native_usage_path,
            model=spec.model or usage_record.model,
            elapsed_ms=spec.elapsed_ms,
            stop_reason=usage_record.stop_reason or spec.stop_reason,
            quota_stop=spec.quota_stop,
            blocked_api_key_env=spec.blocked_api_key_env,
            metered_allowed=spec.metered_allowed,
            output=output,
            citations=spec.citations,
            receipts=spec.receipts,
        )
    )


def write_stdout_captured_result(spec: StdoutCaptureWriteSpec) -> AdapterResultManifest:
    """Write result text and manifest from captured stdout plus native usage."""

    root = spec.scratch_root.resolve()
    result_text_path = _write_result_text_file(root, spec.result_text_path, spec.stdout_text)
    return write_adapter_result_manifest(
        AdapterResultWriteSpec(
            adapter=spec.adapter,
            adapter_version=spec.adapter_version,
            auth_class=spec.auth_class,
            scratch_root=root,
            workload=spec.workload,
            result_text_path=result_text_path,
            native_usage_path=spec.native_usage_path,
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


def _write_result_text_file(root: Path, path: Path, text: str) -> Path:
    result_path = _resolve_scratch_path(root, path)
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(text, encoding="utf-8")
    return result_path.relative_to(root)


def _claude_result_output(stdout_json: str) -> dict[str, Any] | str:
    try:
        payload = json.loads(stdout_json)
    except json.JSONDecodeError as exc:
        raise ValueError("claude JSON output is invalid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("claude JSON output must be an object")
    if "structured_output" in payload and payload["structured_output"] is not None:
        return _manifest_output_value(payload["structured_output"])
    if "result" in payload and payload["result"] is not None:
        return _manifest_output_value(payload["result"])
    raise ValueError("claude JSON result output not found")


def _manifest_output_value(value: Any) -> dict[str, Any] | str:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        return value
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def _result_output_text(output: dict[str, Any] | str) -> str:
    if isinstance(output, dict):
        return json.dumps(output, indent=2, sort_keys=True) + "\n"
    return output


def _resolve_scratch_path(root: Path, path: Path) -> Path:
    if path.is_absolute():
        raise ValueError(f"adapter capture path must be scratch relative: {path}")
    candidate = (root / path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"adapter capture path escapes scratch workspace: {path}") from exc
    return candidate

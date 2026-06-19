"""Run a checked adapter workload package through the scratch adapter runner."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from distill.doctor.adapter_manifest import AdapterManifestError
from distill.doctor.adapter_runner import (
    METERED_API_ENV_VARS,
    AdapterProcessResult,
    AdapterRunResult,
    AdapterRunSpec,
    CaptureWriter,
    Runner,
    run_adapter_command,
)
from distill.doctor.adapter_workload import (
    AdapterWorkloadError,
    AdapterWorkloadPackage,
    load_adapter_workload_package,
)

__all__ = [
    "AdapterWorkloadRunResult",
    "AdapterWorkloadRunSpec",
    "WorkloadCaptureWriter",
    "run_adapter_workload",
]

WorkloadCaptureWriter = Callable[[AdapterProcessResult, Path, AdapterWorkloadPackage], None]


@dataclass(frozen=True)
class AdapterWorkloadRunSpec:
    """Exact adapter command plus the workload package it must satisfy."""

    adapter: str
    argv: tuple[str, ...]
    scratch_root: Path
    workload_path: Path = Path("adapter-workload.json")
    scrubbed_env_vars: tuple[str, ...] = METERED_API_ENV_VARS
    allowed_new_files: tuple[str, ...] = ()
    capture_writer: WorkloadCaptureWriter | None = None


@dataclass(frozen=True)
class AdapterWorkloadRunResult:
    """Verified result from one adapter workload attempt."""

    adapter: str
    workload: AdapterWorkloadPackage | None
    adapter_result: AdapterRunResult | None
    blocked_reasons: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return (
            self.workload is not None
            and self.adapter_result is not None
            and self.adapter_result.ok
            and not self.blocked_reasons
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "adapter": self.adapter,
            "ok": self.ok,
            "workload": self.workload.to_dict() if self.workload else None,
            "adapter_result": self.adapter_result.to_dict() if self.adapter_result else None,
            "blocked_reasons": self.blocked_reasons,
        }


def run_adapter_workload(
    spec: AdapterWorkloadRunSpec,
    *,
    environ: Mapping[str, str],
    runner: Runner | None = None,
) -> AdapterWorkloadRunResult:
    """Run one adapter workload package and verify it stayed inside bounds."""

    scratch_root = spec.scratch_root.resolve()
    blocked_reasons: list[str] = []
    workload_path = _resolve_under_scratch(scratch_root, spec.workload_path)
    if workload_path is None:
        return AdapterWorkloadRunResult(
            adapter=spec.adapter,
            workload=None,
            adapter_result=None,
            blocked_reasons=[f"adapter workload escapes scratch workspace: {spec.workload_path}"],
        )

    workload: AdapterWorkloadPackage | None = None
    try:
        workload = load_adapter_workload_package(workload_path)
    except (
        AdapterWorkloadError,
        AdapterManifestError,
        OSError,
        ValidationError,
        ValueError,
    ) as exc:
        return AdapterWorkloadRunResult(
            adapter=spec.adapter,
            workload=None,
            adapter_result=None,
            blocked_reasons=[str(exc)],
        )

    adapter_result = run_adapter_command(
        AdapterRunSpec(
            adapter=spec.adapter,
            argv=spec.argv,
            scratch_root=scratch_root,
            manifest_path=Path(workload.result_manifest_path),
            command_class=workload.command_class,
            timeout_seconds=workload.max_seconds,
            output_limit=workload.output_limit,
            scrubbed_env_vars=spec.scrubbed_env_vars,
            allowed_new_files=spec.allowed_new_files,
            capture_writer=_bind_capture_writer(spec.capture_writer, workload),
        ),
        environ=environ,
        runner=runner,
    )
    workload_rel = workload_path.relative_to(scratch_root).as_posix()
    _check_workload_result(workload, adapter_result, workload_rel, blocked_reasons)
    return AdapterWorkloadRunResult(
        adapter=spec.adapter,
        workload=workload,
        adapter_result=adapter_result,
        blocked_reasons=blocked_reasons,
    )


def _check_workload_result(
    workload: AdapterWorkloadPackage,
    adapter_result: AdapterRunResult,
    workload_path: str,
    blocked_reasons: list[str],
) -> None:
    manifest = adapter_result.manifest
    if manifest is None:
        return
    if manifest.policy.cost_mode != workload.cost_mode:
        blocked_reasons.append(
            "adapter manifest cost mode mismatch: "
            f"expected {workload.cost_mode}, got {manifest.policy.cost_mode}"
        )
    allowed_reads = {
        workload.prompt_path,
        workload_path,
        workload.result_manifest_path,
        *workload.source_paths,
    }
    if workload.output_schema_path:
        allowed_reads.add(workload.output_schema_path)
    unexpected_reads = sorted(path for path in manifest.files_read if path not in allowed_reads)
    if unexpected_reads:
        blocked_reasons.append(
            "adapter manifest read files outside workload package: " + ", ".join(unexpected_reads)
        )

    allowed_writes = set(workload.allowed_write_paths)
    unexpected_writes = sorted(
        path for path in manifest.files_written if path not in allowed_writes
    )
    if unexpected_writes:
        blocked_reasons.append(
            "adapter manifest wrote files outside workload package: " + ", ".join(unexpected_writes)
        )


def _bind_capture_writer(
    writer: WorkloadCaptureWriter | None,
    workload: AdapterWorkloadPackage,
) -> CaptureWriter | None:
    if writer is None:
        return None

    def capture(process: AdapterProcessResult, scratch_root: Path) -> None:
        writer(process, scratch_root, workload)

    return capture


def _resolve_under_scratch(root: Path, path: Path) -> Path | None:
    candidate = (root / path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate

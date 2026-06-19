"""Scratch-only command runner for future CLI adapter integrations."""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from distill.doctor.adapter_manifest import (
    AdapterManifestError,
    AdapterResultManifest,
    AdapterWorkspaceWriteCheck,
    check_adapter_workspace_writes,
    load_adapter_result_manifest,
    snapshot_scratch_files,
)

METERED_API_ENV_VARS: tuple[str, ...] = (
    "OPENAI_API_KEY",
    "CODEX_API_KEY",
    "ANTHROPIC_API_KEY",
    "XAI_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
)

Runner = Callable[
    [Sequence[str], Path, Mapping[str, str], int],
    "AdapterProcessResult",
]


@dataclass(frozen=True)
class AdapterRunSpec:
    """Exact command and scratch contract for one adapter attempt."""

    adapter: str
    argv: tuple[str, ...]
    scratch_root: Path
    manifest_path: Path = Path("adapter-result.json")
    command_class: Literal["read-only", "scratch-write"] = "read-only"
    timeout_seconds: int = 120
    output_limit: int = 4000
    scrubbed_env_vars: tuple[str, ...] = METERED_API_ENV_VARS
    allowed_new_files: tuple[str, ...] = ()


@dataclass(frozen=True)
class AdapterProcessResult:
    """Subprocess outcome for an adapter command."""

    exit_code: int
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False


@dataclass(frozen=True)
class AdapterRunResult:
    """Parsed and verified result from a scratch adapter attempt."""

    adapter: str
    exit_code: int
    timed_out: bool
    manifest_path: str
    scrubbed_env_vars: tuple[str, ...]
    stdout_tail: str = ""
    stderr_tail: str = ""
    manifest: AdapterResultManifest | None = None
    workspace_check: AdapterWorkspaceWriteCheck | None = None
    blocked_reasons: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return (
            self.exit_code == 0
            and not self.timed_out
            and self.manifest is not None
            and self.workspace_check is not None
            and self.workspace_check.ok
            and not self.blocked_reasons
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "adapter": self.adapter,
            "ok": self.ok,
            "exit_code": self.exit_code,
            "timed_out": self.timed_out,
            "manifest_path": self.manifest_path,
            "scrubbed_env_vars": list(self.scrubbed_env_vars),
            "stdout_tail": self.stdout_tail,
            "stderr_tail": self.stderr_tail,
            "manifest": self.manifest.to_dict() if self.manifest else None,
            "workspace_check": self.workspace_check.to_dict() if self.workspace_check else None,
            "blocked_reasons": self.blocked_reasons,
        }


def run_adapter_command(
    spec: AdapterRunSpec,
    *,
    environ: Mapping[str, str],
    runner: Runner | None = None,
) -> AdapterRunResult:
    """Run one adapter command in scratch and verify its result manifest."""

    blocked_reasons: list[str] = []
    if not spec.argv:
        blocked_reasons.append("adapter argv is empty")
        return _blocked_result(spec, blocked_reasons)
    scratch_root = spec.scratch_root.resolve()
    scratch_root.mkdir(parents=True, exist_ok=True)
    manifest_path = _resolve_manifest_path(scratch_root, spec.manifest_path)
    before = snapshot_scratch_files(scratch_root)
    env, scrubbed = _scrub_environment(environ, spec.scrubbed_env_vars)
    run = runner or _run_subprocess
    process = run(spec.argv, scratch_root, env, spec.timeout_seconds)
    if process.timed_out:
        blocked_reasons.append("adapter command timed out")
    if process.exit_code != 0:
        blocked_reasons.append(f"adapter command exited {process.exit_code}")

    manifest: AdapterResultManifest | None = None
    workspace_check: AdapterWorkspaceWriteCheck | None = None
    if not manifest_path.exists():
        blocked_reasons.append(f"adapter manifest missing: {manifest_path.name}")
    else:
        try:
            manifest = load_adapter_result_manifest(manifest_path, scratch_root=scratch_root)
            _check_manifest_identity(spec, manifest, blocked_reasons)
            workspace_check = check_adapter_workspace_writes(
                manifest,
                scratch_root,
                before_files=before,
                allowed_new_files=(*spec.allowed_new_files, manifest_path.name),
            )
            if workspace_check.missing_files:
                blocked_reasons.append("adapter manifest declared missing files")
            if workspace_check.unexpected_files:
                blocked_reasons.append("adapter wrote unexpected scratch files")
        except (AdapterManifestError, ValueError) as exc:
            blocked_reasons.append(str(exc))

    return AdapterRunResult(
        adapter=spec.adapter,
        exit_code=process.exit_code,
        timed_out=process.timed_out,
        manifest_path=manifest_path.name,
        scrubbed_env_vars=scrubbed,
        stdout_tail=_tail(process.stdout, spec.output_limit),
        stderr_tail=_tail(process.stderr, spec.output_limit),
        manifest=manifest,
        workspace_check=workspace_check,
        blocked_reasons=blocked_reasons,
    )


def _run_subprocess(
    argv: Sequence[str],
    cwd: Path,
    env: Mapping[str, str],
    timeout_seconds: int,
) -> AdapterProcessResult:
    try:
        result = subprocess.run(
            list(argv),
            cwd=cwd,
            env=dict(env),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return AdapterProcessResult(
            exit_code=124,
            stdout=exc.stdout or "",
            stderr=exc.stderr or str(exc),
            timed_out=True,
        )
    except OSError as exc:
        return AdapterProcessResult(exit_code=127, stderr=str(exc))
    return AdapterProcessResult(
        exit_code=result.returncode,
        stdout=result.stdout,
        stderr=result.stderr,
    )


def _blocked_result(spec: AdapterRunSpec, blocked_reasons: list[str]) -> AdapterRunResult:
    return AdapterRunResult(
        adapter=spec.adapter,
        exit_code=2,
        timed_out=False,
        manifest_path=spec.manifest_path.as_posix(),
        scrubbed_env_vars=(),
        blocked_reasons=blocked_reasons,
    )


def _scrub_environment(
    environ: Mapping[str, str],
    names: Sequence[str],
) -> tuple[dict[str, str], tuple[str, ...]]:
    scrub = set(names)
    env = {key: value for key, value in environ.items() if key not in scrub}
    removed = tuple(sorted(key for key in environ if key in scrub))
    return env, removed


def _resolve_manifest_path(scratch_root: Path, manifest_path: Path) -> Path:
    candidate = (scratch_root / manifest_path).resolve()
    try:
        candidate.relative_to(scratch_root)
    except ValueError as exc:
        raise AdapterManifestError(
            f"adapter manifest escapes scratch workspace: {manifest_path}"
        ) from exc
    return candidate


def _check_manifest_identity(
    spec: AdapterRunSpec,
    manifest: AdapterResultManifest,
    blocked_reasons: list[str],
) -> None:
    if manifest.adapter != spec.adapter:
        blocked_reasons.append(
            f"adapter manifest name mismatch: expected {spec.adapter}, got {manifest.adapter}"
        )
    if manifest.command_class != spec.command_class:
        blocked_reasons.append(
            "adapter manifest command class mismatch: "
            f"expected {spec.command_class}, got {manifest.command_class}"
        )


def _tail(text: str, limit: int) -> str:
    if limit <= 0:
        return ""
    return text if len(text) <= limit else text[-limit:]

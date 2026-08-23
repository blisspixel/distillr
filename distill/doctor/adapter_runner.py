"""Scratch-only command runner for future CLI adapter integrations."""

from __future__ import annotations

import contextlib
import os
import subprocess
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Any, Literal

from pydantic import ValidationError

from distill.doctor.adapter_manifest import (
    AdapterManifestError,
    AdapterResultManifest,
    AdapterWorkspaceWriteCheck,
    ScratchFileRevision,
    check_adapter_workspace_writes,
    load_adapter_result_manifest,
    snapshot_scratch_state,
)
from distill.process_resources import (
    ProcessBudgetExceeded,
    assign_windows_memory_job,
    close_windows_job,
    start_bounded_pipe_head_drain,
    terminate_isolated_process_tree,
    wait_for_process_budget,
)
from distill.process_security import resolve_executable, sanitized_package_env

METERED_API_ENV_VARS: tuple[str, ...] = (
    "OPENAI_API_KEY",
    "CODEX_API_KEY",
    "ANTHROPIC_API_KEY",
    "XAI_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
)

_ADAPTER_RUN_OUTPUT_BYTES = 4 * 1024 * 1024
_ADAPTER_RUN_STDIN_BYTES = 16 * 1024 * 1024
_ADAPTER_RUN_TREE_MEMORY_BYTES = 2 * 1024 * 1024 * 1024
_ADAPTER_RESOURCE_EXIT_CODE = 125
_ADAPTER_RUN_MAX_SECONDS = 3600
_ADAPTER_RUN_MAX_OUTPUT_CHARS = 1_000_000


@dataclass(frozen=True)
class AdapterProcessResult:
    """Subprocess outcome for an adapter command."""

    exit_code: int
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False


Runner = Callable[
    [Sequence[str], Path, Mapping[str, str], int, str],
    AdapterProcessResult,
]
CaptureWriter = Callable[[AdapterProcessResult, Path], None]


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
    stdin_text: str = ""
    capture_writer: CaptureWriter | None = None


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


@dataclass(frozen=True)
class _PreparedRun:
    scratch_root: Path
    manifest_path: Path
    before_revisions: dict[str, ScratchFileRevision]


@dataclass
class _RunningProcess:
    process: subprocess.Popen[bytes]
    stdout_stream: IO[bytes] | None = None
    stderr_stream: IO[bytes] | None = None
    stdin_stream: IO[bytes] | None = None
    stdout_capture: Any = None
    stderr_capture: Any = None
    stdout_thread: threading.Thread | None = None
    stderr_thread: threading.Thread | None = None
    stdin_thread: threading.Thread | None = None
    job_handle: int | None = None


def run_adapter_command(
    spec: AdapterRunSpec,
    *,
    environ: Mapping[str, str],
    runner: Runner | None = None,
) -> AdapterRunResult:
    """Run one adapter command in scratch and verify its result manifest."""

    blocked_reasons: list[str] = []
    prepared = _prepare_run(spec, blocked_reasons)
    if prepared is None:
        return _blocked_result(spec, blocked_reasons)
    env, scrubbed = _scrub_environment(environ, spec.scrubbed_env_vars)
    run = runner or _run_subprocess
    try:
        process = run(
            spec.argv,
            prepared.scratch_root,
            env,
            spec.timeout_seconds,
            spec.stdin_text,
        )
    except (OSError, ValueError) as exc:
        process = AdapterProcessResult(exit_code=127, stderr=str(exc))
    _record_process_failures(process, blocked_reasons)
    adapter_revisions = _snapshot_after_process(prepared.scratch_root, blocked_reasons)
    _run_capture_writer(spec, process, prepared.scratch_root, adapter_revisions, blocked_reasons)
    manifest, workspace_check = _verify_run_outputs(
        spec,
        prepared,
        adapter_revisions,
        blocked_reasons,
    )

    return AdapterRunResult(
        adapter=spec.adapter,
        exit_code=process.exit_code,
        timed_out=process.timed_out,
        manifest_path=prepared.manifest_path.name,
        scrubbed_env_vars=scrubbed,
        stdout_tail=_tail(process.stdout, spec.output_limit),
        stderr_tail=_tail(process.stderr, spec.output_limit),
        manifest=manifest,
        workspace_check=workspace_check,
        blocked_reasons=blocked_reasons,
    )


def _prepare_run(spec: AdapterRunSpec, blocked_reasons: list[str]) -> _PreparedRun | None:
    blocked_reasons.extend(_run_spec_errors(spec))
    if blocked_reasons:
        return None
    scratch_root = spec.scratch_root.resolve()
    try:
        scratch_root.mkdir(parents=True, exist_ok=True)
        manifest_path = _resolve_manifest_path(scratch_root, spec.manifest_path)
        before_revisions = snapshot_scratch_state(scratch_root)
    except (AdapterManifestError, OSError, RuntimeError, ValueError) as exc:
        blocked_reasons.append(str(exc))
        return None
    return _PreparedRun(scratch_root, manifest_path, before_revisions)


def _run_spec_errors(spec: AdapterRunSpec) -> list[str]:
    errors: list[str] = []
    if not spec.argv:
        errors.append("adapter argv is empty")
    if (
        isinstance(spec.timeout_seconds, bool)
        or not isinstance(spec.timeout_seconds, int)
        or not 0 < spec.timeout_seconds <= _ADAPTER_RUN_MAX_SECONDS
    ):
        errors.append(f"adapter timeout must be between 1 and {_ADAPTER_RUN_MAX_SECONDS:,} seconds")
    if (
        isinstance(spec.output_limit, bool)
        or not isinstance(spec.output_limit, int)
        or not 0 < spec.output_limit <= _ADAPTER_RUN_MAX_OUTPUT_CHARS
    ):
        errors.append(
            "adapter output limit must be between 1 and "
            f"{_ADAPTER_RUN_MAX_OUTPUT_CHARS:,} characters"
        )
    return errors


def _record_process_failures(
    process: AdapterProcessResult,
    blocked_reasons: list[str],
) -> None:
    if process.timed_out:
        blocked_reasons.append("adapter command timed out")
    if process.exit_code != 0:
        blocked_reasons.append(f"adapter command exited {process.exit_code}")


def _snapshot_after_process(
    scratch_root: Path,
    blocked_reasons: list[str],
) -> dict[str, ScratchFileRevision] | None:
    try:
        return snapshot_scratch_state(scratch_root)
    except AdapterManifestError as exc:
        blocked_reasons.append(str(exc))
        return None


def _run_capture_writer(
    spec: AdapterRunSpec,
    process: AdapterProcessResult,
    scratch_root: Path,
    adapter_revisions: Mapping[str, ScratchFileRevision] | None,
    blocked_reasons: list[str],
) -> None:
    if (
        process.exit_code != 0
        or process.timed_out
        or adapter_revisions is None
        or spec.capture_writer is None
    ):
        return
    try:
        spec.capture_writer(process, scratch_root)
    except (AdapterManifestError, OSError, ValidationError, ValueError) as exc:
        blocked_reasons.append(f"adapter capture failed: {exc}")


def _verify_run_outputs(
    spec: AdapterRunSpec,
    prepared: _PreparedRun,
    adapter_revisions: Mapping[str, ScratchFileRevision] | None,
    blocked_reasons: list[str],
) -> tuple[AdapterResultManifest | None, AdapterWorkspaceWriteCheck | None]:
    if adapter_revisions is None:
        blocked_reasons.append("adapter scratch state could not be verified")
        return None, None
    if not prepared.manifest_path.exists():
        blocked_reasons.append(f"adapter manifest missing: {prepared.manifest_path.name}")
        return None, None
    try:
        manifest = load_adapter_result_manifest(
            prepared.manifest_path,
            scratch_root=prepared.scratch_root,
        )
        _check_manifest_identity(spec, manifest, blocked_reasons)
        workspace_check = check_adapter_workspace_writes(
            manifest,
            prepared.scratch_root,
            before_files=frozenset(prepared.before_revisions),
            allowed_new_files=(*spec.allowed_new_files, prepared.manifest_path.name),
            before_revisions=prepared.before_revisions,
            adapter_revisions=adapter_revisions,
        )
    except (AdapterManifestError, ValueError) as exc:
        blocked_reasons.append(str(exc))
        return None, None
    _record_workspace_failures(workspace_check, blocked_reasons)
    return manifest, workspace_check


def _record_workspace_failures(
    workspace_check: AdapterWorkspaceWriteCheck,
    blocked_reasons: list[str],
) -> None:
    failures = (
        (workspace_check.missing_files, "adapter manifest declared missing files"),
        (workspace_check.unexpected_files, "adapter wrote unexpected scratch files"),
        (
            workspace_check.unexpected_modified_files,
            "adapter modified undeclared scratch files",
        ),
        (workspace_check.removed_files, "adapter removed scratch files"),
    )
    blocked_reasons.extend(message for paths, message in failures if paths)


def _run_subprocess(
    argv: Sequence[str],
    cwd: Path,
    env: Mapping[str, str],
    timeout_seconds: int,
    stdin_text: str,
) -> AdapterProcessResult:
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, int)
        or not 0 < timeout_seconds <= _ADAPTER_RUN_MAX_SECONDS
    ):
        return AdapterProcessResult(
            exit_code=_ADAPTER_RESOURCE_EXIT_CODE,
            stderr=(f"adapter timeout must be between 1 and {_ADAPTER_RUN_MAX_SECONDS:,} seconds"),
        )
    argv_list = list(argv)
    if not argv_list:
        return AdapterProcessResult(exit_code=127, stderr="adapter argv is empty")
    executable = argv_list[0]
    if not Path(executable).is_absolute():
        resolved = resolve_executable(executable, env=env)
        if resolved is None:
            return AdapterProcessResult(
                exit_code=127,
                stderr=f"executable not found: {executable}",
            )
        argv_list[0] = resolved
    try:
        stdin_bytes = stdin_text.encode("utf-8")
    except UnicodeEncodeError:
        return AdapterProcessResult(
            exit_code=_ADAPTER_RESOURCE_EXIT_CODE,
            stderr="adapter stdin is not valid UTF-8 text",
        )
    if len(stdin_bytes) > _ADAPTER_RUN_STDIN_BYTES:
        return AdapterProcessResult(
            exit_code=_ADAPTER_RESOURCE_EXIT_CODE,
            stderr=f"adapter stdin exceeded the {_ADAPTER_RUN_STDIN_BYTES:,}-byte limit",
        )
    try:
        running = _start_adapter_process(argv_list, cwd, env, stdin_bytes)
    except (OSError, ValueError) as exc:
        return AdapterProcessResult(exit_code=127, stderr=str(exc))
    try:
        resource_error, timed_out = _supervise_adapter_process(running, timeout_seconds)
    finally:
        _close_adapter_process(running)
    return _adapter_process_result(running, resource_error, timed_out)


def _start_adapter_process(
    argv: list[str],
    cwd: Path,
    env: Mapping[str, str],
    stdin_bytes: bytes,
) -> _RunningProcess:
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    process = subprocess.Popen(
        argv,
        cwd=cwd,
        env=dict(env),
        stdin=subprocess.PIPE if stdin_bytes else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
        creationflags=creationflags,
        start_new_session=os.name != "nt",
    )
    running = _RunningProcess(process=process)
    try:
        running.stdout_stream = process.stdout
        running.stderr_stream = process.stderr
        if running.stdout_stream is None or running.stderr_stream is None:
            raise OSError("adapter process did not expose output pipes")
        running.stdout_capture, running.stdout_thread = start_bounded_pipe_head_drain(
            running.stdout_stream,
            limit=_ADAPTER_RUN_OUTPUT_BYTES,
            thread_name="distill-adapter-run-stdout",
        )
        running.stderr_capture, running.stderr_thread = start_bounded_pipe_head_drain(
            running.stderr_stream,
            limit=_ADAPTER_RUN_OUTPUT_BYTES,
            thread_name="distill-adapter-run-stderr",
        )
        if stdin_bytes:
            running.stdin_stream = process.stdin
            if running.stdin_stream is None:
                raise OSError("adapter process did not expose its stdin pipe")
            running.stdin_thread = _start_stdin_writer(running.stdin_stream, stdin_bytes)
    except BaseException:
        _close_adapter_process(running)
        raise
    return running


def _supervise_adapter_process(
    running: _RunningProcess,
    timeout_seconds: int,
) -> tuple[str, bool]:
    try:
        running.job_handle = assign_windows_memory_job(
            running.process,
            job_memory_bytes=_ADAPTER_RUN_TREE_MEMORY_BYTES,
        )
        wait_for_process_budget(
            running.process,
            timeout_seconds=timeout_seconds,
            memory_limit_bytes=_ADAPTER_RUN_TREE_MEMORY_BYTES,
        )
    except ProcessBudgetExceeded as exc:
        return str(exc), exc.kind == "time"
    except OSError as exc:
        return str(exc), False
    return "", False


def _close_adapter_process(running: _RunningProcess) -> None:
    terminate_isolated_process_tree(running.process)
    close_windows_job(running.job_handle)
    threads = (running.stdin_thread, running.stdout_thread, running.stderr_thread)
    streams = (running.stdin_stream, running.stdout_stream, running.stderr_stream)
    for thread in threads:
        if thread is not None:
            thread.join(timeout=1)
    for stream in streams:
        if stream is not None:
            with contextlib.suppress(OSError, ValueError):
                stream.close()
    for thread in threads:
        if thread is not None:
            thread.join(timeout=1)


def _adapter_process_result(
    running: _RunningProcess,
    resource_error: str,
    timed_out: bool,
) -> AdapterProcessResult:
    stdout, stdout_error = _decode_process_output(running.stdout_capture, "stdout")
    stderr, stderr_error = _decode_process_output(running.stderr_capture, "stderr")
    errors = [error for error in (resource_error, stdout_error, stderr_error) if error]
    if errors:
        if stderr:
            stderr = f"{stderr.rstrip()}\n"
        stderr += "\n".join(errors)
    if errors:
        return AdapterProcessResult(
            exit_code=124 if timed_out else _ADAPTER_RESOURCE_EXIT_CODE,
            stdout=stdout,
            stderr=stderr,
            timed_out=timed_out,
        )
    return AdapterProcessResult(
        exit_code=(
            running.process.returncode if isinstance(running.process.returncode, int) else 127
        ),
        stdout=stdout,
        stderr=stderr,
    )


def _start_stdin_writer(stream: IO[bytes], payload: bytes) -> threading.Thread:
    def write() -> None:
        try:
            stream.write(payload)
            stream.flush()
        except (BrokenPipeError, OSError, ValueError):
            pass
        finally:
            with contextlib.suppress(OSError, ValueError):
                stream.close()

    thread = threading.Thread(target=write, daemon=True, name="distill-adapter-run-stdin")
    thread.start()
    return thread


def _decode_process_output(capture: Any, stream_name: str) -> tuple[str, str]:
    if capture is None:
        return "", ""
    raw = capture.bytes()
    try:
        output = raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("utf-8", errors="replace"), f"adapter {stream_name} is not valid UTF-8"
    if capture.truncated:
        return (
            output,
            f"adapter {stream_name} exceeded the {_ADAPTER_RUN_OUTPUT_BYTES:,}-byte limit",
        )
    return output, ""


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
    blocked = {name.upper() for name in names}
    env = {
        key: value
        for key, value in sanitized_package_env(environ).items()
        if key.upper() not in blocked
    }
    removed = tuple(sorted(key for key in environ if key not in env))
    return env, removed


def _resolve_manifest_path(scratch_root: Path, manifest_path: Path) -> Path:
    if (
        manifest_path.is_absolute()
        or manifest_path.drive
        or not manifest_path.parts
        or any(part in {"", ".", ".."} for part in manifest_path.parts)
    ):
        raise AdapterManifestError(f"adapter manifest escapes scratch workspace: {manifest_path}")
    return scratch_root.joinpath(*manifest_path.parts)


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

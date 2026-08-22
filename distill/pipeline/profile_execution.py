# pyright: strict
"""Bounded subprocess execution for recurring research profiles."""

from __future__ import annotations

import codecs
import locale
import math
import os
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any, Protocol

from distill.process_security import (
    distill_child_env,
    package_install_context,
    resolve_executable,
)

__all__ = [
    "MAX_PROFILE_TIMEOUT_SECONDS",
    "CommandExecution",
    "CommandExecutor",
    "execute_command",
    "validate_profile_timeout",
]

_OUTPUT_TAIL_CHARS = 4000
_DRAIN_JOIN_SECONDS = 1.0
_DRAIN_CLOSE_JOIN_SECONDS = 0.25
MAX_PROFILE_TIMEOUT_SECONDS = 86_400


@dataclass(frozen=True)
class CommandExecution:
    """Subprocess outcome captured for state and JSON callers."""

    exit_code: int
    elapsed_seconds: float
    stdout_tail: str = ""
    stderr_tail: str = ""
    timed_out: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "exit_code": self.exit_code,
            "elapsed_seconds": round(self.elapsed_seconds, 3),
            "stdout_tail": self.stdout_tail,
            "stderr_tail": self.stderr_tail,
            "timed_out": self.timed_out,
        }


class CommandExecutor(Protocol):
    """Execute one profile child with an isolated environment overlay."""

    def __call__(
        self,
        command: list[str],
        timeout_seconds: int,
        *,
        environment: Mapping[str, str] | None = None,
    ) -> CommandExecution: ...


def execute_command(
    command: list[str],
    timeout_seconds: object,
    *,
    environment: Mapping[str, str] | None = None,
) -> CommandExecution:
    """Run one command with shell disabled and bounded captured output."""

    timeout_value = validate_profile_timeout(timeout_seconds)
    start = time.monotonic()
    execution_command = (
        [sys.executable, "-P", "-m", "distill", *command[1:]]
        if command and command[0] == "distill"
        else list(command)
    )
    if execution_command and not Path(execution_command[0]).is_absolute():
        resolved = resolve_executable(execution_command[0])
        if resolved is None:
            return CommandExecution(
                exit_code=127,
                elapsed_seconds=0.0,
                stderr_tail=f"executable not found: {execution_command[0]}",
            )
        execution_command[0] = resolved
    trusted_cwd, _install_env = package_install_context()
    child_environment = distill_child_env(overlay=environment)
    stdout_tail = _BoundedTextTail()
    stderr_tail = _BoundedTextTail()
    try:
        process = subprocess.Popen(
            execution_command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=trusted_cwd,
            env=child_environment,
            start_new_session=os.name != "nt",
        )
    except FileNotFoundError as exc:
        return CommandExecution(
            exit_code=127,
            elapsed_seconds=time.monotonic() - start,
            stderr_tail=str(exc),
        )
    except OSError as exc:
        return CommandExecution(
            exit_code=126,
            elapsed_seconds=time.monotonic() - start,
            stderr_tail=str(exc),
        )

    streams = (process.stdout, process.stderr)
    drainers = (
        threading.Thread(target=_drain_stream, args=(streams[0], stdout_tail), daemon=True),
        threading.Thread(target=_drain_stream, args=(streams[1], stderr_tail), daemon=True),
    )
    for drainer in drainers:
        drainer.start()
    timed_out = False
    try:
        process.wait(timeout=timeout_value)
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill_process_tree_root(process)
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
    finally:
        _join_drainers(drainers, streams)

    stderr = stderr_tail.value
    if timed_out and not stderr:
        stderr = f"Timed out after {timeout_value:g}s"
    return CommandExecution(
        exit_code=124
        if timed_out
        else (process.returncode if process.returncode is not None else 126),
        elapsed_seconds=time.monotonic() - start,
        stdout_tail=stdout_tail.value,
        stderr_tail=stderr,
        timed_out=timed_out,
    )


def validate_profile_timeout(value: object) -> float:
    """Return a valid per-command timeout or raise before execution mutates state."""

    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError("timeout_seconds must be a finite number between 0 and 86400")
    try:
        normalized = float(value)
    except OverflowError as exc:
        raise ValueError("timeout_seconds must be a finite number between 0 and 86400") from exc
    if not math.isfinite(normalized) or not 0 < normalized <= MAX_PROFILE_TIMEOUT_SECONDS:
        raise ValueError("timeout_seconds must be a finite number between 0 and 86400")
    return normalized


class _BoundedTextTail:
    def __init__(self) -> None:
        decoder_type = codecs.getincrementaldecoder(locale.getpreferredencoding(False))
        self._decoder = decoder_type(errors="replace")
        self._value = ""
        self._lock = threading.Lock()

    def feed(self, content: bytes) -> None:
        with self._lock:
            self._value = _tail(self._value + self._decoder.decode(content))

    def finish(self) -> None:
        with self._lock:
            self._value = _tail(self._value + self._decoder.decode(b"", final=True))

    @property
    def value(self) -> str:
        with self._lock:
            return self._value


def _drain_stream(stream: IO[bytes] | None, tail: _BoundedTextTail) -> None:
    if stream is None:
        return
    try:
        while chunk := stream.read(8_192):
            tail.feed(chunk)
        tail.finish()
    except (OSError, ValueError):
        return
    finally:
        with suppress(OSError):
            stream.close()


def _kill_process_tree_root(process: subprocess.Popen[bytes]) -> None:
    if os.name == "nt":
        taskkill = resolve_executable("taskkill")
        if taskkill is not None:
            trusted_cwd, child_env = package_install_context()
            with suppress(OSError, subprocess.TimeoutExpired):
                subprocess.run(
                    [taskkill, "/PID", str(process.pid), "/T", "/F"],
                    cwd=trusted_cwd,
                    env=child_env,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                    timeout=5,
                )
        if process.poll() is None:
            process.kill()
        return
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except OSError:
        with suppress(OSError):
            process.kill()


def _join_drainers(
    drainers: tuple[threading.Thread, threading.Thread],
    streams: tuple[IO[bytes] | None, IO[bytes] | None],
) -> None:
    for drainer in drainers:
        drainer.join(timeout=_DRAIN_JOIN_SECONDS)
    for drainer, stream in zip(drainers, streams, strict=True):
        if not drainer.is_alive() or stream is None:
            continue
        threading.Thread(target=_close_stream, args=(stream,), daemon=True).start()
    for drainer in drainers:
        if drainer.is_alive():
            drainer.join(timeout=_DRAIN_CLOSE_JOIN_SECONDS)


def _close_stream(stream: IO[bytes]) -> None:
    with suppress(OSError):
        stream.close()


def _tail(value: str) -> str:
    if len(value) <= _OUTPUT_TAIL_CHARS:
        return value
    return value[-_OUTPUT_TAIL_CHARS:]

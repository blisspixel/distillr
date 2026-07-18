"""Failure and cleanup contracts for recurring-profile subprocesses."""

from __future__ import annotations

import io
import subprocess
from collections.abc import Mapping

import distill.pipeline.profile_execution as profile_execution
from distill.pipeline.profile_execution import execute_command


class _CompletedProcess:
    def __init__(self) -> None:
        self.stdout = io.BytesIO(b"out")
        self.stderr = io.BytesIO()
        self.returncode = 0
        self.pid = 12345

    def wait(self, timeout: float | None = None) -> int:
        return 0

    def poll(self) -> int:
        return 0

    def kill(self) -> None:
        raise AssertionError("completed process must not be killed")


def test_execute_command_overlays_environment_without_mutating_parent(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def popen(_command: list[str], **kwargs: object) -> _CompletedProcess:
        captured.update(kwargs)
        return _CompletedProcess()

    monkeypatch.setattr(profile_execution.subprocess, "Popen", popen)

    result = execute_command(
        ["example"],
        timeout_seconds=1,
        environment={"DISTILL_TEST_RECEIPT": "receipt"},
    )

    child_environment = captured["env"]
    assert isinstance(child_environment, Mapping)
    assert child_environment["DISTILL_TEST_RECEIPT"] == "receipt"
    assert result.exit_code == 0
    assert result.stdout_tail == "out"


def test_execute_command_escalates_when_process_survives_tree_kill(monkeypatch) -> None:
    class ResistantProcess(_CompletedProcess):
        def __init__(self) -> None:
            super().__init__()
            self.returncode = None
            self.waits = 0
            self.kills = 0

        def wait(self, timeout: float | None = None) -> int:
            self.waits += 1
            if self.waits < 3:
                raise subprocess.TimeoutExpired(["resistant"], timeout)
            self.returncode = -9
            return -9

        def kill(self) -> None:
            self.kills += 1

    process = ResistantProcess()
    monkeypatch.setattr(profile_execution.subprocess, "Popen", lambda *_args, **_kwargs: process)
    monkeypatch.setattr(profile_execution, "_kill_process_tree_root", lambda _process: None)

    result = execute_command(["resistant"], timeout_seconds=0.1)

    assert process.waits == 3
    assert process.kills == 1
    assert result.exit_code == 124
    assert result.timed_out is True


def test_drain_stream_is_total_for_missing_and_broken_streams() -> None:
    class BrokenStream:
        def read(self, _size: int) -> bytes:
            raise OSError("pipe failed")

        def close(self) -> None:
            raise OSError("already closed")

    tail = profile_execution._BoundedTextTail()

    profile_execution._drain_stream(None, tail)
    profile_execution._drain_stream(BrokenStream(), tail)  # type: ignore[arg-type]

    assert tail.value == ""


def test_windows_tree_kill_falls_back_to_process_kill(monkeypatch) -> None:
    class Process:
        pid = 12345
        kills = 0

        def poll(self) -> None:
            return None

        def kill(self) -> None:
            self.kills += 1

    process = Process()
    monkeypatch.setattr(profile_execution.os, "name", "nt")
    monkeypatch.setattr(profile_execution.subprocess, "run", lambda *_args, **_kwargs: None)

    profile_execution._kill_process_tree_root(process)  # type: ignore[arg-type] - subprocess test double

    assert process.kills == 1


def test_windows_tree_kill_uses_resolved_tool_and_trusted_context(monkeypatch) -> None:
    class Process:
        pid = 12345

        def poll(self) -> int:
            return 0

    calls: list[tuple[list[str], dict[str, object]]] = []

    def run(argv: list[str], **kwargs: object) -> None:
        calls.append((argv, kwargs))

    monkeypatch.setattr(profile_execution.os, "name", "nt")
    monkeypatch.setattr(
        profile_execution, "resolve_executable", lambda _name: "C:/Windows/System32/taskkill.exe"
    )
    monkeypatch.setattr(
        profile_execution,
        "package_install_context",
        lambda: ("C:/trusted", {"PATH": "C:/Windows/System32"}),
    )
    monkeypatch.setattr(profile_execution.subprocess, "run", run)

    profile_execution._kill_process_tree_root(Process())  # type: ignore[arg-type] - subprocess test double

    assert calls == [
        (
            ["C:/Windows/System32/taskkill.exe", "/PID", "12345", "/T", "/F"],
            {
                "cwd": "C:/trusted",
                "env": {"PATH": "C:/Windows/System32"},
                "stdout": subprocess.DEVNULL,
                "stderr": subprocess.DEVNULL,
                "check": False,
                "timeout": 5,
            },
        )
    ]


def test_posix_tree_kill_falls_back_when_process_group_is_missing(monkeypatch) -> None:
    class Process:
        pid = 12345
        kills = 0

        def kill(self) -> None:
            self.kills += 1

    process = Process()
    monkeypatch.setattr(profile_execution.os, "name", "posix")
    monkeypatch.setattr(profile_execution.signal, "SIGKILL", 9, raising=False)
    monkeypatch.setattr(
        profile_execution.os,
        "killpg",
        lambda *_args: (_ for _ in ()).throw(OSError("missing group")),
        raising=False,
    )

    profile_execution._kill_process_tree_root(process)  # type: ignore[arg-type] - subprocess test double

    assert process.kills == 1


def test_join_drainers_closes_only_live_streams_and_rejoins(monkeypatch) -> None:
    class Drainer:
        def __init__(self) -> None:
            self.joins: list[float] = []

        def join(self, timeout: float) -> None:
            self.joins.append(timeout)

        def is_alive(self) -> bool:
            return True

    starts: list[tuple[object, ...]] = []

    class CloseThread:
        def __init__(self, *, target, args, daemon: bool) -> None:
            starts.append(args)

        def start(self) -> None:
            return None

    first = Drainer()
    second = Drainer()
    stream = io.BytesIO()
    monkeypatch.setattr(profile_execution.threading, "Thread", CloseThread)

    profile_execution._join_drainers((first, second), (stream, None))  # type: ignore[arg-type]

    assert starts == [(stream,)]
    assert first.joins == [1.0, 0.25]
    assert second.joins == [1.0, 0.25]


def test_close_stream_suppresses_cleanup_errors() -> None:
    class BrokenStream:
        def close(self) -> None:
            raise OSError("already closed")

    profile_execution._close_stream(BrokenStream())  # type: ignore[arg-type]

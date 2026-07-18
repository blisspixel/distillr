from __future__ import annotations

import io
import subprocess
from types import SimpleNamespace

import pytest

from distill import process_resources as resources


def test_bounded_byte_tail_retains_only_the_configured_suffix() -> None:
    tail = resources.BoundedByteTail(4)

    tail.append(b"abcdef")
    tail.append(b"gh")

    assert tail.bytes() == b"efgh"


def test_bounded_byte_tail_requires_a_positive_limit() -> None:
    with pytest.raises(ValueError, match="positive"):
        resources.BoundedByteTail(0)


def test_bounded_pipe_drain_consumes_all_input_and_retains_tail() -> None:
    stream = io.BytesIO(b"0123456789")
    tail, thread = resources.start_bounded_pipe_drain(
        stream,
        limit=3,
        thread_name="test-drain",
    )
    thread.join(timeout=1)

    assert thread.is_alive() is False
    assert tail.bytes() == b"789"


def test_bounded_pipe_drain_treats_pipe_errors_as_end_of_stream() -> None:
    class BrokenStream:
        def read(self, _size: int) -> bytes:
            raise OSError("pipe closed")

    tail, thread = resources.start_bounded_pipe_drain(
        BrokenStream(),  # type: ignore[arg-type] - binary stream failure test double
        limit=3,
        thread_name="test-broken-drain",
    )
    thread.join(timeout=1)

    assert thread.is_alive() is False
    assert tail.bytes() == b""


class _WaitProcess:
    pid = 73

    def __init__(self) -> None:
        self.returncode: int | None = None
        self.wait_calls = 0

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        self.wait_calls += 1
        if self.wait_calls == 1:
            raise subprocess.TimeoutExpired("worker", timeout)
        self.returncode = 0
        return 0


def test_wait_for_process_budget_tracks_peak_rss(monkeypatch) -> None:
    process = _WaitProcess()
    samples = iter((100, 200))
    monkeypatch.setattr(resources, "process_tree_rss_bytes", lambda _pid: next(samples))

    peak = resources.wait_for_process_budget(
        process,
        timeout_seconds=10,
        memory_limit_bytes=1_000,
    )

    assert peak == 200


def test_wait_for_process_budget_rejects_memory_excess(monkeypatch) -> None:
    process = _WaitProcess()
    monkeypatch.setattr(resources, "process_tree_rss_bytes", lambda _pid: 1_001)

    with pytest.raises(resources.ProcessBudgetExceeded, match="memory budget"):
        resources.wait_for_process_budget(
            process,
            timeout_seconds=10,
            memory_limit_bytes=1_000,
        )


def test_wait_for_process_budget_rejects_elapsed_time(monkeypatch) -> None:
    class RunningProcess(_WaitProcess):
        def wait(self, timeout=None):
            raise AssertionError(f"wait should not be reached: {timeout}")

    samples = iter((0.0, 2.0, 2.25))
    monkeypatch.setattr(resources.time, "monotonic", lambda: next(samples))
    monkeypatch.setattr(resources, "process_tree_rss_bytes", lambda _pid: 0)

    with pytest.raises(resources.ProcessBudgetExceeded, match="time budget") as raised:
        resources.wait_for_process_budget(
            RunningProcess(),  # type: ignore[arg-type] - subprocess test double
            timeout_seconds=1,
            memory_limit_bytes=1_000,
        )

    assert raised.value.observed == 2.25


def test_process_tree_rss_sums_accessible_processes(monkeypatch) -> None:
    child = SimpleNamespace(memory_info=lambda: SimpleNamespace(rss=20))
    root = SimpleNamespace(
        children=lambda recursive: [child],
        memory_info=lambda: SimpleNamespace(rss=10),
    )
    monkeypatch.setattr(resources.psutil, "Process", lambda _pid: root)

    assert resources.process_tree_rss_bytes(73) == 30


@pytest.mark.parametrize(
    "error", [resources.psutil.NoSuchProcess(73), resources.psutil.AccessDenied(73)]
)
def test_process_tree_rss_returns_zero_when_root_is_unavailable(monkeypatch, error) -> None:
    monkeypatch.setattr(
        resources.psutil,
        "Process",
        lambda _pid: (_ for _ in ()).throw(error),
    )

    assert resources.process_tree_rss_bytes(73) == 0


def test_process_tree_rss_skips_descendants_that_exit_mid_sample(monkeypatch) -> None:
    gone = SimpleNamespace(
        memory_info=lambda: (_ for _ in ()).throw(resources.psutil.NoSuchProcess(74))
    )
    root = SimpleNamespace(
        children=lambda recursive: [gone],
        memory_info=lambda: SimpleNamespace(rss=10),
    )
    monkeypatch.setattr(resources.psutil, "Process", lambda _pid: root)

    assert resources.process_tree_rss_bytes(73) == 10


def test_terminate_process_tree_kills_descendants_root_and_popen(monkeypatch) -> None:
    killed: list[str] = []

    class Child:
        def __init__(self, name: str, *, missing: bool = False) -> None:
            self.name = name
            self.missing = missing

        def kill(self) -> None:
            if self.missing:
                raise resources.psutil.NoSuchProcess(74)
            killed.append(self.name)

    root = SimpleNamespace(
        children=lambda recursive: [Child("first"), Child("gone", missing=True), Child("last")],
        kill=lambda: killed.append("root"),
    )
    monkeypatch.setattr(resources.psutil, "Process", lambda _pid: root)

    class Process(_WaitProcess):
        def poll(self):
            return None

        def kill(self) -> None:
            killed.append("popen")

        def wait(self, timeout=None):
            killed.append(f"wait:{timeout}")
            if timeout is not None:
                raise subprocess.TimeoutExpired("worker", timeout)
            return 0

    resources.terminate_process_tree(Process())  # type: ignore[arg-type]

    assert killed == ["last", "first", "root", "popen", "wait:5", "popen", "wait:None"]


def test_terminate_process_tree_handles_an_already_missing_root(monkeypatch) -> None:
    monkeypatch.setattr(
        resources.psutil,
        "Process",
        lambda _pid: (_ for _ in ()).throw(resources.psutil.NoSuchProcess(73)),
    )

    class CompleteProcess(_WaitProcess):
        def __init__(self) -> None:
            super().__init__()
            self.returncode = 0

        def wait(self, timeout=None):
            return 0

    resources.terminate_process_tree(CompleteProcess())  # type: ignore[arg-type]


def test_non_windows_memory_job_is_a_noop(monkeypatch) -> None:
    monkeypatch.setattr(resources.os, "name", "posix")

    assert (
        resources.assign_windows_memory_job(
            _WaitProcess(),  # type: ignore[arg-type] - subprocess test double
            job_memory_bytes=1_024,
        )
        is None
    )


@pytest.mark.parametrize(
    ("process_limit", "job_limit", "message"),
    [
        (None, None, "required"),
        (0, None, "process memory limit"),
        (None, 0, "job memory limit"),
    ],
)
def test_windows_memory_job_rejects_invalid_limits(
    monkeypatch,
    process_limit: int | None,
    job_limit: int | None,
    message: str,
) -> None:
    monkeypatch.setattr(resources.os, "name", "nt")

    with pytest.raises(ValueError, match=message):
        resources.assign_windows_memory_job(
            _WaitProcess(),  # type: ignore[arg-type] - subprocess test double
            process_memory_bytes=process_limit,
            job_memory_bytes=job_limit,
        )


class _KernelCall:
    def __init__(self, result) -> None:
        self.result = result
        self.calls: list[tuple[object, ...]] = []
        self.argtypes = None
        self.restype = None

    def __call__(self, *args):
        self.calls.append(args)
        return self.result


class _Kernel32:
    def __init__(self, *, create=99, configure=True, assign=True) -> None:
        self.CreateJobObjectW = _KernelCall(create)
        self.SetInformationJobObject = _KernelCall(configure)
        self.AssignProcessToJobObject = _KernelCall(assign)
        self.CloseHandle = _KernelCall(True)


def _install_kernel32(monkeypatch, kernel: _Kernel32) -> None:
    import ctypes

    monkeypatch.setattr(resources.os, "name", "nt")
    monkeypatch.setattr(ctypes, "WinDLL", lambda *_args, **_kwargs: kernel)


def test_windows_memory_job_applies_process_and_tree_limits(monkeypatch) -> None:
    kernel = _Kernel32()
    _install_kernel32(monkeypatch, kernel)
    process = SimpleNamespace(_handle=73)

    handle = resources.assign_windows_memory_job(
        process,  # type: ignore[arg-type] - subprocess handle test double
        process_memory_bytes=1_024,
        job_memory_bytes=2_048,
    )

    assert handle == 99
    assert len(kernel.SetInformationJobObject.calls) == 1
    assert len(kernel.AssignProcessToJobObject.calls) == 1
    assert kernel.CloseHandle.calls == []


def test_windows_memory_job_closes_job_when_process_handle_is_unavailable(monkeypatch) -> None:
    kernel = _Kernel32()
    _install_kernel32(monkeypatch, kernel)

    with pytest.raises(OSError, match="process handle"):
        resources.assign_windows_memory_job(
            SimpleNamespace(_handle=None),  # type: ignore[arg-type] - invalid handle test double
            job_memory_bytes=2_048,
        )

    assert len(kernel.CloseHandle.calls) == 1


def test_windows_memory_job_closes_job_when_configuration_fails(monkeypatch) -> None:
    import ctypes

    kernel = _Kernel32(configure=False)
    _install_kernel32(monkeypatch, kernel)
    monkeypatch.setattr(ctypes, "get_last_error", lambda: 5)

    with pytest.raises(OSError):
        resources.assign_windows_memory_job(
            SimpleNamespace(_handle=73),  # type: ignore[arg-type] - subprocess handle test double
            job_memory_bytes=2_048,
        )

    assert len(kernel.CloseHandle.calls) == 1


def test_close_windows_job_ignores_none_and_closes_a_handle(monkeypatch) -> None:
    import ctypes

    kernel = _Kernel32()
    monkeypatch.setattr(ctypes, "WinDLL", lambda *_args, **_kwargs: kernel)

    resources.close_windows_job(None)
    resources.close_windows_job(99)

    assert len(kernel.CloseHandle.calls) == 1


def test_process_budget_requires_positive_limits() -> None:
    with pytest.raises(ValueError, match="positive"):
        resources.wait_for_process_budget(
            _WaitProcess(),  # type: ignore[arg-type] - subprocess test double
            timeout_seconds=0,
            memory_limit_bytes=1,
        )

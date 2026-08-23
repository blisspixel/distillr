from __future__ import annotations

import io
import json
import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from distill.doctor import adapter_runner as adapter_runner_module
from distill.doctor.adapter_runner import (
    AdapterProcessResult,
    AdapterRunSpec,
    _run_subprocess,
    run_adapter_command,
)
from distill.process_resources import ProcessBudgetExceeded


def _manifest(**overrides):
    payload = {
        "schema_version": "adapter-result.v1",
        "adapter": "codex",
        "adapter_version": "codex 0.140.0",
        "auth_class": "included-plan",
        "command_class": "scratch-write",
        "model": "gpt-5.1-codex",
        "prompt_hash": "sha256:prompt",
        "source_hash": "sha256:source",
        "elapsed_ms": 100,
        "usage": {
            "input_tokens": 10,
            "output_tokens": 5,
            "native": {"event_count": 1},
        },
        "stop_reason": "complete",
        "files_read": ["sources/input.md"],
        "files_written": ["result.json"],
        "output": {"summary": "ok"},
        "policy": {
            "cost_mode": "no-metered",
            "blocked_api_key_env": [],
            "metered_allowed": False,
        },
    }
    payload.update(overrides)
    return payload


def test_adapter_runner_scrubs_env_and_accepts_valid_manifest(tmp_path):
    seen_env: dict[str, str] = {}
    _stage_source(tmp_path)

    def runner(
        _argv: Sequence[str],
        cwd: Path,
        env: Mapping[str, str],
        _timeout: int,
        _stdin: str,
    ) -> AdapterProcessResult:
        seen_env.update(env)
        (cwd / "result.json").write_text("{}", encoding="utf-8")
        (cwd / "adapter-result.json").write_text(json.dumps(_manifest()), encoding="utf-8")
        return AdapterProcessResult(exit_code=0, stdout="done")

    result = run_adapter_command(
        AdapterRunSpec(
            adapter="codex",
            argv=("codex", "exec", "--json"),
            scratch_root=tmp_path,
            command_class="scratch-write",
        ),
        environ={
            "OPENAI_API_KEY": "secret",
            "PATH": "bin",
            "PYTHONPATH": "untrusted",
            "NODE_OPTIONS": "--require untrusted.js",
        },
        runner=runner,
    )

    assert result.ok
    assert "OPENAI_API_KEY" not in seen_env
    assert "PYTHONPATH" not in seen_env
    assert "NODE_OPTIONS" not in seen_env
    assert seen_env["PATH"] == "bin"
    assert "OPENAI_API_KEY" in result.scrubbed_env_vars
    assert "PYTHONPATH" in result.scrubbed_env_vars
    assert result.workspace_check is not None
    assert result.workspace_check.ok
    assert result.to_dict()["manifest"]["adapter"] == "codex"


def test_adapter_runner_blocks_missing_manifest(tmp_path):
    def runner(
        _argv: Sequence[str],
        _cwd: Path,
        _env: Mapping[str, str],
        _timeout: int,
        _stdin: str,
    ) -> AdapterProcessResult:
        return AdapterProcessResult(exit_code=0)

    result = run_adapter_command(
        AdapterRunSpec(adapter="codex", argv=("codex", "exec"), scratch_root=tmp_path),
        environ={},
        runner=runner,
    )

    assert not result.ok
    assert result.manifest is None
    assert "adapter manifest missing: adapter-result.json" in result.blocked_reasons


def test_adapter_runner_blocks_unexpected_scratch_writes(tmp_path):
    _stage_source(tmp_path)

    def runner(
        _argv: Sequence[str],
        cwd: Path,
        _env: Mapping[str, str],
        _timeout: int,
        _stdin: str,
    ) -> AdapterProcessResult:
        (cwd / "result.json").write_text("{}", encoding="utf-8")
        (cwd / "extra.txt").write_text("unexpected", encoding="utf-8")
        (cwd / "adapter-result.json").write_text(json.dumps(_manifest()), encoding="utf-8")
        return AdapterProcessResult(exit_code=0)

    result = run_adapter_command(
        AdapterRunSpec(
            adapter="codex",
            argv=("codex", "exec"),
            scratch_root=tmp_path,
            command_class="scratch-write",
        ),
        environ={},
        runner=runner,
    )

    assert not result.ok
    assert "adapter wrote unexpected scratch files" in result.blocked_reasons
    assert result.workspace_check is not None
    assert result.workspace_check.unexpected_files == ("extra.txt",)


def test_read_only_adapter_cannot_modify_existing_source(tmp_path):
    _stage_source(tmp_path)

    def runner(
        _argv: Sequence[str],
        cwd: Path,
        _env: Mapping[str, str],
        _timeout: int,
        _stdin: str,
    ) -> AdapterProcessResult:
        (cwd / "sources" / "input.md").write_text("tampered", encoding="utf-8")
        (cwd / "adapter-result.json").write_text(
            json.dumps(_manifest(command_class="read-only", files_written=[])),
            encoding="utf-8",
        )
        return AdapterProcessResult(exit_code=0)

    result = run_adapter_command(
        AdapterRunSpec(
            adapter="codex",
            argv=("codex", "exec"),
            scratch_root=tmp_path,
            command_class="read-only",
        ),
        environ={},
        runner=runner,
    )

    assert not result.ok
    assert result.workspace_check is not None
    assert result.workspace_check.modified_files == ("sources/input.md",)
    assert result.workspace_check.unexpected_modified_files == ("sources/input.md",)
    assert "adapter modified undeclared scratch files" in result.blocked_reasons


def test_adapter_cannot_remove_existing_source(tmp_path):
    _stage_source(tmp_path)

    def runner(
        _argv: Sequence[str],
        cwd: Path,
        _env: Mapping[str, str],
        _timeout: int,
        _stdin: str,
    ) -> AdapterProcessResult:
        (cwd / "sources" / "input.md").unlink()
        (cwd / "adapter-result.json").write_text(
            json.dumps(_manifest(command_class="read-only", files_written=[])),
            encoding="utf-8",
        )
        return AdapterProcessResult(exit_code=0)

    result = run_adapter_command(
        AdapterRunSpec(
            adapter="codex",
            argv=("codex", "exec"),
            scratch_root=tmp_path,
            command_class="read-only",
        ),
        environ={},
        runner=runner,
    )

    assert not result.ok
    assert result.workspace_check is not None
    assert result.workspace_check.removed_files == ("sources/input.md",)
    assert "adapter removed scratch files" in result.blocked_reasons


def test_adapter_created_symlink_blocks_verification(tmp_path):
    _stage_source(tmp_path)
    outside = tmp_path.parent / f"{tmp_path.name}-outside.txt"
    outside.write_text("outside", encoding="utf-8")

    def runner(
        _argv: Sequence[str],
        cwd: Path,
        _env: Mapping[str, str],
        _timeout: int,
        _stdin: str,
    ) -> AdapterProcessResult:
        try:
            (cwd / "linked.txt").symlink_to(outside)
        except OSError as exc:
            pytest.skip(f"symlinks unavailable: {exc}")
        (cwd / "adapter-result.json").write_text(
            json.dumps(_manifest(command_class="read-only", files_written=[])),
            encoding="utf-8",
        )
        return AdapterProcessResult(exit_code=0)

    result = run_adapter_command(
        AdapterRunSpec(
            adapter="codex",
            argv=("codex", "exec"),
            scratch_root=tmp_path,
            command_class="read-only",
        ),
        environ={},
        runner=runner,
    )

    assert not result.ok
    assert result.manifest is None
    assert outside.read_text(encoding="utf-8") == "outside"
    assert any("linked path" in reason for reason in result.blocked_reasons)


def test_adapter_runner_blocks_manifest_identity_mismatch(tmp_path):
    def runner(
        _argv: Sequence[str],
        cwd: Path,
        _env: Mapping[str, str],
        _timeout: int,
        _stdin: str,
    ) -> AdapterProcessResult:
        (cwd / "result.json").write_text("{}", encoding="utf-8")
        (cwd / "adapter-result.json").write_text(
            json.dumps(_manifest(adapter="grok")),
            encoding="utf-8",
        )
        return AdapterProcessResult(exit_code=0)

    result = run_adapter_command(
        AdapterRunSpec(
            adapter="codex",
            argv=("codex", "exec"),
            scratch_root=tmp_path,
            command_class="scratch-write",
        ),
        environ={},
        runner=runner,
    )

    assert not result.ok
    assert any("adapter manifest name mismatch" in reason for reason in result.blocked_reasons)


def test_adapter_runner_blocks_empty_argv(tmp_path):
    result = run_adapter_command(
        AdapterRunSpec(adapter="codex", argv=(), scratch_root=tmp_path),
        environ={},
        runner=lambda _argv, _cwd, _env, _timeout, _stdin: AdapterProcessResult(exit_code=0),
    )

    assert not result.ok
    assert result.blocked_reasons == ["adapter argv is empty"]


@pytest.mark.parametrize("timeout_seconds", [0, 3601])
def test_adapter_runner_rejects_invalid_timeout_before_execution(
    tmp_path,
    timeout_seconds,
):
    called = False

    def runner(*_args):
        nonlocal called
        called = True
        return AdapterProcessResult(exit_code=0)

    result = run_adapter_command(
        AdapterRunSpec(
            adapter="codex",
            argv=("codex",),
            scratch_root=tmp_path,
            timeout_seconds=timeout_seconds,
        ),
        environ={},
        runner=runner,
    )

    assert not result.ok
    assert not called
    assert any("adapter timeout must be between" in reason for reason in result.blocked_reasons)


@pytest.mark.parametrize("output_limit", [0, 1_000_001])
def test_adapter_runner_rejects_invalid_output_limit_before_execution(
    tmp_path,
    output_limit,
):
    called = False

    def runner(*_args):
        nonlocal called
        called = True
        return AdapterProcessResult(exit_code=0)

    result = run_adapter_command(
        AdapterRunSpec(
            adapter="codex",
            argv=("codex",),
            scratch_root=tmp_path,
            output_limit=output_limit,
        ),
        environ={},
        runner=runner,
    )

    assert not result.ok
    assert not called
    assert any(
        "adapter output limit must be between" in reason for reason in result.blocked_reasons
    )


@pytest.mark.parametrize("error", [OSError("launch failed"), ValueError("invalid launch")])
def test_adapter_runner_reports_runner_launch_failure(tmp_path, error):
    def runner(*_args):
        raise error

    result = run_adapter_command(
        AdapterRunSpec(adapter="codex", argv=("codex",), scratch_root=tmp_path),
        environ={},
        runner=runner,
    )

    assert not result.ok
    assert result.exit_code == 127
    assert result.stderr_tail == str(error)
    assert "adapter command exited 127" in result.blocked_reasons


def test_adapter_runner_rejects_unsafe_manifest_path_before_execution(tmp_path):
    called = False

    def runner(*_args):
        nonlocal called
        called = True
        return AdapterProcessResult(exit_code=0)

    result = run_adapter_command(
        AdapterRunSpec(
            adapter="codex",
            argv=("codex",),
            scratch_root=tmp_path,
            manifest_path=Path("..") / "adapter-result.json",
        ),
        environ={},
        runner=runner,
    )

    assert not result.ok
    assert not called
    assert any("manifest escapes scratch workspace" in reason for reason in result.blocked_reasons)


def test_adapter_runner_blocks_unverifiable_post_process_state(tmp_path, monkeypatch):
    calls = 0

    def snapshot(_root):
        nonlocal calls
        calls += 1
        if calls == 1:
            return {}
        raise adapter_runner_module.AdapterManifestError("scratch changed unsafely")

    def runner(_argv, cwd, _env, _timeout, _stdin):
        (cwd / "adapter-result.json").write_text(json.dumps(_manifest()), encoding="utf-8")
        return AdapterProcessResult(exit_code=0)

    monkeypatch.setattr(adapter_runner_module, "snapshot_scratch_state", snapshot)

    result = run_adapter_command(
        AdapterRunSpec(adapter="codex", argv=("codex",), scratch_root=tmp_path),
        environ={},
        runner=runner,
    )

    assert not result.ok
    assert result.manifest is None
    assert "scratch changed unsafely" in result.blocked_reasons
    assert "adapter scratch state could not be verified" in result.blocked_reasons


def test_adapter_runner_blocks_invalid_manifest_after_success(tmp_path):
    def runner(_argv, cwd, _env, _timeout, _stdin):
        (cwd / "adapter-result.json").write_text("not JSON", encoding="utf-8")
        return AdapterProcessResult(exit_code=0)

    result = run_adapter_command(
        AdapterRunSpec(adapter="codex", argv=("codex",), scratch_root=tmp_path),
        environ={},
        runner=runner,
    )

    assert not result.ok
    assert result.manifest is None
    assert "adapter manifest is invalid structured data" in result.blocked_reasons


def test_adapter_runner_blocks_command_class_mismatch(tmp_path):
    def runner(_argv, cwd, _env, _timeout, _stdin):
        (cwd / "result.json").write_text("{}", encoding="utf-8")
        (cwd / "adapter-result.json").write_text(json.dumps(_manifest()), encoding="utf-8")
        return AdapterProcessResult(exit_code=0)

    result = run_adapter_command(
        AdapterRunSpec(
            adapter="codex",
            argv=("codex",),
            scratch_root=tmp_path,
            command_class="read-only",
        ),
        environ={},
        runner=runner,
    )

    assert not result.ok
    assert any("command class mismatch" in reason for reason in result.blocked_reasons)


def test_adapter_runner_passes_stdin_text(tmp_path):
    seen_stdin = ""
    _stage_source(tmp_path)

    def runner(
        _argv: Sequence[str],
        cwd: Path,
        _env: Mapping[str, str],
        _timeout: int,
        stdin: str,
    ) -> AdapterProcessResult:
        nonlocal seen_stdin
        seen_stdin = stdin
        (cwd / "result.json").write_text("{}", encoding="utf-8")
        (cwd / "adapter-result.json").write_text(json.dumps(_manifest()), encoding="utf-8")
        return AdapterProcessResult(exit_code=0)

    result = run_adapter_command(
        AdapterRunSpec(
            adapter="codex",
            argv=("codex", "exec", "-"),
            scratch_root=tmp_path,
            command_class="scratch-write",
            stdin_text="staged prompt",
        ),
        environ={},
        runner=runner,
    )

    assert result.ok
    assert seen_stdin == "staged prompt"


def test_adapter_runner_blocks_timeout(tmp_path):
    result = run_adapter_command(
        AdapterRunSpec(adapter="codex", argv=("codex",), scratch_root=tmp_path, timeout_seconds=1),
        environ={},
        runner=lambda *a: AdapterProcessResult(exit_code=0, timed_out=True),
    )
    assert not result.ok
    assert any("timed out" in r for r in result.blocked_reasons)


def test_run_subprocess_decodes_timeout_byte_output(tmp_path, monkeypatch):
    process = _FakeProcess(stdout=b"partial \xff", stderr=b"error \xff")
    monkeypatch.setattr(adapter_runner_module.subprocess, "Popen", lambda *_a, **_kw: process)
    monkeypatch.setattr(adapter_runner_module, "assign_windows_memory_job", lambda *_a, **_kw: None)
    monkeypatch.setattr(
        adapter_runner_module,
        "wait_for_process_budget",
        lambda *_a, **_kw: (_ for _ in ()).throw(ProcessBudgetExceeded("time", 1, 2)),
    )
    monkeypatch.setattr(
        adapter_runner_module,
        "terminate_isolated_process_tree",
        lambda proc: setattr(proc, "returncode", -9),
    )
    monkeypatch.setattr(adapter_runner_module, "close_windows_job", lambda _handle: None)

    result = _run_subprocess((str(tmp_path / "codex.exe"),), tmp_path, {}, 1, "")

    assert result.exit_code == 124
    assert result.timed_out is True
    assert result.stdout == "partial \ufffd"
    assert result.stderr.startswith("error \ufffd\n")
    assert "child process time budget exceeded" in result.stderr
    assert "adapter stdout is not valid UTF-8" in result.stderr
    assert "adapter stderr is not valid UTF-8" in result.stderr


def test_run_subprocess_handles_real_stdin_stdout_and_stderr(tmp_path):
    script = (
        "import sys; value = sys.stdin.read(); "
        "print(value.upper()); print('warning', file=sys.stderr)"
    )

    result = _run_subprocess(
        (str(Path(sys.executable).resolve()), "-I", "-c", script),
        tmp_path,
        os.environ,
        10,
        "hello",
    )

    assert result.exit_code == 0
    assert result.timed_out is False
    assert result.stdout.strip() == "HELLO"
    assert result.stderr.strip() == "warning"


def test_run_subprocess_drains_but_blocks_oversized_output(tmp_path, monkeypatch):
    process = _FakeProcess(stdout=b"abcde")
    monkeypatch.setattr(adapter_runner_module, "_ADAPTER_RUN_OUTPUT_BYTES", 4)
    monkeypatch.setattr(adapter_runner_module.subprocess, "Popen", lambda *_a, **_kw: process)
    monkeypatch.setattr(adapter_runner_module, "assign_windows_memory_job", lambda *_a, **_kw: None)

    def complete(proc, **_kwargs):
        proc.returncode = 0
        return 1

    monkeypatch.setattr(adapter_runner_module, "wait_for_process_budget", complete)
    monkeypatch.setattr(
        adapter_runner_module, "terminate_isolated_process_tree", lambda _proc: None
    )
    monkeypatch.setattr(adapter_runner_module, "close_windows_job", lambda _handle: None)

    result = _run_subprocess((str(tmp_path / "codex.exe"),), tmp_path, {}, 1, "")

    assert result.exit_code == 125
    assert result.stdout == "abcd"
    assert "adapter stdout exceeded the 4-byte limit" in result.stderr


def test_run_subprocess_rejects_oversized_stdin_before_launch(tmp_path, monkeypatch):
    called = False

    def popen(*_args, **_kwargs):
        nonlocal called
        called = True
        return _FakeProcess()

    monkeypatch.setattr(adapter_runner_module, "_ADAPTER_RUN_STDIN_BYTES", 4)
    monkeypatch.setattr(adapter_runner_module.subprocess, "Popen", popen)

    result = _run_subprocess((str(tmp_path / "codex.exe"),), tmp_path, {}, 1, "abcde")

    assert result.exit_code == 125
    assert not called
    assert "stdin exceeded the 4-byte limit" in result.stderr


@pytest.mark.parametrize("timeout_seconds", [0, 3601, True])
def test_run_subprocess_rejects_invalid_timeout_before_launch(
    tmp_path,
    monkeypatch,
    timeout_seconds,
):
    called = False

    def popen(*_args, **_kwargs):
        nonlocal called
        called = True
        return _FakeProcess()

    monkeypatch.setattr(adapter_runner_module.subprocess, "Popen", popen)

    result = _run_subprocess(
        (str(tmp_path / "codex.exe"),),
        tmp_path,
        {},
        timeout_seconds,
        "",
    )

    assert result.exit_code == 125
    assert not called
    assert "adapter timeout must be between" in result.stderr


def test_run_subprocess_reports_prelaunch_failures(tmp_path, monkeypatch):
    empty = _run_subprocess((), tmp_path, {}, 1, "")
    missing = _run_subprocess(("missing-adapter-command",), tmp_path, {}, 1, "")
    invalid_stdin = _run_subprocess(
        (str(tmp_path / "adapter.exe"),),
        tmp_path,
        {},
        1,
        "\ud800",
    )

    monkeypatch.setattr(
        adapter_runner_module,
        "_start_adapter_process",
        lambda *_args: (_ for _ in ()).throw(OSError("launch boundary failed")),
    )
    launch_error = _run_subprocess(
        (str(tmp_path / "adapter.exe"),),
        tmp_path,
        {},
        1,
        "",
    )

    assert empty.exit_code == 127
    assert empty.stderr == "adapter argv is empty"
    assert missing.exit_code == 127
    assert "executable not found" in missing.stderr
    assert invalid_stdin.exit_code == 125
    assert "stdin is not valid UTF-8" in invalid_stdin.stderr
    assert launch_error.exit_code == 127
    assert launch_error.stderr == "launch boundary failed"


def test_start_adapter_process_cleans_up_when_output_pipes_are_missing(
    tmp_path,
    monkeypatch,
):
    process = _FakeProcess()
    process.stdout = None
    cleaned = False

    def cleanup(_running):
        nonlocal cleaned
        cleaned = True

    monkeypatch.setattr(adapter_runner_module.subprocess, "Popen", lambda *_a, **_kw: process)
    monkeypatch.setattr(adapter_runner_module, "_close_adapter_process", cleanup)

    with pytest.raises(OSError, match="output pipes"):
        adapter_runner_module._start_adapter_process(
            [str(tmp_path / "adapter.exe")],
            tmp_path,
            {},
            b"",
        )

    assert cleaned


def test_start_adapter_process_cleans_up_when_stdin_pipe_is_missing(
    tmp_path,
    monkeypatch,
):
    process = _FakeProcess()
    cleaned = False

    def cleanup(_running):
        nonlocal cleaned
        cleaned = True

    monkeypatch.setattr(adapter_runner_module.subprocess, "Popen", lambda *_a, **_kw: process)
    monkeypatch.setattr(
        adapter_runner_module,
        "start_bounded_pipe_head_drain",
        lambda *_args, **_kwargs: (object(), None),
    )
    monkeypatch.setattr(adapter_runner_module, "_close_adapter_process", cleanup)

    with pytest.raises(OSError, match="stdin pipe"):
        adapter_runner_module._start_adapter_process(
            [str(tmp_path / "adapter.exe")],
            tmp_path,
            {},
            b"input",
        )

    assert cleaned


def test_supervise_adapter_process_reports_setup_error(monkeypatch):
    running = adapter_runner_module._RunningProcess(process=_FakeProcess())
    monkeypatch.setattr(
        adapter_runner_module,
        "assign_windows_memory_job",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("job setup failed")),
    )

    error, timed_out = adapter_runner_module._supervise_adapter_process(running, 1)

    assert error == "job setup failed"
    assert timed_out is False


def test_decode_process_output_accepts_missing_capture():
    assert adapter_runner_module._decode_process_output(None, "stdout") == ("", "")


def test_adapter_runner_blocks_nonzero_exit(tmp_path):
    _stage_source(tmp_path)
    result = run_adapter_command(
        AdapterRunSpec(adapter="codex", argv=("codex",), scratch_root=tmp_path),
        environ={},
        runner=lambda *a: AdapterProcessResult(exit_code=2),
    )
    assert not result.ok
    assert any("exited 2" in r for r in result.blocked_reasons)


def test_adapter_runner_blocks_capture_failure(tmp_path):
    _stage_source(tmp_path)

    def bad_capture(_proc, _root):
        raise ValueError("bad capture")

    result = run_adapter_command(
        AdapterRunSpec(
            adapter="codex",
            argv=("codex",),
            scratch_root=tmp_path,
            capture_writer=bad_capture,
        ),
        environ={},
        runner=lambda *a: AdapterProcessResult(exit_code=0),
    )
    assert not result.ok
    assert any("capture failed" in r for r in result.blocked_reasons)


def _stage_source(root: Path) -> None:
    source_dir = root / "sources"
    source_dir.mkdir()
    (source_dir / "input.md").write_text("source", encoding="utf-8")


class _FakeProcess:
    pid = 271

    def __init__(self, *, stdout: bytes = b"", stderr: bytes = b"") -> None:
        self.stdout = io.BytesIO(stdout)
        self.stderr = io.BytesIO(stderr)
        self.stdin = None
        self.returncode: int | None = None

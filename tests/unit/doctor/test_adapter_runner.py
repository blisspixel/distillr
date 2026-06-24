from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from distill.doctor.adapter_runner import (
    AdapterProcessResult,
    AdapterRunSpec,
    run_adapter_command,
)


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
        environ={"OPENAI_API_KEY": "secret", "PATH": "bin"},
        runner=runner,
    )

    assert result.ok
    assert "OPENAI_API_KEY" not in seen_env
    assert seen_env["PATH"] == "bin"
    assert result.scrubbed_env_vars == ("OPENAI_API_KEY",)
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

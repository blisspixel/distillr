from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from distill.doctor.adapter_runner import AdapterProcessResult
from distill.doctor.adapter_workload_runner import (
    AdapterWorkloadRunSpec,
    run_adapter_workload,
)


def _workload(**overrides):
    payload = {
        "schema_version": "adapter-workload.v1",
        "workload": "profile-enrichment",
        "command_class": "read-only",
        "prompt_path": "prompt.md",
        "source_paths": ["sources/input.md"],
        "output_schema_path": "schemas/result.json",
        "result_manifest_path": "adapter-result.json",
        "allowed_write_paths": [],
        "cost_mode": "no-metered",
        "max_seconds": 120,
        "output_limit": 4000,
        "metadata": {"profile": "ai-developer-news"},
    }
    payload.update(overrides)
    return payload


def _manifest(**overrides):
    payload = {
        "schema_version": "adapter-result.v1",
        "adapter": "codex",
        "adapter_version": "codex 0.140.0",
        "auth_class": "included-plan",
        "command_class": "read-only",
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
        "files_read": ["adapter-workload.json", "prompt.md", "sources/input.md"],
        "files_written": [],
        "output": {"summary": "ok"},
        "policy": {
            "cost_mode": "no-metered",
            "blocked_api_key_env": [],
            "metered_allowed": False,
        },
    }
    payload.update(overrides)
    return payload


def test_adapter_workload_runner_accepts_read_only_manifest(tmp_path):
    _stage_workload(tmp_path)

    def runner(
        _argv: Sequence[str],
        cwd: Path,
        _env: Mapping[str, str],
        _timeout: int,
    ) -> AdapterProcessResult:
        (cwd / "adapter-result.json").write_text(json.dumps(_manifest()), encoding="utf-8")
        return AdapterProcessResult(exit_code=0, stdout="done")

    result = run_adapter_workload(
        AdapterWorkloadRunSpec(
            adapter="codex",
            argv=("codex", "exec", "--json"),
            scratch_root=tmp_path,
        ),
        environ={},
        runner=runner,
    )

    assert result.ok
    assert result.workload is not None
    assert result.workload.workload == "profile-enrichment"
    assert result.adapter_result is not None
    assert result.adapter_result.workspace_check is not None
    assert result.adapter_result.workspace_check.ok
    assert result.to_dict()["adapter_result"]["manifest"]["adapter"] == "codex"


def test_adapter_workload_runner_accepts_declared_capture_file(tmp_path):
    _stage_workload(tmp_path)

    def runner(
        _argv: Sequence[str],
        cwd: Path,
        _env: Mapping[str, str],
        _timeout: int,
    ) -> AdapterProcessResult:
        (cwd / "result.txt").write_text("captured stdout", encoding="utf-8")
        (cwd / "adapter-result.json").write_text(json.dumps(_manifest()), encoding="utf-8")
        return AdapterProcessResult(exit_code=0, stdout="done")

    result = run_adapter_workload(
        AdapterWorkloadRunSpec(
            adapter="codex",
            argv=("codex", "exec", "--json"),
            scratch_root=tmp_path,
            allowed_new_files=("result.txt",),
        ),
        environ={},
        runner=runner,
    )

    assert result.ok
    assert result.adapter_result is not None
    assert result.adapter_result.workspace_check is not None
    assert result.adapter_result.workspace_check.new_files == (
        "adapter-result.json",
        "result.txt",
    )


def test_adapter_workload_runner_blocks_undeclared_capture_file(tmp_path):
    _stage_workload(tmp_path)

    def runner(
        _argv: Sequence[str],
        cwd: Path,
        _env: Mapping[str, str],
        _timeout: int,
    ) -> AdapterProcessResult:
        (cwd / "result.txt").write_text("captured stdout", encoding="utf-8")
        (cwd / "adapter-result.json").write_text(json.dumps(_manifest()), encoding="utf-8")
        return AdapterProcessResult(exit_code=0)

    result = run_adapter_workload(
        AdapterWorkloadRunSpec(
            adapter="codex",
            argv=("codex", "exec", "--json"),
            scratch_root=tmp_path,
        ),
        environ={},
        runner=runner,
    )

    assert not result.ok
    assert result.adapter_result is not None
    assert "adapter wrote unexpected scratch files" in result.adapter_result.blocked_reasons


def test_adapter_workload_runner_blocks_reads_outside_workload(tmp_path):
    _stage_workload(tmp_path)

    def runner(
        _argv: Sequence[str],
        cwd: Path,
        _env: Mapping[str, str],
        _timeout: int,
    ) -> AdapterProcessResult:
        (cwd / "adapter-result.json").write_text(
            json.dumps(_manifest(files_read=["sources/secret.md"])),
            encoding="utf-8",
        )
        return AdapterProcessResult(exit_code=0)

    result = run_adapter_workload(
        AdapterWorkloadRunSpec(adapter="codex", argv=("codex", "exec"), scratch_root=tmp_path),
        environ={},
        runner=runner,
    )

    assert not result.ok
    assert any("read files outside workload package" in reason for reason in result.blocked_reasons)


def test_adapter_workload_runner_blocks_writes_outside_workload(tmp_path):
    _stage_workload(
        tmp_path,
        command_class="scratch-write",
        allowed_write_paths=["result.json"],
    )

    def runner(
        _argv: Sequence[str],
        cwd: Path,
        _env: Mapping[str, str],
        _timeout: int,
    ) -> AdapterProcessResult:
        (cwd / "other.json").write_text("{}", encoding="utf-8")
        (cwd / "adapter-result.json").write_text(
            json.dumps(
                _manifest(
                    command_class="scratch-write",
                    files_written=["other.json"],
                )
            ),
            encoding="utf-8",
        )
        return AdapterProcessResult(exit_code=0)

    result = run_adapter_workload(
        AdapterWorkloadRunSpec(adapter="codex", argv=("codex", "exec"), scratch_root=tmp_path),
        environ={},
        runner=runner,
    )

    assert not result.ok
    assert any(
        "wrote files outside workload package" in reason for reason in result.blocked_reasons
    )


def test_adapter_workload_runner_blocks_cost_mode_mismatch(tmp_path):
    _stage_workload(tmp_path)

    def runner(
        _argv: Sequence[str],
        cwd: Path,
        _env: Mapping[str, str],
        _timeout: int,
    ) -> AdapterProcessResult:
        manifest = _manifest(
            policy={
                "cost_mode": "auto",
                "blocked_api_key_env": [],
                "metered_allowed": False,
            }
        )
        (cwd / "adapter-result.json").write_text(json.dumps(manifest), encoding="utf-8")
        return AdapterProcessResult(exit_code=0)

    result = run_adapter_workload(
        AdapterWorkloadRunSpec(adapter="codex", argv=("codex", "exec"), scratch_root=tmp_path),
        environ={},
        runner=runner,
    )

    assert not result.ok
    assert any("cost mode mismatch" in reason for reason in result.blocked_reasons)


def test_adapter_workload_runner_blocks_invalid_package_before_running(tmp_path):
    called = False
    _stage_workload(tmp_path, source_paths=[])

    def runner(
        _argv: Sequence[str],
        _cwd: Path,
        _env: Mapping[str, str],
        _timeout: int,
    ) -> AdapterProcessResult:
        nonlocal called
        called = True
        return AdapterProcessResult(exit_code=0)

    result = run_adapter_workload(
        AdapterWorkloadRunSpec(adapter="codex", argv=("codex", "exec"), scratch_root=tmp_path),
        environ={},
        runner=runner,
    )

    assert not result.ok
    assert result.adapter_result is None
    assert not called
    assert any("at least one source path" in reason for reason in result.blocked_reasons)


def _stage_workload(root: Path, **overrides) -> None:
    (root / "sources").mkdir(parents=True)
    (root / "schemas").mkdir(parents=True)
    (root / "prompt.md").write_text("prompt", encoding="utf-8")
    (root / "sources" / "input.md").write_text("source", encoding="utf-8")
    (root / "schemas" / "result.json").write_text("{}", encoding="utf-8")
    (root / "adapter-workload.json").write_text(
        json.dumps(_workload(**overrides)),
        encoding="utf-8",
    )

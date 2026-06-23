from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from distill.doctor.adapter_capture import (
    ClaudeCaptureWriteSpec,
    CodexCaptureWriteSpec,
    write_claude_captured_result,
    write_codex_captured_result,
)
from distill.doctor.adapter_native_usage import load_adapter_native_usage
from distill.doctor.adapter_runner import AdapterProcessResult
from distill.doctor.adapter_workload import AdapterWorkloadPackage
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
        _stdin: str,
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
        _stdin: str,
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


def test_adapter_workload_runner_accepts_capture_writer_manifest(tmp_path):
    _stage_workload(tmp_path)

    def runner(
        _argv: Sequence[str],
        cwd: Path,
        _env: Mapping[str, str],
        _timeout: int,
        _stdin: str,
    ) -> AdapterProcessResult:
        (cwd / "result.txt").write_text("captured result", encoding="utf-8")
        return AdapterProcessResult(
            exit_code=0,
            stdout=(
                '{"type":"turn.completed","usage":{"input_tokens":12,'
                '"cached_input_tokens":8,"output_tokens":4,'
                '"reasoning_output_tokens":1}}'
            ),
        )

    def capture_writer(
        process: AdapterProcessResult,
        scratch_root: Path,
        workload: AdapterWorkloadPackage,
    ) -> None:
        write_codex_captured_result(
            CodexCaptureWriteSpec(
                adapter_version="codex 0.140.0",
                auth_class="included-plan",
                scratch_root=scratch_root,
                workload=workload,
                stdout_jsonl=process.stdout,
                model="gpt-5.1-codex",
                elapsed_ms=250,
            )
        )

    result = run_adapter_workload(
        AdapterWorkloadRunSpec(
            adapter="codex",
            argv=("codex", "exec", "--json"),
            scratch_root=tmp_path,
            allowed_new_files=("native-usage.json", "result.txt"),
            capture_writer=capture_writer,
        ),
        environ={},
        runner=runner,
    )

    assert result.ok
    assert result.adapter_result is not None
    assert result.adapter_result.manifest is not None
    assert result.adapter_result.manifest.usage.input_tokens == 12
    assert result.adapter_result.manifest.usage.output_tokens == 4
    assert result.adapter_result.manifest.usage.native["cached_input_tokens"] == 8
    assert result.adapter_result.workspace_check is not None
    assert result.adapter_result.workspace_check.new_files == (
        "adapter-result.json",
        "native-usage.json",
        "result.txt",
    )


def test_adapter_workload_runner_accepts_claude_capture_writer_manifest(tmp_path):
    _stage_workload(tmp_path)

    def runner(
        _argv: Sequence[str],
        _cwd: Path,
        _env: Mapping[str, str],
        _timeout: int,
        _stdin: str,
    ) -> AdapterProcessResult:
        return AdapterProcessResult(
            exit_code=0,
            stdout=json.dumps(
                {
                    "type": "result",
                    "subtype": "success",
                    "duration_ms": 800,
                    "num_turns": 1,
                    "structured_output": {"summary": "ok"},
                    "stop_reason": "end_turn",
                    "session_id": "session_456",
                    "usage": {"input_tokens": 16, "output_tokens": 3},
                }
            ),
        )

    def capture_writer(
        process: AdapterProcessResult,
        scratch_root: Path,
        workload: AdapterWorkloadPackage,
    ) -> None:
        write_claude_captured_result(
            ClaudeCaptureWriteSpec(
                adapter_version="claude 2.1.173",
                auth_class="included-plan",
                scratch_root=scratch_root,
                workload=workload,
                stdout_json=process.stdout,
                model="claude-fable-5",
                elapsed_ms=800,
            )
        )

    result = run_adapter_workload(
        AdapterWorkloadRunSpec(
            adapter="claude",
            argv=("claude", "-p", "--output-format", "json"),
            scratch_root=tmp_path,
            allowed_new_files=("native-usage.json", "result.txt"),
            capture_writer=capture_writer,
        ),
        environ={},
        runner=runner,
    )

    assert result.ok
    assert result.adapter_result is not None
    assert result.adapter_result.manifest is not None
    assert result.adapter_result.manifest.adapter == "claude"
    assert result.adapter_result.manifest.output == {"summary": "ok"}
    assert result.adapter_result.manifest.usage.input_tokens == 16
    assert result.adapter_result.manifest.usage.output_tokens == 3
    assert result.adapter_result.workspace_check is not None
    assert result.adapter_result.workspace_check.new_files == (
        "adapter-result.json",
        "native-usage.json",
        "result.txt",
    )


def test_adapter_workload_runner_passes_staged_stdin(tmp_path):
    seen_stdin = ""
    _stage_workload(tmp_path)

    def runner(
        _argv: Sequence[str],
        cwd: Path,
        _env: Mapping[str, str],
        _timeout: int,
        stdin: str,
    ) -> AdapterProcessResult:
        nonlocal seen_stdin
        seen_stdin = stdin
        (cwd / "adapter-result.json").write_text(json.dumps(_manifest()), encoding="utf-8")
        return AdapterProcessResult(exit_code=0)

    result = run_adapter_workload(
        AdapterWorkloadRunSpec(
            adapter="codex",
            argv=("codex", "exec", "-"),
            scratch_root=tmp_path,
            stdin_path=Path("prompt.md"),
        ),
        environ={},
        runner=runner,
    )

    assert result.ok
    assert seen_stdin == "prompt"


def test_adapter_workload_runner_blocks_stdin_path_escape(tmp_path):
    called = False
    _stage_workload(tmp_path)

    def runner(
        _argv: Sequence[str],
        _cwd: Path,
        _env: Mapping[str, str],
        _timeout: int,
        _stdin: str,
    ) -> AdapterProcessResult:
        nonlocal called
        called = True
        return AdapterProcessResult(exit_code=0)

    result = run_adapter_workload(
        AdapterWorkloadRunSpec(
            adapter="codex",
            argv=("codex", "exec", "-"),
            scratch_root=tmp_path,
            stdin_path=Path("..") / "prompt.md",
        ),
        environ={},
        runner=runner,
    )

    assert not result.ok
    assert not called
    assert any(
        "adapter stdin path escapes scratch workspace" in reason
        for reason in result.blocked_reasons
    )


def test_adapter_workload_runner_blocks_capture_writer_failure(tmp_path):
    _stage_workload(tmp_path)

    def runner(
        _argv: Sequence[str],
        cwd: Path,
        _env: Mapping[str, str],
        _timeout: int,
        _stdin: str,
    ) -> AdapterProcessResult:
        (cwd / "result.txt").write_text("captured result", encoding="utf-8")
        return AdapterProcessResult(exit_code=0, stdout='{"type":"turn.started"}')

    def capture_writer(
        _process: AdapterProcessResult,
        _scratch_root: Path,
        _workload: AdapterWorkloadPackage,
    ) -> None:
        raise ValueError("native usage unavailable")

    result = run_adapter_workload(
        AdapterWorkloadRunSpec(
            adapter="codex",
            argv=("codex", "exec", "--json"),
            scratch_root=tmp_path,
            capture_writer=capture_writer,
        ),
        environ={},
        runner=runner,
    )

    assert not result.ok
    assert result.adapter_result is not None
    assert "adapter capture failed: native usage unavailable" in (
        result.adapter_result.blocked_reasons
    )
    assert "adapter manifest missing: adapter-result.json" in (
        result.adapter_result.blocked_reasons
    )


def test_adapter_workload_runner_blocks_undeclared_capture_file(tmp_path):
    _stage_workload(tmp_path)

    def runner(
        _argv: Sequence[str],
        cwd: Path,
        _env: Mapping[str, str],
        _timeout: int,
        _stdin: str,
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
        _stdin: str,
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
        _stdin: str,
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
        _stdin: str,
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
        _stdin: str,
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


def test_adapter_workload_runner_blocks_workload_path_escape(tmp_path):
    called = False

    def runner(
        _argv: Sequence[str],
        _cwd: Path,
        _env: Mapping[str, str],
        _timeout: int,
        _stdin: str,
    ) -> AdapterProcessResult:
        nonlocal called
        called = True
        return AdapterProcessResult(exit_code=0)

    result = run_adapter_workload(
        AdapterWorkloadRunSpec(
            adapter="codex",
            argv=("codex", "exec"),
            scratch_root=tmp_path,
            workload_path=Path("..") / "adapter-workload.json",
        ),
        environ={},
        runner=runner,
    )

    assert not result.ok
    assert result.adapter_result is None
    assert not called
    assert any(
        "adapter workload escapes scratch workspace" in reason for reason in result.blocked_reasons
    )


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


def test_adapter_workload_runner_uses_default_capture_for_grok(tmp_path):
    _stage_workload(tmp_path)

    def runner(
        _argv: Sequence[str],
        cwd: Path,
        _env: Mapping[str, str],
        _timeout: int,
        _stdin: str,
    ) -> AdapterProcessResult:
        (cwd / "adapter-result.json").write_text(
            json.dumps(_manifest(adapter="grok", model="grok-4.3")),
            encoding="utf-8",
        )
        (cwd / "result.txt").write_text(json.dumps({"summary": "ok"}), encoding="utf-8")
        return AdapterProcessResult(
            exit_code=0,
            stdout=json.dumps(
                {"model": "grok-4.3", "usage": {"input_tokens": 120, "output_tokens": 45}}
            ),
        )

    result = run_adapter_workload(
        AdapterWorkloadRunSpec(
            adapter="grok",
            argv=("grok", "run", "--json"),
            scratch_root=tmp_path,
            allowed_new_files=("native-usage.json", "result.txt"),
            # no capture_writer -> uses default from get_default_capture_writer
        ),
        environ={},
        runner=runner,
    )

    assert result.ok
    assert result.adapter_result is not None
    assert result.adapter_result.manifest is not None
    assert result.adapter_result.manifest.adapter == "grok"
    assert result.adapter_result.manifest.usage.input_tokens == 120
    assert result.adapter_result.manifest.usage.output_tokens == 45
    assert result.adapter_result.manifest.model == "grok-4.3"
    # default writer should have written native-usage.json
    usage = load_adapter_native_usage(Path("native-usage.json"), scratch_root=tmp_path)
    assert usage.adapter == "grok"


def test_adapter_workload_runner_uses_default_capture_for_gemini_cli(tmp_path):
    _stage_workload(tmp_path)

    def runner(
        _argv: Sequence[str],
        cwd: Path,
        _env: Mapping[str, str],
        _timeout: int,
        _stdin: str,
    ) -> AdapterProcessResult:
        (cwd / "adapter-result.json").write_text(
            json.dumps(_manifest(adapter="gemini-cli", model="gemini-2.5-pro")),
            encoding="utf-8",
        )
        (cwd / "result.txt").write_text(json.dumps({"summary": "ok"}), encoding="utf-8")
        return AdapterProcessResult(
            exit_code=0,
            stdout=json.dumps(
                {
                    "model": "gemini-2.5-pro",
                    "usageMetadata": {"promptTokenCount": 200, "candidatesTokenCount": 50},
                }
            ),
        )

    result = run_adapter_workload(
        AdapterWorkloadRunSpec(
            adapter="gemini-cli",
            argv=("gemini", "run", "--json"),
            scratch_root=tmp_path,
            allowed_new_files=("native-usage.json", "result.txt"),
            # no capture_writer -> uses default
        ),
        environ={},
        runner=runner,
    )

    assert result.ok
    assert result.adapter_result is not None
    assert result.adapter_result.manifest is not None
    assert result.adapter_result.manifest.adapter == "gemini-cli"
    assert result.adapter_result.manifest.usage.input_tokens == 200
    assert result.adapter_result.manifest.usage.output_tokens == 50
    assert result.adapter_result.manifest.model == "gemini-2.5-pro"
    usage = load_adapter_native_usage(Path("native-usage.json"), scratch_root=tmp_path)
    assert usage.adapter == "gemini-cli"


def test_adapter_workload_runner_uses_default_capture_for_antigravity(tmp_path):
    _stage_workload(tmp_path)

    def runner(
        _argv: Sequence[str],
        cwd: Path,
        _env: Mapping[str, str],
        _timeout: int,
        _stdin: str,
    ) -> AdapterProcessResult:
        (cwd / "adapter-result.json").write_text(
            json.dumps(_manifest(adapter="antigravity", model="antigravity-1")),
            encoding="utf-8",
        )
        (cwd / "result.txt").write_text(json.dumps({"summary": "ok"}), encoding="utf-8")
        return AdapterProcessResult(
            exit_code=0,
            stdout=json.dumps({"usage": {"input_tokens": 80, "output_tokens": 30}}),
        )

    result = run_adapter_workload(
        AdapterWorkloadRunSpec(
            adapter="antigravity",
            argv=("antigravity", "chat", "--mode", "ask", "-"),
            scratch_root=tmp_path,
            allowed_new_files=("native-usage.json", "result.txt"),
            # no capture_writer -> uses default
        ),
        environ={},
        runner=runner,
    )

    assert result.ok
    assert result.adapter_result is not None
    assert result.adapter_result.manifest is not None
    assert result.adapter_result.manifest.adapter == "antigravity"
    assert result.adapter_result.manifest.usage.input_tokens == 80
    assert result.adapter_result.manifest.usage.output_tokens == 30
    usage = load_adapter_native_usage(Path("native-usage.json"), scratch_root=tmp_path)
    assert usage.adapter == "antigravity"

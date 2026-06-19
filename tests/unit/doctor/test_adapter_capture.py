from __future__ import annotations

import json
from pathlib import Path

import pytest

from distill.doctor.adapter_capture import (
    CodexCaptureWriteSpec,
    StdoutCaptureWriteSpec,
    write_codex_captured_result,
    write_stdout_captured_result,
)
from distill.doctor.adapter_native_usage import (
    AdapterNativeUsageError,
    load_adapter_native_usage,
)
from distill.doctor.adapter_workload import AdapterWorkloadPackage


def _workload(**overrides) -> AdapterWorkloadPackage:
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
    return AdapterWorkloadPackage.model_validate(payload)


def test_write_codex_captured_result_writes_usage_and_manifest(tmp_path):
    _stage_inputs(tmp_path)

    manifest = write_codex_captured_result(
        CodexCaptureWriteSpec(
            adapter_version="codex 0.140.0",
            auth_class="included-plan",
            scratch_root=tmp_path,
            workload=_workload(),
            stdout_jsonl=(
                '{"type":"turn.completed","usage":{"input_tokens":12,'
                '"cached_input_tokens":8,"output_tokens":4,'
                '"reasoning_output_tokens":1}}'
            ),
            model="gpt-5.1-codex",
            elapsed_ms=250,
            citations=("https://example.test/source",),
            receipts=("sources/input.md",),
        )
    )

    usage_record = load_adapter_native_usage(Path("native-usage.json"), scratch_root=tmp_path)
    assert usage_record.adapter == "codex"
    assert usage_record.source == "stdout-json"
    assert manifest.output == "result text"
    assert manifest.usage.input_tokens == 12
    assert manifest.usage.output_tokens == 4
    assert manifest.usage.native["cached_input_tokens"] == 8
    assert manifest.usage.native["reasoning_output_tokens"] == 1
    assert manifest.files_read == ["prompt.md", "schemas/result.json", "sources/input.md"]
    assert (
        json.loads((tmp_path / "adapter-result.json").read_text(encoding="utf-8"))["adapter"]
        == "codex"
    )


def test_write_codex_captured_result_rejects_missing_usage(tmp_path):
    _stage_inputs(tmp_path)

    with pytest.raises(AdapterNativeUsageError, match="usage not found"):
        write_codex_captured_result(
            CodexCaptureWriteSpec(
                adapter_version="codex 0.140.0",
                auth_class="included-plan",
                scratch_root=tmp_path,
                workload=_workload(),
                stdout_jsonl='{"type":"turn.started"}',
            )
        )


def test_write_codex_captured_result_rejects_usage_path_escape(tmp_path):
    _stage_inputs(tmp_path)

    with pytest.raises(ValueError, match="escapes scratch workspace"):
        write_codex_captured_result(
            CodexCaptureWriteSpec(
                adapter_version="codex 0.140.0",
                auth_class="included-plan",
                scratch_root=tmp_path,
                workload=_workload(),
                stdout_jsonl=(
                    '{"type":"turn.completed","usage":{"input_tokens":1,"output_tokens":1}}'
                ),
                native_usage_path=Path("..") / "native-usage.json",
            )
        )


def test_write_stdout_captured_result_writes_result_and_manifest(tmp_path):
    _stage_inputs(tmp_path)
    _stage_native_usage(tmp_path, adapter="grok")

    manifest = write_stdout_captured_result(
        StdoutCaptureWriteSpec(
            adapter="grok",
            adapter_version="grok 0.2.50",
            auth_class="included-plan",
            scratch_root=tmp_path,
            workload=_workload(),
            stdout_text="captured stdout result",
            native_usage_path=Path("native-usage.json"),
            model="grok-build",
            elapsed_ms=300,
        )
    )

    assert (tmp_path / "result.txt").read_text(encoding="utf-8") == "captured stdout result"
    assert manifest.adapter == "grok"
    assert manifest.output == "captured stdout result"
    assert manifest.usage.input_tokens == 14
    assert manifest.usage.output_tokens == 6
    assert manifest.usage.native["event_count"] == 1


def test_write_stdout_captured_result_rejects_usage_adapter_mismatch(tmp_path):
    _stage_inputs(tmp_path)
    _stage_native_usage(tmp_path, adapter="codex")

    with pytest.raises(ValueError, match="adapter native usage adapter mismatch"):
        write_stdout_captured_result(
            StdoutCaptureWriteSpec(
                adapter="grok",
                adapter_version="grok 0.2.50",
                auth_class="included-plan",
                scratch_root=tmp_path,
                workload=_workload(),
                stdout_text="captured stdout result",
                native_usage_path=Path("native-usage.json"),
            )
        )


def test_write_stdout_captured_result_rejects_result_path_escape(tmp_path):
    _stage_inputs(tmp_path)
    _stage_native_usage(tmp_path, adapter="grok")

    with pytest.raises(ValueError, match="escapes scratch workspace"):
        write_stdout_captured_result(
            StdoutCaptureWriteSpec(
                adapter="grok",
                adapter_version="grok 0.2.50",
                auth_class="included-plan",
                scratch_root=tmp_path,
                workload=_workload(),
                stdout_text="captured stdout result",
                result_text_path=Path("..") / "result.txt",
            )
        )


def _stage_inputs(root: Path) -> None:
    (root / "sources").mkdir()
    (root / "schemas").mkdir()
    (root / "prompt.md").write_text("prompt", encoding="utf-8")
    (root / "sources" / "input.md").write_text("source", encoding="utf-8")
    (root / "schemas" / "result.json").write_text("{}", encoding="utf-8")
    (root / "result.txt").write_text("result text", encoding="utf-8")


def _stage_native_usage(root: Path, *, adapter: str) -> None:
    (root / "native-usage.json").write_text(
        json.dumps(
            {
                "schema_version": "adapter-native-usage.v1",
                "adapter": adapter,
                "source": "stdout-json",
                "usage": {
                    "input_tokens": 14,
                    "output_tokens": 6,
                    "native": {"event_count": 1},
                },
            }
        ),
        encoding="utf-8",
    )

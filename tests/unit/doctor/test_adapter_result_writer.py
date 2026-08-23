from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from distill.doctor import adapter_result_writer as adapter_result_writer_module
from distill.doctor.adapter_manifest import (
    AdapterQuotaStop,
    AdapterUsage,
    load_adapter_result_manifest,
)
from distill.doctor.adapter_result_writer import (
    AdapterResultWriteSpec,
    write_adapter_result_manifest,
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


def test_adapter_result_writer_writes_valid_manifest(tmp_path):
    _stage_inputs(tmp_path)

    manifest = write_adapter_result_manifest(
        AdapterResultWriteSpec(
            adapter="codex",
            adapter_version="codex 0.140.0",
            auth_class="included-plan",
            scratch_root=tmp_path,
            workload=_workload(),
            model="gpt-5.1-codex",
            elapsed_ms=100,
            usage=AdapterUsage(input_tokens=10, output_tokens=5, native={"event_count": 1}),
            citations=("https://example.test/source",),
            receipts=("sources/input.md",),
        )
    )

    assert manifest.schema_version == "adapter-result.v1"
    assert manifest.output == "result text"
    assert manifest.prompt_hash.startswith("sha256:")
    assert manifest.source_hash.startswith("sha256:")
    assert manifest.files_read == ["prompt.md", "schemas/result.json", "sources/input.md"]
    loaded = load_adapter_result_manifest(tmp_path / "adapter-result.json", scratch_root=tmp_path)
    assert loaded.to_dict() == manifest.to_dict()


def test_adapter_result_writer_uses_native_usage_signal(tmp_path):
    _stage_inputs(tmp_path)

    manifest = write_adapter_result_manifest(
        AdapterResultWriteSpec(
            adapter="codex",
            adapter_version="codex 0.140.0",
            auth_class="included-plan",
            scratch_root=tmp_path,
            workload=_workload(),
            native={"event_count": 1},
        )
    )

    assert manifest.usage.input_tokens is None
    assert manifest.usage.output_tokens is None
    assert manifest.usage.native == {"event_count": 1}


def test_adapter_result_writer_loads_native_usage_path(tmp_path):
    _stage_inputs(tmp_path)
    (tmp_path / "native-usage.json").write_text(
        json.dumps(
            {
                "schema_version": "adapter-native-usage.v1",
                "adapter": "codex",
                "source": "usage-file",
                "usage": {
                    "input_tokens": 12,
                    "output_tokens": 7,
                    "native": {"event_count": 2},
                },
                "model": "gpt-5.1-codex",
                "request_id": "run_123",
            }
        ),
        encoding="utf-8",
    )

    manifest = write_adapter_result_manifest(
        AdapterResultWriteSpec(
            adapter="codex",
            adapter_version="codex 0.140.0",
            auth_class="included-plan",
            scratch_root=tmp_path,
            workload=_workload(),
            native_usage_path=Path("native-usage.json"),
        )
    )

    assert manifest.usage.input_tokens == 12
    assert manifest.usage.output_tokens == 7
    assert manifest.usage.native["event_count"] == 2
    assert manifest.usage.native["distill_usage_signal"]["source"] == "usage-file"


def test_adapter_result_writer_rejects_missing_usage_signal(tmp_path):
    _stage_inputs(tmp_path)

    with pytest.raises(ValidationError, match="usage must include"):
        write_adapter_result_manifest(
            AdapterResultWriteSpec(
                adapter="codex",
                adapter_version="codex 0.140.0",
                auth_class="included-plan",
                scratch_root=tmp_path,
                workload=_workload(),
            )
        )


def test_adapter_result_writer_rejects_no_metered_metered_route_blockers(tmp_path):
    _stage_inputs(tmp_path)

    with pytest.raises(ValidationError, match="metered route blockers"):
        write_adapter_result_manifest(
            AdapterResultWriteSpec(
                adapter="codex",
                adapter_version="codex 0.140.0",
                auth_class="included-plan",
                scratch_root=tmp_path,
                workload=_workload(),
                blocked_metered_routes=("ai-credit-overage",),
                native={"event_count": 1},
            )
        )


def test_adapter_result_writer_rejects_result_path_escape(tmp_path):
    _stage_inputs(tmp_path)

    with pytest.raises(ValueError, match="escapes scratch workspace"):
        write_adapter_result_manifest(
            AdapterResultWriteSpec(
                adapter="codex",
                adapter_version="codex 0.140.0",
                auth_class="included-plan",
                scratch_root=tmp_path,
                workload=_workload(),
                result_text_path=Path("..") / "result.txt",
                native={"event_count": 1},
            )
        )


def test_adapter_result_writer_records_quota_stop(tmp_path):
    _stage_inputs(tmp_path)

    manifest = write_adapter_result_manifest(
        AdapterResultWriteSpec(
            adapter="codex",
            adapter_version="codex 0.140.0",
            auth_class="included-plan",
            scratch_root=tmp_path,
            workload=_workload(),
            stop_reason="rate-limit",
            quota_stop=AdapterQuotaStop(
                reached=True,
                reason="daily plan quota exhausted",
                retry_after_seconds=3600,
                provider_code="rate_limit",
                native={"remaining_requests": 0},
            ),
            native={"event_count": 1},
        )
    )

    assert manifest.quota_stop is not None
    assert manifest.quota_stop.reached is True
    assert (
        json.loads((tmp_path / "adapter-result.json").read_text(encoding="utf-8"))["quota_stop"][
            "retry_after_seconds"
        ]
        == 3600
    )


def test_adapter_result_writer_enforces_workload_output_limit(tmp_path):
    _stage_inputs(tmp_path)

    with pytest.raises(ValueError, match="5-character output limit"):
        write_adapter_result_manifest(
            AdapterResultWriteSpec(
                adapter="codex",
                adapter_version="codex 0.140.0",
                auth_class="included-plan",
                scratch_root=tmp_path,
                workload=_workload(output_limit=5),
                native={"event_count": 1},
            )
        )


def test_adapter_result_writer_rejects_linked_result_without_touching_target(tmp_path):
    _stage_inputs(tmp_path)
    target = tmp_path / "target.txt"
    target.write_text("outside result", encoding="utf-8")
    result_path = tmp_path / "result.txt"
    result_path.unlink()
    try:
        result_path.symlink_to(target)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")

    with pytest.raises(ValueError, match="linked component"):
        write_adapter_result_manifest(
            AdapterResultWriteSpec(
                adapter="codex",
                adapter_version="codex 0.140.0",
                auth_class="included-plan",
                scratch_root=tmp_path,
                workload=_workload(),
                native={"event_count": 1},
            )
        )

    assert target.read_text(encoding="utf-8") == "outside result"


def test_adapter_result_writer_rejects_linked_manifest_without_touching_target(tmp_path):
    _stage_inputs(tmp_path)
    target = tmp_path / "target.json"
    target.write_text('{"preserved": true}', encoding="utf-8")
    manifest_path = tmp_path / "linked-manifest.json"
    try:
        manifest_path.symlink_to(target)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")

    with pytest.raises(ValueError, match="linked component"):
        write_adapter_result_manifest(
            AdapterResultWriteSpec(
                adapter="codex",
                adapter_version="codex 0.140.0",
                auth_class="included-plan",
                scratch_root=tmp_path,
                workload=_workload(result_manifest_path="linked-manifest.json"),
                native={"event_count": 1},
            )
        )

    assert target.read_text(encoding="utf-8") == '{"preserved": true}'


def test_adapter_result_writer_rejects_missing_prompt_or_source(tmp_path):
    _stage_inputs(tmp_path)
    (tmp_path / "prompt.md").unlink()

    with pytest.raises(ValueError, match="adapter input must be a confined"):
        write_adapter_result_manifest(
            AdapterResultWriteSpec(
                adapter="codex",
                adapter_version="codex 0.140.0",
                auth_class="included-plan",
                scratch_root=tmp_path,
                workload=_workload(),
                native={"event_count": 1},
            )
        )

    (tmp_path / "prompt.md").write_text("prompt", encoding="utf-8")
    (tmp_path / "sources" / "input.md").unlink()
    with pytest.raises(ValueError, match="adapter source must be a confined"):
        write_adapter_result_manifest(
            AdapterResultWriteSpec(
                adapter="codex",
                adapter_version="codex 0.140.0",
                auth_class="included-plan",
                scratch_root=tmp_path,
                workload=_workload(),
                native={"event_count": 1},
            )
        )


def test_adapter_result_writer_enforces_source_aggregate_limit(tmp_path, monkeypatch):
    _stage_inputs(tmp_path)
    monkeypatch.setattr(adapter_result_writer_module, "_ADAPTER_INPUT_TOTAL_MAX_BYTES", 1)

    with pytest.raises(ValueError, match="1-byte aggregate limit"):
        write_adapter_result_manifest(
            AdapterResultWriteSpec(
                adapter="codex",
                adapter_version="codex 0.140.0",
                auth_class="included-plan",
                scratch_root=tmp_path,
                workload=_workload(),
                native={"event_count": 1},
            )
        )


def test_adapter_result_writer_rejects_invalid_result_encoding(tmp_path):
    _stage_inputs(tmp_path)
    (tmp_path / "result.txt").write_bytes(b"\xff")

    with pytest.raises(ValueError, match="adapter result must be a confined"):
        write_adapter_result_manifest(
            AdapterResultWriteSpec(
                adapter="codex",
                adapter_version="codex 0.140.0",
                auth_class="included-plan",
                scratch_root=tmp_path,
                workload=_workload(),
                native={"event_count": 1},
            )
        )


def test_adapter_result_writer_enforces_manifest_byte_limit(tmp_path, monkeypatch):
    _stage_inputs(tmp_path)
    monkeypatch.setattr(adapter_result_writer_module, "_ADAPTER_MANIFEST_MAX_BYTES", 1)

    with pytest.raises(ValueError, match="adapter manifest exceeds the 1-byte limit"):
        write_adapter_result_manifest(
            AdapterResultWriteSpec(
                adapter="codex",
                adapter_version="codex 0.140.0",
                auth_class="included-plan",
                scratch_root=tmp_path,
                workload=_workload(),
                native={"event_count": 1},
            )
        )


def _stage_inputs(root: Path) -> None:
    (root / "sources").mkdir()
    (root / "schemas").mkdir()
    (root / "prompt.md").write_text("prompt", encoding="utf-8")
    (root / "sources" / "input.md").write_text("source", encoding="utf-8")
    (root / "schemas" / "result.json").write_text("{}", encoding="utf-8")
    (root / "result.txt").write_text("result text", encoding="utf-8")

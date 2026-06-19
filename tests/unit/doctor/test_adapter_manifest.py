from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from distill.doctor.adapter_manifest import (
    ADAPTER_RESULT_SCHEMA_VERSION,
    AdapterManifestError,
    adapter_result_manifest_contract,
    check_adapter_workspace_writes,
    load_adapter_result_manifest,
    snapshot_scratch_files,
    validate_adapter_result_manifest,
)


def _manifest(**overrides):
    payload = {
        "schema_version": ADAPTER_RESULT_SCHEMA_VERSION,
        "adapter": "codex",
        "adapter_version": "codex 0.140.0",
        "auth_class": "included-plan",
        "command_class": "scratch-write",
        "model": "gpt-5.1-codex",
        "prompt_hash": "sha256:prompt",
        "source_hash": "sha256:source",
        "elapsed_ms": 1234,
        "usage": {
            "input_tokens": 100,
            "output_tokens": 25,
            "native": {"event_count": 3},
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


def test_adapter_manifest_accepts_valid_no_metered_result(tmp_path):
    manifest = validate_adapter_result_manifest(_manifest(), scratch_root=tmp_path)

    assert manifest.schema_version == "adapter-result.v1"
    assert manifest.auth_class == "included-plan"
    assert manifest.resolve_written_paths(tmp_path) == (tmp_path.resolve() / "result.json",)


def test_adapter_manifest_loads_json_and_reports_contract(tmp_path):
    manifest_path = tmp_path / "adapter-result.json"
    manifest_path.write_text(json.dumps(_manifest()), encoding="utf-8")

    manifest = load_adapter_result_manifest(manifest_path, scratch_root=tmp_path)
    contract = adapter_result_manifest_contract()

    assert manifest.adapter == "codex"
    assert contract["schema_version"] == "adapter-result.v1"
    assert "usage" in contract["required_fields"]
    assert "quota_stop" in contract["optional_fields"]
    assert "files_written" in contract["path_fields"]


def test_adapter_manifest_requires_usage_signal():
    payload = _manifest(
        usage={
            "input_tokens": None,
            "output_tokens": None,
            "native": {},
        }
    )

    with pytest.raises(ValidationError, match="usage must include"):
        validate_adapter_result_manifest(payload)


def test_adapter_manifest_rejects_read_only_writes():
    payload = _manifest(command_class="read-only", files_written=["result.json"])

    with pytest.raises(ValidationError, match="read-only manifests cannot record"):
        validate_adapter_result_manifest(payload)


def test_adapter_manifest_accepts_quota_stop_metadata():
    manifest = validate_adapter_result_manifest(
        _manifest(
            stop_reason="rate_limit",
            quota_stop={
                "reached": True,
                "reason": "daily plan quota exhausted",
                "retry_after_seconds": 3600,
                "provider_code": "rate_limit",
                "native": {"remaining_requests": 0},
            },
        )
    )

    assert manifest.quota_stop is not None
    assert manifest.quota_stop.reached is True
    assert manifest.quota_stop.retry_after_seconds == 3600
    assert manifest.to_dict()["quota_stop"]["native"] == {"remaining_requests": 0}


def test_adapter_manifest_requires_quota_stop_for_quota_reason():
    with pytest.raises(ValidationError, match="quota or rate-limit stop_reason requires"):
        validate_adapter_result_manifest(_manifest(stop_reason="quota"))


def test_adapter_manifest_rejects_mismatched_quota_stop():
    payload = _manifest(
        quota_stop={
            "reached": True,
            "reason": "daily plan quota exhausted",
            "retry_after_seconds": None,
            "provider_code": "",
            "native": {},
        }
    )

    with pytest.raises(ValidationError, match=r"quota_stop\.reached requires"):
        validate_adapter_result_manifest(payload)


def test_adapter_manifest_rejects_negative_retry_after():
    payload = _manifest(
        stop_reason="rate-limit",
        quota_stop={
            "reached": True,
            "reason": "daily plan quota exhausted",
            "retry_after_seconds": -1,
            "provider_code": "rate_limit",
            "native": {},
        },
    )

    with pytest.raises(ValidationError, match="retry_after_seconds must be non-negative"):
        validate_adapter_result_manifest(payload)


@pytest.mark.parametrize(
    "override",
    [
        {"auth_class": "metered-api"},
        {
            "policy": {
                "cost_mode": "no-metered",
                "blocked_api_key_env": ["OPENAI_API_KEY"],
                "metered_allowed": False,
            }
        },
        {
            "policy": {
                "cost_mode": "no-metered",
                "blocked_api_key_env": [],
                "metered_allowed": True,
            }
        },
    ],
)
def test_adapter_manifest_fails_closed_for_no_metered_policy(override):
    with pytest.raises(ValidationError):
        validate_adapter_result_manifest(_manifest(**override))


@pytest.mark.parametrize(
    "bad_path",
    [
        "../library/result.json",
        "/tmp/result.json",
        "C:/Users/nicks/result.json",
        "./result.json",
        "result/../secret.json",
    ],
)
def test_adapter_manifest_rejects_unsafe_written_paths(bad_path):
    with pytest.raises(ValidationError):
        validate_adapter_result_manifest(_manifest(files_written=[bad_path]))


def test_adapter_manifest_rejects_non_mapping_file(tmp_path):
    manifest_path = tmp_path / "adapter-result.yaml"
    manifest_path.write_text("- not\n- a\n- mapping\n", encoding="utf-8")

    with pytest.raises(AdapterManifestError, match="must be a mapping"):
        load_adapter_result_manifest(manifest_path)


def test_workspace_write_check_accepts_declared_adapter_outputs(tmp_path):
    source_dir = tmp_path / "sources"
    source_dir.mkdir()
    (source_dir / "input.md").write_text("source", encoding="utf-8")
    before = snapshot_scratch_files(tmp_path)
    (tmp_path / "result.json").write_text("{}", encoding="utf-8")
    (tmp_path / "adapter-result.json").write_text("{}", encoding="utf-8")
    manifest = validate_adapter_result_manifest(_manifest(), scratch_root=tmp_path)

    check = check_adapter_workspace_writes(
        manifest,
        tmp_path,
        before_files=before,
        allowed_new_files=("adapter-result.json",),
    )

    assert check.ok
    assert check.missing_files == ()
    assert check.unexpected_files == ()
    assert check.to_dict()["new_files"] == ["adapter-result.json", "result.json"]


def test_workspace_write_check_reports_missing_and_unexpected_files(tmp_path):
    (tmp_path / "extra.txt").write_text("unexpected", encoding="utf-8")
    manifest = validate_adapter_result_manifest(_manifest(), scratch_root=tmp_path)

    check = check_adapter_workspace_writes(manifest, tmp_path)

    assert not check.ok
    assert check.missing_files == ("result.json",)
    assert check.unexpected_files == ("extra.txt",)

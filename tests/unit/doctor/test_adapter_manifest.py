from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from distill.doctor import adapter_manifest as adapter_manifest_module
from distill.doctor.adapter_manifest import (
    ADAPTER_RESULT_SCHEMA_VERSION,
    AdapterManifestError,
    adapter_result_manifest_contract,
    check_adapter_workspace_writes,
    load_adapter_result_manifest,
    snapshot_scratch_files,
    snapshot_scratch_state,
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
    assert "blocked_metered_routes" in contract["policy_fields"]
    assert contract["workspace_write_check"]["flags_undeclared_modifications"] is True
    assert contract["workspace_write_check"]["flags_removed_files"] is True
    assert contract["workspace_write_check"]["rejects_links_and_special_files"] is True


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
                "blocked_metered_routes": [],
                "metered_allowed": True,
            }
        },
        {
            "policy": {
                "cost_mode": "no-metered",
                "blocked_api_key_env": [],
                "blocked_metered_routes": ["ai-credit-overage"],
                "metered_allowed": False,
            }
        },
    ],
)
def test_adapter_manifest_fails_closed_for_no_metered_policy(override):
    with pytest.raises(ValidationError):
        validate_adapter_result_manifest(_manifest(**override))


@pytest.mark.parametrize(
    "marker",
    ["", "ai credit overage", "https://gateway.example/route"],
)
def test_adapter_manifest_rejects_unsafe_metered_route_markers(marker):
    payload = _manifest(
        policy={
            "cost_mode": "paid-ok",
            "blocked_api_key_env": [],
            "blocked_metered_routes": [marker],
            "metered_allowed": True,
        }
    )

    with pytest.raises(ValidationError, match="metered route marker"):
        validate_adapter_result_manifest(payload)


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


def test_adapter_manifest_rejects_oversized_file_before_parse(tmp_path, monkeypatch):
    manifest_path = tmp_path / "adapter-result.json"
    manifest_path.write_bytes(b"x" * 5)
    monkeypatch.setattr(adapter_manifest_module, "_ADAPTER_MANIFEST_MAX_BYTES", 4)

    with pytest.raises(AdapterManifestError, match="no larger than 4 bytes"):
        load_adapter_result_manifest(manifest_path, scratch_root=tmp_path)


def test_adapter_manifest_rejects_symlink_without_reading_target(tmp_path):
    outside = tmp_path.parent / f"{tmp_path.name}-manifest.json"
    outside.write_text(json.dumps(_manifest()), encoding="utf-8")
    manifest_path = tmp_path / "adapter-result.json"
    try:
        manifest_path.symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")

    with pytest.raises(AdapterManifestError, match="confined private regular"):
        load_adapter_result_manifest(manifest_path, scratch_root=tmp_path)


def test_adapter_manifest_wraps_malformed_yaml_and_rejects_nonfinite_json(tmp_path):
    manifest_path = tmp_path / "adapter-result.yaml"
    manifest_path.write_text("value: [", encoding="utf-8")
    with pytest.raises(AdapterManifestError, match="invalid structured data"):
        load_adapter_result_manifest(manifest_path)

    manifest_path = tmp_path / "adapter-result.json"
    manifest_path.write_text('{"elapsed_ms": NaN}', encoding="utf-8")
    with pytest.raises(AdapterManifestError, match="invalid structured data"):
        load_adapter_result_manifest(manifest_path)


def test_scratch_snapshot_accepts_binary_and_tracks_exact_revision(tmp_path):
    binary = tmp_path / "result.bin"
    binary.write_bytes(b"\x00\xff")

    before = snapshot_scratch_state(tmp_path)
    binary.write_bytes(b"\x00\xfe")
    after = snapshot_scratch_state(tmp_path)

    assert before["result.bin"].size == 2
    assert before["result.bin"].sha256 != after["result.bin"].sha256


def test_scratch_snapshot_accepts_missing_workspace(tmp_path):
    assert snapshot_scratch_state(tmp_path / "missing") == {}


def test_scratch_snapshot_rejects_non_directory_root(tmp_path):
    scratch_file = tmp_path / "scratch.txt"
    scratch_file.write_text("not a directory", encoding="utf-8")

    with pytest.raises(AdapterManifestError, match="must be a regular directory"):
        snapshot_scratch_state(scratch_file)


def test_scratch_snapshot_enforces_entry_and_aggregate_limits(tmp_path, monkeypatch):
    scratch_file = tmp_path / "result.bin"
    scratch_file.write_bytes(b"ab")
    monkeypatch.setattr(adapter_manifest_module, "_SCRATCH_MAX_ENTRIES", 0)

    with pytest.raises(AdapterManifestError, match="0-entry limit"):
        snapshot_scratch_state(tmp_path)

    monkeypatch.setattr(adapter_manifest_module, "_SCRATCH_MAX_ENTRIES", 10)
    monkeypatch.setattr(adapter_manifest_module, "_SCRATCH_TOTAL_MAX_BYTES", 1)
    with pytest.raises(AdapterManifestError, match="1-byte aggregate limit"):
        snapshot_scratch_state(tmp_path)


def test_scratch_snapshot_enforces_per_file_limit(tmp_path, monkeypatch):
    (tmp_path / "result.bin").write_bytes(b"ab")
    monkeypatch.setattr(adapter_manifest_module, "_SCRATCH_FILE_MAX_BYTES", 1)

    with pytest.raises(AdapterManifestError, match="1-byte limit"):
        snapshot_scratch_state(tmp_path)


def test_scratch_snapshot_rejects_hard_linked_file(tmp_path):
    source = tmp_path / "source.bin"
    source.write_bytes(b"content")
    linked = tmp_path / "linked.bin"
    try:
        linked.hardlink_to(source)
    except OSError as exc:
        pytest.skip(f"hard links unavailable: {exc}")

    with pytest.raises(AdapterManifestError, match="non-private regular file"):
        snapshot_scratch_state(tmp_path)


def test_scratch_snapshot_rejects_unstable_confined_read(tmp_path, monkeypatch):
    (tmp_path / "result.bin").write_bytes(b"content")
    monkeypatch.setattr(adapter_manifest_module, "read_confined_bytes", lambda *_a, **_kw: None)

    with pytest.raises(AdapterManifestError, match="not a stable private regular file"):
        snapshot_scratch_state(tmp_path)


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

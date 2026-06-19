from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from distill.doctor.adapter_native_usage import (
    AdapterNativeUsageError,
    adapter_native_usage_contract,
    load_adapter_native_usage,
    validate_adapter_native_usage,
)


def _usage_payload(**overrides):
    payload = {
        "schema_version": "adapter-native-usage.v1",
        "adapter": "codex",
        "source": "usage-file",
        "usage": {
            "input_tokens": 10,
            "output_tokens": 5,
            "native": {"event_count": 1},
        },
        "model": "gpt-5.1-codex",
        "request_id": "run_123",
        "stop_reason": "complete",
        "metadata": {"events": 3},
    }
    payload.update(overrides)
    return payload


def test_adapter_native_usage_contract_is_versioned():
    contract = adapter_native_usage_contract()

    assert contract["schema_version"] == "adapter-native-usage.v1"
    assert "usage" in contract["required_fields"]
    assert contract["requires_signal"] is True


def test_load_adapter_native_usage_from_scratch(tmp_path):
    path = tmp_path / "native-usage.json"
    path.write_text(json.dumps(_usage_payload()), encoding="utf-8")

    record = load_adapter_native_usage(path.relative_to(tmp_path), scratch_root=tmp_path)
    usage = record.to_adapter_usage()

    assert record.adapter == "codex"
    assert usage.input_tokens == 10
    assert usage.output_tokens == 5
    assert usage.native["event_count"] == 1
    assert usage.native["distill_usage_signal"] == {
        "schema_version": "adapter-native-usage.v1",
        "source": "usage-file",
        "model": "gpt-5.1-codex",
        "request_id": "run_123",
        "stop_reason": "complete",
        "metadata": {"events": 3},
    }


def test_adapter_native_usage_accepts_metadata_only_signal():
    record = validate_adapter_native_usage(
        _usage_payload(
            usage={
                "input_tokens": None,
                "output_tokens": None,
                "native": {"request_count": 1},
            }
        )
    )

    assert record.to_adapter_usage().native["request_count"] == 1


def test_adapter_native_usage_rejects_missing_signal():
    with pytest.raises(ValidationError, match="native usage must include"):
        validate_adapter_native_usage(
            _usage_payload(
                usage={
                    "input_tokens": None,
                    "output_tokens": None,
                    "native": {},
                }
            )
        )


def test_adapter_native_usage_rejects_unknown_adapter():
    with pytest.raises(ValidationError, match="unknown adapter"):
        validate_adapter_native_usage(_usage_payload(adapter="unknown"))


def test_load_adapter_native_usage_rejects_path_escape(tmp_path):
    with pytest.raises(AdapterNativeUsageError, match="escapes scratch workspace"):
        load_adapter_native_usage(Path("..") / "native-usage.json", scratch_root=tmp_path)

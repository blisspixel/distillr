from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from distill.doctor.adapter_workload import (
    ADAPTER_WORKLOAD_SCHEMA_VERSION,
    AdapterWorkloadError,
    adapter_workload_contract,
    load_adapter_workload_package,
    validate_adapter_workload_package,
)


def _workload(**overrides):
    payload = {
        "schema_version": ADAPTER_WORKLOAD_SCHEMA_VERSION,
        "workload": "profile-enrichment",
        "command_class": "read-only",
        "prompt_path": "prompt.md",
        "source_paths": ["sources/input.md"],
        "output_schema_path": "schemas/profile.json",
        "result_manifest_path": "adapter-result.json",
        "allowed_write_paths": [],
        "cost_mode": "no-metered",
        "max_seconds": 120,
        "output_limit": 4000,
        "metadata": {"profile": "ai-developer-news"},
    }
    payload.update(overrides)
    return payload


def test_adapter_workload_accepts_valid_read_only_package():
    package = validate_adapter_workload_package(_workload(prompt_path="prompts\\profile.md"))

    assert package.schema_version == "adapter-workload.v1"
    assert package.workload == "profile-enrichment"
    assert package.prompt_path == "prompts/profile.md"
    assert package.source_paths == ["sources/input.md"]
    assert package.to_dict()["metadata"]["profile"] == "ai-developer-news"


def test_adapter_workload_contract_reports_path_fields():
    contract = adapter_workload_contract()

    assert contract["schema_version"] == "adapter-workload.v1"
    assert "profile-enrichment" in contract["workloads"]
    assert "source_paths" in contract["path_fields"]
    assert contract["paths_are_scratch_relative"] is True


@pytest.mark.parametrize(
    "override",
    [
        {"prompt_path": "../prompt.md"},
        {"source_paths": ["/tmp/input.md"]},
        {"output_schema_path": "schemas/../profile.json"},
        {"result_manifest_path": "C:/tmp/adapter-result.json"},
        {"allowed_write_paths": ["./result.json"], "command_class": "scratch-write"},
    ],
)
def test_adapter_workload_rejects_unsafe_paths(override):
    with pytest.raises(ValidationError):
        validate_adapter_workload_package(_workload(**override))


def test_adapter_workload_requires_sources():
    with pytest.raises(ValidationError, match="at least one source path"):
        validate_adapter_workload_package(_workload(source_paths=[]))


def test_adapter_workload_rejects_read_only_write_paths():
    with pytest.raises(ValidationError, match="read-only adapter workloads"):
        validate_adapter_workload_package(_workload(allowed_write_paths=["result.json"]))


def test_adapter_workload_loads_json(tmp_path):
    path = tmp_path / "workload.json"
    path.write_text(json.dumps(_workload()), encoding="utf-8")

    package = load_adapter_workload_package(path)

    assert package.result_manifest_path == "adapter-result.json"


def test_adapter_workload_rejects_non_mapping_yaml(tmp_path):
    path = tmp_path / "workload.yaml"
    path.write_text("- not\n- mapping\n", encoding="utf-8")

    with pytest.raises(AdapterWorkloadError, match="must be a mapping"):
        load_adapter_workload_package(path)


def test_adapter_workload_requires_positive_limits():
    with pytest.raises(ValidationError, match="limits must be positive"):
        validate_adapter_workload_package(_workload(max_seconds=0))

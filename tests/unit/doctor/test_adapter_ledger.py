from __future__ import annotations

import json

from distill.doctor.adapter_ledger import (
    adapter_manifest_ledger_record,
    adapter_manifest_token_usage,
)
from distill.doctor.adapter_manifest import (
    ADAPTER_RESULT_SCHEMA_VERSION,
    validate_adapter_result_manifest,
)
from distill.pipeline.costs import CostTracker, save_run_log


def _manifest(**overrides):
    payload = {
        "schema_version": ADAPTER_RESULT_SCHEMA_VERSION,
        "adapter": "codex",
        "adapter_version": "codex 0.140.0",
        "auth_class": "included-plan",
        "command_class": "read-only",
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


def test_adapter_manifest_token_usage_marks_included_plan_no_metered():
    manifest = validate_adapter_result_manifest(_manifest())

    usage = adapter_manifest_token_usage(manifest, call_type="profile_enrichment")

    assert usage.prompt_tokens == 100
    assert usage.completion_tokens == 25
    assert usage.model == "gpt-5.1-codex"
    assert usage.call_type == "profile_enrichment"
    assert usage.provider_name == "codex"
    assert usage.provider_type == "included-plan"
    assert usage.no_metered_cost is True


def test_adapter_manifest_ledger_record_writes_zero_dollar_run_log(tmp_path):
    manifest = validate_adapter_result_manifest(_manifest())
    record = adapter_manifest_ledger_record(manifest)
    tracker = CostTracker()
    tracker.record(record.token_usage)

    save_run_log(tmp_path, "adapter-run", tracker, metadata=record.metadata)

    entry = json.loads(
        (tmp_path / ".distill" / "cost_log.jsonl").read_text(encoding="utf-8").strip()
    )
    assert entry["actual_cost"] == 0.0
    assert entry["usage_ledger"]["no_metered_llm_calls"] == 1
    assert entry["usage_ledger"]["metered_llm_calls"] == 0
    assert entry["by_provider"]["codex"]["no_metered_cost"] is True
    assert entry["by_route_class"]["included-plan"]["calls"] == 1
    assert entry["metadata"]["adapter_manifest"]["auth_class"] == "included-plan"


def test_adapter_manifest_ledger_record_preserves_quota_stop_metadata():
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

    record = adapter_manifest_ledger_record(manifest)

    quota_stop = record.metadata["adapter_manifest"]["quota_stop"]
    assert quota_stop["reached"] is True
    assert quota_stop["reason"] == "daily plan quota exhausted"
    assert quota_stop["retry_after_seconds"] == 3600


def test_adapter_manifest_ledger_record_supports_new_plan_quota_adapters():
    # Grok as example of completed non-Codex wiring
    manifest = validate_adapter_result_manifest(
        _manifest(
            adapter="grok",
            adapter_version="grok 0.2.50",
            model="grok-4.3",
            usage={
                "input_tokens": 150,
                "output_tokens": 40,
                "native": {"adapter_format": "grok-json"},
            },
        )
    )

    record = adapter_manifest_ledger_record(manifest, call_type="profile_enrichment")

    assert record.token_usage.prompt_tokens == 150
    assert record.token_usage.completion_tokens == 40
    assert record.token_usage.provider_name == "grok"
    assert record.token_usage.provider_type == "included-plan"
    assert record.metadata["adapter_manifest"]["adapter"] == "grok"
    assert record.metadata["adapter_manifest"]["auth_class"] == "included-plan"

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from distill.doctor.adapter_native_usage import (
    AdapterNativeUsageError,
    adapter_native_usage_contract,
    antigravity_json_native_usage,
    claude_json_native_usage,
    codex_jsonl_native_usage,
    gemini_cli_json_native_usage,
    grok_json_native_usage,
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


def test_load_adapter_native_usage_accepts_yaml_without_scratch_root(tmp_path):
    path = tmp_path / "native-usage.yaml"
    path.write_text(
        "\n".join(
            [
                "schema_version: adapter-native-usage.v1",
                "adapter: codex",
                "source: usage-file",
                "usage:",
                "  input_tokens: 2",
                "  output_tokens: 1",
                "  native:",
                "    event_count: 1",
            ]
        ),
        encoding="utf-8",
    )

    record = load_adapter_native_usage(path)

    assert record.adapter == "codex"
    assert record.to_adapter_usage().input_tokens == 2


def test_load_adapter_native_usage_rejects_non_mapping_payload(tmp_path):
    path = tmp_path / "native-usage.json"
    path.write_text("[]", encoding="utf-8")

    with pytest.raises(AdapterNativeUsageError, match="native usage must be a mapping"):
        load_adapter_native_usage(path)


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


def test_load_adapter_native_usage_rejects_absolute_path_with_scratch_root(tmp_path):
    with pytest.raises(AdapterNativeUsageError, match="must be scratch relative"):
        load_adapter_native_usage(tmp_path / "native-usage.json", scratch_root=tmp_path)


def test_codex_jsonl_native_usage_collects_turn_completed_usage():
    record = codex_jsonl_native_usage(
        "\n".join(
            [
                '{"type":"thread.started","thread_id":"thread_123"}',
                '{"type":"item.completed","item":{"type":"agent_message","text":"ok"}}',
                (
                    '{"type":"turn.completed","usage":{"input_tokens":24763,'
                    '"cached_input_tokens":24448,"output_tokens":122,'
                    '"reasoning_output_tokens":0}}'
                ),
            ]
        ),
        model="gpt-5.1-codex",
    )
    usage = record.to_adapter_usage()

    assert record.adapter == "codex"
    assert record.source == "stdout-json"
    assert record.request_id == "thread_123"
    assert usage.input_tokens == 24763
    assert usage.output_tokens == 122
    assert usage.native["cached_input_tokens"] == 24448
    assert usage.native["reasoning_output_tokens"] == 0
    assert usage.native["usage_event_count"] == 1
    assert usage.native["distill_usage_signal"]["model"] == "gpt-5.1-codex"


def test_codex_jsonl_native_usage_sums_multiple_turns():
    record = codex_jsonl_native_usage(
        "\n".join(
            [
                '{"type":"turn.completed","usage":{"input_tokens":10,"output_tokens":2}}',
                '{"type":"turn.completed","usage":{"input_tokens":4,"output_tokens":3}}',
            ]
        )
    )
    usage = record.to_adapter_usage()

    assert usage.input_tokens == 14
    assert usage.output_tokens == 5
    assert usage.native["usage_event_count"] == 2


def test_codex_jsonl_native_usage_rejects_invalid_json():
    with pytest.raises(AdapterNativeUsageError, match="invalid JSON"):
        codex_jsonl_native_usage("{not json")


def test_codex_jsonl_native_usage_rejects_missing_usage():
    with pytest.raises(AdapterNativeUsageError, match="usage not found"):
        codex_jsonl_native_usage('{"type":"turn.started"}')


def test_codex_jsonl_native_usage_rejects_bad_token_field():
    with pytest.raises(AdapterNativeUsageError, match="non-negative integer"):
        codex_jsonl_native_usage(
            '{"type":"turn.completed","usage":{"input_tokens":true,"output_tokens":1}}'
        )


def test_codex_jsonl_native_usage_marks_failed_turn_and_skips_blank_lines():
    record = codex_jsonl_native_usage(
        "\n".join(
            [
                "",
                '{"type":"turn.failed"}',
                '{"type":"turn.completed","usage":{"input_tokens":1,"output_tokens":1}}',
            ]
        )
    )

    assert record.stop_reason == "failed"
    assert record.to_adapter_usage().native["event_count"] == 2


def test_codex_jsonl_native_usage_rejects_non_object_line():
    with pytest.raises(AdapterNativeUsageError, match="line must be an object: 1"):
        codex_jsonl_native_usage("[]")


def test_codex_jsonl_native_usage_rejects_non_object_completed_usage():
    with pytest.raises(AdapterNativeUsageError, match=r"turn\.completed usage must be an object"):
        codex_jsonl_native_usage('{"type":"turn.completed","usage":[]}')


def test_claude_json_native_usage_collects_result_usage():
    record = claude_json_native_usage(
        json.dumps(
            {
                "type": "result",
                "subtype": "success",
                "is_error": False,
                "duration_ms": 4047,
                "duration_api_ms": 3011,
                "num_turns": 1,
                "result": '{"summary":"ok"}',
                "stop_reason": "end_turn",
                "session_id": "session_123",
                "total_cost_usd": 0.079,
                "usage": {
                    "input_tokens": 20,
                    "cache_creation_input_tokens": 6,
                    "cache_read_input_tokens": 8,
                    "output_tokens": 13,
                },
            }
        ),
        model="claude-fable-5",
    )
    usage = record.to_adapter_usage()

    assert record.adapter == "claude"
    assert record.source == "stdout-json"
    assert record.request_id == "session_123"
    assert record.stop_reason == "end_turn"
    assert usage.input_tokens == 20
    assert usage.output_tokens == 13
    assert usage.native["cache_creation_input_tokens"] == 6
    assert usage.native["cache_read_input_tokens"] == 8
    assert usage.native["duration_ms"] == 4047
    assert usage.native["duration_api_ms"] == 3011
    assert usage.native["num_turns"] == 1
    assert usage.native["total_cost_usd"] == 0.079
    assert usage.native["result_subtypes"] == ("success",)


def test_claude_json_native_usage_collects_stream_message_usage():
    record = claude_json_native_usage(
        "\n".join(
            [
                '{"type":"system","subtype":"init","session_id":"session_abc"}',
                (
                    '{"type":"assistant","message":{"model":"claude-fable-5",'
                    '"usage":{"input_tokens":9,"output_tokens":4}}}'
                ),
            ]
        )
    )
    usage = record.to_adapter_usage()

    assert record.model == "claude-fable-5"
    assert record.request_id == "session_abc"
    assert usage.input_tokens == 9
    assert usage.output_tokens == 4
    assert usage.native["usage_event_count"] == 1


def test_claude_json_native_usage_rejects_missing_usage():
    with pytest.raises(AdapterNativeUsageError, match="claude JSON usage not found"):
        claude_json_native_usage('{"type":"result","result":"ok"}')


def test_claude_json_native_usage_rejects_bad_token_field():
    with pytest.raises(AdapterNativeUsageError, match="non-negative integer"):
        claude_json_native_usage('{"type":"result","usage":{"input_tokens":-1,"output_tokens":1}}')


def test_claude_json_native_usage_rejects_empty_output():
    with pytest.raises(AdapterNativeUsageError, match="claude JSON output is empty"):
        claude_json_native_usage("   ")


def test_claude_json_native_usage_rejects_non_mapping_json_output():
    with pytest.raises(AdapterNativeUsageError, match="must be an object or JSONL objects"):
        claude_json_native_usage("[]")


def test_claude_json_native_usage_rejects_invalid_jsonl_line():
    with pytest.raises(AdapterNativeUsageError, match="invalid JSON: 2"):
        claude_json_native_usage('{"type":"system"}\n{not json')


def test_claude_json_native_usage_rejects_non_object_jsonl_line():
    with pytest.raises(AdapterNativeUsageError, match="line must be an object: 1"):
        claude_json_native_usage("[]\n{}")


def test_claude_json_native_usage_rejects_top_level_usage_array():
    with pytest.raises(AdapterNativeUsageError, match="claude JSON usage must be an object"):
        claude_json_native_usage('{"type":"result","usage":[]}')


def test_claude_json_native_usage_rejects_message_usage_array():
    with pytest.raises(AdapterNativeUsageError, match="message usage must be an object"):
        claude_json_native_usage('{"type":"assistant","message":{"usage":[]}}')


def test_claude_json_native_usage_failed_result_and_explicit_stop_reason():
    failed = claude_json_native_usage(
        '{"type":"result","is_error":true,"usage":{"input_tokens":1,"output_tokens":1}}'
    )
    explicit = claude_json_native_usage(
        '{"type":"result","is_error":true,"usage":{"input_tokens":1,"output_tokens":1}}',
        stop_reason="rate-limit",
    )

    assert failed.stop_reason == "failed"
    assert explicit.stop_reason == "rate-limit"


def test_claude_json_native_usage_rejects_bad_total_cost():
    with pytest.raises(AdapterNativeUsageError, match="total_cost_usd must be a non-negative"):
        claude_json_native_usage(
            '{"type":"result","total_cost_usd":true,"usage":{"input_tokens":1,"output_tokens":1}}'
        )


# --- New adapter parser tests (0.19 native usage wiring) ---


def test_grok_json_native_usage_collects_top_level():
    record = grok_json_native_usage(
        json.dumps(
            {
                "model": "grok-4.3",
                "usage": {"input_tokens": 1200, "output_tokens": 340},
                "request_id": "grok_req_1",
            }
        )
    )
    usage = record.to_adapter_usage()
    assert record.adapter == "grok"
    assert record.request_id == "grok_req_1"
    assert usage.input_tokens == 1200
    assert usage.output_tokens == 340
    assert usage.native["adapter_format"] == "grok-json"


def test_gemini_cli_json_native_usage_normalizes_usage_metadata():
    record = gemini_cli_json_native_usage(
        json.dumps(
            {
                "model": "gemini-2.5-pro",
                "usageMetadata": {
                    "promptTokenCount": 850,
                    "candidatesTokenCount": 210,
                },
            }
        )
    )
    usage = record.to_adapter_usage()
    assert record.adapter == "gemini-cli"
    assert usage.input_tokens == 850
    assert usage.output_tokens == 210


def test_antigravity_json_native_usage_forces_adapter_name():
    record = antigravity_json_native_usage('{"usage": {"input_tokens": 55, "output_tokens": 12}}')
    assert record.adapter == "antigravity"
    assert record.to_adapter_usage().input_tokens == 55


def test_new_adapters_reject_missing_usage():
    with pytest.raises(AdapterNativeUsageError, match="usage not found"):
        grok_json_native_usage('{"model":"grok-4.3"}')
    with pytest.raises(AdapterNativeUsageError, match="usage not found"):
        gemini_cli_json_native_usage('{"foo":1}')


def test_gemini_cli_json_native_usage_accepts_alternative_keys():
    record = gemini_cli_json_native_usage(
        json.dumps({"usage": {"prompt_tokens": 100, "completion_tokens": 25}})
    )
    usage = record.to_adapter_usage()
    assert usage.input_tokens == 100
    assert usage.output_tokens == 25


def test_gemini_cli_json_native_usage_rejects_boolean_token_counts():
    with pytest.raises(AdapterNativeUsageError, match="must be a non-negative integer"):
        gemini_cli_json_native_usage(
            json.dumps({"usageMetadata": {"promptTokenCount": True, "candidatesTokenCount": 1}})
        )


def test_gemini_cli_json_native_usage_rejects_float_token_counts():
    with pytest.raises(AdapterNativeUsageError, match="prompt_tokens must be a non-negative"):
        gemini_cli_json_native_usage(
            json.dumps({"usage": {"prompt_tokens": 1.5, "completion_tokens": 1}})
        )


def test_grok_json_native_usage_rejects_bad_json():
    with pytest.raises(AdapterNativeUsageError, match="usage not found"):
        grok_json_native_usage("not json at all")


def test_grok_json_native_usage_rejects_missing_usage():
    with pytest.raises(AdapterNativeUsageError, match="usage not found"):
        grok_json_native_usage('{"model": "grok-4.3", "foo": "bar"}')


def test_gemini_cli_json_native_usage_rejects_missing_usage():
    with pytest.raises(AdapterNativeUsageError, match="usage not found"):
        gemini_cli_json_native_usage('{"model": "gemini"}')


def test_grok_json_native_usage_message_wrap_fallback():
    # message level carries tokens directly for the fallback append path
    record = grok_json_native_usage(
        json.dumps({"message": {"input_tokens": 500, "output_tokens": 150}})
    )
    assert record.adapter == "grok"
    assert record.to_adapter_usage().input_tokens == 500


def test_gemini_cli_json_native_usage_usage_metadata_list_fallback():
    # first has no useful count -> get None -> sum path over list
    payload = json.dumps(
        [
            {"usageMetadata": {"other": 1}},
            {"usageMetadata": {"promptTokenCount": 20, "candidatesTokenCount": 10}},
        ]
    )
    record = gemini_cli_json_native_usage(payload)
    assert record.to_adapter_usage().input_tokens == 20
    assert record.to_adapter_usage().output_tokens == 10


def test_gemini_cli_json_native_usage_uses_session_id_fallback():
    record = gemini_cli_json_native_usage(
        json.dumps(
            {
                "session_id": "session-1",
                "usage": {"input_tokens": 1, "output_tokens": 1},
            }
        )
    )

    assert record.request_id == "session-1"


def test_antigravity_reuses_gemini_and_overrides_name():
    record = antigravity_json_native_usage('{"usage": {"input_tokens": 77, "output_tokens": 3}}')
    assert record.adapter == "antigravity"
    assert record.to_adapter_usage().output_tokens == 3


def test_generic_jsonl_parse_and_empty():
    # hits _parse_generic_json_events jsonl tolerant path and empty
    from distill.doctor.adapter_native_usage import _parse_generic_json_events

    assert _parse_generic_json_events("") == []
    events = _parse_generic_json_events('{"a":1}\n{"b":2}')
    assert len(events) == 2


def test_generic_json_parser_ignores_noise_and_non_mapping_list_entries():
    from distill.doctor.adapter_native_usage import _parse_generic_json_events

    assert _parse_generic_json_events('[{"a": 1}, 2, {"b": 3}]') == [{"a": 1}, {"b": 3}]
    assert _parse_generic_json_events('noise\n{"a": 1}\n[]') == [{"a": 1}]


def test_new_adapters_validate_and_contract_roundtrip():
    rec = grok_json_native_usage('{"usage":{"input_tokens":1,"output_tokens":1}}')
    d = rec.to_dict()
    rec2 = validate_adapter_native_usage(d)
    assert rec2.adapter == "grok"
    # contract mentions adapters
    contract = adapter_native_usage_contract()
    assert "grok" in contract["adapters"]


def test_grok_json_native_usage_sums_if_multiple():
    # tolerant jsonl
    record = grok_json_native_usage(
        '\n{"usage": {"input_tokens": 10, "output_tokens": 2}}\n{"usage": {"input_tokens": 5, "output_tokens": 3}}'
    )
    usage = record.to_adapter_usage()
    assert usage.input_tokens == 15
    assert usage.output_tokens == 5


def test_antigravity_json_native_usage_handles_metadata_style():
    record = antigravity_json_native_usage(
        json.dumps({"usageMetadata": {"promptTokenCount": 40, "candidatesTokenCount": 8}})
    )
    assert record.to_adapter_usage().input_tokens == 40

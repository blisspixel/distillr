from __future__ import annotations

import json
from dataclasses import replace

import pytest

from distill.doctor.adapter_commands import (
    AdapterCommandError,
    inline_adapter_command_schema,
    plan_adapter_command,
)
from distill.doctor.adapter_workload import validate_adapter_workload_package
from distill.doctor.adapters import AdapterProbe


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
        "metadata": {},
    }
    payload.update(overrides)
    return validate_adapter_workload_package(payload)


def test_codex_command_plan_records_read_only_argv_but_stays_blocked():
    plan = plan_adapter_command("codex", _workload())

    assert plan.argv == (
        "codex",
        "exec",
        "--sandbox",
        "read-only",
        "--ephemeral",
        "--json",
        "--output-schema",
        "schemas/result.json",
        "--output-last-message",
        "result.txt",
        "-",
    )
    assert not plan.ok
    assert plan.stdin_path == "prompt.md"
    assert plan.schema_path == "schemas/result.json"
    assert plan.result_text_path == "result.txt"
    assert plan.allowed_new_files == ("result.txt",)
    assert "adapter doctor probe is required" in plan.blocked_reasons
    assert "native usage collection is not implemented: codex" in plan.blocked_reasons
    assert plan.to_dict()["schema_path"] == "schemas/result.json"
    assert plan.to_dict()["allowed_new_files"] == ["result.txt"]
    assert plan.to_dict()["ok"] is False


def test_codex_command_plan_requires_output_schema():
    plan = plan_adapter_command("codex", _workload(output_schema_path=None))

    assert "--output-schema" in plan.argv
    assert "codex command template requires output_schema_path" in plan.blocked_reasons
    assert not plan.ok


def test_claude_command_plan_records_read_only_argv_but_stays_blocked():
    plan = plan_adapter_command("claude", _workload())

    assert plan.argv == (
        "claude",
        "-p",
        "--input-format",
        "text",
        "--output-format",
        "json",
        "--tools",
        "",
        "--no-session-persistence",
    )
    assert plan.stdin_path == "prompt.md"
    assert plan.schema_path == "schemas/result.json"
    assert plan.result_text_path == "result.txt"
    assert plan.allowed_new_files == ("result.txt",)
    assert "adapter doctor probe is required" in plan.blocked_reasons
    assert "claude command template requires schema inlining before execution" in (
        plan.blocked_reasons
    )
    assert "native usage collection is not implemented: claude" in plan.blocked_reasons
    assert not plan.ok


def test_inline_adapter_command_schema_materializes_claude_schema(tmp_path):
    schema = {
        "type": "object",
        "properties": {"summary": {"type": "string"}},
        "required": ["summary"],
    }
    (tmp_path / "schemas").mkdir()
    (tmp_path / "schemas" / "result.json").write_text(json.dumps(schema), encoding="utf-8")
    plan = plan_adapter_command("claude", _workload())

    materialized = inline_adapter_command_schema(plan, scratch_root=tmp_path)

    schema_index = materialized.argv.index("--json-schema")
    assert materialized.argv[schema_index + 1] == json.dumps(
        schema,
        separators=(",", ":"),
        sort_keys=True,
    )
    assert materialized.argv.index("--json-schema") < materialized.argv.index("--tools")
    assert "claude command template requires schema inlining before execution" not in (
        materialized.blocked_reasons
    )
    assert "native usage collection is not implemented: claude" in materialized.blocked_reasons
    assert "claude command template requires schema inlining before execution" in (
        plan.blocked_reasons
    )


def test_inline_adapter_command_schema_rejects_non_object_schema(tmp_path):
    (tmp_path / "schemas").mkdir()
    (tmp_path / "schemas" / "result.json").write_text("[]", encoding="utf-8")
    plan = plan_adapter_command("claude", _workload())

    with pytest.raises(AdapterCommandError, match="schema must be a JSON object"):
        inline_adapter_command_schema(plan, scratch_root=tmp_path)


def test_inline_adapter_command_schema_rejects_path_escape(tmp_path):
    plan = replace(plan_adapter_command("claude", _workload()), schema_path="../schema.json")

    with pytest.raises(AdapterCommandError, match="escapes scratch workspace"):
        inline_adapter_command_schema(plan, scratch_root=tmp_path)


def test_grok_command_plan_records_read_only_argv_but_stays_blocked():
    plan = plan_adapter_command("grok", _workload())

    assert plan.argv == (
        "grok",
        "--no-auto-update",
        "--prompt-file",
        "prompt.md",
        "--output-format",
        "json",
        "--cwd",
        ".",
        "--disable-web-search",
        "--no-subagents",
        "--no-memory",
        "--max-turns",
        "1",
    )
    assert plan.schema_path == "schemas/result.json"
    assert plan.result_text_path == "result.txt"
    assert plan.allowed_new_files == ("result.txt",)
    assert "adapter doctor probe is required" in plan.blocked_reasons
    assert (
        "grok command template does not enforce output_schema_path natively" in plan.blocked_reasons
    )
    assert "native usage collection is not implemented: grok" in plan.blocked_reasons
    assert not plan.ok


def test_codex_command_plan_inherits_probe_blockers():
    probe = AdapterProbe(
        name="codex",
        binary="codex",
        route_class="included-plan",
        installed=True,
        no_metered_candidate=True,
        no_metered_eligible=False,
        support_statement="planned",
        missing_flags=["--output-schema"],
        blocked_reasons=["support statement is not current"],
    )

    plan = plan_adapter_command("codex", _workload(), probe=probe)

    assert "support statement is not current" in plan.blocked_reasons
    assert "adapter missing required flags: --output-schema" in plan.blocked_reasons
    assert "adapter is not no-metered eligible" in plan.blocked_reasons
    assert not plan.ok


def test_command_plan_blocks_unknown_adapter_template():
    plan = plan_adapter_command("gemini-cli", _workload())

    assert plan.argv == ()
    assert "adapter doctor probe is required" in plan.blocked_reasons
    assert "adapter command template is not implemented: gemini-cli" in plan.blocked_reasons
    assert not plan.ok

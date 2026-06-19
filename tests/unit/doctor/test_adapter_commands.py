from __future__ import annotations

from distill.doctor.adapter_commands import plan_adapter_command
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
    assert "native adapter-result.v1 manifest writer is not implemented" in plan.blocked_reasons
    assert plan.to_dict()["ok"] is False


def test_codex_command_plan_requires_output_schema():
    plan = plan_adapter_command("codex", _workload(output_schema_path=None))

    assert "--output-schema" in plan.argv
    assert "codex command template requires output_schema_path" in plan.blocked_reasons
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
    plan = plan_adapter_command("claude", _workload())

    assert plan.argv == ()
    assert plan.blocked_reasons == ["adapter command template is not implemented: claude"]
    assert not plan.ok

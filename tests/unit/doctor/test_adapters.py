from __future__ import annotations

from collections.abc import Sequence

from distill.doctor import adapters


def test_adapter_doctor_blocks_missing_binaries(monkeypatch):
    monkeypatch.setattr(adapters.shutil, "which", lambda _binary: None)

    report = adapters.adapter_doctor_report(environ={}, runner=lambda _cmd, _timeout: (0, "", ""))

    assert report.schema_version == "adapter-doctor.v1"
    assert report.manifest_contract["schema_version"] == "adapter-result.v1"
    assert report.no_metered_ready == []
    codex = next(probe for probe in report.adapters if probe.name == "codex")
    assert not codex.installed
    assert "codex is not installed" in codex.blocked_reasons


def test_adapter_doctor_records_required_flags_and_env_blockers(monkeypatch):
    monkeypatch.setattr(adapters.shutil, "which", lambda binary: f"/bin/{binary}")

    def runner(command: Sequence[str], _timeout: int) -> tuple[int, str, str]:
        text = "codex 0.140.0" if command == ("codex", "--version") else "--json --sandbox"
        return 0, text, ""

    report = adapters.adapter_doctor_report(
        environ={"OPENAI_API_KEY": "key"},
        runner=runner,
    )

    codex = next(probe for probe in report.adapters if probe.name == "codex")
    assert codex.installed
    assert codex.version == "codex 0.140.0"
    assert codex.env_blockers_present == ["OPENAI_API_KEY"]
    assert "--output-schema" in codex.missing_flags
    assert not codex.no_metered_eligible


def test_credit_metered_copilot_is_not_no_metered_candidate(monkeypatch):
    monkeypatch.setattr(adapters.shutil, "which", lambda binary: f"/bin/{binary}")

    report = adapters.adapter_doctor_report(environ={}, runner=lambda _cmd, _timeout: (0, "", ""))

    copilot = next(probe for probe in report.adapters if probe.name == "copilot")
    assert copilot.route_class == "credit-metered"
    assert copilot.no_metered_candidate is False
    assert copilot.no_metered_eligible is False

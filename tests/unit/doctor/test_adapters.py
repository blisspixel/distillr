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
    assert codex.support_statement == "planned"
    assert codex.support_statement_detail["status"] == "planned"
    assert codex.support_statement_detail["no_metered_current"] is False
    assert (
        "official installed-session auth proof"
        in codex.support_statement_detail["required_evidence"]
    )
    assert any("codex" in source for source in codex.support_statement_detail["sources"])


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
    assert codex.auth_mode == "api-key-env"
    assert codex.env_blockers_present == ["OPENAI_API_KEY"]
    assert "--output-schema" in codex.missing_flags
    assert not codex.no_metered_eligible


def test_credit_metered_copilot_is_not_no_metered_candidate(monkeypatch):
    monkeypatch.setattr(adapters.shutil, "which", lambda binary: f"/bin/{binary}")

    report = adapters.adapter_doctor_report(environ={}, runner=lambda _cmd, _timeout: (0, "", ""))

    copilot = next(probe for probe in report.adapters if probe.name == "copilot")
    assert copilot.route_class == "credit-metered"
    assert copilot.auth_mode == "credit-metered"
    assert copilot.no_metered_candidate is False
    assert copilot.no_metered_eligible is False
    assert copilot.support_statement_detail["status"] == "credit-metered candidate"
    assert copilot.support_statement_detail["no_metered_current"] is False
    assert (
        "explicit paid-ok or future plan-credit policy"
        in copilot.support_statement_detail["required_evidence"]
    )


def test_adapter_doctor_detects_metered_config_without_leaking_secret(monkeypatch, tmp_path):
    monkeypatch.setattr(adapters.shutil, "which", lambda binary: f"/bin/{binary}")
    config_dir = tmp_path / ".codex"
    config_dir.mkdir()
    (config_dir / "config.toml").write_text(
        '[model_provider.openai]\napi_key = "secret-value"\n',
        encoding="utf-8",
    )

    report = adapters.adapter_doctor_report(
        environ={},
        home_dir=tmp_path,
        runner=_runner_with_required_flags,
    )

    codex = next(probe for probe in report.adapters if probe.name == "codex")
    assert codex.auth_mode == "api-key-config"
    assert codex.config_files_found == ["~/.codex/config.toml"]
    assert "~/.codex/config.toml: api_key" in codex.auth_evidence
    assert "secret-value" not in " ".join(codex.auth_evidence + codex.blocked_reasons)
    assert any("references API-key auth" in reason for reason in codex.blocked_reasons)
    assert not codex.no_metered_eligible


def test_adapter_doctor_reports_session_config_but_keeps_route_blocked(monkeypatch, tmp_path):
    monkeypatch.setattr(adapters.shutil, "which", lambda binary: f"/bin/{binary}")
    config_dir = tmp_path / ".grok"
    config_dir.mkdir()
    (config_dir / "config.toml").write_text(
        '[auth]\ncached_token = "redacted-token"\n',
        encoding="utf-8",
    )

    report = adapters.adapter_doctor_report(
        environ={},
        home_dir=tmp_path,
        runner=_runner_with_required_flags,
    )

    grok = next(probe for probe in report.adapters if probe.name == "grok")
    assert grok.auth_mode == "session-config"
    assert "~/.grok/config.toml: cached_token" in grok.auth_evidence
    assert "redacted-token" not in " ".join(grok.auth_evidence + grok.blocked_reasons)
    assert "support statement is not current" in grok.blocked_reasons
    assert not grok.no_metered_eligible


def test_adapter_doctor_blocks_unknown_auth_for_installed_candidate(monkeypatch, tmp_path):
    monkeypatch.setattr(adapters.shutil, "which", lambda binary: f"/bin/{binary}")

    report = adapters.adapter_doctor_report(
        environ={},
        home_dir=tmp_path,
        runner=_runner_with_required_flags,
    )

    codex = next(probe for probe in report.adapters if probe.name == "codex")
    assert codex.auth_mode == "unknown"
    assert "auth mode is unknown" in codex.blocked_reasons


def _runner_with_required_flags(command: Sequence[str], _timeout: int) -> tuple[int, str, str]:
    output_by_command = {
        ("codex", "--version"): "codex 0.140.0",
        ("codex", "exec", "--help"): "--json --sandbox --output-schema --output-last-message",
        ("claude", "--version"): "claude 2.1.173",
        ("claude", "-p", "--help"): "--output-format --max-turns --no-session-persistence",
        ("grok", "--version"): "grok 0.2.50",
        ("grok", "--help"): "--output-format",
        ("gemini", "--version"): "gemini 1.0.0",
        ("gemini", "--help"): "",
        ("antigravity", "--version"): "antigravity 1.0.0",
        ("antigravity", "--help"): "",
        ("gh", "--version"): "gh 2.0.0",
        ("gh", "copilot", "--help"): "",
    }
    return 0, output_by_command.get(tuple(command), ""), ""

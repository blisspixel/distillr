from __future__ import annotations

from collections.abc import Sequence

from distill.doctor import adapters


def test_adapter_doctor_blocks_missing_binaries(monkeypatch):
    monkeypatch.setattr(adapters, "resolve_executable", lambda _binary: None)

    report = adapters.adapter_doctor_report(environ={}, runner=lambda _cmd, _timeout: (0, "", ""))

    assert report.schema_version == "adapter-doctor.v1"
    assert report.manifest_contract["schema_version"] == "adapter-result.v1"
    assert report.workload_contract["schema_version"] == "adapter-workload.v1"
    assert report.usage_contract["schema_version"] == "adapter-native-usage.v1"
    assert report.no_metered_ready == []
    codex = next(probe for probe in report.adapters if probe.name == "codex")
    assert not codex.installed
    assert "codex is not installed" in codex.blocked_reasons
    assert codex.support_statement == "planned"
    assert codex.support_statement_detail["status"] == "planned"
    assert codex.support_statement_detail["checked_on"] == "2026-06-30"
    assert codex.support_statement_detail["no_metered_current"] is False
    assert (
        "official installed-session auth proof"
        in codex.support_statement_detail["required_evidence"]
    )
    assert (
        "no paid credit, overage, gateway, or API-backed route"
        in codex.support_statement_detail["required_evidence"]
    )
    assert any("codex" in source for source in codex.support_statement_detail["sources"])


def test_adapter_doctor_records_required_flags_and_env_blockers(monkeypatch):
    monkeypatch.setattr(adapters, "resolve_executable", lambda binary: f"/bin/{binary}")

    def runner(command: Sequence[str], _timeout: int) -> tuple[int, str, str]:
        text = (
            "codex 0.140.0"
            if _command_key(command) == ("codex", "--version")
            else "--json --sandbox"
        )
        return 0, text, ""

    report = adapters.adapter_doctor_report(
        environ={"OPENAI_API_KEY": "key"},
        runner=runner,
    )

    codex = next(probe for probe in report.adapters if probe.name == "codex")
    assert codex.installed
    assert codex.version == "codex 0.140.0"
    assert codex.auth_mode == "metered-env"
    assert codex.env_blockers_present == ["OPENAI_API_KEY"]
    assert "--output-schema" in codex.missing_flags
    assert not codex.no_metered_eligible


def test_adapter_doctor_blocks_google_api_key_for_gemini(monkeypatch):
    monkeypatch.setattr(adapters, "resolve_executable", lambda binary: f"/bin/{binary}")

    report = adapters.adapter_doctor_report(
        environ={"GOOGLE_API_KEY": "key"},
        runner=_runner_with_required_flags,
    )

    gemini = next(probe for probe in report.adapters if probe.name == "gemini-cli")
    antigravity = next(probe for probe in report.adapters if probe.name == "antigravity")
    assert gemini.auth_mode == "metered-env"
    assert gemini.env_blockers_present == ["GOOGLE_API_KEY"]
    assert "GOOGLE_API_KEY is set" in gemini.blocked_reasons
    assert antigravity.auth_mode == "metered-env"
    assert antigravity.env_blockers_present == ["GOOGLE_API_KEY"]
    assert "GOOGLE_API_KEY is set" in antigravity.blocked_reasons


def test_adapter_doctor_blocks_google_cloud_credential_routes(monkeypatch):
    monkeypatch.setattr(adapters, "resolve_executable", lambda binary: f"/bin/{binary}")

    report = adapters.adapter_doctor_report(
        environ={"GOOGLE_APPLICATION_CREDENTIALS": "creds.json"},
        runner=_runner_with_required_flags,
    )

    gemini = next(probe for probe in report.adapters if probe.name == "gemini-cli")
    antigravity = next(probe for probe in report.adapters if probe.name == "antigravity")
    assert gemini.env_blockers_present == ["GOOGLE_APPLICATION_CREDENTIALS"]
    assert "GOOGLE_APPLICATION_CREDENTIALS is set" in gemini.blocked_reasons
    assert not gemini.no_metered_eligible
    assert antigravity.env_blockers_present == ["GOOGLE_APPLICATION_CREDENTIALS"]
    assert "GOOGLE_APPLICATION_CREDENTIALS is set" in antigravity.blocked_reasons
    assert not antigravity.no_metered_eligible


def test_adapter_doctor_blocks_claude_gateway_and_cloud_provider_routes(monkeypatch):
    monkeypatch.setattr(adapters, "resolve_executable", lambda binary: f"/bin/{binary}")

    report = adapters.adapter_doctor_report(
        environ={"ANTHROPIC_BASE_URL": "https://gateway.example", "CLAUDE_CODE_USE_VERTEX": "1"},
        runner=_runner_with_required_flags,
    )

    claude = next(probe for probe in report.adapters if probe.name == "claude")
    assert claude.env_blockers_present == ["ANTHROPIC_BASE_URL", "CLAUDE_CODE_USE_VERTEX"]
    assert "ANTHROPIC_BASE_URL is set" in claude.blocked_reasons
    assert "CLAUDE_CODE_USE_VERTEX is set" in claude.blocked_reasons
    assert not claude.no_metered_eligible


def test_adapter_doctor_blocks_gateway_and_credential_config_routes(monkeypatch, tmp_path):
    monkeypatch.setattr(adapters, "resolve_executable", lambda binary: f"/bin/{binary}")
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    (claude_dir / "settings.json").write_text(
        '{"env":{"ANTHROPIC_BASE_URL":"https://gateway.example"}}',
        encoding="utf-8",
    )
    gemini_dir = tmp_path / ".gemini"
    gemini_dir.mkdir()
    (gemini_dir / "settings.json").write_text(
        '{"auth":{"GOOGLE_APPLICATION_CREDENTIALS":"creds.json"}}',
        encoding="utf-8",
    )

    report = adapters.adapter_doctor_report(
        environ={},
        home_dir=tmp_path,
        runner=_runner_with_required_flags,
    )

    claude = next(probe for probe in report.adapters if probe.name == "claude")
    gemini = next(probe for probe in report.adapters if probe.name == "gemini-cli")
    assert claude.auth_mode == "metered-config"
    assert "~/.claude/settings.json: ANTHROPIC_BASE_URL" in claude.auth_evidence
    assert (
        "~/.claude/settings.json: ANTHROPIC_BASE_URL references a metered route"
        in claude.blocked_reasons
    )
    assert gemini.auth_mode == "metered-config"
    assert "~/.gemini/settings.json: GOOGLE_APPLICATION_CREDENTIALS" in gemini.auth_evidence
    assert (
        "~/.gemini/settings.json: GOOGLE_APPLICATION_CREDENTIALS references a metered route"
        in gemini.blocked_reasons
    )


def test_credit_metered_copilot_is_not_no_metered_candidate(monkeypatch):
    monkeypatch.setattr(adapters, "resolve_executable", lambda binary: f"/bin/{binary}")

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
    monkeypatch.setattr(adapters, "resolve_executable", lambda binary: f"/bin/{binary}")
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
    assert codex.auth_mode == "metered-config"
    assert codex.config_files_found == ["~/.codex/config.toml"]
    assert "~/.codex/config.toml: api_key" in codex.auth_evidence
    assert "secret-value" not in " ".join(codex.auth_evidence + codex.blocked_reasons)
    assert any("references a metered route" in reason for reason in codex.blocked_reasons)
    assert not codex.no_metered_eligible


def test_adapter_doctor_reports_session_config_but_keeps_route_blocked(monkeypatch, tmp_path):
    monkeypatch.setattr(adapters, "resolve_executable", lambda binary: f"/bin/{binary}")
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


def test_adapter_doctor_reads_bom_prefixed_toml_config(monkeypatch, tmp_path):
    monkeypatch.setattr(adapters, "resolve_executable", lambda binary: f"/bin/{binary}")
    config_dir = tmp_path / ".grok"
    config_dir.mkdir()
    (config_dir / "config.toml").write_text(
        '\ufeff[auth]\ncached_token = "redacted-token"\n',
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
    assert "~/.grok/config.toml could not be parsed" not in grok.blocked_reasons


def test_adapter_doctor_reports_malformed_config_without_leaking_values(monkeypatch, tmp_path):
    monkeypatch.setattr(adapters, "resolve_executable", lambda binary: f"/bin/{binary}")
    config_dir = tmp_path / ".codex"
    config_dir.mkdir()
    (config_dir / "config.toml").write_text(
        '[model_provider.openai\napi_key = "secret-value"\n',
        encoding="utf-8",
    )

    report = adapters.adapter_doctor_report(
        environ={},
        home_dir=tmp_path,
        runner=_runner_with_required_flags,
    )

    codex = next(probe for probe in report.adapters if probe.name == "codex")
    output_text = " ".join(codex.auth_evidence + codex.blocked_reasons)
    assert codex.config_files_found == ["~/.codex/config.toml"]
    assert "~/.codex/config.toml could not be parsed" in codex.blocked_reasons
    assert "auth mode is unknown" in codex.blocked_reasons
    assert "secret-value" not in output_text
    assert not codex.no_metered_eligible


def test_antigravity_uses_current_agy_cli_and_config_path(monkeypatch, tmp_path):
    monkeypatch.setattr(adapters, "resolve_executable", lambda binary: f"/bin/{binary}")
    config_dir = tmp_path / ".gemini" / "antigravity-cli"
    config_dir.mkdir(parents=True)
    (config_dir / "settings.json").write_text(
        '{"auth":{"session":"present"}}',
        encoding="utf-8",
    )

    report = adapters.adapter_doctor_report(
        environ={},
        home_dir=tmp_path,
        runner=_runner_with_required_flags,
    )

    antigravity = next(probe for probe in report.adapters if probe.name == "antigravity")
    assert antigravity.binary == "agy"
    assert "~/.gemini/antigravity-cli/settings.json" in antigravity.config_files_checked
    assert antigravity.config_files_found == ["~/.gemini/antigravity-cli/settings.json"]
    assert "~/.gemini/antigravity-cli/settings.json: session" in antigravity.auth_evidence
    assert antigravity.auth_mode == "session-config"
    assert antigravity.support_statement_detail["checked_on"] == "2026-06-30"
    assert (
        "https://antigravity.google/docs/plans" in antigravity.support_statement_detail["sources"]
    )
    assert "support statement is not current" in antigravity.blocked_reasons
    assert not antigravity.no_metered_eligible


def test_adapter_doctor_reports_session_auth_command_without_leaking_values(monkeypatch):
    monkeypatch.setattr(adapters, "resolve_executable", lambda binary: f"/bin/{binary}")

    def runner(command: Sequence[str], _timeout: int) -> tuple[int, str, str]:
        if _command_key(command) == ("claude", "auth", "status", "--json"):
            return (
                0,
                '{"auth":{"method":"oauth","state":"authenticated","account":"user@example.test"}}',
                "",
            )
        return _runner_with_required_flags(command, _timeout)

    report = adapters.adapter_doctor_report(environ={}, runner=runner)

    claude = next(probe for probe in report.adapters if probe.name == "claude")
    assert claude.auth_mode == "session-command"
    assert "auth_status: oauth" in claude.auth_evidence
    assert "auth_status: authenticated" in claude.auth_evidence
    assert "user@example.test" not in " ".join(claude.auth_evidence + claude.blocked_reasons)
    assert "support statement is not current" in claude.blocked_reasons
    assert not claude.no_metered_eligible


def test_adapter_doctor_reports_metered_auth_command(monkeypatch):
    monkeypatch.setattr(adapters, "resolve_executable", lambda binary: f"/bin/{binary}")

    def runner(command: Sequence[str], _timeout: int) -> tuple[int, str, str]:
        if _command_key(command) == ("claude", "auth", "status", "--json"):
            return 0, '{"auth":{"method":"api_key"}}', ""
        return _runner_with_required_flags(command, _timeout)

    report = adapters.adapter_doctor_report(environ={}, runner=runner)

    claude = next(probe for probe in report.adapters if probe.name == "claude")
    assert claude.auth_mode == "metered-command"
    assert "auth_status: api_key" in claude.auth_evidence
    assert "auth_status: api_key references a metered route" in claude.blocked_reasons
    assert not claude.no_metered_eligible


def test_adapter_doctor_blocks_unknown_auth_for_installed_candidate(monkeypatch, tmp_path):
    monkeypatch.setattr(adapters, "resolve_executable", lambda binary: f"/bin/{binary}")

    report = adapters.adapter_doctor_report(
        environ={},
        home_dir=tmp_path,
        runner=_runner_with_required_flags,
    )

    codex = next(probe for probe in report.adapters if probe.name == "codex")
    assert codex.auth_mode == "unknown"
    assert "auth mode is unknown" in codex.blocked_reasons


def test_adapter_doctor_probes_use_exact_discovered_executables(monkeypatch):
    resolved = {
        binary: rf"C:\Program Files\adapter shims\{binary}.cmd"
        for binary in ("agy", "claude", "codex", "gemini", "gh", "grok")
    }
    monkeypatch.setattr(adapters, "resolve_executable", resolved.get)
    commands: list[tuple[str, ...]] = []

    def runner(command: Sequence[str], timeout: int) -> tuple[int, str, str]:
        commands.append(tuple(command))
        return _runner_with_required_flags(command, timeout)

    report = adapters.adapter_doctor_report(environ={}, runner=runner)

    assert (resolved["codex"], "--version") in commands
    assert (resolved["codex"], "exec", "--help") in commands
    assert (resolved["claude"], "auth", "status", "--json") in commands
    assert (resolved["claude"], "-p", "--help") in commands
    assert (resolved["gemini"], "--help") in commands
    assert next(probe for probe in report.adapters if probe.name == "codex").version == (
        "codex 0.140.0"
    )
    codex_spec = next(spec for spec in adapters.adapter_specs() if spec.name == "codex")
    assert codex_spec.probes[0].command == ("codex", "--version")


def test_adapter_doctor_gives_slow_startup_probes_bounded_headroom(monkeypatch):
    monkeypatch.setattr(adapters, "resolve_executable", lambda binary: f"/bin/{binary}")
    default_timeouts: list[int] = []
    override_timeouts: list[int] = []

    def default_runner(command: Sequence[str], timeout: int) -> tuple[int, str, str]:
        default_timeouts.append(timeout)
        return _runner_with_required_flags(command, timeout)

    def override_runner(command: Sequence[str], timeout: int) -> tuple[int, str, str]:
        override_timeouts.append(timeout)
        return _runner_with_required_flags(command, timeout)

    adapters.adapter_doctor_report(environ={}, runner=default_runner)
    adapters.adapter_doctor_report(environ={}, runner=override_runner, timeout_seconds=2)

    assert default_timeouts and set(default_timeouts) == {10}
    assert override_timeouts and set(override_timeouts) == {2}


def test_adapter_doctor_posix_probes_keep_resolved_executable_identity(monkeypatch):
    monkeypatch.setattr(adapters, "resolve_executable", lambda binary: f"/opt/adapters/{binary}")
    commands: list[tuple[str, ...]] = []

    def runner(command: Sequence[str], timeout: int) -> tuple[int, str, str]:
        commands.append(tuple(command))
        return _runner_with_required_flags(command, timeout)

    adapters.adapter_doctor_report(environ={}, runner=runner)

    assert ("/opt/adapters/codex", "--version") in commands
    assert ("/opt/adapters/claude", "auth", "status", "--json") in commands
    assert all(command[0].startswith("/opt/adapters/") for command in commands)


def test_adapter_command_runner_keeps_shell_disabled(monkeypatch):
    executable = r"C:\Program Files\adapter shims\codex.cmd"
    calls: list[tuple[list[str], dict[str, object]]] = []

    def run(command: list[str], **kwargs: object):
        calls.append((command, kwargs))
        return adapters.subprocess.CompletedProcess(command, 0, "codex 0.140.0\n", "")

    monkeypatch.setattr(adapters.subprocess, "run", run)
    monkeypatch.setattr(
        adapters,
        "package_install_context",
        lambda: ("/trusted", {"PATH": "/opt/adapters"}),
    )

    result = adapters._run_command((executable, "--version"), 7)

    assert result == (0, "codex 0.140.0\n", "")
    assert calls == [
        (
            [executable, "--version"],
            {
                "capture_output": True,
                "text": True,
                "timeout": 7,
                "check": False,
                "shell": False,
                "cwd": "/trusted",
                "env": {"PATH": "/opt/adapters"},
            },
        )
    ]


def _command_key(command: Sequence[str]) -> tuple[str, ...]:
    executable = command[0].replace("\\", "/").rsplit("/", maxsplit=1)[-1]
    for suffix in (".bat", ".cmd", ".com", ".exe"):
        if executable.lower().endswith(suffix):
            executable = executable[: -len(suffix)]
            break
    return (executable, *command[1:])


def _runner_with_required_flags(command: Sequence[str], _timeout: int) -> tuple[int, str, str]:
    output_by_command = {
        ("codex", "--version"): "codex 0.140.0",
        ("codex", "exec", "--help"): "--json --sandbox --output-schema --output-last-message",
        ("claude", "--version"): "claude 2.1.206",
        ("claude", "-p", "--help"): (
            "--input-format --output-format --json-schema --permission-mode "
            "--tools --no-session-persistence"
        ),
        ("claude", "auth", "status", "--json"): "{}",
        ("grok", "--version"): "grok 0.2.50",
        ("grok", "--help"): "--output-format",
        ("grok", "inspect", "--json"): "{}",
        ("gemini", "--version"): "gemini 1.0.0",
        ("gemini", "--help"): "--prompt --approval-mode --output-format",
        ("agy", "--version"): "agy 1.0.0",
        ("agy", "--help"): "-p",
        ("gh", "--version"): "gh 2.0.0",
        ("gh", "copilot", "--help"): "",
    }
    return 0, output_by_command.get(_command_key(command), ""), ""

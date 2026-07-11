# pyright: strict
"""Read-only doctor checks for candidate CLI model adapters."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tomllib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from distill.doctor.adapter_manifest import adapter_result_manifest_contract
from distill.doctor.adapter_native_usage import adapter_native_usage_contract
from distill.doctor.adapter_workload import adapter_workload_contract

__all__ = [
    "AdapterDoctorReport",
    "AdapterProbe",
    "AdapterSpec",
    "AuthCommandProbe",
    "CommandProbe",
    "ConfigProbe",
    "SupportStatement",
    "adapter_doctor_report",
    "adapter_specs",
]


CommandRunner = Callable[[Sequence[str], int], tuple[int, str, str]]

_DEFAULT_PROBE_TIMEOUT_SECONDS = 10

_CLAUDE_METERED_ENV_BLOCKERS = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_BASE_URL",
    "CLAUDE_CODE_USE_BEDROCK",
    "CLAUDE_CODE_USE_VERTEX",
)
_CLAUDE_CONFIG_METERED_MARKERS = (
    "apiKeyHelper",
    "api_key",
    "env_key",
    *_CLAUDE_METERED_ENV_BLOCKERS,
)
_CLAUDE_AUTH_METERED_MARKERS = (
    *_CLAUDE_CONFIG_METERED_MARKERS,
    "apiKey",
    "console",
)

_GEMINI_FAMILY_METERED_ENV_BLOCKERS = (
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "GOOGLE_APPLICATION_CREDENTIALS",
    "GOOGLE_CLOUD_LOCATION",
    "GOOGLE_CLOUD_PROJECT",
)
_GEMINI_FAMILY_CONFIG_METERED_MARKERS = (
    "api_key",
    "env_key",
    *_GEMINI_FAMILY_METERED_ENV_BLOCKERS,
)


@dataclass(frozen=True)
class ConfigProbe:
    """One local config file to scan for auth-route markers."""

    display_path: str
    relative_path: tuple[str, ...]
    metered_markers: tuple[str, ...]
    session_markers: tuple[str, ...] = ()


@dataclass(frozen=True)
class CommandProbe:
    """One read-only command needed to classify an adapter."""

    label: str
    command: tuple[str, ...]
    required_flags: tuple[str, ...] = ()


@dataclass(frozen=True)
class AuthCommandProbe:
    """One read-only command that may prove adapter auth route class."""

    label: str
    command: tuple[str, ...]
    metered_markers: tuple[str, ...]
    session_markers: tuple[str, ...]


@dataclass(frozen=True)
class SupportStatement:
    """Support status for a candidate adapter route."""

    status: str
    checked_on: str
    sources: tuple[str, ...]
    required_evidence: tuple[str, ...]
    no_metered_current: bool = False
    notes: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "checked_on": self.checked_on,
            "sources": list(self.sources),
            "required_evidence": list(self.required_evidence),
            "no_metered_current": self.no_metered_current,
            "notes": self.notes,
        }


@dataclass(frozen=True)
class AdapterSpec:
    """Static policy for a candidate adapter route."""

    name: str
    binary: str
    route_class: str
    support_statement: SupportStatement
    probes: tuple[CommandProbe, ...]
    env_blockers: tuple[str, ...] = ()
    config_probes: tuple[ConfigProbe, ...] = ()
    auth_probes: tuple[AuthCommandProbe, ...] = ()
    no_metered_candidate: bool = True


@dataclass(frozen=True)
class AdapterProbe:
    """Observed adapter readiness from read-only checks."""

    name: str
    binary: str
    route_class: str
    installed: bool
    no_metered_candidate: bool
    no_metered_eligible: bool
    support_statement: str
    support_statement_detail: dict[str, Any] = field(default_factory=dict)  # pyright: ignore[reportUnknownVariableType] "dataclass default_factory appears as dict[Unknown] under strict; to_dict usage confirms shape"
    version: str = ""
    auth_mode: str = "unknown"
    auth_evidence: list[str] = field(default_factory=list)  # pyright: ignore[reportUnknownVariableType] "dataclass default_factory appears as list[Unknown] under strict; to_dict + construction confirms list[str]"
    config_files_checked: list[str] = field(default_factory=list)  # pyright: ignore[reportUnknownVariableType] "dataclass default_factory appears as list[Unknown] under strict; usage confirms list[str]"
    config_files_found: list[str] = field(default_factory=list)  # pyright: ignore[reportUnknownVariableType] "dataclass default_factory appears as list[Unknown] under strict; usage confirms list[str]"
    missing_flags: list[str] = field(default_factory=list)  # pyright: ignore[reportUnknownVariableType] "dataclass default_factory appears as list[Unknown] under strict; usage confirms list[str]"
    env_blockers_present: list[str] = field(default_factory=list)  # pyright: ignore[reportUnknownVariableType] "dataclass default_factory appears as list[Unknown] under strict; usage confirms list[str]"
    blocked_reasons: list[str] = field(default_factory=list)  # pyright: ignore[reportUnknownVariableType] "dataclass default_factory appears as list[Unknown] under strict; usage confirms list[str]"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "binary": self.binary,
            "route_class": self.route_class,
            "installed": self.installed,
            "no_metered_candidate": self.no_metered_candidate,
            "no_metered_eligible": self.no_metered_eligible,
            "support_statement": self.support_statement,
            "support_statement_detail": self.support_statement_detail,
            "version": self.version,
            "auth_mode": self.auth_mode,
            "auth_evidence": self.auth_evidence,
            "config_files_checked": self.config_files_checked,
            "config_files_found": self.config_files_found,
            "missing_flags": self.missing_flags,
            "env_blockers_present": self.env_blockers_present,
            "blocked_reasons": self.blocked_reasons,
        }


@dataclass(frozen=True)
class AdapterDoctorReport:
    """Structured adapter doctor result."""

    schema_version: str
    adapters: list[AdapterProbe]
    manifest_contract: dict[str, object] = field(default_factory=adapter_result_manifest_contract)
    workload_contract: dict[str, object] = field(default_factory=adapter_workload_contract)
    usage_contract: dict[str, object] = field(default_factory=adapter_native_usage_contract)

    @property
    def no_metered_ready(self) -> list[str]:
        return [probe.name for probe in self.adapters if probe.no_metered_eligible]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "no_metered_ready": self.no_metered_ready,
            "manifest_contract": self.manifest_contract,
            "workload_contract": self.workload_contract,
            "usage_contract": self.usage_contract,
            "adapters": [probe.to_dict() for probe in self.adapters],
        }


def adapter_specs() -> tuple[AdapterSpec, ...]:
    """Return candidate adapter specs in stable display order."""

    return (
        AdapterSpec(
            name="codex",
            binary="codex",
            route_class="included-plan",
            support_statement=_support_statement(
                status="planned",
                sources=(
                    "https://developers.openai.com/codex/auth",
                    "https://developers.openai.com/codex/pricing",
                    "https://developers.openai.com/codex/cli/reference",
                    "https://developers.openai.com/codex/noninteractive",
                    "https://developers.openai.com/codex/concepts/sandboxing",
                    "https://help.openai.com/en/articles/11369540-using-codex-with-your-chatgpt-plan",
                ),
                notes=(
                    "Codex supports ChatGPT-managed auth with included plan usage, "
                    "but credits can extend usage after included limits and API-key "
                    "auth uses standard API billing. Keep blocked until doctor can "
                    "prove ChatGPT-managed auth plus non-credit no-metered policy."
                ),
            ),
            env_blockers=("OPENAI_API_KEY", "CODEX_API_KEY"),
            config_probes=(
                ConfigProbe(
                    "~/.codex/config.toml",
                    (".codex", "config.toml"),
                    ("api_key", "env_key", "OPENAI_API_KEY", "CODEX_API_KEY"),
                    ("chatgpt", "oauth", "session"),
                ),
            ),
            probes=(
                CommandProbe("version", ("codex", "--version")),
                CommandProbe(
                    "exec_help",
                    ("codex", "exec", "--help"),
                    ("--json", "--sandbox", "--output-schema", "--output-last-message"),
                ),
            ),
        ),
        AdapterSpec(
            name="claude",
            binary="claude",
            route_class="included-plan",
            support_statement=_support_statement(
                status="planned",
                sources=(
                    "https://code.claude.com/docs/en/cli-reference",
                    "https://code.claude.com/docs/en/settings",
                    "https://docs.anthropic.com/en/docs/claude-code/costs",
                    "https://docs.anthropic.com/en/docs/claude-code/iam",
                    "https://support.claude.com/en/articles/11145838-use-claude-code-with-your-pro-or-max-plan",
                ),
                notes=(
                    "Claude Code Pro, Max, Team, and Enterprise usage can be "
                    "included in subscription limits, but API, cloud-provider, "
                    "gateway, and usage-credit paths are billable. Keep blocked "
                    "until doctor proves a subscription session and no paid "
                    "workspace or API-credit route."
                ),
            ),
            env_blockers=_CLAUDE_METERED_ENV_BLOCKERS,
            config_probes=(
                ConfigProbe(
                    "~/.claude/settings.json",
                    (".claude", "settings.json"),
                    _CLAUDE_CONFIG_METERED_MARKERS,
                    ("oauth", "subscription", "session"),
                ),
                ConfigProbe(
                    "~/.claude.json",
                    (".claude.json",),
                    _CLAUDE_CONFIG_METERED_MARKERS,
                    ("oauth", "subscription", "session"),
                ),
            ),
            probes=(
                CommandProbe("version", ("claude", "--version")),
                CommandProbe(
                    "print_help",
                    ("claude", "-p", "--help"),
                    (
                        "--input-format",
                        "--output-format",
                        "--json-schema",
                        "--permission-mode",
                        "--tools",
                        "--no-session-persistence",
                    ),
                ),
            ),
            auth_probes=(
                AuthCommandProbe(
                    "auth_status",
                    ("claude", "auth", "status", "--json"),
                    _CLAUDE_AUTH_METERED_MARKERS,
                    ("oauth", "subscription", "logged_in", "authenticated"),
                ),
            ),
        ),
        AdapterSpec(
            name="grok",
            binary="grok",
            route_class="included-plan",
            support_statement=_support_statement(
                status="planned",
                sources=(
                    "https://docs.x.ai/build/cli/headless-scripting",
                    "https://docs.x.ai/build/enterprise",
                    "https://docs.x.ai/build/modes-and-commands",
                ),
                notes=(
                    "Grok Build exposes headless automation, cached-token session "
                    "markers, and API-key markers, but the current docs do not "
                    "provide a machine-checkable no-metered fixed-quota statement "
                    "for Distill. Keep blocked until route-class and quota proof "
                    "are explicit."
                ),
            ),
            env_blockers=("XAI_API_KEY",),
            config_probes=(
                ConfigProbe(
                    "~/.grok/config.toml",
                    (".grok", "config.toml"),
                    ("api_key", "env_key", "XAI_API_KEY", "xai.api_key"),
                    ("cached_token", "oauth", "session"),
                ),
            ),
            probes=(
                CommandProbe("version", ("grok", "--version")),
                CommandProbe("help", ("grok", "--help"), ("--output-format",)),
            ),
            auth_probes=(
                AuthCommandProbe(
                    "inspect_json",
                    ("grok", "inspect", "--json"),
                    ("api_key", "env_key", "XAI_API_KEY", "xai.api_key"),
                    ("cached_token", "oauth", "session"),
                ),
            ),
        ),
        AdapterSpec(
            name="gemini-cli",
            binary="gemini",
            route_class="included-plan",
            support_statement=_support_statement(
                status="planned",
                sources=(
                    "https://github.com/google-gemini/gemini-cli",
                    "https://github.com/google-gemini/gemini-cli/blob/main/docs/get-started/authentication.mdx",
                    "https://github.com/google-gemini/gemini-cli/blob/main/docs/resources/quota-and-pricing.md",
                    "https://cloud.google.com/blog/topics/developers-practitioners/choosing-antigravity-or-gemini-cli",
                ),
                notes=(
                    "Gemini CLI supports Google-account quota and API-key modes, "
                    "and current Google guidance routes consumer Free, Pro, and "
                    "Ultra users toward Antigravity after the 2026-06-18 "
                    "transition. Keep blocked until installed auth mode, quota "
                    "class, and non-API usage can be proved."
                ),
            ),
            env_blockers=_GEMINI_FAMILY_METERED_ENV_BLOCKERS,
            config_probes=(
                ConfigProbe(
                    "~/.gemini/settings.json",
                    (".gemini", "settings.json"),
                    _GEMINI_FAMILY_CONFIG_METERED_MARKERS,
                    ("oauth", "login", "session"),
                ),
            ),
            probes=(
                CommandProbe("version", ("gemini", "--version")),
                CommandProbe(
                    "help",
                    ("gemini", "--help"),
                    ("--prompt", "--approval-mode", "--output-format"),
                ),
            ),
        ),
        AdapterSpec(
            name="antigravity",
            binary="agy",
            route_class="included-plan",
            support_statement=_support_statement(
                status="planned",
                sources=(
                    "https://antigravity.google/docs/cli-install",
                    "https://antigravity.google/docs/cli-overview",
                    "https://antigravity.google/docs/cli-using",
                    "https://antigravity.google/docs/plans",
                    "https://codelabs.developers.google.com/antigravity-cli-hands-on",
                    "https://cloud.google.com/blog/topics/developers-practitioners/choosing-antigravity-or-gemini-cli",
                ),
                notes=(
                    "Antigravity now documents the `agy` CLI, Google-account "
                    "plans, fixed quota, and AI-credit overages. Keep blocked "
                    "until doctor can prove logged-in plan auth, overages disabled "
                    "or bounded, native usage evidence, and eval graduation."
                ),
            ),
            env_blockers=_GEMINI_FAMILY_METERED_ENV_BLOCKERS,
            config_probes=(
                ConfigProbe(
                    "~/.gemini/antigravity-cli/settings.json",
                    (".gemini", "antigravity-cli", "settings.json"),
                    _GEMINI_FAMILY_CONFIG_METERED_MARKERS,
                    ("oauth", "login", "session"),
                ),
                ConfigProbe(
                    "~/.antigravity/settings.json",
                    (".antigravity", "settings.json"),
                    _GEMINI_FAMILY_CONFIG_METERED_MARKERS,
                    ("oauth", "login", "session"),
                ),
            ),
            probes=(
                CommandProbe("version", ("agy", "--version")),
                CommandProbe("help", ("agy", "--help"), ("-p",)),
            ),
        ),
        AdapterSpec(
            name="copilot",
            binary="gh",
            route_class="credit-metered",
            support_statement=SupportStatement(
                status="credit-metered candidate",
                checked_on="2026-06-18",
                sources=(
                    "https://docs.github.com/copilot/concepts/agents/about-copilot-cli",
                    "https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-command-reference",
                    "https://docs.github.com/en/copilot/concepts/usage-limits",
                ),
                required_evidence=(
                    "explicit paid-ok or future plan-credit policy",
                    "machine-readable output or adapter-result.v1 manifest",
                    "native AI-credit usage signal",
                    "eval evidence for the workload",
                ),
                no_metered_current=False,
                notes="Credit-metered candidate only. Not a no-metered default.",
            ),
            no_metered_candidate=False,
            probes=(
                CommandProbe("version", ("gh", "--version")),
                CommandProbe("copilot_help", ("gh", "copilot", "--help")),
            ),
        ),
    )


def adapter_doctor_report(
    *,
    environ: Mapping[str, str] | None = None,
    runner: CommandRunner | None = None,
    home_dir: Path | None = None,
    timeout_seconds: int = _DEFAULT_PROBE_TIMEOUT_SECONDS,
) -> AdapterDoctorReport:
    """Run read-only adapter checks and return a fail-closed report."""

    env = os.environ if environ is None else environ
    run = runner or _run_command
    home = home_dir or Path.home()
    return AdapterDoctorReport(
        schema_version="adapter-doctor.v1",
        adapters=[
            _probe_adapter(
                spec,
                env=env,
                runner=run,
                home_dir=home,
                timeout_seconds=timeout_seconds,
            )
            for spec in adapter_specs()
        ],
    )


def _probe_adapter(
    spec: AdapterSpec,
    *,
    env: Mapping[str, str],
    runner: CommandRunner,
    home_dir: Path,
    timeout_seconds: int,
) -> AdapterProbe:
    executable = shutil.which(spec.binary)
    installed = executable is not None
    env_blockers_present = [name for name in spec.env_blockers if env.get(name)]
    config_result = _scan_config_probes(spec.config_probes, home_dir)
    blocked_reasons: list[str] = []
    auth_command_result = _AuthCommandResult(
        metered_evidence=[],
        session_evidence=[],
        blocked_reasons=[],
    )

    if executable is None:
        blocked_reasons.append(f"{spec.binary} is not installed")
    else:
        auth_command_result = _run_auth_command_probes(
            spec.auth_probes,
            runner=runner,
            executable=executable,
            timeout_seconds=timeout_seconds,
        )
        blocked_reasons.extend(auth_command_result.blocked_reasons)

    auth_mode = _auth_mode(
        spec=spec,
        installed=installed,
        env_blockers_present=env_blockers_present,
        config_result=config_result,
        auth_command_result=auth_command_result,
    )

    for blocker in env_blockers_present:
        blocked_reasons.append(f"{blocker} is set")
    blocked_reasons.extend(config_result.blocked_reasons)
    for evidence in config_result.metered_evidence:
        blocked_reasons.append(f"{evidence} references a metered route")
    for evidence in auth_command_result.metered_evidence:
        blocked_reasons.append(f"{evidence} references a metered route")

    command_result = _CommandProbeResult(version="", missing_flags=[], blocked_reasons=[])
    if executable is not None:
        command_result = _run_command_probes(
            spec.probes,
            runner=runner,
            executable=executable,
            timeout_seconds=timeout_seconds,
        )
        blocked_reasons.extend(command_result.blocked_reasons)

    for flag in command_result.missing_flags:
        blocked_reasons.append(f"missing required flag {flag}")
    if installed and spec.no_metered_candidate and auth_mode == "unknown":
        blocked_reasons.append("auth mode is unknown")
    if spec.no_metered_candidate and not spec.support_statement.no_metered_current:
        blocked_reasons.append("support statement is not current")

    no_metered_eligible = (
        spec.no_metered_candidate
        and spec.route_class == "included-plan"
        and installed
        and not blocked_reasons
    )
    return AdapterProbe(
        name=spec.name,
        binary=spec.binary,
        route_class=spec.route_class,
        installed=installed,
        no_metered_candidate=spec.no_metered_candidate,
        no_metered_eligible=no_metered_eligible,
        support_statement=spec.support_statement.status,
        support_statement_detail=spec.support_statement.to_dict(),
        version=command_result.version,
        auth_mode=auth_mode,
        auth_evidence=sorted(
            config_result.metered_evidence
            + config_result.session_evidence
            + auth_command_result.metered_evidence
            + auth_command_result.session_evidence
        ),
        config_files_checked=[probe.display_path for probe in spec.config_probes],
        config_files_found=config_result.files_found,
        missing_flags=sorted(set(command_result.missing_flags)),
        env_blockers_present=env_blockers_present,
        blocked_reasons=blocked_reasons,
    )


def _run_command(command: Sequence[str], timeout_seconds: int) -> tuple[int, str, str]:
    try:
        result = subprocess.run(
            list(command),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
            shell=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 124, "", str(exc)
    return result.returncode, result.stdout, result.stderr


def _support_statement(
    *,
    status: str,
    sources: tuple[str, ...],
    notes: str = "Planned route. Blocked until proof and eval evidence exist.",
) -> SupportStatement:
    return SupportStatement(
        status=status,
        checked_on="2026-06-30",
        sources=sources,
        required_evidence=(
            "official installed-session auth proof",
            "no API-key environment or config blockers",
            "no paid credit, overage, gateway, or API-backed route",
            "adapter-result.v1 manifest with native usage signal",
            "scratch-only write check",
            "distill eval evidence for the workload",
        ),
        no_metered_current=False,
        notes=notes,
    )


def _first_line(output: str) -> str:
    return next((line.strip() for line in output.splitlines() if line.strip()), "")


@dataclass(frozen=True)
class _CommandProbeResult:
    version: str
    missing_flags: list[str]
    blocked_reasons: list[str]


def _run_command_probes(
    probes: Sequence[CommandProbe],
    *,
    runner: CommandRunner,
    executable: str,
    timeout_seconds: int,
) -> _CommandProbeResult:
    version = ""
    missing_flags: list[str] = []
    blocked_reasons: list[str] = []
    for probe in probes:
        command = _command_with_executable(probe.command, executable)
        exit_code, stdout, stderr = runner(command, timeout_seconds)
        output = f"{stdout}\n{stderr}"
        if probe.label == "version" and exit_code == 0:
            version = _first_line(output)
        if exit_code != 0:
            blocked_reasons.append(f"{probe.label} exited {exit_code}")
        missing_flags.extend(flag for flag in probe.required_flags if flag not in output)
    return _CommandProbeResult(
        version=version,
        missing_flags=missing_flags,
        blocked_reasons=blocked_reasons,
    )


@dataclass(frozen=True)
class _ConfigScanResult:
    files_found: list[str]
    metered_evidence: list[str]
    session_evidence: list[str]
    blocked_reasons: list[str]


@dataclass(frozen=True)
class _AuthCommandResult:
    metered_evidence: list[str]
    session_evidence: list[str]
    blocked_reasons: list[str]


def _run_auth_command_probes(
    probes: Sequence[AuthCommandProbe],
    *,
    runner: CommandRunner,
    executable: str,
    timeout_seconds: int,
) -> _AuthCommandResult:
    metered_evidence: list[str] = []
    session_evidence: list[str] = []
    blocked_reasons: list[str] = []
    for probe in probes:
        command = _command_with_executable(probe.command, executable)
        exit_code, stdout, stderr = runner(command, timeout_seconds)
        if exit_code != 0:
            blocked_reasons.append(f"{probe.label} exited {exit_code}")
            continue
        try:
            keys = _json_marker_keys(stdout or stderr)
        except json.JSONDecodeError:
            blocked_reasons.append(f"{probe.label} output is not JSON")
            continue
        metered_evidence.extend(
            f"{probe.label}: {marker}"
            for marker in probe.metered_markers
            if _marker_present(marker, keys)
        )
        session_evidence.extend(
            f"{probe.label}: {marker}"
            for marker in probe.session_markers
            if _marker_present(marker, keys)
        )
    return _AuthCommandResult(
        metered_evidence=sorted(set(metered_evidence)),
        session_evidence=sorted(set(session_evidence)),
        blocked_reasons=blocked_reasons,
    )


def _command_with_executable(command: tuple[str, ...], executable: str) -> tuple[str, ...]:
    """Use the exact discovered executable for Windows probe processes."""

    if not _is_windows():
        return command
    return (executable, *command[1:])


def _is_windows() -> bool:
    return os.name == "nt"


def _scan_config_probes(probes: Sequence[ConfigProbe], home_dir: Path) -> _ConfigScanResult:
    files_found: list[str] = []
    metered_evidence: list[str] = []
    session_evidence: list[str] = []
    blocked_reasons: list[str] = []
    for probe in probes:
        path = home_dir.joinpath(*probe.relative_path)
        if not path.exists():
            continue
        files_found.append(probe.display_path)
        try:
            keys = _config_marker_keys(path)
        except (OSError, UnicodeDecodeError):
            blocked_reasons.append(f"{probe.display_path} could not be read")
            continue
        except (json.JSONDecodeError, tomllib.TOMLDecodeError):
            blocked_reasons.append(f"{probe.display_path} could not be parsed")
            continue
        metered_evidence.extend(
            f"{probe.display_path}: {marker}"
            for marker in probe.metered_markers
            if _marker_present(marker, keys)
        )
        session_evidence.extend(
            f"{probe.display_path}: {marker}"
            for marker in probe.session_markers
            if _marker_present(marker, keys)
        )
    return _ConfigScanResult(
        files_found=files_found,
        metered_evidence=sorted(set(metered_evidence)),
        session_evidence=sorted(set(session_evidence)),
        blocked_reasons=sorted(set(blocked_reasons)),
    )


def _json_marker_keys(text: str) -> set[str]:
    payload = json.loads(text)
    return _flatten_config_keys(payload)


def _config_marker_keys(path: Path) -> set[str]:
    text = path.read_text(encoding="utf-8-sig")
    suffix = path.suffix.lower()
    if suffix == ".toml":
        parsed = tomllib.loads(text)
    elif suffix == ".json":
        parsed = json.loads(text)
    else:
        return set()
    return _flatten_config_keys(parsed)


def _flatten_config_keys(value: object, prefix: str = "") -> set[str]:
    keys: set[str] = set()
    if isinstance(value, Mapping):
        for raw_key, raw_child in cast("Mapping[object, object]", value).items():  # pyright: ignore[reportUnknownVariableType]
            key_text: str = str(raw_key)
            full_key = f"{prefix}.{key_text}" if prefix else key_text
            keys.add(full_key)
            keys.update(_flatten_config_keys(raw_child, full_key))
    elif isinstance(value, list):
        for raw_item in cast(list[object], value):  # pyright: ignore[reportUnknownVariableType]
            keys.update(_flatten_config_keys(raw_item, prefix))
    elif isinstance(value, str):
        keys.add(value)
    return keys


def _marker_present(marker: str, keys: set[str]) -> bool:
    marker_lower = marker.lower()
    return any(
        key.lower() == marker_lower or key.lower().endswith(f".{marker_lower}") for key in keys
    )


def _auth_mode(
    *,
    spec: AdapterSpec,
    installed: bool,
    env_blockers_present: list[str],
    config_result: _ConfigScanResult,
    auth_command_result: _AuthCommandResult,
) -> str:
    if spec.route_class == "credit-metered":
        return "credit-metered"
    if env_blockers_present:
        return "metered-env"
    if config_result.metered_evidence:
        return "metered-config"
    if auth_command_result.metered_evidence:
        return "metered-command"
    if auth_command_result.session_evidence:
        return "session-command"
    if config_result.session_evidence:
        return "session-config"
    if not installed:
        return "not-checked"
    return "unknown"

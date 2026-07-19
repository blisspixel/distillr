# pyright: strict
"""Read-only doctor checks for candidate CLI model adapters."""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
import tomllib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from distill.doctor.adapter_manifest import adapter_result_manifest_contract
from distill.doctor.adapter_native_usage import adapter_native_usage_contract
from distill.doctor.adapter_workload import adapter_workload_contract
from distill.library.confined import read_confined_bytes, validate_confined_path
from distill.process_resources import (
    ProcessBudgetExceeded,
    assign_windows_memory_job,
    close_windows_job,
    start_bounded_pipe_head_drain,
    terminate_isolated_process_tree,
    wait_for_process_budget,
)
from distill.process_security import package_install_context, resolve_executable

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
_ADAPTER_PROBE_OUTPUT_BYTES = 256 * 1024
_ADAPTER_PROBE_TREE_MEMORY_BYTES = 512 * 1024 * 1024
_ADAPTER_CONFIG_BYTES = 1024 * 1024
_ADAPTER_AUTH_JSON_BYTES = 256 * 1024
_ADAPTER_CONFIG_MAX_DEPTH = 64
_ADAPTER_CONFIG_MAX_NODES = 10_000
_ADAPTER_CONFIG_MAX_KEY_CHARS = 512
_ADAPTER_CONFIG_MAX_PATH_CHARS = 4_096
_ADAPTER_CONFIG_MAX_VALUE_CHARS = 4_096
_ADAPTER_RESOURCE_EXIT_CODE = 124
_ADAPTER_OUTPUT_EXIT_CODE = 125
_ADAPTER_BLOCKED_PREFIX = "Distill adapter probe blocked:"

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


class _StructuredInputBlocked(ValueError):
    """Raised when auth or config input crosses a deterministic boundary."""


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
    executable = resolve_executable(spec.binary)
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


def _run_command(  # noqa: C901
    command: Sequence[str], timeout_seconds: int
) -> tuple[int, str, str]:
    trusted_cwd, child_env = package_install_context()
    process: subprocess.Popen[bytes] | None = None
    job_handle: int | None = None
    stdout_stream: Any = None
    stderr_stream: Any = None
    stdout_head: Any = None
    stderr_head: Any = None
    stdout_thread: Any = None
    stderr_thread: Any = None
    resource_reason = ""
    try:
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        process = subprocess.Popen(
            list(command),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            cwd=trusted_cwd,
            env=child_env,
            creationflags=creationflags,
            start_new_session=os.name != "nt",
        )
        stdout_stream = process.stdout
        stderr_stream = process.stderr
        if stdout_stream is None or stderr_stream is None:
            raise OSError("adapter probe did not expose diagnostic pipes")
        stdout_head, stdout_thread = start_bounded_pipe_head_drain(
            stdout_stream,
            limit=_ADAPTER_PROBE_OUTPUT_BYTES,
            thread_name="distill-adapter-stdout",
        )
        stderr_head, stderr_thread = start_bounded_pipe_head_drain(
            stderr_stream,
            limit=_ADAPTER_PROBE_OUTPUT_BYTES,
            thread_name="distill-adapter-stderr",
        )
        job_handle = assign_windows_memory_job(
            process,
            job_memory_bytes=_ADAPTER_PROBE_TREE_MEMORY_BYTES,
        )
        wait_for_process_budget(
            process,
            timeout_seconds=timeout_seconds,
            memory_limit_bytes=_ADAPTER_PROBE_TREE_MEMORY_BYTES,
        )
    except ProcessBudgetExceeded as exc:
        resource_reason = f"{_ADAPTER_BLOCKED_PREFIX} {exc}"
    except OSError:
        resource_reason = f"{_ADAPTER_BLOCKED_PREFIX} child process could not be supervised"
    finally:
        if process is not None:
            terminate_isolated_process_tree(process)
        close_windows_job(job_handle)
        for thread in (stdout_thread, stderr_thread):
            if thread is not None:
                thread.join(timeout=1)
        for stream in (stdout_stream, stderr_stream):
            if stream is not None:
                with contextlib.suppress(OSError, ValueError):
                    stream.close()
        for thread in (stdout_thread, stderr_thread):
            if thread is not None:
                thread.join(timeout=1)

    stdout, stdout_reason = _decode_probe_output(stdout_head, "stdout")
    stderr, stderr_reason = _decode_probe_output(stderr_head, "stderr")
    reasons = [reason for reason in (resource_reason, stdout_reason, stderr_reason) if reason]
    if reasons:
        if stderr:
            stderr = f"{stderr.rstrip()}\n"
        stderr += "\n".join(reasons)
    if resource_reason:
        return _ADAPTER_RESOURCE_EXIT_CODE, stdout, stderr
    if stdout_reason or stderr_reason:
        return _ADAPTER_OUTPUT_EXIT_CODE, stdout, stderr
    if process is None or not isinstance(process.returncode, int):
        return _ADAPTER_RESOURCE_EXIT_CODE, stdout, stderr
    return process.returncode, stdout, stderr


def _decode_probe_output(capture: Any, stream_name: str) -> tuple[str, str]:
    if capture is None:
        return "", ""
    raw = capture.bytes()
    try:
        output = raw.decode("utf-8")
    except UnicodeDecodeError:
        return "", f"{_ADAPTER_BLOCKED_PREFIX} {stream_name} is not valid UTF-8"
    if capture.truncated:
        return (
            output,
            (
                f"{_ADAPTER_BLOCKED_PREFIX} {stream_name} exceeded "
                f"{_ADAPTER_PROBE_OUTPUT_BYTES}-byte limit "
                f"(observed at least {capture.total_bytes} bytes)"
            ),
        )
    return output, ""


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
        if probe.label == "version":
            version = _first_line(output)
        if exit_code != 0:
            blocked_reasons.append(
                _probe_block_reason(stderr) or f"{probe.label} exited {exit_code}"
            )
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
            blocked_reasons.append(
                _probe_block_reason(stderr) or f"{probe.label} exited {exit_code}"
            )
            continue
        try:
            keys = _json_marker_keys(stdout or stderr)
        except json.JSONDecodeError:
            blocked_reasons.append(f"{probe.label} output is not JSON")
            continue
        except _StructuredInputBlocked as exc:
            blocked_reasons.append(f"{probe.label} output blocked: {exc}")
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
    """Use the exact discovered executable for every probe process."""

    return (executable, *command[1:])


def _probe_block_reason(stderr: str) -> str:
    return next(
        (
            line.strip()
            for line in stderr.splitlines()
            if line.strip().startswith(_ADAPTER_BLOCKED_PREFIX)
        ),
        "",
    )


def _scan_config_probes(probes: Sequence[ConfigProbe], home_dir: Path) -> _ConfigScanResult:
    files_found: list[str] = []
    metered_evidence: list[str] = []
    session_evidence: list[str] = []
    blocked_reasons: list[str] = []
    for probe in probes:
        path = home_dir.joinpath(*probe.relative_path)
        try:
            path.lstat()
        except FileNotFoundError:
            continue
        except OSError:
            files_found.append(probe.display_path)
            blocked_reasons.append(f"{probe.display_path} could not be inspected safely")
            continue
        files_found.append(probe.display_path)
        try:
            keys = _config_marker_keys(path, home_dir)
        except _StructuredInputBlocked as exc:
            blocked_reasons.append(f"{probe.display_path} blocked: {exc}")
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
    try:
        raw = text.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise _StructuredInputBlocked("auth JSON is not valid UTF-8") from exc
    if len(raw) > _ADAPTER_AUTH_JSON_BYTES:
        raise _StructuredInputBlocked(f"auth JSON exceeds {_ADAPTER_AUTH_JSON_BYTES}-byte limit")
    try:
        payload = json.loads(text)
    except (MemoryError, RecursionError) as exc:
        raise _StructuredInputBlocked("auth JSON parser resource limit exceeded") from exc
    return _flatten_config_keys(payload)


def _config_marker_keys(path: Path, home_dir: Path) -> set[str]:
    validated = validate_confined_path(path, home_dir, expect_directory=False)
    if validated is None or validated[1].st_nlink != 1:
        raise _StructuredInputBlocked("path is not a confined regular file")
    if validated[1].st_size > _ADAPTER_CONFIG_BYTES:
        raise _StructuredInputBlocked(f"file exceeds {_ADAPTER_CONFIG_BYTES}-byte limit")
    raw = read_confined_bytes(path, home_dir, max_bytes=_ADAPTER_CONFIG_BYTES)
    if raw is None:
        raise _StructuredInputBlocked("file could not be read safely")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise _StructuredInputBlocked("file is not valid UTF-8") from exc
    suffix = path.suffix.lower()
    try:
        if suffix == ".toml":
            parsed = tomllib.loads(text)
        elif suffix == ".json":
            parsed = json.loads(text)
        else:
            return set()
    except (MemoryError, RecursionError) as exc:
        raise _StructuredInputBlocked("config parser resource limit exceeded") from exc
    return _flatten_config_keys(parsed)


def _flatten_config_keys(value: object, prefix: str = "") -> set[str]:  # noqa: C901
    keys: set[str] = set()
    pending: list[tuple[object, str, int]] = [(value, prefix, 0)]
    visited = 0
    while pending:
        current, current_prefix, depth = pending.pop()
        visited += 1
        if visited > _ADAPTER_CONFIG_MAX_NODES:
            raise _StructuredInputBlocked("structured input node limit exceeded")
        if depth > _ADAPTER_CONFIG_MAX_DEPTH:
            raise _StructuredInputBlocked("structured input depth limit exceeded")
        if isinstance(current, Mapping):
            for raw_key, raw_child in cast("Mapping[object, object]", current).items():  # pyright: ignore[reportUnknownVariableType]
                key_text = str(raw_key)
                if len(key_text) > _ADAPTER_CONFIG_MAX_KEY_CHARS:
                    raise _StructuredInputBlocked("structured input key length limit exceeded")
                full_key = f"{current_prefix}.{key_text}" if current_prefix else key_text
                if len(full_key) > _ADAPTER_CONFIG_MAX_PATH_CHARS:
                    raise _StructuredInputBlocked("structured input path length limit exceeded")
                keys.add(full_key)
                pending.append((raw_child, full_key, depth + 1))
        elif isinstance(current, list):
            items = cast(list[object], current)  # pyright: ignore[reportUnknownVariableType]
            pending.extend((raw_item, current_prefix, depth + 1) for raw_item in items)
        elif isinstance(current, str):
            if len(current) > _ADAPTER_CONFIG_MAX_VALUE_CHARS:
                raise _StructuredInputBlocked("structured input value length limit exceeded")
            keys.add(current)
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

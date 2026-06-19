"""Read-only doctor checks for candidate CLI model adapters."""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field

__all__ = [
    "AdapterDoctorReport",
    "AdapterProbe",
    "AdapterSpec",
    "CommandProbe",
    "adapter_doctor_report",
    "adapter_specs",
]


CommandRunner = Callable[[Sequence[str], int], tuple[int, str, str]]


@dataclass(frozen=True)
class CommandProbe:
    """One read-only command needed to classify an adapter."""

    label: str
    command: tuple[str, ...]
    required_flags: tuple[str, ...] = ()


@dataclass(frozen=True)
class AdapterSpec:
    """Static policy for a candidate adapter route."""

    name: str
    binary: str
    route_class: str
    support_statement: str
    probes: tuple[CommandProbe, ...]
    env_blockers: tuple[str, ...] = ()
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
    version: str = ""
    missing_flags: list[str] = field(default_factory=list)
    env_blockers_present: list[str] = field(default_factory=list)
    blocked_reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "binary": self.binary,
            "route_class": self.route_class,
            "installed": self.installed,
            "no_metered_candidate": self.no_metered_candidate,
            "no_metered_eligible": self.no_metered_eligible,
            "support_statement": self.support_statement,
            "version": self.version,
            "missing_flags": self.missing_flags,
            "env_blockers_present": self.env_blockers_present,
            "blocked_reasons": self.blocked_reasons,
        }


@dataclass(frozen=True)
class AdapterDoctorReport:
    """Structured adapter doctor result."""

    schema_version: str
    adapters: list[AdapterProbe]

    @property
    def no_metered_ready(self) -> list[str]:
        return [probe.name for probe in self.adapters if probe.no_metered_eligible]

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "no_metered_ready": self.no_metered_ready,
            "adapters": [probe.to_dict() for probe in self.adapters],
        }


def adapter_specs() -> tuple[AdapterSpec, ...]:
    """Return candidate adapter specs in stable display order."""

    return (
        AdapterSpec(
            name="codex",
            binary="codex",
            route_class="included-plan",
            support_statement="planned",
            env_blockers=("OPENAI_API_KEY", "CODEX_API_KEY"),
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
            support_statement="planned",
            env_blockers=("ANTHROPIC_API_KEY",),
            probes=(
                CommandProbe("version", ("claude", "--version")),
                CommandProbe(
                    "print_help",
                    ("claude", "-p", "--help"),
                    ("--output-format", "--max-turns", "--no-session-persistence"),
                ),
            ),
        ),
        AdapterSpec(
            name="grok",
            binary="grok",
            route_class="included-plan",
            support_statement="planned",
            env_blockers=("XAI_API_KEY",),
            probes=(
                CommandProbe("version", ("grok", "--version")),
                CommandProbe("help", ("grok", "--help"), ("--output-format",)),
            ),
        ),
        AdapterSpec(
            name="gemini-cli",
            binary="gemini",
            route_class="included-plan",
            support_statement="planned",
            env_blockers=("GEMINI_API_KEY",),
            probes=(
                CommandProbe("version", ("gemini", "--version")),
                CommandProbe("help", ("gemini", "--help")),
            ),
        ),
        AdapterSpec(
            name="antigravity",
            binary="antigravity",
            route_class="included-plan",
            support_statement="planned",
            env_blockers=("GEMINI_API_KEY",),
            probes=(
                CommandProbe("version", ("antigravity", "--version")),
                CommandProbe("help", ("antigravity", "--help")),
            ),
        ),
        AdapterSpec(
            name="copilot",
            binary="gh",
            route_class="credit-metered",
            support_statement="credit-metered candidate",
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
    timeout_seconds: int = 5,
) -> AdapterDoctorReport:
    """Run read-only adapter checks and return a fail-closed report."""

    env = environ or os.environ
    run = runner or _run_command
    return AdapterDoctorReport(
        schema_version="adapter-doctor.v1",
        adapters=[
            _probe_adapter(spec, env=env, runner=run, timeout_seconds=timeout_seconds)
            for spec in adapter_specs()
        ],
    )


def _probe_adapter(
    spec: AdapterSpec,
    *,
    env: Mapping[str, str],
    runner: CommandRunner,
    timeout_seconds: int,
) -> AdapterProbe:
    installed = shutil.which(spec.binary) is not None
    env_blockers_present = [name for name in spec.env_blockers if env.get(name)]
    missing_flags: list[str] = []
    blocked_reasons: list[str] = []
    version = ""

    if not installed:
        blocked_reasons.append(f"{spec.binary} is not installed")
    for blocker in env_blockers_present:
        blocked_reasons.append(f"{blocker} is set")

    if installed:
        for probe in spec.probes:
            exit_code, stdout, stderr = runner(probe.command, timeout_seconds)
            output = f"{stdout}\n{stderr}"
            if probe.label == "version" and exit_code == 0:
                version = _first_line(output)
            if exit_code != 0:
                blocked_reasons.append(f"{probe.label} exited {exit_code}")
            missing_flags.extend(flag for flag in probe.required_flags if flag not in output)

    for flag in missing_flags:
        blocked_reasons.append(f"missing required flag {flag}")
    if spec.support_statement == "planned":
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
        support_statement=spec.support_statement,
        version=version,
        missing_flags=sorted(set(missing_flags)),
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
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 124, "", str(exc)
    return result.returncode, result.stdout, result.stderr


def _first_line(output: str) -> str:
    return next((line.strip() for line in output.splitlines() if line.strip()), "")

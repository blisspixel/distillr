"""Command-plan templates for future CLI adapter workload runs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from distill.doctor.adapter_workload import AdapterWorkloadPackage
from distill.doctor.adapters import AdapterProbe

__all__ = [
    "AdapterCommandPlan",
    "plan_adapter_command",
]


@dataclass(frozen=True)
class AdapterCommandPlan:
    """Exact argv shape plus blockers for a future adapter workload run."""

    adapter: str
    workload: str
    argv: tuple[str, ...] = ()
    blocked_reasons: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.argv) and not self.blocked_reasons

    def to_dict(self) -> dict[str, Any]:
        return {
            "adapter": self.adapter,
            "workload": self.workload,
            "argv": list(self.argv),
            "blocked_reasons": self.blocked_reasons,
            "ok": self.ok,
        }


def plan_adapter_command(
    adapter: str,
    workload: AdapterWorkloadPackage,
    *,
    probe: AdapterProbe | None = None,
) -> AdapterCommandPlan:
    """Return the future exact argv for an adapter workload plus blockers."""

    blocked_reasons: list[str] = []
    if probe is not None:
        blocked_reasons.extend(probe.blocked_reasons)
        if not probe.installed:
            blocked_reasons.append(f"{adapter} is not installed")
        if probe.missing_flags:
            blocked_reasons.append(
                "adapter missing required flags: " + ", ".join(probe.missing_flags)
            )
        if not probe.no_metered_eligible:
            blocked_reasons.append("adapter is not no-metered eligible")

    if adapter == "codex":
        argv, template_blockers = _codex_command(workload)
        blocked_reasons.extend(template_blockers)
        return AdapterCommandPlan(
            adapter=adapter,
            workload=workload.workload,
            argv=argv,
            blocked_reasons=_dedupe(blocked_reasons),
        )

    blocked_reasons.append(f"adapter command template is not implemented: {adapter}")
    return AdapterCommandPlan(
        adapter=adapter,
        workload=workload.workload,
        blocked_reasons=_dedupe(blocked_reasons),
    )


def _codex_command(workload: AdapterWorkloadPackage) -> tuple[tuple[str, ...], list[str]]:
    blocked_reasons: list[str] = []
    if workload.command_class != "read-only":
        blocked_reasons.append("codex command template currently supports read-only workloads only")
    if not workload.output_schema_path:
        blocked_reasons.append("codex command template requires output_schema_path")
    blocked_reasons.append("adapter-specific capture wiring is not implemented")
    schema_path = workload.output_schema_path or "schemas/result.json"
    return (
        (
            "codex",
            "exec",
            "--sandbox",
            "read-only",
            "--ephemeral",
            "--json",
            "--output-schema",
            schema_path,
            "--output-last-message",
            "result.txt",
            "-",
        ),
        blocked_reasons,
    )


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result

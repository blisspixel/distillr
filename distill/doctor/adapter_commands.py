"""Command-plan templates for future CLI adapter workload runs."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from distill.doctor.adapter_workload import AdapterWorkloadPackage
from distill.doctor.adapters import AdapterProbe

__all__ = [
    "AdapterCommandError",
    "AdapterCommandPlan",
    "inline_adapter_command_schema",
    "plan_adapter_command",
]

CLAUDE_SCHEMA_INLINE_BLOCKER = "claude command template requires schema inlining before execution"


class AdapterCommandError(ValueError):
    """Raised when a command plan cannot be materialized safely."""


@dataclass(frozen=True)
class AdapterCommandPlan:
    """Exact argv shape plus blockers for a future adapter workload run."""

    adapter: str
    workload: str
    argv: tuple[str, ...] = ()
    stdin_path: str = ""
    schema_path: str = ""
    result_text_path: str = ""
    allowed_new_files: tuple[str, ...] = ()
    blocked_reasons: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.argv) and not self.blocked_reasons

    def to_dict(self) -> dict[str, Any]:
        return {
            "adapter": self.adapter,
            "workload": self.workload,
            "argv": list(self.argv),
            "stdin_path": self.stdin_path,
            "schema_path": self.schema_path,
            "result_text_path": self.result_text_path,
            "allowed_new_files": list(self.allowed_new_files),
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
    if probe is None:
        blocked_reasons.append("adapter doctor probe is required")
    else:
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
        argv, template_blockers, metadata = _codex_command(workload)
        blocked_reasons.extend(template_blockers)
        return AdapterCommandPlan(
            adapter=adapter,
            workload=workload.workload,
            argv=argv,
            blocked_reasons=_dedupe(blocked_reasons),
            **metadata,
        )

    if adapter == "claude":
        argv, template_blockers, metadata = _claude_command(workload)
        blocked_reasons.extend(template_blockers)
        return AdapterCommandPlan(
            adapter=adapter,
            workload=workload.workload,
            argv=argv,
            blocked_reasons=_dedupe(blocked_reasons),
            **metadata,
        )

    if adapter == "grok":
        argv, template_blockers, metadata = _grok_command(workload)
        blocked_reasons.extend(template_blockers)
        return AdapterCommandPlan(
            adapter=adapter,
            workload=workload.workload,
            argv=argv,
            blocked_reasons=_dedupe(blocked_reasons),
            **metadata,
        )

    blocked_reasons.append(f"adapter command template is not implemented: {adapter}")
    return AdapterCommandPlan(
        adapter=adapter,
        workload=workload.workload,
        blocked_reasons=_dedupe(blocked_reasons),
    )


def inline_adapter_command_schema(
    plan: AdapterCommandPlan,
    *,
    scratch_root: Path,
) -> AdapterCommandPlan:
    """Inline a staged schema file into a command plan when the adapter requires it."""

    if plan.adapter != "claude" or not plan.schema_path:
        return plan
    if CLAUDE_SCHEMA_INLINE_BLOCKER not in plan.blocked_reasons:
        return plan
    schema_payload = _load_schema_payload(scratch_root, Path(plan.schema_path))
    schema_json = json.dumps(schema_payload, separators=(",", ":"), sort_keys=True)
    blocked_reasons = [
        reason for reason in plan.blocked_reasons if reason != CLAUDE_SCHEMA_INLINE_BLOCKER
    ]
    return replace(
        plan,
        argv=_insert_before(plan.argv, "--tools", ("--json-schema", schema_json)),
        blocked_reasons=blocked_reasons,
    )


def _codex_command(
    workload: AdapterWorkloadPackage,
) -> tuple[tuple[str, ...], list[str], dict[str, Any]]:
    blocked_reasons: list[str] = []
    if workload.command_class != "read-only":
        blocked_reasons.append("codex command template currently supports read-only workloads only")
    if not workload.output_schema_path:
        blocked_reasons.append("codex command template requires output_schema_path")
    blocked_reasons.append("native usage collection is not implemented: codex")
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
        {
            "stdin_path": workload.prompt_path,
            "schema_path": schema_path,
            "result_text_path": "result.txt",
            "allowed_new_files": ("result.txt",),
        },
    )


def _claude_command(
    workload: AdapterWorkloadPackage,
) -> tuple[tuple[str, ...], list[str], dict[str, Any]]:
    blocked_reasons: list[str] = []
    if workload.command_class != "read-only":
        blocked_reasons.append(
            "claude command template currently supports read-only workloads only"
        )
    if not workload.output_schema_path:
        blocked_reasons.append("claude command template requires output_schema_path")
    blocked_reasons.append(CLAUDE_SCHEMA_INLINE_BLOCKER)
    blocked_reasons.append("native usage collection is not implemented: claude")
    schema_path = workload.output_schema_path or "schemas/result.json"
    return (
        (
            "claude",
            "-p",
            "--input-format",
            "text",
            "--output-format",
            "json",
            "--tools",
            "",
            "--no-session-persistence",
        ),
        blocked_reasons,
        {
            "stdin_path": workload.prompt_path,
            "schema_path": schema_path,
            "result_text_path": "result.txt",
            "allowed_new_files": ("result.txt",),
        },
    )


def _grok_command(
    workload: AdapterWorkloadPackage,
) -> tuple[tuple[str, ...], list[str], dict[str, Any]]:
    blocked_reasons: list[str] = []
    if workload.command_class != "read-only":
        blocked_reasons.append("grok command template currently supports read-only workloads only")
    if not workload.output_schema_path:
        blocked_reasons.append("grok command template requires output_schema_path")
    blocked_reasons.append("grok command template does not enforce output_schema_path natively")
    blocked_reasons.append("native usage collection is not implemented: grok")
    return (
        (
            "grok",
            "--no-auto-update",
            "--prompt-file",
            workload.prompt_path,
            "--output-format",
            "json",
            "--cwd",
            ".",
            "--disable-web-search",
            "--no-subagents",
            "--no-memory",
            "--max-turns",
            "1",
        ),
        blocked_reasons,
        {
            "schema_path": workload.output_schema_path or "schemas/result.json",
            "result_text_path": "result.txt",
            "allowed_new_files": ("result.txt",),
        },
    )


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _load_schema_payload(root: Path, schema_path: Path) -> Mapping[str, Any]:
    path = _resolve_scratch_file(root, schema_path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise AdapterCommandError(f"adapter command schema is invalid JSON: {schema_path}") from exc
    if not isinstance(payload, Mapping):
        raise AdapterCommandError(f"adapter command schema must be a JSON object: {schema_path}")
    return payload


def _resolve_scratch_file(root: Path, path: Path) -> Path:
    scratch_root = root.resolve()
    candidate = (scratch_root / path).resolve()
    try:
        candidate.relative_to(scratch_root)
    except ValueError as exc:
        raise AdapterCommandError(
            f"adapter command path escapes scratch workspace: {path}"
        ) from exc
    return candidate


def _insert_before(
    argv: tuple[str, ...],
    marker: str,
    inserted: tuple[str, ...],
) -> tuple[str, ...]:
    try:
        index = argv.index(marker)
    except ValueError:
        return (*argv, *inserted)
    return (*argv[:index], *inserted, *argv[index:])

"""Run recurring research profile candidates with durable state."""

from __future__ import annotations

import json
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from hashlib import blake2s
from pathlib import Path
from typing import Any

from distill.library.paths import atomic_write_text, sanitize_path_component
from distill.pipeline.profile_preview import (
    ProfilePreviewCandidate,
    ProfilePreviewResult,
    command_text,
)

__all__ = [
    "CommandExecution",
    "ProfileRunCommand",
    "ProfileRunEvent",
    "ProfileRunResult",
    "execute_command",
    "profile_run_state_path",
    "run_profile_preview",
]

_COMPLETABLE_KINDS = frozenset({"feed_item", "youtube_video"})
_STATE_SCHEMA_VERSION = "profile-run-state.v1"
_RESULT_SCHEMA_VERSION = "profile-run.v1"
_OUTPUT_TAIL_CHARS = 4000


@dataclass(frozen=True)
class CommandExecution:
    """Subprocess outcome captured for state and JSON callers."""

    exit_code: int
    elapsed_seconds: float
    stdout_tail: str = ""
    stderr_tail: str = ""
    timed_out: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "exit_code": self.exit_code,
            "elapsed_seconds": round(self.elapsed_seconds, 3),
            "stdout_tail": self.stdout_tail,
            "stderr_tail": self.stderr_tail,
            "timed_out": self.timed_out,
        }


CommandExecutor = Callable[[list[str], int], CommandExecution]


@dataclass(frozen=True)
class ProfileRunCommand:
    """One preview candidate prepared for a profile run."""

    key: str
    kind: str
    title: str
    source_label: str
    command: list[str]
    resume_policy: str
    status: str
    skip_reason: str = ""
    execution: CommandExecution | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "key": self.key,
            "kind": self.kind,
            "title": self.title,
            "source_label": self.source_label,
            "command": self.command,
            "command_text": command_text(self.command),
            "resume_policy": self.resume_policy,
            "status": self.status,
            "skip_reason": self.skip_reason,
        }
        if self.execution is not None:
            payload["execution"] = self.execution.to_dict()
        return payload


@dataclass(frozen=True)
class ProfileRunEvent:
    """One attempted command in a profile run."""

    key: str
    kind: str
    title: str
    command: list[str]
    resume_policy: str
    status: str
    attempted_at: str
    execution: CommandExecution

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "kind": self.kind,
            "title": self.title,
            "command": self.command,
            "command_text": command_text(self.command),
            "resume_policy": self.resume_policy,
            "status": self.status,
            "attempted_at": self.attempted_at,
            "execution": self.execution.to_dict(),
        }


@dataclass(frozen=True)
class ProfileRunResult:
    """Structured output for CLI JSON and external loops."""

    schema_version: str
    profile: str
    topic: str
    cost_mode: str
    state_path: str
    approved: bool
    executed: bool
    fresh_item_limit: int
    ordering: str
    commands: list[ProfileRunCommand] = field(default_factory=list)
    events: list[ProfileRunEvent] = field(default_factory=list)
    warnings: list[dict[str, str]] = field(default_factory=list)

    @property
    def selected_count(self) -> int:
        return sum(1 for command in self.commands if command.status != "skipped")

    @property
    def skipped_count(self) -> int:
        return sum(1 for command in self.commands if command.status == "skipped")

    @property
    def succeeded_count(self) -> int:
        return sum(1 for event in self.events if event.status == "succeeded")

    @property
    def failed_count(self) -> int:
        return sum(1 for event in self.events if event.status == "failed")

    @property
    def pending_count(self) -> int:
        if self.approved:
            return 0
        return self.selected_count

    @property
    def health_status(self) -> str:
        if self.failed_count:
            return "failed"
        if self.selected_count == 0:
            return "complete"
        if not self.approved:
            return "approval_required"
        return "ok"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "profile": self.profile,
            "topic": self.topic,
            "cost_mode": self.cost_mode,
            "state_path": self.state_path,
            "approved": self.approved,
            "executed": self.executed,
            "fresh_item_limit": self.fresh_item_limit,
            "ordering": self.ordering,
            "candidate_count": len(self.commands),
            "selected_count": self.selected_count,
            "skipped_count": self.skipped_count,
            "pending_count": self.pending_count,
            "succeeded_count": self.succeeded_count,
            "failed_count": self.failed_count,
            "health": {
                "status": self.health_status,
                "warnings": len(self.warnings),
            },
            "commands": [command.to_dict() for command in self.commands],
            "events": [event.to_dict() for event in self.events],
            "warnings": self.warnings,
        }


def profile_run_state_path(library_dir: Path, profile_name: str) -> Path:
    """Return the durable run-state path for one recurring profile."""

    safe_name = sanitize_path_component(profile_name)
    return library_dir / ".distill" / "profiles" / safe_name / "run_state.json"


def execute_command(command: list[str], timeout_seconds: int) -> CommandExecution:
    """Run one command with shell disabled and bounded captured output."""

    start = time.monotonic()
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
        return CommandExecution(
            exit_code=completed.returncode,
            elapsed_seconds=time.monotonic() - start,
            stdout_tail=_tail(completed.stdout),
            stderr_tail=_tail(completed.stderr),
        )
    except FileNotFoundError as exc:
        return CommandExecution(
            exit_code=127,
            elapsed_seconds=time.monotonic() - start,
            stderr_tail=str(exc),
        )
    except subprocess.TimeoutExpired as exc:
        return CommandExecution(
            exit_code=124,
            elapsed_seconds=time.monotonic() - start,
            stdout_tail=_tail(_coerce_text(exc.stdout)),
            stderr_tail=_tail(_coerce_text(exc.stderr) or f"Timed out after {timeout_seconds}s"),
            timed_out=True,
        )


def run_profile_preview(
    preview: ProfilePreviewResult,
    *,
    library_dir: Path,
    approved: bool,
    timeout_seconds: int = 1800,
    executor: CommandExecutor = execute_command,
) -> ProfileRunResult:
    """Execute or plan the commands from a profile preview."""

    state_path = profile_run_state_path(library_dir, preview.profile)
    state = _load_state(state_path, profile=preview.profile, topic=preview.topic)
    commands = _build_commands(preview.candidates, completed=_completed_keys(state))
    events: list[ProfileRunEvent] = []

    if approved:
        state["profile"] = preview.profile
        state["topic"] = preview.topic
        state["updated_at"] = _now_iso()
        state["last_run_at"] = state["updated_at"]
        state.setdefault("completed", {})
        state.setdefault("last_success", {})
        state.setdefault("last_failure", {})
        state.setdefault("attempts", [])
        _save_state(state_path, state)

        updated_commands: list[ProfileRunCommand] = []
        for item in commands:
            if item.status == "skipped":
                updated_commands.append(item)
                continue
            execution = executor(item.command, timeout_seconds)
            status = "succeeded" if execution.exit_code == 0 else "failed"
            event = ProfileRunEvent(
                key=item.key,
                kind=item.kind,
                title=item.title,
                command=item.command,
                resume_policy=item.resume_policy,
                status=status,
                attempted_at=_now_iso(),
                execution=execution,
            )
            events.append(event)
            updated = replace(item, status=status, execution=execution)
            updated_commands.append(updated)
            _record_event(state, event)
            _save_state(state_path, state)
        commands = updated_commands

    return ProfileRunResult(
        schema_version=_RESULT_SCHEMA_VERSION,
        profile=preview.profile,
        topic=preview.topic,
        cost_mode=preview.cost_mode,
        state_path=str(state_path),
        approved=approved,
        executed=approved,
        fresh_item_limit=preview.fresh_item_limit,
        ordering=preview.ordering,
        commands=commands,
        events=events,
        warnings=[warning.to_dict() for warning in preview.warnings],
    )


def _build_commands(
    candidates: list[ProfilePreviewCandidate],
    *,
    completed: set[str],
) -> list[ProfileRunCommand]:
    commands: list[ProfileRunCommand] = []
    for candidate in candidates:
        key = _candidate_key(candidate)
        resume_policy = _resume_policy(candidate)
        skipped = resume_policy == "complete-on-success" and key in completed
        commands.append(
            ProfileRunCommand(
                key=key,
                kind=candidate.kind,
                title=candidate.title,
                source_label=candidate.source_label,
                command=list(candidate.command),
                resume_policy=resume_policy,
                status="skipped" if skipped else "pending",
                skip_reason="completed" if skipped else "",
            )
        )
    return commands


def _candidate_key(candidate: ProfilePreviewCandidate) -> str:
    if candidate.identity:
        return f"{candidate.kind}:{candidate.identity}"
    raw = json.dumps(candidate.command, ensure_ascii=True, separators=(",", ":"))
    digest = blake2s(raw.encode("utf-8"), digest_size=8).hexdigest()
    return f"{candidate.kind}:command:{digest}"


def _resume_policy(candidate: ProfilePreviewCandidate) -> str:
    if candidate.kind in _COMPLETABLE_KINDS and "--preview" not in candidate.command:
        return "complete-on-success"
    return "repeat-each-run"


def _load_state(path: Path, *, profile: str, topic: str) -> dict[str, Any]:
    if not path.exists():
        return _empty_state(profile, topic)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Profile run state is not parseable: {path}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"Profile run state must be a JSON object: {path}")
    if data.get("schema_version") != _STATE_SCHEMA_VERSION:
        raise ValueError(f"Unsupported profile run state schema in {path}")
    data.setdefault("profile", profile)
    data.setdefault("topic", topic)
    data.setdefault("completed", {})
    data.setdefault("last_success", {})
    data.setdefault("last_failure", {})
    data.setdefault("attempts", [])
    return data


def _empty_state(profile: str, topic: str) -> dict[str, Any]:
    now = _now_iso()
    return {
        "schema_version": _STATE_SCHEMA_VERSION,
        "profile": profile,
        "topic": topic,
        "created_at": now,
        "updated_at": now,
        "completed": {},
        "last_success": {},
        "last_failure": {},
        "attempts": [],
    }


def _save_state(path: Path, state: dict[str, Any]) -> None:
    state["updated_at"] = _now_iso()
    atomic_write_text(path, json.dumps(state, indent=2, sort_keys=True) + "\n")


def _completed_keys(state: dict[str, Any]) -> set[str]:
    completed = state.get("completed", {})
    if not isinstance(completed, dict):
        return set()
    return {str(key) for key in completed}


def _record_event(state: dict[str, Any], event: ProfileRunEvent) -> None:
    payload = event.to_dict()
    state.setdefault("attempts", []).append(payload)
    if event.status == "succeeded":
        state.setdefault("last_success", {})[event.key] = payload
        state.setdefault("last_failure", {}).pop(event.key, None)
        if event.resume_policy == "complete-on-success":
            state.setdefault("completed", {})[event.key] = {
                "completed_at": event.attempted_at,
                "command": event.command,
                "exit_code": event.execution.exit_code,
            }
    else:
        state.setdefault("last_failure", {})[event.key] = payload


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _tail(value: str) -> str:
    if len(value) <= _OUTPUT_TAIL_CHARS:
        return value
    return value[-_OUTPUT_TAIL_CHARS:]


def _coerce_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value

# pyright: strict
"""Run recurring research profile candidates with durable state."""

from __future__ import annotations

import json
import math
import secrets
import time
from collections.abc import Callable, Generator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from hashlib import blake2s
from pathlib import Path
from typing import Any, BinaryIO, cast

from distill.library.locking import exclusive_file_lock, open_lock_file
from distill.library.okf import okf_bundle_output_dir, validate_okf_bundle
from distill.library.paths import sanitize_path_component
from distill.parsing import parse_bounded_json_int
from distill.pipeline.costs import PROFILE_RECEIPT_ENV, CostTracker, save_run_log
from distill.pipeline.next_actions import NextAction
from distill.pipeline.profile_actions import profile_next_actions as _profile_next_actions
from distill.pipeline.profile_execution import (
    CommandExecution,
    CommandExecutor,
    execute_command,
    validate_profile_timeout,
)
from distill.pipeline.profile_execution import subprocess as subprocess
from distill.pipeline.profile_preview import (
    ProfilePreviewCandidate,
    ProfilePreviewResult,
    command_text,
)
from distill.pipeline.profile_state import (
    completed_keys as _completed_keys,
)
from distill.pipeline.profile_state import (
    load_profile_state,
    profile_state_shape_error,
    read_profile_state_document,
    record_profile_event,
    save_profile_state,
)
from distill.pipeline.profile_state import (
    prune_inactive_event_state as _prune_inactive_event_state,
)

__all__ = [
    "CommandExecution",
    "ProfileRunCommand",
    "ProfileRunEvent",
    "ProfileRunResult",
    "execute_command",
    "profile_run_state_path",
    "profile_state_shape_error",
    "read_profile_state_document",
    "run_profile_preview",
]

_COMPLETABLE_KINDS = frozenset({"feed_item", "youtube_video"})
_RESULT_SCHEMA_VERSION = "profile-run.v1"
_MAX_COST_APPEND_BYTES = 10_000_000
_PROFILE_LOCK_TIMEOUT_SECONDS = 1.0


@dataclass(frozen=True)
class _CostLogCheckpoint:
    exists: bool
    device: int = 0
    inode: int = 0
    size: int = 0


class _ProfileBusyError(Exception):
    """Signal that another process holds the profile execution lock."""


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
        payload: dict[str, Any] = {
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
    generated_at: str
    state_path: str
    approved: bool
    executed: bool
    fresh_item_limit: int
    ordering: str
    busy: bool = False
    max_metered_usd: float = 0.0
    metered_spend_usd: float = 0.0
    metered_spend_verified: bool = True
    commands: list[ProfileRunCommand] = field(default_factory=list[ProfileRunCommand])
    events: list[ProfileRunEvent] = field(default_factory=list[ProfileRunEvent])
    next_actions: list[NextAction] = field(default_factory=list[NextAction])
    warnings: list[dict[str, str]] = field(default_factory=list[dict[str, str]])
    last_run: dict[str, object] = field(default_factory=dict[str, object])
    okf_bundle_required: bool = False
    okf_bundle_dir: str = ""
    okf_bundle_valid: bool = False

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
        if self.busy:
            return self.selected_count
        if self.approved:
            return 0
        return self.selected_count

    @property
    def health_status(self) -> str:
        if self.busy:
            return "busy"
        durable_status = self.last_run.get("status")
        if not self.approved and durable_status in {
            "failed",
            "output_failed",
            "budget_unverified",
            "budget_exceeded",
        }:
            return str(durable_status)
        if not self.metered_spend_verified:
            return "budget_unverified"
        if self.metered_spend_usd > self.max_metered_usd:
            return "budget_exceeded"
        if self.failed_count:
            return "failed"
        if (
            self.okf_bundle_required
            and not self.okf_bundle_valid
            and (
                self.approved or self.last_run.get("status") in {"ok", "complete", "output_failed"}
            )
        ):
            return "output_failed"
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
            "generated_at": self.generated_at,
            "state_path": self.state_path,
            "approved": self.approved,
            "executed": self.executed,
            "busy": self.busy,
            "fresh_item_limit": self.fresh_item_limit,
            "ordering": self.ordering,
            "max_metered_usd": self.max_metered_usd,
            "metered_spend_usd": round(self.metered_spend_usd, 6),
            "metered_spend_verified": self.metered_spend_verified,
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
            "next_actions": [action.to_dict() for action in self.next_actions],
            "warnings": self.warnings,
            "last_run": self.last_run,
            "okf_bundle_required": self.okf_bundle_required,
            "okf_bundle_dir": self.okf_bundle_dir,
            "okf_bundle_valid": self.okf_bundle_valid,
        }


def profile_run_state_path(library_dir: Path, profile_name: str) -> Path:
    """Return the durable run-state path for one recurring profile."""

    safe_name = sanitize_path_component(profile_name)
    if safe_name != profile_name:
        raise ValueError("profile_name must be a canonical cross-platform path component")
    return library_dir / ".distill" / "profiles" / safe_name / "run_state.json"


def _effective_profile_command(
    command: list[str],
    *,
    cost_mode: str,
    remaining_budget: float,
) -> list[str]:
    if cost_mode == "no-metered":
        return _with_cost_mode(command, "no-metered")
    if remaining_budget > 0:
        return list(command)
    return _with_cost_mode(command, "no-metered")


def _with_cost_mode(command: list[str], cost_mode: str) -> list[str]:
    updated = list(command)
    if not updated or updated[0] != "distill":
        return updated
    for index, argument in enumerate(updated[1:], start=1):
        if argument == "--cost-mode" and index + 1 < len(updated):
            updated[index + 1] = cost_mode
            return updated
        if argument.startswith("--cost-mode="):
            updated[index] = f"--cost-mode={cost_mode}"
            return updated
    updated[1:1] = ["--cost-mode", cost_mode]
    return updated


def _profile_budget_environment(
    command: list[str],
    *,
    remaining_budget: float,
    workflow_budgets_usd: Mapping[str, float] | None,
) -> dict[str, str]:
    command_name = _distill_command_name(command)
    if not command_name:
        return {}
    budgets: dict[str, float] = {}
    for key, value in (workflow_budgets_usd or {}).items():
        normalized = _finite_nonnegative_float(value)
        if key and normalized is not None:
            budgets[key] = normalized
    configured = budgets.get(command_name)
    budgets[command_name] = (
        min(configured, remaining_budget) if configured is not None else remaining_budget
    )
    serialized = ",".join(f"{key}={budgets[key]:.12g}" for key in sorted(budgets))
    return {"DISTILL_COST_WORKFLOW_BUDGETS": serialized}


def _distill_command_name(command: list[str]) -> str:
    index = 1
    while index < len(command):
        argument = command[index]
        if argument == "--cost-mode":
            index += 2
            continue
        if argument.startswith("--cost-mode=") or argument == "--json":
            index += 1
            continue
        return "" if argument.startswith("-") else argument.strip().lower()
    return ""


def _distill_cost_mode(command: list[str]) -> str:
    for index, argument in enumerate(command[1:], start=1):
        if argument == "--cost-mode" and index + 1 < len(command):
            return command[index + 1]
        if argument.startswith("--cost-mode="):
            return argument.partition("=")[2]
    return ""


def _cost_log_checkpoint(path: Path) -> _CostLogCheckpoint | None:
    try:
        file_stat = path.stat()
    except FileNotFoundError:
        return _CostLogCheckpoint(exists=False)
    except OSError:
        return None
    return _CostLogCheckpoint(
        exists=True,
        device=file_stat.st_dev,
        inode=file_stat.st_ino,
        size=file_stat.st_size,
    )


def _appended_cost(
    path: Path,
    checkpoint: _CostLogCheckpoint | None,
    *,
    receipt_id: str,
    require_receipt: bool,
) -> tuple[float, bool]:
    if checkpoint is None:
        return 0.0, False
    append = _read_cost_log_append(path, checkpoint)
    if append is None:
        return 0.0, False
    content, append_complete = append
    return _parse_cost_log_append(
        content,
        receipt_id=receipt_id,
        require_receipt=require_receipt,
        append_complete=append_complete,
    )


def _read_cost_log_append(path: Path, checkpoint: _CostLogCheckpoint) -> tuple[bytes, bool] | None:
    try:
        current = path.stat()
    except FileNotFoundError:
        return None if checkpoint.exists else (b"", True)
    except OSError:
        return None
    if checkpoint.exists and (
        current.st_dev != checkpoint.device
        or current.st_ino != checkpoint.inode
        or current.st_size < checkpoint.size
    ):
        return None
    appended_size = current.st_size - checkpoint.size
    try:
        with path.open("rb") as stream:
            stream.seek(checkpoint.size)
            content = stream.read(_MAX_COST_APPEND_BYTES + 1)
    except OSError:
        return None
    complete = appended_size <= _MAX_COST_APPEND_BYTES and len(content) == appended_size
    return content[:_MAX_COST_APPEND_BYTES], complete


def _parse_cost_log_append(
    content: bytes,
    *,
    receipt_id: str,
    require_receipt: bool,
    append_complete: bool,
) -> tuple[float, bool]:
    if not content:
        return 0.0, append_complete and not require_receipt
    matched_receipt = False
    tracker_costs: dict[str, float] = {}
    total = 0.0
    verified = append_complete and content.endswith(b"\n")
    lines = content.split(b"\n")
    if lines and not lines[-1]:
        lines.pop()
    for raw_line in lines:
        if not raw_line:
            continue
        try:
            line = raw_line.removesuffix(b"\r").decode("utf-8")
            receipt_cost = _validated_receipt_cost(
                json.loads(line, parse_int=parse_bounded_json_int), receipt_id
            )
        except (OverflowError, TypeError, UnicodeDecodeError, ValueError):
            verified = False
            continue
        if receipt_cost is None:
            continue
        matched_receipt = True
        tracker_id, cost = receipt_cost
        previous = tracker_costs.get(tracker_id, 0.0)
        if cost <= previous:
            continue
        next_total = total + (cost - previous)
        if not math.isfinite(next_total):
            return total, False
        total = next_total
        tracker_costs[tracker_id] = cost
    return total, verified and (matched_receipt or not require_receipt)


def _validated_receipt_cost(row: object, receipt_id: str) -> tuple[str, float] | None:
    if not isinstance(row, dict):
        raise ValueError("cost ledger row must be an object")
    mapping = cast(dict[str, object], row)
    if mapping.get("profile_receipt_id") != receipt_id:
        return None
    tracker_id = _validated_receipt_tracker_id(mapping.get("profile_receipt_tracker_id"))
    cost = _validated_receipt_float(mapping.get("profile_receipt_cost_usd"))
    return tracker_id, cost


def _validated_receipt_tracker_id(value: object) -> str:
    if not isinstance(value, str) or len(value) != 32:
        raise ValueError("invalid profile receipt tracker id")
    if any(character not in "0123456789abcdef" for character in value):
        raise ValueError("invalid profile receipt tracker id")
    return value


def _validated_receipt_float(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError("invalid profile receipt cost")
    cost = float(value)
    if not math.isfinite(cost) or cost < 0:
        raise ValueError("invalid profile receipt cost")
    return cost


def _is_finite_nonnegative_number(value: object) -> bool:
    return _finite_nonnegative_float(value) is not None


def _finite_nonnegative_float(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    try:
        normalized = float(value)
    except OverflowError:
        return None
    if not math.isfinite(normalized) or normalized < 0:
        return None
    return normalized


def run_profile_preview(
    preview: ProfilePreviewResult,
    *,
    library_dir: Path,
    approved: bool,
    profile_ref: str = "",
    timeout_seconds: int = 1800,
    executor: CommandExecutor = execute_command,
    workflow_budgets_usd: Mapping[str, float] | None = None,
    result_finalizer: Callable[[ProfileRunResult], ProfileRunResult] | None = None,
) -> ProfileRunResult:
    """Execute or plan the commands from a profile preview."""

    validate_profile_timeout(timeout_seconds)
    if not approved:
        return _run_profile_preview_unlocked(
            preview,
            library_dir=library_dir,
            approved=False,
            profile_ref=profile_ref,
            timeout_seconds=timeout_seconds,
            executor=executor,
            workflow_budgets_usd=workflow_budgets_usd,
        )

    state_path = profile_run_state_path(library_dir, preview.profile)
    lock_path = state_path.with_name("run.lock")
    try:
        with (
            open_lock_file(lock_path) as lock_file,
            _profile_execution_lock(lock_file, profile=preview.profile),
        ):
            return _run_profile_preview_unlocked(
                preview,
                library_dir=library_dir,
                approved=True,
                profile_ref=profile_ref,
                timeout_seconds=timeout_seconds,
                executor=executor,
                workflow_budgets_usd=workflow_budgets_usd,
                result_finalizer=result_finalizer,
            )
    except _ProfileBusyError:
        return _busy_profile_run_result(
            preview,
            library_dir=library_dir,
            profile_ref=profile_ref or preview.profile,
        )


@contextmanager
def _profile_execution_lock(lock_file: BinaryIO, *, profile: str) -> Generator[None]:
    acquired = False
    try:
        with exclusive_file_lock(
            lock_file,
            timeout_seconds=_PROFILE_LOCK_TIMEOUT_SECONDS,
            timeout_message=f"Profile {profile!r} is already running",
        ):
            acquired = True
            yield
    except TimeoutError as exc:
        if acquired:
            raise
        raise _ProfileBusyError from exc


def _run_profile_preview_unlocked(
    preview: ProfilePreviewResult,
    *,
    library_dir: Path,
    approved: bool,
    profile_ref: str = "",
    timeout_seconds: int = 1800,
    executor: CommandExecutor = execute_command,
    workflow_budgets_usd: Mapping[str, float] | None = None,
    result_finalizer: Callable[[ProfileRunResult], ProfileRunResult] | None = None,
) -> ProfileRunResult:
    """Run a preview while the caller holds its profile lock when approved."""

    if not _is_finite_nonnegative_number(preview.max_metered_usd):
        raise ValueError("profile max_metered_usd must be a finite nonnegative number")

    state_path = profile_run_state_path(library_dir, preview.profile)
    state = _load_state(state_path, profile=preview.profile, topic=preview.topic)
    commands = _build_commands(preview.candidates, completed=_completed_keys(state))
    events: list[ProfileRunEvent] = []
    warnings = [warning.to_dict() for warning in preview.warnings]
    metered_spend = 0.0
    metered_spend_verified = True
    cost_log_path = library_dir / ".distill" / "cost_log.jsonl"
    started = time.monotonic()
    run_started_at = ""

    if approved:
        _prune_inactive_event_state(state, active_keys={command.key for command in commands})
        run_started_at = _now_iso()
        state["profile"] = preview.profile
        state["topic"] = preview.topic
        state["updated_at"] = run_started_at
        state["last_started_at"] = run_started_at
        state["last_run"] = _last_run_state(
            status="running",
            max_metered_usd=preview.max_metered_usd,
            metered_spend_usd=0.0,
            metered_spend_verified=False,
            started_at=run_started_at,
        )
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
            remaining_budget = (
                max(0.0, preview.max_metered_usd - metered_spend) if metered_spend_verified else 0.0
            )
            effective_command = _effective_profile_command(
                item.command,
                cost_mode=preview.cost_mode,
                remaining_budget=remaining_budget,
            )
            metered_permitted = (
                remaining_budget > 0 and _distill_cost_mode(effective_command) != "no-metered"
            )
            receipt_id = secrets.token_hex(32)
            cost_log_checkpoint = _cost_log_checkpoint(cost_log_path)
            environment = {PROFILE_RECEIPT_ENV: receipt_id}
            if metered_permitted:
                environment.update(
                    _profile_budget_environment(
                        effective_command,
                        remaining_budget=remaining_budget,
                        workflow_budgets_usd=workflow_budgets_usd,
                    )
                )
            execution = executor(
                effective_command,
                timeout_seconds,
                environment=environment,
            )
            appended_spend, spend_verified = _appended_cost(
                cost_log_path,
                cost_log_checkpoint,
                receipt_id=receipt_id,
                require_receipt=metered_permitted,
            )
            if metered_permitted and (execution.exit_code != 0 or execution.timed_out):
                spend_verified = False
            next_metered_spend = metered_spend + appended_spend
            if math.isfinite(next_metered_spend):
                metered_spend = next_metered_spend
            else:
                metered_spend = max(metered_spend, appended_spend)
                spend_verified = False
            if not spend_verified and metered_spend_verified:
                metered_spend_verified = False
                warnings.append(
                    {
                        "source": "profile_budget",
                        "message": (
                            "Could not verify appended cost-ledger rows; remaining commands "
                            "were restricted to no-metered routes."
                        ),
                    }
                )
            status = (
                "succeeded"
                if execution.exit_code == 0
                and not execution.timed_out
                and spend_verified
                and appended_spend <= remaining_budget
                else "failed"
            )
            event = ProfileRunEvent(
                key=item.key,
                kind=item.kind,
                title=item.title,
                command=effective_command,
                resume_policy=item.resume_policy,
                status=status,
                attempted_at=_now_iso(),
                execution=execution,
            )
            events.append(event)
            updated = replace(
                item,
                command=effective_command,
                status=status,
                execution=execution,
            )
            updated_commands.append(updated)
            _record_event(state, event)
            state["last_run"] = _last_run_state(
                status=(
                    "budget_unverified"
                    if not metered_spend_verified
                    else "failed"
                    if any(record.status == "failed" for record in events)
                    else "running"
                ),
                max_metered_usd=preview.max_metered_usd,
                metered_spend_usd=metered_spend,
                metered_spend_verified=metered_spend_verified,
                started_at=run_started_at,
            )
            _save_state(state_path, state)
        commands = updated_commands

    durable_last_run = _last_run_from_state(state)
    okf_bundle_dir, okf_bundle_valid = _durable_okf_bundle_state(
        library_dir,
        preview,
        durable_last_run,
    )
    result = ProfileRunResult(
        schema_version=_RESULT_SCHEMA_VERSION,
        profile=preview.profile,
        topic=preview.topic,
        cost_mode=preview.cost_mode,
        generated_at=_now_iso(),
        state_path=str(state_path),
        approved=approved,
        executed=approved,
        fresh_item_limit=preview.fresh_item_limit,
        ordering=preview.ordering,
        max_metered_usd=preview.max_metered_usd,
        metered_spend_usd=metered_spend,
        metered_spend_verified=metered_spend_verified,
        commands=commands,
        events=events,
        warnings=warnings,
        last_run=durable_last_run,
        okf_bundle_required=preview.okf_export_required,
        okf_bundle_dir=okf_bundle_dir,
        okf_bundle_valid=okf_bundle_valid,
    )
    result = _apply_result_finalizer(
        result,
        approved=approved,
        result_finalizer=result_finalizer,
    )
    if approved:
        state["last_run_at"] = result.generated_at
        state["last_run"] = _last_run_state(
            status=result.health_status,
            max_metered_usd=result.max_metered_usd,
            metered_spend_usd=result.metered_spend_usd,
            metered_spend_verified=result.metered_spend_verified,
            started_at=run_started_at,
            finished_at=result.generated_at,
        )
        _save_state(state_path, state)
        result = replace(result, last_run=_last_run_from_state(state))
        save_run_log(
            library_dir,
            "profile-run",
            CostTracker(),
            elapsed_seconds=time.monotonic() - started,
            metadata={
                "profile": preview.profile,
                "topic": preview.topic,
                "cost_mode": preview.cost_mode,
                "selected_count": str(result.selected_count),
                "skipped_count": str(result.skipped_count),
                "succeeded_count": str(result.succeeded_count),
                "failed_count": str(result.failed_count),
                "max_metered_usd": f"{result.max_metered_usd:.6f}",
                "metered_spend_usd": f"{result.metered_spend_usd:.6f}",
                "metered_spend_verified": str(result.metered_spend_verified).lower(),
            },
        )
    else:
        result = replace(result, last_run=_last_run_from_state(state))
    return replace(
        result,
        next_actions=_profile_next_actions(
            result,
            library_dir=library_dir,
            profile_ref=profile_ref or preview.profile,
        ),
    )


def _apply_result_finalizer(
    result: ProfileRunResult,
    *,
    approved: bool,
    result_finalizer: Callable[[ProfileRunResult], ProfileRunResult] | None,
) -> ProfileRunResult:
    """Apply required-output finalization only to the lock-holding execution."""

    if not approved or result_finalizer is None:
        return result
    return result_finalizer(result)


def _durable_okf_bundle_state(
    library_dir: Path,
    preview: ProfilePreviewResult,
    last_run: Mapping[str, object],
) -> tuple[str, bool]:
    """Revalidate a previously successful required bundle on verifier runs."""

    if not preview.okf_export_required:
        return "", False
    output_dir = okf_bundle_output_dir(library_dir, preview.topic)
    if last_run.get("status") not in {"ok", "complete"}:
        return str(output_dir), False
    try:
        valid = validate_okf_bundle(output_dir).ok
    except (OSError, UnicodeError, ValueError):
        valid = False
    return str(output_dir), valid


def _busy_profile_run_result(
    preview: ProfilePreviewResult,
    *,
    library_dir: Path,
    profile_ref: str,
) -> ProfileRunResult:
    state_path = profile_run_state_path(library_dir, preview.profile)
    result = ProfileRunResult(
        schema_version=_RESULT_SCHEMA_VERSION,
        profile=preview.profile,
        topic=preview.topic,
        cost_mode=preview.cost_mode,
        generated_at=_now_iso(),
        state_path=str(state_path),
        approved=True,
        executed=False,
        busy=True,
        fresh_item_limit=preview.fresh_item_limit,
        ordering=preview.ordering,
        max_metered_usd=preview.max_metered_usd,
        commands=_build_commands(preview.candidates, completed=set()),
        warnings=[
            {
                "source": "profile_lock",
                "message": f"Profile {preview.profile!r} is already running.",
            }
        ],
    )
    return replace(
        result,
        next_actions=_profile_next_actions(
            result,
            library_dir=library_dir,
            profile_ref=profile_ref,
        ),
    )


def _last_run_state(
    *,
    status: str,
    max_metered_usd: float,
    metered_spend_usd: float,
    metered_spend_verified: bool,
    started_at: str,
    finished_at: str = "",
) -> dict[str, object]:
    payload: dict[str, object] = {
        "status": status,
        "max_metered_usd": max_metered_usd,
        "metered_spend_usd": metered_spend_usd,
        "metered_spend_verified": metered_spend_verified,
        "started_at": started_at,
    }
    if finished_at:
        payload["finished_at"] = finished_at
    return payload


def _last_run_from_state(state: Mapping[str, object]) -> dict[str, object]:
    last_run = state.get("last_run")
    if not isinstance(last_run, dict):
        return {}
    return dict(cast(dict[str, object], last_run))


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
    return load_profile_state(path, profile=profile, topic=topic, created_at=_now_iso())


def _save_state(path: Path, state: dict[str, Any]) -> None:
    save_profile_state(path, state, updated_at=_now_iso())


def _record_event(state: dict[str, Any], event: ProfileRunEvent) -> None:
    record_profile_event(
        state,
        payload=event.to_dict(),
        key=event.key,
        status=event.status,
        resume_policy=event.resume_policy,
        attempted_at=event.attempted_at,
        command=event.command,
        exit_code=event.execution.exit_code,
    )


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

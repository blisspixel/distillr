# pyright: strict
"""Loop-readable next actions for recurring profile results."""

from __future__ import annotations

from hashlib import blake2s
from pathlib import Path
from typing import Protocol

from distill.pipeline.next_actions import (
    NextAction,
    NextActionVerifier,
    action_id,
    loop_metadata,
)


class ProfileActionResult(Protocol):
    @property
    def busy(self) -> bool: ...

    @property
    def approved(self) -> bool: ...

    @property
    def cost_mode(self) -> str: ...

    @property
    def profile(self) -> str: ...

    @property
    def topic(self) -> str: ...

    @property
    def state_path(self) -> str: ...

    @property
    def selected_count(self) -> int: ...

    @property
    def failed_count(self) -> int: ...

    @property
    def health_status(self) -> str: ...


def profile_next_actions(
    result: ProfileActionResult,
    *,
    library_dir: Path,
    profile_ref: str,
) -> list[NextAction]:
    """Build the bounded action required by the current profile outcome."""

    if (
        result.busy
        or result.failed_count
        or result.health_status
        in {
            "failed",
            "output_failed",
            "budget_unverified",
            "budget_exceeded",
        }
    ):
        return [
            _profile_action(result, library_dir=library_dir, profile_ref=profile_ref, retry=True)
        ]
    if not result.approved and result.selected_count:
        return [
            _profile_action(result, library_dir=library_dir, profile_ref=profile_ref, retry=False)
        ]
    return []


def _profile_action(
    result: ProfileActionResult,
    *,
    library_dir: Path,
    profile_ref: str,
    retry: bool,
) -> NextAction:
    suffix = "retry" if retry else "run"
    profile_digest = blake2s(result.profile.encode("utf-8"), digest_size=8).hexdigest()
    action_id_value = action_id("profile", f"{result.profile}-{profile_digest}", suffix)
    selected = result.selected_count if result.busy or not retry else result.failed_count
    approval = _approval_for_cost_mode(result.cost_mode)
    return NextAction(
        id=action_id_value,
        kind="profile_run_retry" if retry else "profile_run",
        severity="warning" if retry else "info",
        rationale=_profile_action_rationale(
            selected,
            retry=retry,
            health_status=result.health_status,
            busy=result.busy,
        ),
        command=_profile_run_command(
            result.cost_mode,
            profile_ref,
            json_output=False,
            approved=True,
        ),
        approval=approval,
        estimated_cost_usd=0.0 if approval == "operator" else None,
        writes=_profile_action_writes(result, library_dir),
        verifier=NextActionVerifier(
            command=_profile_run_command(
                result.cost_mode,
                profile_ref,
                json_output=True,
                approved=False,
            ),
            expect=(
                "state file exists and last_run.status in ['ok', 'complete'] and "
                "last_run.metered_spend_verified == true and required output is valid"
            ),
        ),
        loop=loop_metadata(action_id_value, max_attempts=3 if retry else 1),
    )


def _profile_action_rationale(
    count: int,
    *,
    retry: bool,
    health_status: str,
    busy: bool,
) -> str:
    if busy:
        return (
            "Another profile run holds the execution lock; retry after it reaches a terminal state."
        )
    if health_status == "output_failed":
        return "The required profile output failed; rerun and verify durable terminal health."
    if retry and health_status in {"budget_unverified", "budget_exceeded"}:
        label = health_status.replace("_", " ")
        return (
            f"The previous profile run remains {label}; rerun and verify durable terminal health."
        )
    if retry and health_status == "failed" and count == 0:
        return "The previous profile run remains failed; rerun and verify durable terminal health."
    if retry:
        return (
            f"{count} profile command(s) failed; rerun skips completed exact items "
            "and retries pending work."
        )
    return f"{count} profile command(s) are pending approval."


def _approval_for_cost_mode(cost_mode: str) -> str:
    return "operator" if cost_mode == "no-metered" else "spend"


def _profile_run_command(
    cost_mode: str,
    profile_ref: str,
    *,
    json_output: bool,
    approved: bool,
) -> list[str]:
    command = ["distill"]
    if cost_mode != "auto":
        command.extend(["--cost-mode", cost_mode])
    if json_output:
        command.append("--json")
    command.extend(["profile", "run", profile_ref])
    if approved:
        command.append("--yes")
    return command


def _profile_action_writes(result: ProfileActionResult, library_dir: Path) -> list[str]:
    return [
        library_relative(Path(result.state_path), library_dir),
        f"topics/{result.topic}/**/*",
        ".distill/cost_log.jsonl",
    ]


def library_relative(path: Path, library_dir: Path) -> str:
    """Return a portable library-relative path when confinement permits it."""

    try:
        return path.relative_to(library_dir).as_posix()
    except ValueError:
        return str(path)

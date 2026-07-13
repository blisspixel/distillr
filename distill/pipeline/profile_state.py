# pyright: strict
"""Bounded persistence and validation for recurring profile run state."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from distill.library.paths import atomic_write_text
from distill.parsing import strict_json_loads

__all__ = [
    "completed_keys",
    "load_profile_state",
    "profile_state_shape_error",
    "prune_inactive_event_state",
    "read_profile_state_document",
    "record_profile_event",
    "save_profile_state",
]

_STATE_SCHEMA_VERSION = "profile-run-state.v1"
_MAX_STATE_BYTES = 10_000_000
_MAX_STATE_ATTEMPTS = 100
_MAX_STATE_KEYED_EVENTS = 500
_MAX_STATE_COMPLETIONS = 2_000
_LAST_RUN_STATUSES = frozenset(
    {
        "running",
        "ok",
        "complete",
        "failed",
        "output_failed",
        "budget_unverified",
        "budget_exceeded",
    }
)


def load_profile_state(
    path: Path,
    *,
    profile: str,
    topic: str,
    created_at: str,
) -> dict[str, Any]:
    """Load one validated state document or initialize an empty state."""

    if not path.exists():
        return _empty_state(profile, topic, created_at=created_at)
    try:
        raw_data = read_profile_state_document(path)
    except (OSError, RecursionError, UnicodeError, ValueError) as exc:
        raise ValueError(f"Profile run state is not parseable: {path}") from exc
    if not isinstance(raw_data, dict):
        raise ValueError(f"Profile run state must be a JSON object: {path}")
    data = cast(dict[str, Any], raw_data)
    shape_error = profile_state_shape_error(data, profile=profile, topic=topic)
    if shape_error:
        if shape_error.startswith("schema_version"):
            raise ValueError(f"Unsupported profile run state schema in {path}")
        raise ValueError(f"Invalid profile run state in {path}: {shape_error}")
    data.setdefault("profile", profile)
    data.setdefault("topic", topic)
    data.setdefault("completed", {})
    data.setdefault("last_success", {})
    data.setdefault("last_failure", {})
    data.setdefault("attempts", [])
    return data


def _empty_state(profile: str, topic: str, *, created_at: str) -> dict[str, Any]:
    return {
        "schema_version": _STATE_SCHEMA_VERSION,
        "profile": profile,
        "topic": topic,
        "created_at": created_at,
        "updated_at": created_at,
        "completed": {},
        "last_success": {},
        "last_failure": {},
        "attempts": [],
    }


def save_profile_state(path: Path, state: dict[str, Any], *, updated_at: str) -> None:
    """Persist one state document atomically within the state size cap."""

    state["updated_at"] = updated_at
    content = json.dumps(state, indent=2, sort_keys=True) + "\n"
    if len(content.encode("utf-8")) > _MAX_STATE_BYTES:
        raise ValueError(f"profile run state exceeds the {_MAX_STATE_BYTES:,}-byte cap")
    atomic_write_text(path, content)


def prune_inactive_event_state(state: dict[str, Any], *, active_keys: set[str]) -> None:
    """Remove transient success and failure entries for inactive commands."""

    for field_name in ("last_success", "last_failure"):
        entries = state.get(field_name)
        if isinstance(entries, dict):
            typed_entries = cast(dict[str, Any], entries)
            state[field_name] = {
                key: value for key, value in typed_entries.items() if key in active_keys
            }


def completed_keys(state: dict[str, Any]) -> set[str]:
    """Return the normalized keys of durably completed commands."""

    completed = state.get("completed", {})
    if not isinstance(completed, Mapping):
        return set()
    completed_map = cast(Mapping[object, object], completed)
    return {str(key) for key in completed_map}


def record_profile_event(
    state: dict[str, Any],
    *,
    payload: dict[str, Any],
    key: str,
    status: str,
    resume_policy: str,
    attempted_at: str,
    command: list[str],
    exit_code: int,
) -> None:
    """Record one bounded event and update its durable command state."""

    attempts = cast(list[dict[str, Any]], state.setdefault("attempts", []))
    attempts.append(payload)
    del attempts[:-_MAX_STATE_ATTEMPTS]
    if status == "succeeded":
        last_success = cast(dict[str, Any], state.setdefault("last_success", {}))
        last_failure = cast(dict[str, Any], state.setdefault("last_failure", {}))
        _set_bounded_state_entry(last_success, key, payload, limit=_MAX_STATE_KEYED_EVENTS)
        last_failure.pop(key, None)
        if resume_policy == "complete-on-success":
            completed = cast(dict[str, Any], state.setdefault("completed", {}))
            _set_bounded_state_entry(
                completed,
                key,
                {
                    "completed_at": attempted_at,
                    "command": command,
                    "exit_code": exit_code,
                },
                limit=_MAX_STATE_COMPLETIONS,
            )
        return
    last_failure = cast(dict[str, Any], state.setdefault("last_failure", {}))
    _set_bounded_state_entry(last_failure, key, payload, limit=_MAX_STATE_KEYED_EVENTS)


def _set_bounded_state_entry(
    entries: dict[str, Any], key: str, value: object, *, limit: int
) -> None:
    entries.pop(key, None)
    entries[key] = value
    while len(entries) > limit:
        del entries[next(iter(entries))]


def read_profile_state_document(path: Path) -> object:
    """Read one bounded profile state JSON document."""

    with path.open("rb") as stream:
        content = stream.read(_MAX_STATE_BYTES + 1)
    if len(content) > _MAX_STATE_BYTES:
        raise ValueError(f"profile state exceeds the {_MAX_STATE_BYTES:,}-byte cap")
    return strict_json_loads(content)


def profile_state_shape_error(
    state: Mapping[str, object], *, profile: str | None = None, topic: str | None = None
) -> str:
    """Return a structural state error, or an empty string when safe to mutate."""

    for error in (
        _state_identity_error(state, profile=profile, topic=topic),
        _state_event_collections_error(state),
        _state_attempts_error(state),
        _state_last_run_error(state),
    ):
        if error:
            return error
    return ""


def _state_identity_error(
    state: Mapping[str, object], *, profile: str | None, topic: str | None
) -> str:
    if state.get("schema_version") != _STATE_SCHEMA_VERSION:
        return f"schema_version must be {_STATE_SCHEMA_VERSION!r}"
    for field_name, expected in (("profile", profile), ("topic", topic)):
        if expected is None:
            continue
        recorded = state.get(field_name)
        if recorded is not None and recorded != expected:
            return f"{field_name} does not match {expected!r}"
    return ""


def _state_event_collections_error(state: Mapping[str, object]) -> str:
    for field_name in ("completed", "last_success", "last_failure"):
        value = state.get(field_name)
        if value is not None and not isinstance(value, dict):
            return f"{field_name} must be a JSON object"
        limit = _MAX_STATE_COMPLETIONS if field_name == "completed" else _MAX_STATE_KEYED_EVENTS
        if isinstance(value, dict):
            entries = cast(dict[object, object], value)
            if any(not isinstance(item, dict) for item in entries.values()):
                return f"{field_name} entries must be JSON objects"
            if len(entries) > limit:
                return f"{field_name} cannot contain more than {limit} entries"
    return ""


def _state_attempts_error(state: Mapping[str, object]) -> str:
    attempts = state.get("attempts")
    if attempts is None:
        return ""
    if not isinstance(attempts, list):
        return "attempts must be an array of JSON objects"
    attempt_entries = cast(list[object], attempts)
    if any(not isinstance(item, dict) for item in attempt_entries):
        return "attempts must be an array of JSON objects"
    if len(attempt_entries) > _MAX_STATE_ATTEMPTS:
        return f"attempts cannot contain more than {_MAX_STATE_ATTEMPTS} entries"
    return ""


def _state_last_run_error(state: Mapping[str, object]) -> str:
    last_run = state.get("last_run")
    if last_run is None:
        return ""
    if not isinstance(last_run, dict):
        return "last_run must be a JSON object"
    run = cast(dict[object, object], last_run)
    if run.get("status") not in _LAST_RUN_STATUSES:
        return "last_run.status is invalid"
    if not isinstance(run.get("metered_spend_verified"), bool):
        return "last_run.metered_spend_verified must be boolean"
    for field_name in ("max_metered_usd", "metered_spend_usd"):
        if not _is_finite_nonnegative_number(run.get(field_name)):
            return f"last_run.{field_name} must be a finite nonnegative number"
    started_at = _parse_state_timestamp(run.get("started_at"))
    if started_at is None:
        return "last_run.started_at must be a UTC timestamp"
    raw_finished_at = run.get("finished_at")
    finished_at = _parse_state_timestamp(raw_finished_at) if raw_finished_at is not None else None
    if raw_finished_at is not None and finished_at is None:
        return "last_run.finished_at must be a UTC timestamp"
    if finished_at is not None and finished_at < started_at:
        return "last_run.finished_at cannot precede last_run.started_at"
    return ""


def _is_finite_nonnegative_number(value: object) -> bool:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return False
    try:
        normalized = float(value)
    except OverflowError:
        return False
    return math.isfinite(normalized) and normalized >= 0


def _parse_state_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError:
        return None

"""Boundary contracts for durable recurring-profile state."""

from __future__ import annotations

from pathlib import Path

import pytest

import distill.pipeline.profile_state as profile_state
from distill.pipeline.profile_state import (
    completed_keys,
    profile_state_shape_error,
    prune_inactive_event_state,
    record_profile_event,
    save_profile_state,
)


def _valid_last_run(**overrides: object) -> dict[str, object]:
    run: dict[str, object] = {
        "status": "ok",
        "max_metered_usd": 1.0,
        "metered_spend_usd": 0.25,
        "metered_spend_verified": True,
        "started_at": "2026-07-13T01:00:00Z",
        "finished_at": "2026-07-13T02:00:00Z",
    }
    run.update(overrides)
    return run


def _state(**overrides: object) -> dict[str, object]:
    state: dict[str, object] = {"schema_version": "profile-run-state.v1"}
    state.update(overrides)
    return state


def test_completed_keys_and_pruning_are_total_for_untrusted_collections() -> None:
    assert completed_keys({"completed": []}) == set()
    state = {
        "last_success": {"active": {}, "stale": {}},
        "last_failure": "invalid",
    }

    prune_inactive_event_state(state, active_keys={"active"})

    assert state == {"last_success": {"active": {}}, "last_failure": "invalid"}


def test_record_profile_event_evicts_oldest_bounded_entries(monkeypatch) -> None:
    monkeypatch.setattr(profile_state, "_MAX_STATE_KEYED_EVENTS", 1)
    monkeypatch.setattr(profile_state, "_MAX_STATE_COMPLETIONS", 1)
    state: dict[str, object] = {
        "last_failure": {"first": {"status": "failed"}},
    }

    for key in ("first", "second"):
        record_profile_event(
            state,
            payload={"key": key},
            key=key,
            status="succeeded",
            resume_policy="complete-on-success",
            attempted_at="2026-07-13T02:00:00Z",
            command=["distill", "video", key],
            exit_code=0,
        )

    assert state["attempts"] == [{"key": "first"}, {"key": "second"}]
    assert state["last_success"] == {"second": {"key": "second"}}
    assert state["completed"] == {
        "second": {
            "completed_at": "2026-07-13T02:00:00Z",
            "command": ["distill", "video", "second"],
            "exit_code": 0,
        }
    }
    assert state["last_failure"] == {}


def test_save_profile_state_refuses_documents_over_the_byte_cap(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(profile_state, "_MAX_STATE_BYTES", 64)

    with pytest.raises(ValueError, match="exceeds the 64-byte cap"):
        save_profile_state(
            tmp_path / "state.json",
            {"schema_version": "profile-run-state.v1", "payload": "x" * 100},
            updated_at="2026-07-13T02:00:00Z",
        )

    assert not (tmp_path / "state.json").exists()


@pytest.mark.parametrize(
    ("state", "message"),
    [
        (_state(completed={"bad": 1}), "completed entries must be JSON objects"),
        (_state(last_success={str(index): {} for index in range(501)}), "more than 500"),
        (_state(attempts=[{}] * 101), "more than 100"),
        (_state(last_run=[]), "last_run must be a JSON object"),
        (_state(last_run=_valid_last_run(status="unknown")), "status is invalid"),
        (
            _state(last_run=_valid_last_run(metered_spend_verified=1)),
            "metered_spend_verified must be boolean",
        ),
        (
            _state(last_run=_valid_last_run(max_metered_usd=True)),
            "max_metered_usd must be a finite nonnegative number",
        ),
        (
            _state(last_run=_valid_last_run(metered_spend_usd=10**400)),
            "metered_spend_usd must be a finite nonnegative number",
        ),
        (
            _state(last_run=_valid_last_run(finished_at=7)),
            "finished_at must be a UTC timestamp",
        ),
        (
            _state(last_run=_valid_last_run(started_at=None)),
            "started_at must be a UTC timestamp",
        ),
    ],
)
def test_profile_state_shape_reports_each_unsafe_boundary(
    state: dict[str, object],
    message: str,
) -> None:
    assert message in profile_state_shape_error(state)


def test_profile_state_identity_allows_unspecified_expected_values() -> None:
    assert (
        profile_state_shape_error(
            _state(profile="recorded", topic="recorded"),
            profile=None,
            topic=None,
        )
        == ""
    )

from __future__ import annotations

import io
import json
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

import distill.pipeline.profile_run as profile_run_module
from distill.library.okf import okf_bundle_output_dir
from distill.pipeline.costs import PROFILE_RECEIPT_ENV
from distill.pipeline.profile_actions import library_relative, profile_next_actions
from distill.pipeline.profile_health import collect_profile_health
from distill.pipeline.profile_preview import ProfilePreviewCandidate, ProfilePreviewResult
from distill.pipeline.profile_run import (
    CommandExecution,
    execute_command,
    profile_run_state_path,
    run_profile_preview,
)


def _preview() -> ProfilePreviewResult:
    return ProfilePreviewResult(
        schema_version="profile-preview.v1",
        profile="agent-loops",
        topic="agent-loops",
        cost_mode="no-metered",
        ordering="test order",
        fresh_item_limit=3,
        candidates=[
            ProfilePreviewCandidate(
                kind="youtube_video",
                title="Exact video",
                url="https://youtube.com/watch?v=v1",
                source="@Example",
                source_label="Example",
                identity="youtube:v1",
                command=[
                    "distill",
                    "--cost-mode",
                    "no-metered",
                    "video",
                    "https://youtube.com/watch?v=v1",
                    "--topic",
                    "agent-loops",
                ],
            ),
            ProfilePreviewCandidate(
                kind="query",
                title="agent loops",
                url="",
                source="agent loops",
                source_label="saved query",
                identity="query:agent loops",
                command=[
                    "distill",
                    "--cost-mode",
                    "no-metered",
                    "latest",
                    "agent loops",
                    "--topic",
                    "agent-loops",
                    "--preview",
                ],
            ),
        ],
    )


def _write_valid_okf_bundle(library_dir: Path, topic: str) -> Path:
    output_dir = okf_bundle_output_dir(library_dir, topic)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "index.md").write_text("# Index\n", encoding="utf-8")
    (output_dir / "log.md").write_text("# Log\n", encoding="utf-8")
    (output_dir / "artifact.md").write_text(
        "---\ntype: Source Insight\n---\n\n# Artifact\n",
        encoding="utf-8",
    )
    return output_dir


def _metered_preview(*, max_metered_usd: float = 1.0) -> ProfilePreviewResult:
    candidates = [
        ProfilePreviewCandidate(
            kind="youtube_video",
            title=f"Video {index}",
            url=f"https://youtube.com/watch?v=v{index}",
            source="@Example",
            source_label="Example",
            identity=f"youtube:v{index}",
            command=[
                "distill",
                "video",
                f"https://youtube.com/watch?v=v{index}",
                "--topic",
                "agent-loops",
            ],
        )
        for index in range(2)
    ]
    return ProfilePreviewResult(
        schema_version="profile-preview.v1",
        profile="agent-loops",
        topic="agent-loops",
        cost_mode="auto",
        ordering="test order",
        fresh_item_limit=2,
        max_metered_usd=max_metered_usd,
        candidates=candidates,
    )


def _append_profile_receipt(
    library_dir: Path,
    environment: Mapping[str, str] | None,
    cost: float,
    *,
    tracker_id: str = "0" * 32,
) -> None:
    assert environment is not None
    path = library_dir / ".distill" / "cost_log.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "profile_receipt_id": environment[PROFILE_RECEIPT_ENV],
        "profile_receipt_tracker_id": tracker_id,
        "profile_receipt_cost_usd": cost,
        "actual_cost": round(cost, 6),
    }
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(row) + "\n")


def test_profile_run_without_approval_only_returns_plan(tmp_path):
    calls: list[list[str]] = []

    result = run_profile_preview(
        _preview(),
        library_dir=tmp_path,
        approved=False,
        executor=lambda command, _timeout, **_kwargs: (
            calls.append(command) or CommandExecution(0, 0.1)
        ),
    )

    assert result.health_status == "approval_required"
    assert result.pending_count == 2
    assert calls == []
    assert not profile_run_state_path(tmp_path, "agent-loops").exists()
    action = result.to_dict()["next_actions"][0]
    assert action["id"].startswith("profile.agent.loops.")
    assert action["id"].endswith(".run")
    assert action["kind"] == "profile_run"
    assert action["approval"] == "operator"
    assert action["estimated_cost_usd"] == 0.0
    assert action["command"] == [
        "distill",
        "--cost-mode",
        "no-metered",
        "profile",
        "run",
        "agent-loops",
        "--yes",
    ]
    assert action["loop"]["acceptance_metric"] == "verifier_passed"
    assert action["verifier"]["command"] == [
        "distill",
        "--cost-mode",
        "no-metered",
        "--json",
        "profile",
        "run",
        "agent-loops",
    ]


def test_profile_action_identity_does_not_collapse_valid_punctuation(tmp_path):
    def plan(profile: str):
        result = SimpleNamespace(
            busy=False,
            approved=False,
            cost_mode="no-metered",
            profile=profile,
            topic="identity",
            state_path=str(tmp_path / f"{profile}.json"),
            selected_count=1,
            failed_count=0,
            health_status="approval_required",
        )
        return profile_next_actions(result, library_dir=tmp_path, profile_ref=profile)[0]

    hyphenated = plan("a-b")
    dotted = plan("a.b")

    assert hyphenated.id != dotted.id
    assert hyphenated.loop is not None
    assert dotted.loop is not None
    assert hyphenated.loop.state_path != dotted.loop.state_path


@pytest.mark.parametrize("profile_name", ["a.", "con", "nul", "com1"])
def test_profile_run_state_path_rejects_noncanonical_profile_names(
    tmp_path: Path, profile_name: str
) -> None:
    with pytest.raises(ValueError, match="canonical cross-platform"):
        profile_run_state_path(tmp_path, profile_name)


def test_profile_run_marks_exact_items_complete_but_keeps_seeds_repeatable(tmp_path):
    calls: list[list[str]] = []

    def executor(command: list[str], _timeout: int, **_kwargs) -> CommandExecution:
        calls.append(command)
        return CommandExecution(exit_code=0, elapsed_seconds=0.1)

    first = run_profile_preview(
        _preview(),
        library_dir=tmp_path,
        approved=True,
        executor=executor,
    )

    assert first.succeeded_count == 2
    assert first.health_status == "ok"
    assert first.to_dict()["pending_count"] == 0
    assert len(calls) == 2

    state_path = profile_run_state_path(tmp_path, "agent-loops")
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert "youtube_video:youtube:v1" in state["completed"]
    assert "query:query:agent loops" not in state["completed"]
    cost_row = json.loads((tmp_path / ".distill" / "cost_log.jsonl").read_text(encoding="utf-8"))
    assert cost_row["command"] == "profile-run"
    assert cost_row["actual_cost"] == 0.0
    assert cost_row["metadata"]["profile"] == "agent-loops"
    assert cost_row["metadata"]["succeeded_count"] == "2"

    second = run_profile_preview(
        _preview(),
        library_dir=tmp_path,
        approved=False,
        executor=executor,
    )

    statuses = {command.key: command.status for command in second.commands}
    assert statuses["youtube_video:youtube:v1"] == "skipped"
    assert statuses["query:query:agent loops"] == "pending"


def test_profile_run_serializes_approved_runs_per_profile(tmp_path, monkeypatch) -> None:
    entered = threading.Event()
    release = threading.Event()
    calls: list[list[str]] = []
    first_result: list[object] = []
    overlapping_exports: list[str] = []
    monkeypatch.setattr(profile_run_module, "_PROFILE_LOCK_TIMEOUT_SECONDS", 0.05)

    def executor(command: list[str], _timeout: int, **_kwargs) -> CommandExecution:
        calls.append(command)
        if len(calls) == 1:
            entered.set()
            assert release.wait(timeout=2)
        return CommandExecution(exit_code=0, elapsed_seconds=0.1)

    worker = threading.Thread(
        target=lambda: first_result.append(
            run_profile_preview(
                _preview(),
                library_dir=tmp_path,
                approved=True,
                executor=executor,
            )
        )
    )
    worker.start()
    assert entered.wait(timeout=2)

    overlapping = run_profile_preview(
        _preview(),
        library_dir=tmp_path,
        approved=True,
        executor=executor,
        result_finalizer=lambda result: overlapping_exports.append(result.profile) or result,
    )

    assert overlapping.health_status == "busy"
    assert overlapping.executed is False
    assert overlapping.pending_count == 2
    assert overlapping.warnings[0]["source"] == "profile_lock"
    assert len(calls) == 1
    assert overlapping_exports == []
    active_state = json.loads(
        profile_run_state_path(tmp_path, "agent-loops").read_text(encoding="utf-8")
    )
    assert active_state["last_run"]["status"] == "running"

    release.set()
    worker.join(timeout=2)
    assert not worker.is_alive()
    assert len(first_result) == 1
    assert len(calls) == 2


def test_profile_run_does_not_misreport_executor_timeout_as_lock_contention(tmp_path) -> None:
    def executor(_command: list[str], _timeout: int, **_kwargs) -> CommandExecution:
        raise TimeoutError("executor timeout")

    with pytest.raises(TimeoutError, match="executor timeout"):
        run_profile_preview(
            _preview(),
            library_dir=tmp_path,
            approved=True,
            executor=executor,
        )


def test_profile_run_rejects_invalid_timeout_before_state_mutation(tmp_path: Path) -> None:
    state_path = profile_run_state_path(tmp_path, "agent-loops")

    with pytest.raises(ValueError, match="timeout_seconds"):
        run_profile_preview(
            _preview(),
            library_dir=tmp_path,
            approved=True,
            timeout_seconds=86_401,
        )

    assert not state_path.exists()
    assert not state_path.with_name("run.lock").exists()


def test_profile_run_approved_run_skips_completed_exact_items(tmp_path):
    calls: list[list[str]] = []

    def executor(command: list[str], _timeout: int, **_kwargs) -> CommandExecution:
        calls.append(command)
        return CommandExecution(exit_code=0, elapsed_seconds=0.1)

    run_profile_preview(
        _preview(),
        library_dir=tmp_path,
        approved=True,
        executor=executor,
    )
    calls.clear()

    result = run_profile_preview(
        _preview(),
        library_dir=tmp_path,
        approved=True,
        executor=executor,
    )

    statuses = {command.key: command.status for command in result.commands}
    assert statuses["youtube_video:youtube:v1"] == "skipped"
    assert statuses["query:query:agent loops"] == "succeeded"
    assert len(calls) == 1


def test_profile_run_with_only_completed_items_is_complete(tmp_path):
    preview = ProfilePreviewResult(
        schema_version="profile-preview.v1",
        profile="agent-loops",
        topic="agent-loops",
        cost_mode="no-metered",
        ordering="test order",
        fresh_item_limit=1,
        candidates=[_preview().candidates[0]],
    )
    state_path = profile_run_state_path(tmp_path, "agent-loops")
    state_path.parent.mkdir(parents=True)
    state_path.write_text(
        json.dumps(
            {
                "schema_version": "profile-run-state.v1",
                "completed": {"youtube_video:youtube:v1": {"exit_code": 0}},
            }
        ),
        encoding="utf-8",
    )

    result = run_profile_preview(preview, library_dir=tmp_path, approved=False)

    assert result.selected_count == 0
    assert result.health_status == "complete"
    assert result.to_dict()["next_actions"] == []


def test_profile_run_failure_is_recorded_without_completion(tmp_path):
    def executor(_command: list[str], _timeout: int, **_kwargs) -> CommandExecution:
        return CommandExecution(exit_code=2, elapsed_seconds=0.1, stderr_tail="failed")

    result = run_profile_preview(
        _preview(),
        library_dir=tmp_path,
        approved=True,
        executor=executor,
    )

    assert result.failed_count == 2
    assert result.health_status == "failed"
    action = result.to_dict()["next_actions"][0]
    assert action["id"].startswith("profile.agent.loops.")
    assert action["id"].endswith(".retry")
    assert action["kind"] == "profile_run_retry"
    assert action["severity"] == "warning"
    assert action["loop"]["max_attempts"] == 3

    state = json.loads(profile_run_state_path(tmp_path, "agent-loops").read_text(encoding="utf-8"))
    assert state["completed"] == {}
    assert "youtube_video:youtube:v1" in state["last_failure"]
    assert state["attempts"][0]["execution"]["stderr_tail"] == "failed"


def test_empty_verifier_preserves_durable_failure_and_retry_action(tmp_path: Path) -> None:
    failed = run_profile_preview(
        _preview(),
        library_dir=tmp_path,
        approved=True,
        executor=lambda _command, _timeout, **_kwargs: CommandExecution(
            exit_code=2,
            elapsed_seconds=0.1,
        ),
    )
    assert failed.health_status == "failed"

    verifier = run_profile_preview(
        replace(_preview(), candidates=[]),
        library_dir=tmp_path,
        approved=False,
    )

    assert verifier.selected_count == 0
    assert verifier.last_run["status"] == "failed"
    assert verifier.health_status == "failed"
    assert verifier.next_actions[0].kind == "profile_run_retry"
    assert "remains failed" in verifier.next_actions[0].rationale


@pytest.mark.parametrize("terminal_status", ["budget_unverified", "budget_exceeded"])
def test_all_skipped_verifier_preserves_durable_budget_failure(
    tmp_path: Path,
    terminal_status: str,
) -> None:
    preview = replace(_preview(), candidates=_preview().candidates[:1])
    successful = run_profile_preview(
        preview,
        library_dir=tmp_path,
        approved=True,
        executor=lambda _command, _timeout, **_kwargs: CommandExecution(
            exit_code=0,
            elapsed_seconds=0.1,
        ),
    )
    assert successful.health_status == "ok"
    state_path = profile_run_state_path(tmp_path, preview.profile)
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["last_run"]["status"] = terminal_status
    state["last_run"]["metered_spend_verified"] = terminal_status != "budget_unverified"
    state_path.write_text(json.dumps(state), encoding="utf-8")

    verifier = run_profile_preview(preview, library_dir=tmp_path, approved=False)

    assert verifier.selected_count == 0
    assert verifier.skipped_count == 1
    assert verifier.last_run["status"] == terminal_status
    assert verifier.health_status == terminal_status
    assert verifier.next_actions[0].kind == "profile_run_retry"
    assert terminal_status.replace("_", " ") in verifier.next_actions[0].rationale


def test_required_output_failure_persists_unhealthy_verifier_until_recovery(tmp_path: Path):
    required_preview = replace(_preview(), okf_export_required=True)
    output_failed = run_profile_preview(
        required_preview,
        library_dir=tmp_path,
        approved=True,
        executor=lambda _command, _timeout, **_kwargs: CommandExecution(
            exit_code=0,
            elapsed_seconds=0.1,
        ),
        result_finalizer=lambda result: replace(
            result,
            okf_bundle_required=True,
            okf_bundle_valid=False,
        ),
    )

    assert output_failed.health_status == "output_failed"
    assert output_failed.last_run["status"] == "output_failed"
    assert output_failed.next_actions[0].kind == "profile_run_retry"
    assert output_failed.next_actions[0].verifier.expect == (
        "state file exists and last_run.status in ['ok', 'complete'] and "
        "last_run.metered_spend_verified == true and required output is valid"
    )
    before_recovery = run_profile_preview(
        required_preview,
        library_dir=tmp_path,
        approved=False,
    )
    assert before_recovery.last_run["status"] == "output_failed"
    assert before_recovery.health_status == "output_failed"
    assert before_recovery.okf_bundle_required is True
    assert before_recovery.next_actions[0].kind == "profile_run_retry"

    def successful_finalizer(result):
        output_dir = _write_valid_okf_bundle(tmp_path, "agent-loops")
        return replace(
            result,
            okf_bundle_required=True,
            okf_bundle_dir=str(output_dir),
            okf_bundle_valid=True,
        )

    recovered = run_profile_preview(
        required_preview,
        library_dir=tmp_path,
        approved=True,
        executor=lambda _command, _timeout, **_kwargs: CommandExecution(
            exit_code=0,
            elapsed_seconds=0.1,
        ),
        result_finalizer=successful_finalizer,
    )
    after_recovery = run_profile_preview(
        required_preview,
        library_dir=tmp_path,
        approved=False,
    )

    assert recovered.health_status == "ok"
    assert recovered.next_actions == []
    assert after_recovery.last_run["status"] == "ok"
    assert after_recovery.last_run["metered_spend_verified"] is True
    assert after_recovery.okf_bundle_valid is True


def test_required_output_verifier_rejects_deleted_bundle(tmp_path: Path):
    required_preview = replace(_preview(), okf_export_required=True)

    def successful_finalizer(result):
        output_dir = _write_valid_okf_bundle(tmp_path, "agent-loops")
        return replace(
            result,
            okf_bundle_dir=str(output_dir),
            okf_bundle_valid=True,
        )

    successful = run_profile_preview(
        required_preview,
        library_dir=tmp_path,
        approved=True,
        executor=lambda _command, _timeout, **_kwargs: CommandExecution(
            exit_code=0,
            elapsed_seconds=0.1,
        ),
        result_finalizer=successful_finalizer,
    )
    shutil.rmtree(Path(successful.okf_bundle_dir))

    verifier = run_profile_preview(required_preview, library_dir=tmp_path, approved=False)

    assert successful.health_status == "ok"
    assert verifier.last_run["status"] == "ok"
    assert verifier.okf_bundle_valid is False
    assert verifier.health_status == "output_failed"
    assert verifier.next_actions[0].kind == "profile_run_retry"


def test_required_output_failure_survives_all_dynamic_commands_becoming_complete(
    tmp_path: Path,
):
    required_preview = ProfilePreviewResult(
        schema_version="profile-preview.v1",
        profile="agent-loops",
        topic="agent-loops",
        cost_mode="no-metered",
        ordering="test order",
        fresh_item_limit=1,
        okf_export_required=True,
        candidates=[_preview().candidates[0]],
    )
    first = run_profile_preview(
        required_preview,
        library_dir=tmp_path,
        approved=True,
        executor=lambda _command, _timeout, **_kwargs: CommandExecution(
            exit_code=0,
            elapsed_seconds=0.1,
        ),
        result_finalizer=lambda result: replace(result, okf_bundle_valid=False),
    )

    verifier = run_profile_preview(
        required_preview,
        library_dir=tmp_path,
        approved=False,
    )

    assert first.health_status == "output_failed"
    assert verifier.selected_count == 0
    assert verifier.health_status == "output_failed"
    assert verifier.okf_bundle_required is True
    assert verifier.last_run["status"] == "output_failed"
    assert verifier.next_actions[0].kind == "profile_run_retry"


def test_profile_run_prunes_failures_for_removed_candidates(tmp_path):
    def failing_executor(_command: list[str], _timeout: int, **_kwargs) -> CommandExecution:
        return CommandExecution(exit_code=2, elapsed_seconds=0.1, stderr_tail="failed")

    failed = run_profile_preview(
        _preview(),
        library_dir=tmp_path,
        approved=True,
        executor=failing_executor,
    )
    assert failed.failed_count == 2

    query_only = replace(
        _preview(),
        candidates=[_preview().candidates[1]],
        fresh_item_limit=1,
    )
    recovered = run_profile_preview(
        query_only,
        library_dir=tmp_path,
        approved=True,
        executor=lambda _command, _timeout, **_kwargs: CommandExecution(
            exit_code=0,
            elapsed_seconds=0.1,
        ),
    )

    state = json.loads(profile_run_state_path(tmp_path, "agent-loops").read_text(encoding="utf-8"))
    assert recovered.health_status == "ok"
    assert state["last_failure"] == {}

    profile_path = tmp_path / "profiles" / "agent-loops.yaml"
    profile_path.parent.mkdir(parents=True)
    profile_path.write_text(
        "\n".join(
            [
                "schema_version: research-profile.v1",
                "name: agent-loops",
                "topic: agent-loops",
                "goal_file: goals/agent-loops.md",
                "cost_mode: no-metered",
                "queries: [agent loops]",
                "limits:",
                "  max_metered_usd: 0",
            ]
        ),
        encoding="utf-8",
    )
    assert collect_profile_health(tmp_path).last_failed == []


def test_profile_run_refuses_unparseable_state(tmp_path):
    state_path = profile_run_state_path(tmp_path, "agent-loops")
    state_path.parent.mkdir(parents=True)
    state_path.write_text("{", encoding="utf-8")

    try:
        run_profile_preview(_preview(), library_dir=tmp_path, approved=False)
    except ValueError as exc:
        assert "not parseable" in str(exc)
    else:
        raise AssertionError("Expected unparseable state to fail closed")


@pytest.mark.parametrize(
    "invalid_number",
    ["NaN", "Infinity", "1e999", "9" * 101],
)
def test_profile_run_refuses_nonfinite_or_oversized_json_numbers(
    tmp_path: Path,
    invalid_number: str,
) -> None:
    state_path = profile_run_state_path(tmp_path, "agent-loops")
    state_path.parent.mkdir(parents=True)
    state_path.write_text(
        f'{{"schema_version":"profile-run-state.v1","untrusted":{invalid_number}}}',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="not parseable"):
        run_profile_preview(_preview(), library_dir=tmp_path, approved=False)


def test_profile_run_refuses_non_object_and_wrong_schema_state(tmp_path):
    state_path = profile_run_state_path(tmp_path, "agent-loops")
    state_path.parent.mkdir(parents=True)

    state_path.write_text("[]", encoding="utf-8")
    try:
        run_profile_preview(_preview(), library_dir=tmp_path, approved=False)
    except ValueError as exc:
        assert "must be a JSON object" in str(exc)
    else:
        raise AssertionError("Expected non-object state to fail closed")

    state_path.write_text('{"schema_version": "unknown"}', encoding="utf-8")
    try:
        run_profile_preview(_preview(), library_dir=tmp_path, approved=False)
    except ValueError as exc:
        assert "Unsupported profile run state schema" in str(exc)
    else:
        raise AssertionError("Expected wrong schema to fail closed")


def test_profile_run_rejects_wrong_typed_state_collections(tmp_path):
    state_path = profile_run_state_path(tmp_path, "agent-loops")
    state_path.parent.mkdir(parents=True)
    state_path.write_text(
        json.dumps({"schema_version": "profile-run-state.v1", "completed": []}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="completed must be a JSON object"):
        run_profile_preview(_preview(), library_dir=tmp_path, approved=False)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("attempts", {}, "attempts must be an array"),
        ("attempts", [1], "attempts must be an array"),
        ("last_success", [], "last_success must be a JSON object"),
        ("last_failure", "bad", "last_failure must be a JSON object"),
    ],
)
def test_profile_run_rejects_invalid_nested_state_before_execution(
    tmp_path: Path, field: str, value: object, message: str
) -> None:
    state_path = profile_run_state_path(tmp_path, "agent-loops")
    state_path.parent.mkdir(parents=True)
    state_path.write_text(
        json.dumps({"schema_version": "profile-run-state.v1", field: value}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=message):
        run_profile_preview(_preview(), library_dir=tmp_path, approved=True)


@pytest.mark.parametrize("field", ["profile", "topic"])
def test_profile_run_rejects_mismatched_state_provenance(tmp_path: Path, field: str) -> None:
    state_path = profile_run_state_path(tmp_path, "agent-loops")
    state_path.parent.mkdir(parents=True)
    state_path.write_text(
        json.dumps(
            {
                "schema_version": "profile-run-state.v1",
                "profile": "agent-loops",
                "topic": "agent-loops",
                field: "different",
                "completed": {},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=f"{field} does not match"):
        run_profile_preview(_preview(), library_dir=tmp_path, approved=False)


@pytest.mark.parametrize(
    ("last_run", "message"),
    [
        (
            {
                "status": "ok",
                "max_metered_usd": 0,
                "metered_spend_usd": 0,
                "metered_spend_verified": True,
                "started_at": "not-a-time",
            },
            "started_at",
        ),
        (
            {
                "status": "ok",
                "max_metered_usd": 0,
                "metered_spend_usd": 0,
                "metered_spend_verified": True,
                "started_at": "2026-07-13T01:00:00Z",
                "finished_at": "2026-07-13T00:00:00Z",
            },
            "cannot precede",
        ),
    ],
)
def test_profile_run_rejects_invalid_last_run_timestamps(
    tmp_path: Path, last_run: dict[str, object], message: str
) -> None:
    state_path = profile_run_state_path(tmp_path, "agent-loops")
    state_path.parent.mkdir(parents=True)
    state_path.write_text(
        json.dumps(
            {
                "schema_version": "profile-run-state.v1",
                "profile": "agent-loops",
                "topic": "agent-loops",
                "last_run": last_run,
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=message):
        run_profile_preview(_preview(), library_dir=tmp_path, approved=False)


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (
            '{"schema_version":"profile-run-state.v1","value":' + "9" * 5_000 + "}",
            "not parseable",
        ),
        ("[" * 2_000 + "0" + "]" * 2_000, "must be a JSON object"),
    ],
)
def test_profile_run_wraps_pathological_state_json(
    tmp_path: Path, content: str, message: str
) -> None:
    state_path = profile_run_state_path(tmp_path, "agent-loops")
    state_path.parent.mkdir(parents=True)
    state_path.write_text(content, encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        run_profile_preview(_preview(), library_dir=tmp_path, approved=False)


def test_profile_run_rejects_state_over_byte_cap_before_json_parse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_path = profile_run_state_path(tmp_path, "agent-loops")
    state_path.parent.mkdir(parents=True)
    state_path.write_bytes(b"{" + b" " * 32 + b"}")
    monkeypatch.setattr("distill.pipeline.profile_state._MAX_STATE_BYTES", 16)

    with pytest.raises(ValueError, match="not parseable") as raised:
        run_profile_preview(_preview(), library_dir=tmp_path, approved=False)

    assert "byte cap" in str(raised.value.__cause__)


def test_profile_run_retains_only_recent_attempt_history(tmp_path: Path) -> None:
    def executor(_command: list[str], _timeout: int, **_kwargs) -> CommandExecution:
        return CommandExecution(exit_code=0, elapsed_seconds=0.01)

    for _ in range(105):
        run_profile_preview(
            _preview(),
            library_dir=tmp_path,
            approved=True,
            executor=executor,
        )

    state = json.loads(profile_run_state_path(tmp_path, "agent-loops").read_text(encoding="utf-8"))
    assert len(state["attempts"]) == 100


def test_profile_run_auto_cost_mode_and_command_hash_keys(tmp_path):
    preview = ProfilePreviewResult(
        schema_version="profile-preview.v1",
        profile="agent-loops",
        topic="agent-loops",
        cost_mode="auto",
        ordering="test order",
        fresh_item_limit=1,
        candidates=[
            ProfilePreviewCandidate(
                kind="domain",
                title="example.com",
                url="https://example.com",
                source="example.com",
                source_label="example.com",
                identity="",
                command=["distill", "site", "https://example.com", "--topic", "agent-loops"],
            )
        ],
    )

    result = run_profile_preview(
        preview,
        library_dir=tmp_path,
        approved=False,
        profile_ref="profiles/agent-loops.yaml",
    )

    action = result.to_dict()["next_actions"][0]
    assert result.commands[0].key.startswith("domain:command:")
    assert action["approval"] == "spend"
    assert action["estimated_cost_usd"] is None
    assert action["command"] == ["distill", "profile", "run", "profiles/agent-loops.yaml", "--yes"]
    assert action["verifier"]["command"] == [
        "distill",
        "--json",
        "profile",
        "run",
        "profiles/agent-loops.yaml",
    ]


def test_profile_run_zero_budget_forces_every_command_to_no_metered(tmp_path: Path) -> None:
    commands: list[list[str]] = []
    environments: list[Mapping[str, str] | None] = []

    def executor(
        command: list[str],
        _timeout: int,
        *,
        environment: Mapping[str, str] | None = None,
    ) -> CommandExecution:
        commands.append(command)
        environments.append(environment)
        return CommandExecution(exit_code=0, elapsed_seconds=0.1)

    result = run_profile_preview(
        _metered_preview(max_metered_usd=0),
        library_dir=tmp_path,
        approved=True,
        executor=executor,
    )

    assert all(command[1:3] == ["--cost-mode", "no-metered"] for command in commands)
    assert all(set(environment or {}) == {PROFILE_RECEIPT_ENV} for environment in environments)
    assert result.metered_spend_usd == 0
    assert result.metered_spend_verified is True
    assert result.health_status == "ok"
    assert result.to_dict()["max_metered_usd"] == 0


def test_profile_run_no_metered_mode_overrides_contradictory_candidate_argv(
    tmp_path: Path,
) -> None:
    preview = _metered_preview(max_metered_usd=0)
    preview = replace(
        preview,
        cost_mode="no-metered",
        candidates=[
            replace(
                preview.candidates[0],
                command=[
                    "distill",
                    "--cost-mode",
                    "paid-ok",
                    "video",
                    preview.candidates[0].url,
                ],
            )
        ],
    )
    calls: list[list[str]] = []

    def executor(command: list[str], _timeout: int, **_kwargs) -> CommandExecution:
        calls.append(command)
        return CommandExecution(exit_code=0, elapsed_seconds=0.1)

    run_profile_preview(preview, library_dir=tmp_path, approved=True, executor=executor)

    assert calls[0][1:3] == ["--cost-mode", "no-metered"]


def test_profile_run_enforces_remaining_aggregate_budget(tmp_path: Path) -> None:
    calls: list[tuple[list[str], Mapping[str, str] | None]] = []

    def executor(
        command: list[str],
        _timeout: int,
        *,
        environment: Mapping[str, str] | None = None,
    ) -> CommandExecution:
        calls.append((command, environment))
        if len(calls) == 1:
            _append_profile_receipt(tmp_path, environment, 1.0)
        return CommandExecution(exit_code=0, elapsed_seconds=0.1)

    result = run_profile_preview(
        _metered_preview(),
        library_dir=tmp_path,
        approved=True,
        executor=executor,
        workflow_budgets_usd={
            "site": 0.5,
            "video": 2.0,
            "boolean": True,
            "overflow": 10**4_000,
        },
    )

    assert calls[0][0][1] == "video"
    assert calls[0][1] is not None
    assert calls[0][1]["DISTILL_COST_WORKFLOW_BUDGETS"] == "site=0.5,video=1"
    assert calls[1][0][1:3] == ["--cost-mode", "no-metered"]
    assert set(calls[1][1] or {}) == {PROFILE_RECEIPT_ENV}
    assert result.metered_spend_usd == 1.0
    assert result.metered_spend_verified is True
    assert result.health_status == "ok"


def test_profile_run_deduplicates_cumulative_receipts_per_tracker(tmp_path: Path) -> None:
    def executor(
        _command: list[str],
        _timeout: int,
        *,
        environment: Mapping[str, str] | None = None,
    ) -> CommandExecution:
        _append_profile_receipt(tmp_path, environment, 0.2)
        _append_profile_receipt(tmp_path, environment, 0.3)
        return CommandExecution(exit_code=0, elapsed_seconds=0.1)

    preview = _metered_preview()
    preview = replace(preview, candidates=preview.candidates[:1])

    result = run_profile_preview(
        preview,
        library_dir=tmp_path,
        approved=True,
        executor=executor,
    )

    assert result.metered_spend_usd == 0.3
    assert result.metered_spend_verified is True


def test_profile_run_sums_distinct_tracker_receipts_without_rounding(tmp_path: Path) -> None:
    def executor(
        _command: list[str],
        _timeout: int,
        *,
        environment: Mapping[str, str] | None = None,
    ) -> CommandExecution:
        _append_profile_receipt(tmp_path, environment, 0.2, tracker_id="1" * 32)
        _append_profile_receipt(tmp_path, environment, 0.0000001, tracker_id="2" * 32)
        return CommandExecution(exit_code=0, elapsed_seconds=0.1)

    preview = replace(_metered_preview(), candidates=_metered_preview().candidates[:1])
    result = run_profile_preview(
        preview,
        library_dir=tmp_path,
        approved=True,
        executor=executor,
    )

    assert result.metered_spend_usd == pytest.approx(0.2000001)
    assert result.metered_spend_verified is True


@pytest.mark.parametrize("malformed_first", [False, True])
def test_profile_run_preserves_known_spend_around_malformed_complete_rows(
    tmp_path: Path, malformed_first: bool
) -> None:
    calls: list[list[str]] = []

    def executor(
        command: list[str],
        _timeout: int,
        *,
        environment: Mapping[str, str] | None = None,
    ) -> CommandExecution:
        calls.append(command)
        if len(calls) == 1:
            path = tmp_path / ".distill" / "cost_log.jsonl"
            path.parent.mkdir(parents=True, exist_ok=True)
            if malformed_first:
                path.write_text("{malformed}\n", encoding="utf-8")
            _append_profile_receipt(tmp_path, environment, 0.25)
            if not malformed_first:
                with path.open("a", encoding="utf-8") as stream:
                    stream.write("{malformed}\n")
        return CommandExecution(exit_code=0, elapsed_seconds=0.1)

    result = run_profile_preview(
        _metered_preview(),
        library_dir=tmp_path,
        approved=True,
        executor=executor,
    )

    assert result.metered_spend_usd == 0.25
    assert result.metered_spend_verified is False
    assert calls[1][1:3] == ["--cost-mode", "no-metered"]


def test_profile_run_preserves_known_spend_before_partial_row(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def executor(
        command: list[str],
        _timeout: int,
        *,
        environment: Mapping[str, str] | None = None,
    ) -> CommandExecution:
        calls.append(command)
        if len(calls) == 1:
            _append_profile_receipt(tmp_path, environment, 0.25)
            with (tmp_path / ".distill" / "cost_log.jsonl").open("a", encoding="utf-8") as stream:
                stream.write('{"partial":')
        return CommandExecution(exit_code=0, elapsed_seconds=0.1)

    result = run_profile_preview(
        _metered_preview(),
        library_dir=tmp_path,
        approved=True,
        executor=executor,
    )

    assert result.metered_spend_usd == 0.25
    assert result.metered_spend_verified is False
    assert calls[1][1:3] == ["--cost-mode", "no-metered"]


@pytest.mark.parametrize("include_matching", [False, True])
def test_profile_run_ignores_well_formed_unrelated_receipts(
    tmp_path: Path, include_matching: bool
) -> None:
    def executor(
        _command: list[str],
        _timeout: int,
        *,
        environment: Mapping[str, str] | None = None,
    ) -> CommandExecution:
        assert environment is not None
        unrelated_environment = dict(environment)
        unrelated_environment[PROFILE_RECEIPT_ENV] = "f" * 64
        _append_profile_receipt(tmp_path, unrelated_environment, 9.0)
        if include_matching:
            _append_profile_receipt(tmp_path, environment, 0.25)
        return CommandExecution(exit_code=0, elapsed_seconds=0.1)

    preview = replace(_metered_preview(), candidates=_metered_preview().candidates[:1])
    result = run_profile_preview(
        preview,
        library_dir=tmp_path,
        approved=True,
        executor=executor,
    )

    assert result.metered_spend_usd == (0.25 if include_matching else 0.0)
    assert result.metered_spend_verified is include_matching


def test_profile_run_counts_matching_receipt_from_no_metered_child(tmp_path: Path) -> None:
    def executor(
        _command: list[str],
        _timeout: int,
        *,
        environment: Mapping[str, str] | None = None,
    ) -> CommandExecution:
        _append_profile_receipt(tmp_path, environment, 0.0000001)
        return CommandExecution(exit_code=0, elapsed_seconds=0.1)

    preview = replace(
        _metered_preview(max_metered_usd=0),
        candidates=_metered_preview(max_metered_usd=0).candidates[:1],
    )
    result = run_profile_preview(
        preview,
        library_dir=tmp_path,
        approved=True,
        executor=executor,
    )

    assert result.metered_spend_usd == 0.0000001
    assert result.metered_spend_verified is True
    assert result.health_status == "budget_exceeded"
    assert result.failed_count == 1


def test_profile_run_success_without_required_receipt_fails_closed(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def executor(command: list[str], _timeout: int, **_kwargs) -> CommandExecution:
        calls.append(command)
        return CommandExecution(exit_code=0, elapsed_seconds=0.1)

    result = run_profile_preview(
        _metered_preview(),
        library_dir=tmp_path,
        approved=True,
        executor=executor,
    )

    assert result.metered_spend_verified is False
    assert result.health_status == "budget_unverified"
    assert result.failed_count == 1
    assert calls[1][1:3] == ["--cost-mode", "no-metered"]
    assert result.next_actions[0].kind == "profile_run_retry"

    state_path = profile_run_state_path(tmp_path, "agent-loops")
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert "youtube_video:youtube:v0" not in state["completed"]
    assert state["last_run"] == {
        "finished_at": result.generated_at,
        "max_metered_usd": 1.0,
        "metered_spend_usd": 0.0,
        "metered_spend_verified": False,
        "started_at": state["last_started_at"],
        "status": "budget_unverified",
    }

    retry_plan = run_profile_preview(
        _metered_preview(),
        library_dir=tmp_path,
        approved=False,
    )
    assert retry_plan.commands[0].status == "pending"

    profile_path = tmp_path / "profiles" / "agent-loops.yaml"
    profile_path.parent.mkdir(parents=True)
    profile_path.write_text(
        "\n".join(
            [
                "schema_version: research-profile.v1",
                "name: agent-loops",
                "topic: agent-loops",
                "goal_file: goals/agent-loops.md",
                "cost_mode: no-metered",
                "queries: [agent loops]",
                "limits:",
                "  max_metered_usd: 0",
            ]
        ),
        encoding="utf-8",
    )
    health = collect_profile_health(tmp_path)
    assert health.last_failed[0]["status"] == "budget_unverified"


def test_profile_run_freshness_is_anchored_to_terminal_completion(tmp_path, monkeypatch) -> None:
    clock = {"value": "2026-07-13T00:00:00Z"}
    monkeypatch.setattr(profile_run_module, "_now_iso", lambda: clock["value"])

    def executor(_command: list[str], _timeout: int, **_kwargs) -> CommandExecution:
        clock["value"] = "2026-07-13T02:00:00Z"
        return CommandExecution(exit_code=0, elapsed_seconds=7_200)

    result = run_profile_preview(
        replace(_preview(), candidates=_preview().candidates[:1], fresh_item_limit=1),
        library_dir=tmp_path,
        approved=True,
        executor=executor,
    )

    state = json.loads(profile_run_state_path(tmp_path, "agent-loops").read_text(encoding="utf-8"))
    assert state["last_started_at"] == "2026-07-13T00:00:00Z"
    assert state["last_run_at"] == "2026-07-13T02:00:00Z"
    assert result.generated_at == state["last_run_at"]

    profile_path = tmp_path / "profiles" / "agent-loops.yaml"
    profile_path.parent.mkdir(parents=True)
    profile_path.write_text(
        "\n".join(
            [
                "schema_version: research-profile.v1",
                "name: agent-loops",
                "topic: agent-loops",
                "goal_file: goals/agent-loops.md",
                "cost_mode: no-metered",
                "freshness:",
                "  cadence: daily",
                "  stale_after: PT1H",
                "queries: [agent loops]",
                "limits:",
                "  max_metered_usd: 0",
            ]
        ),
        encoding="utf-8",
    )
    health = collect_profile_health(
        tmp_path,
        now=datetime(2026, 7, 13, 2, 30, tzinfo=UTC),
    )
    assert health.stale == []


@pytest.mark.parametrize("digits", [4_000, 5_000])
def test_profile_run_malformed_large_receipt_fails_closed(tmp_path: Path, digits: int) -> None:
    calls: list[list[str]] = []

    def executor(
        command: list[str],
        _timeout: int,
        *,
        environment: Mapping[str, str] | None = None,
    ) -> CommandExecution:
        calls.append(command)
        if len(calls) == 1:
            assert environment is not None
            path = tmp_path / ".distill" / "cost_log.jsonl"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                '{"profile_receipt_id":"'
                + environment[PROFILE_RECEIPT_ENV]
                + '","profile_receipt_tracker_id":"'
                + "0" * 32
                + '","profile_receipt_cost_usd":'
                + "9" * digits
                + "}\n",
                encoding="utf-8",
            )
        return CommandExecution(exit_code=0, elapsed_seconds=0.1)

    result = run_profile_preview(
        _metered_preview(),
        library_dir=tmp_path,
        approved=True,
        executor=executor,
    )

    assert result.metered_spend_verified is False
    assert result.health_status == "budget_unverified"
    assert calls[1][1:3] == ["--cost-mode", "no-metered"]


def test_profile_run_requires_receipt_and_success_for_metered_child(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def executor(
        command: list[str],
        _timeout: int,
        *,
        environment: Mapping[str, str] | None = None,
    ) -> CommandExecution:
        calls.append(command)
        if len(calls) == 1:
            _append_profile_receipt(tmp_path, environment, 0.25)
            return CommandExecution(exit_code=124, elapsed_seconds=0.1, timed_out=True)
        return CommandExecution(exit_code=0, elapsed_seconds=0.1)

    result = run_profile_preview(
        _metered_preview(),
        library_dir=tmp_path,
        approved=True,
        executor=executor,
    )

    assert result.metered_spend_usd == 0.25
    assert result.metered_spend_verified is False
    assert calls[1][1:3] == ["--cost-mode", "no-metered"]


def test_profile_run_timed_out_flag_overrides_zero_exit_code(tmp_path: Path) -> None:
    def executor(
        _command: list[str],
        _timeout: int,
        *,
        environment: Mapping[str, str] | None = None,
    ) -> CommandExecution:
        _append_profile_receipt(tmp_path, environment, 0.25)
        return CommandExecution(exit_code=0, elapsed_seconds=0.1, timed_out=True)

    preview = replace(_metered_preview(), candidates=_metered_preview().candidates[:1])
    result = run_profile_preview(
        preview,
        library_dir=tmp_path,
        approved=True,
        executor=executor,
    )

    assert result.failed_count == 1
    assert result.succeeded_count == 0
    assert result.metered_spend_usd == 0.25
    assert result.metered_spend_verified is False


@pytest.mark.parametrize("budget", [-1.0, float("inf"), float("nan"), True, 10**4_000])
def test_profile_run_rejects_invalid_manual_budget(tmp_path: Path, budget: object) -> None:
    with pytest.raises(ValueError, match="finite nonnegative"):
        run_profile_preview(
            _metered_preview(max_metered_usd=budget),
            library_dir=tmp_path,
            approved=False,
        )


def test_profile_run_fails_closed_when_cumulative_spend_overflows(tmp_path: Path) -> None:
    def executor(
        _command: list[str],
        _timeout: int,
        *,
        environment: Mapping[str, str] | None = None,
    ) -> CommandExecution:
        _append_profile_receipt(tmp_path, environment, 1e308)
        return CommandExecution(exit_code=0, elapsed_seconds=0.1)

    result = run_profile_preview(
        _metered_preview(max_metered_usd=1e308),
        library_dir=tmp_path,
        approved=True,
        executor=executor,
    )

    assert result.metered_spend_usd == 1e308
    assert result.metered_spend_verified is False
    assert result.health_status == "budget_unverified"
    assert result.failed_count == 1


def test_execute_command_normalizes_subprocess_outcomes(monkeypatch):
    failed = execute_command(
        [
            sys.executable,
            "-c",
            "import sys; sys.stdout.write('x' * 5_000_000); "
            "sys.stderr.write('err'); raise SystemExit(3)",
        ],
        timeout_seconds=7,
    )
    assert failed.exit_code == 3
    assert len(failed.stdout_tail) == 4000
    assert failed.stderr_tail == "err"

    missing_result = execute_command(["definitely-missing-distill-executable"], timeout_seconds=7)
    assert missing_result.exit_code == 127
    assert missing_result.stderr_tail

    timeout = execute_command(
        [
            sys.executable,
            "-c",
            "import sys,time; print('partial', flush=True); time.sleep(5)",
        ],
        timeout_seconds=0.1,
    )
    assert timeout.exit_code == 124
    assert timeout.stdout_tail.strip() == "partial"
    assert timeout.stderr_tail == "Timed out after 0.1s"
    assert timeout.timed_out is True

    monkeypatch.setattr(
        "distill.pipeline.profile_run.subprocess.Popen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("argument list too long")),
    )
    launch_error = execute_command(["oversized"], timeout_seconds=7)
    assert launch_error.exit_code == 127
    assert "executable not found" in launch_error.stderr_tail


def test_execute_command_timeout_is_not_held_open_by_grandchild_pipes() -> None:
    start = time.monotonic()
    result = execute_command(
        [
            sys.executable,
            "-c",
            "import subprocess,sys,time; "
            "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(5)']); "
            "print('started', flush=True); time.sleep(5)",
        ],
        timeout_seconds=0.1,
    )

    assert result.exit_code == 124
    assert result.timed_out is True
    assert result.stdout_tail.strip() == "started"
    assert time.monotonic() - start < 3


@pytest.mark.parametrize("timeout", [0, -1, True, float("inf"), float("nan"), 10**4_000])
def test_execute_command_rejects_invalid_timeout(timeout: object) -> None:
    with pytest.raises(ValueError, match="timeout_seconds"):
        execute_command([sys.executable, "-c", "pass"], timeout_seconds=timeout)


def test_execute_command_uses_the_running_interpreter_for_distill(monkeypatch):
    invoked = []

    class FakeProcess:
        stdout = io.BytesIO()
        stderr = io.BytesIO()
        returncode = 0

        def wait(self, timeout=None):
            return 0

    def completed(command, **_kwargs):
        invoked.append(command)
        return FakeProcess()

    monkeypatch.setattr("distill.pipeline.profile_run.subprocess.Popen", completed)

    result = execute_command(["distill", "doctor"], timeout_seconds=7)

    assert result.exit_code == 0
    assert invoked == [[sys.executable, "-P", "-m", "distill", "doctor"]]


def test_isolated_module_execution_ignores_cwd_distill_package(tmp_path):
    planted_package = tmp_path / "distill"
    planted_package.mkdir()
    marker = tmp_path / "hijacked.txt"
    (planted_package / "__main__.py").write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('executed')\n",
        encoding="utf-8",
    )

    completed = subprocess.run(
        [sys.executable, "-P", "-m", "distill", "--help"],
        cwd=tmp_path,
        capture_output=True,
        check=False,
        encoding="utf-8",
        errors="replace",
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0
    assert not marker.exists()


def test_profile_run_pure_fallback_helpers(tmp_path):
    assert library_relative(tmp_path / "outside.json", tmp_path / "library") == str(
        tmp_path / "outside.json"
    )


def test_profile_run_command_and_cost_ledger_helpers_fail_closed(tmp_path: Path) -> None:
    assert profile_run_module._with_cost_mode([], "no-metered") == []
    assert profile_run_module._with_cost_mode(["python", "task.py"], "no-metered") == [
        "python",
        "task.py",
    ]
    assert profile_run_module._with_cost_mode(
        ["distill", "--cost-mode=auto", "latest"],
        "no-metered",
    ) == ["distill", "--cost-mode=no-metered", "latest"]
    assert profile_run_module._distill_command_name(["distill", "--cost-mode", "no-metered"]) == ""
    assert (
        profile_run_module._distill_command_name(
            ["distill", "--cost-mode=no-metered", "--json", "LATEST"]
        )
        == "latest"
    )
    assert (
        profile_run_module._distill_cost_mode(["distill", "--cost-mode", "no-metered", "latest"])
        == "no-metered"
    )

    missing = tmp_path / "missing-cost-log.jsonl"
    assert profile_run_module._appended_cost(
        missing,
        None,
        receipt_id="receipt",
        require_receipt=True,
    ) == (0.0, False)
    assert profile_run_module._appended_cost(
        missing,
        profile_run_module._CostLogCheckpoint(exists=True),
        receipt_id="receipt",
        require_receipt=False,
    ) == (0.0, False)

    cost_log = tmp_path / "cost-log.jsonl"
    cost_log.write_text("seed\n", encoding="utf-8")
    current = cost_log.stat()
    mismatched = profile_run_module._CostLogCheckpoint(
        exists=True,
        device=current.st_dev,
        inode=current.st_ino + 1,
        size=current.st_size,
    )
    assert profile_run_module._read_cost_log_append(cost_log, mismatched) is None

    receipt_id = "r" * 64
    tracker_id = "a" * 32
    rows = [
        b"",
        b"[]",
        json.dumps(
            {
                "profile_receipt_id": receipt_id,
                "profile_receipt_tracker_id": tracker_id,
                "profile_receipt_cost_usd": 1.0,
            }
        ).encode(),
        json.dumps(
            {
                "profile_receipt_id": receipt_id,
                "profile_receipt_tracker_id": tracker_id,
                "profile_receipt_cost_usd": 0.5,
            }
        ).encode(),
        json.dumps(
            {
                "profile_receipt_id": receipt_id,
                "profile_receipt_tracker_id": "short",
                "profile_receipt_cost_usd": 2.0,
            }
        ).encode(),
        json.dumps(
            {
                "profile_receipt_id": receipt_id,
                "profile_receipt_tracker_id": "z" * 32,
                "profile_receipt_cost_usd": 2.0,
            }
        ).encode(),
    ]
    total, verified = profile_run_module._parse_cost_log_append(
        b"\n".join(rows) + b"\n",
        receipt_id=receipt_id,
        require_receipt=True,
        append_complete=True,
    )
    assert total == 1.0
    assert verified is False

    for invalid_cost in (True, float("nan"), -1):
        with pytest.raises(ValueError, match="invalid profile receipt cost"):
            profile_run_module._validated_receipt_float(invalid_cost)

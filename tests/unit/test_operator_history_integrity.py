"""Concurrency and failure controls for append-only operator histories."""

from __future__ import annotations

import json
import multiprocessing
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from distill.commands import _topic_changes
from distill.commands import eval as eval_command
from distill.config import DistillConfig
from distill.jsonl import read_jsonl_objects_strict
from distill.pipeline import summary as summary_module
from distill.pipeline.summary import RunSummary


def _topic_append(config: DistillConfig, index: int) -> Path:
    generated_at = datetime(2026, 7, 18, 12, 0, 0) + timedelta(seconds=index)
    return _topic_changes._append_topic_change_history(
        config,
        topic="integrity",
        summary=f"change-{index}",
        baseline=None,
        generated_at=generated_at,
        watch_name="integrity-watch",
        query="integrity",
        cadence="daily",
        new_videos=[],
        new_pages=[],
        new_papers=[],
        refreshed_outputs=[],
    )


def _process_summary_writer(log_dir: str, index: int, start) -> None:
    if not start.wait(timeout=10):
        raise TimeoutError("summary process start gate timed out")
    summary_module._save_run_artifacts(
        RunSummary(command=f"process-{index}", run_id=f"run-process-{index}"),
        Path(log_dir),
    )


def _strict_rows(path: Path, *, max_rows: int = 100) -> list[dict[str, object]]:
    return read_jsonl_objects_strict(
        path,
        max_file_bytes=4 * 1024 * 1024,
        max_row_bytes=256 * 1024,
        max_rows=max_rows,
    )


def _assert_latest_projections_correlate(log_dir: Path) -> dict[str, object]:
    payload = json.loads((log_dir / "latest_run.json").read_text(encoding="utf-8"))
    markdown = (log_dir / "latest_run_errors.md").read_text(encoding="utf-8")
    assert f"- Timestamp: `{payload['timestamp']}`" in markdown
    assert f"- Run ID: `{payload['run_id']}`" in markdown
    assert f"- Command: `{payload['command']}`" in markdown
    return payload


def test_eval_append_separates_a_torn_tail_from_the_next_complete_row(tmp_path: Path) -> None:
    path = tmp_path / "eval" / "results.jsonl"
    path.parent.mkdir()
    path.write_bytes(b'{"incomplete":')

    eval_command._append_results_log(path, ['{"fixture":"complete"}'])

    assert path.read_bytes() == b'{"incomplete":\n{"fixture":"complete"}\n'


def test_eval_append_rejects_a_multiply_linked_target(tmp_path: Path) -> None:
    external = tmp_path / "external.jsonl"
    external.write_text('{"preserve":true}\n', encoding="utf-8")
    path = tmp_path / "results.jsonl"
    os.link(external, path)

    with pytest.raises(ValueError, match="multiply linked"):
        eval_command._append_results_log(path, ['{"fixture":"blocked"}'])

    assert external.read_text(encoding="utf-8") == '{"preserve":true}\n'


def test_topic_history_thread_contention_preserves_every_complete_row(tmp_path: Path) -> None:
    config = DistillConfig(distill_output_dir=tmp_path / "library")
    with ThreadPoolExecutor(max_workers=8) as executor:
        paths = list(executor.map(lambda index: _topic_append(config, index), range(32)))

    assert len(set(paths)) == 1
    rows = _strict_rows(paths[0], max_rows=32)
    assert len(rows) == 32
    assert {row["summary"] for row in rows} == {f"change-{index}" for index in range(32)}


def test_topic_history_rejects_a_multiply_linked_target(tmp_path: Path) -> None:
    config = DistillConfig(distill_output_dir=tmp_path / "library")
    path = config.topic_dir("integrity") / "change_history.jsonl"
    path.parent.mkdir(parents=True)
    external = tmp_path / "external.jsonl"
    external.write_text('{"preserve":true}\n', encoding="utf-8")
    os.link(external, path)

    with pytest.raises(ValueError, match="multiply linked"):
        _topic_append(config, 1)

    assert external.read_text(encoding="utf-8") == '{"preserve":true}\n'


@pytest.mark.parametrize(
    "unsafe_name",
    ["run_log.jsonl", "latest_run.json", "latest_run_errors.md"],
)
def test_run_artifacts_reject_unsafe_targets_before_projection_changes(
    tmp_path: Path,
    unsafe_name: str,
) -> None:
    external = tmp_path / "external.txt"
    external.write_text("preserve", encoding="utf-8")
    os.link(external, tmp_path / unsafe_name)

    with pytest.raises(ValueError, match=r"linked|unsafe"):
        summary_module._save_run_artifacts(
            RunSummary(command="blocked", run_id="run-blocked"),
            tmp_path,
        )

    assert external.read_text(encoding="utf-8") == "preserve"
    for name in ("run_log.jsonl", "latest_run.json", "latest_run_errors.md"):
        candidate = tmp_path / name
        if name == unsafe_name:
            assert candidate.samefile(external)
        else:
            assert not candidate.exists()


def test_run_projection_failure_restores_correlated_prior_projections(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    summary_module._save_run_artifacts(
        RunSummary(command="previous", run_id="run-previous"),
        tmp_path,
    )
    original_write = summary_module.atomic_write_text
    failed = False

    def fail_markdown_once(path: Path, content: str) -> None:
        nonlocal failed
        if path.name == "latest_run_errors.md" and not failed:
            failed = True
            raise OSError("forced markdown failure")
        original_write(path, content)

    monkeypatch.setattr(summary_module, "atomic_write_text", fail_markdown_once)

    with pytest.raises(OSError, match="forced markdown failure"):
        summary_module._save_run_artifacts(
            RunSummary(command="failed-update", run_id="run-failed-update"),
            tmp_path,
        )

    latest = _assert_latest_projections_correlate(tmp_path)
    assert latest["run_id"] == "run-previous"
    rows = _strict_rows(tmp_path / "run_log.jsonl")
    assert [row["run_id"] for row in rows] == ["run-previous", "run-failed-update"]


def test_first_run_projection_failure_removes_the_unpaired_projection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_write = summary_module.atomic_write_text

    def fail_markdown(path: Path, content: str) -> None:
        if path.name == "latest_run_errors.md":
            raise OSError("forced first-run markdown failure")
        original_write(path, content)

    monkeypatch.setattr(summary_module, "atomic_write_text", fail_markdown)

    with pytest.raises(OSError, match="forced first-run markdown failure"):
        summary_module._save_run_artifacts(
            RunSummary(command="first-failed", run_id="run-first-failed"),
            tmp_path,
        )

    assert not (tmp_path / "latest_run.json").exists()
    assert not (tmp_path / "latest_run_errors.md").exists()
    assert [row["run_id"] for row in _strict_rows(tmp_path / "run_log.jsonl")] == [
        "run-first-failed"
    ]


def test_oversized_run_projection_refuses_before_touching_any_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    summary_module._save_run_artifacts(
        RunSummary(command="previous", run_id="run-previous"),
        tmp_path,
    )
    paths = [
        tmp_path / "run_log.jsonl",
        tmp_path / "latest_run.json",
        tmp_path / "latest_run_errors.md",
    ]
    before = {path: path.read_bytes() for path in paths}
    monkeypatch.setattr(summary_module, "_MAX_RUN_PROJECTION_BYTES", 512)

    with pytest.raises(ValueError, match="byte limit"):
        summary_module._save_run_artifacts(
            RunSummary(command="x" * 2_000, run_id="run-oversized"),
            tmp_path,
        )

    assert {path: path.read_bytes() for path in paths} == before


def test_forced_thread_interleaving_keeps_projection_pairs_serialized(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_write = summary_module.atomic_write_text
    first_json_entered = threading.Event()
    second_attempted = threading.Event()
    writes: list[tuple[str, str]] = []
    failures: list[BaseException] = []

    def observed_write(path: Path, content: str) -> None:
        if path.suffix == ".json":
            command = str(json.loads(content)["command"])
        else:
            command = content.split("- Command: `", 1)[1].split("`", 1)[0]
        if path.name == "latest_run.json" and command == "first":
            first_json_entered.set()
            assert second_attempted.wait(timeout=5)
        writes.append((command, path.name))
        original_write(path, content)

    monkeypatch.setattr(summary_module, "atomic_write_text", observed_write)

    def save(command: str) -> None:
        if command == "second":
            second_attempted.set()
        try:
            summary_module._save_run_artifacts(
                RunSummary(command=command, run_id=f"run-{command}"),
                tmp_path,
            )
        except BaseException as exc:
            failures.append(exc)

    first = threading.Thread(target=save, args=("first",))
    first.start()
    assert first_json_entered.wait(timeout=5)
    second = threading.Thread(target=save, args=("second",))
    second.start()
    first.join(timeout=10)
    second.join(timeout=10)

    assert failures == []
    assert not first.is_alive()
    assert not second.is_alive()
    assert writes == [
        ("first", "latest_run.json"),
        ("first", "latest_run_errors.md"),
        ("second", "latest_run.json"),
        ("second", "latest_run_errors.md"),
    ]
    rows = _strict_rows(tmp_path / "run_log.jsonl")
    assert {row["run_id"] for row in rows} == {"run-first", "run-second"}
    assert _assert_latest_projections_correlate(tmp_path)["run_id"] == "run-second"


def test_run_artifact_process_contention_preserves_all_rows_and_latest_pair(
    tmp_path: Path,
) -> None:
    context = multiprocessing.get_context("spawn")
    start = context.Event()
    processes = [
        context.Process(target=_process_summary_writer, args=(str(tmp_path), index, start))
        for index in range(6)
    ]
    for process in processes:
        process.start()
    start.set()
    for process in processes:
        process.join(timeout=20)

    assert [process.exitcode for process in processes] == [0] * len(processes)
    rows = _strict_rows(tmp_path / "run_log.jsonl")
    assert len(rows) == len(processes)
    assert {row["run_id"] for row in rows} == {
        f"run-process-{index}" for index in range(len(processes))
    }
    latest = _assert_latest_projections_correlate(tmp_path)
    assert latest["run_id"] in {row["run_id"] for row in rows}

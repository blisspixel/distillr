"""Hermetic tests for bounded independent-ingest execution."""

from __future__ import annotations

import threading
from contextvars import ContextVar

import pytest

from distill.pipeline.concurrency import MAX_INGEST_WORKERS, iter_bounded


def test_iter_bounded_caps_live_workers_and_processes_every_item():
    barrier = threading.Barrier(MAX_INGEST_WORKERS)
    lock = threading.Lock()
    active = 0
    peak = 0

    def worker(item: int) -> int:
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        barrier.wait(timeout=5)
        with lock:
            active -= 1
        return item * 2

    items = [1, 2, 3, 4, 5, 6]
    results = list(iter_bounded(items, worker, max_workers=MAX_INGEST_WORKERS))

    assert peak == MAX_INGEST_WORKERS
    assert sorted(result.value for result in results) == [2, 4, 6, 8, 10, 12]
    assert all(result.error is None for result in results)


def test_iter_bounded_propagates_context_and_serializes_submission_callback():
    marker: ContextVar[str] = ContextVar("bounded_test_marker", default="missing")
    marker.set("run-123")
    coordinator_thread = threading.get_ident()
    submission_threads: list[int] = []

    results = list(
        iter_bounded(
            ["a", "b"],
            lambda item: f"{item}:{marker.get()}",
            max_workers=2,
            on_submit=lambda _index, _item: submission_threads.append(threading.get_ident()),
        )
    )

    assert sorted(result.value for result in results) == ["a:run-123", "b:run-123"]
    assert submission_threads == [coordinator_thread, coordinator_thread]


def test_iter_bounded_returns_item_errors_and_does_not_refill_after_close():
    started: list[int] = []

    def worker(item: int) -> int:
        started.append(item)
        raise ValueError(f"bad {item}")

    results = iter_bounded([1, 2], worker, max_workers=1)
    first = next(results)
    results.close()

    assert first.index == 0
    assert isinstance(first.error, ValueError)
    assert first.value is None
    assert started == [1]


@pytest.mark.parametrize("workers", [0, MAX_INGEST_WORKERS + 1])
def test_iter_bounded_rejects_an_unbounded_worker_count(workers: int):
    with pytest.raises(ValueError, match="max_workers"):
        list(iter_bounded([1], lambda item: item, max_workers=workers))


def test_iter_bounded_empty_input_does_not_construct_a_worker_pool():
    assert list(iter_bounded([], lambda item: item, max_workers=1)) == []

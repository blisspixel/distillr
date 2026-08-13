# pyright: strict
"""Small bounded-concurrency primitives for independent ingest items.

Report sections deliberately do not use this module. They depend on ordered
continuity and remain sequential.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from concurrent.futures import Future, ThreadPoolExecutor, wait
from contextvars import copy_context
from dataclasses import dataclass

MAX_INGEST_WORKERS = 3


@dataclass(frozen=True)
class BoundedTaskResult[ItemT, ResultT]:
    """One completed item from :func:`iter_bounded`.

    Worker exceptions are values so the caller can distinguish retryable
    per-item failures from workflow-wide hard stops on the coordinating thread.
    """

    index: int
    item: ItemT
    value: ResultT | None = None
    error: Exception | None = None


def _completed_result[ItemT, ResultT](
    future: Future[ResultT],
    index: int,
    item: ItemT,
) -> BoundedTaskResult[ItemT, ResultT]:
    try:
        return BoundedTaskResult(index=index, item=item, value=future.result())
    except Exception as exc:
        return BoundedTaskResult(index=index, item=item, error=exc)


def iter_bounded[ItemT, ResultT](
    items: Sequence[ItemT],
    worker: Callable[[ItemT], ResultT],
    *,
    max_workers: int,
    on_submit: Callable[[int, ItemT], None] | None = None,
) -> Iterator[BoundedTaskResult[ItemT, ResultT]]:
    """Yield completed independent work while keeping only a small window live.

    At most ``max_workers`` futures exist at once. Each submission receives a
    distinct copy of the current context so run ids and other context variables
    survive the thread boundary without sharing one entered ``Context``.
    """

    if not 1 <= max_workers <= MAX_INGEST_WORKERS:
        raise ValueError(f"max_workers must be between 1 and {MAX_INGEST_WORKERS}")
    if not items:
        return

    executor = ThreadPoolExecutor(
        max_workers=min(max_workers, len(items)),
        thread_name_prefix="distill-ingest",
    )
    pending: dict[Future[ResultT], tuple[int, ItemT]] = {}
    next_index = 0

    def submit(index: int) -> None:
        item = items[index]
        if on_submit is not None:
            on_submit(index, item)
        context = copy_context()
        pending[executor.submit(context.run, worker, item)] = (index, item)

    try:
        while next_index < min(max_workers, len(items)):
            submit(next_index)
            next_index += 1

        while pending:
            done, _ = wait(tuple(pending), return_when="FIRST_COMPLETED")
            for future in sorted(done, key=lambda candidate: pending[candidate][0]):
                index, item = pending.pop(future)
                yield _completed_result(future, index, item)

            # Refill only after the caller handles the complete ready set. If a
            # later result in that set is a hard stop, raising closes this
            # generator before any replacement work is submitted.
            for _ in done:
                if next_index < len(items):
                    submit(next_index)
                    next_index += 1
    finally:
        executor.shutdown(wait=True, cancel_futures=True)

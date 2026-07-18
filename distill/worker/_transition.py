# pyright: strict
"""Cross-process serialization for worker queue transitions."""

from __future__ import annotations

import functools
from collections.abc import Callable
from pathlib import Path
from typing import Concatenate, Protocol

from distill.library.locking import exclusive_path_lock
from distill.worker._contracts import WorkerTaskConflict

_TRANSITION_LOCK_TIMEOUT_SECONDS = 30.0


class TransitionOwner(Protocol):
    transition_lock_path: Path


def serialized_transition[Owner: TransitionOwner, **P, R](
    method: Callable[Concatenate[Owner, P], R],
) -> Callable[Concatenate[Owner, P], R]:
    """Serialize every queue state observation and mutation across processes."""

    @functools.wraps(method)
    def wrapper(self: Owner, *args: P.args, **kwargs: P.kwargs) -> R:
        try:
            with exclusive_path_lock(
                self.transition_lock_path,
                timeout_seconds=_TRANSITION_LOCK_TIMEOUT_SECONDS,
                timeout_message="worker task transition lock timed out",
            ):
                return method(self, *args, **kwargs)
        except TimeoutError as exc:
            raise WorkerTaskConflict("worker task transition lock timed out") from exc

    return wrapper

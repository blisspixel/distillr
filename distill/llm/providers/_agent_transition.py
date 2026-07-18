# pyright: strict
"""Cross-process serialization for deferred-provider state transitions."""

from __future__ import annotations

import functools
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any, Concatenate, Protocol

from distill.library.locking import exclusive_path_lock
from distill.llm.router import ConfigurationError

_TRANSITION_LOCK_TIMEOUT_SECONDS = 30.0


class TransitionOwner(Protocol):
    @property
    def transition_lock_path(self) -> Path: ...


def serialized_agent_call[Owner: TransitionOwner, **P, R](
    method: Callable[Concatenate[Owner, P], Coroutine[Any, Any, R]],
) -> Callable[Concatenate[Owner, P], Coroutine[Any, Any, R]]:
    """Serialize task dedupe, creation, and replay with worker transitions."""

    @functools.wraps(method)
    async def wrapper(self: Owner, *args: P.args, **kwargs: P.kwargs) -> R:
        try:
            with exclusive_path_lock(
                self.transition_lock_path,
                timeout_seconds=_TRANSITION_LOCK_TIMEOUT_SECONDS,
                timeout_message="agent task transition lock timed out",
            ):
                return await method(self, *args, **kwargs)
        except TimeoutError as exc:
            raise ConfigurationError("agent task transition lock timed out") from exc

    return wrapper

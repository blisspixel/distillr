# pyright: strict
"""Courtesy wait when Ollama already has a different model resident."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import Awaitable, Callable

from distill.llm._parsing import parse_ascii_uint
from distill.llm.errors import ProviderBusyTimeoutError
from distill.llm.providers._ollama_metadata import (  # pyright: ignore[reportPrivateUsage]
    _canonical_model_name,
)

logger = logging.getLogger("distill.llm.providers.ollama")

_CONTENTION_INITIAL_BACKOFF_SECONDS = 1.0
# A brief courtesy yield, not the whole call timeout. Ollama 0.32 loads models
# concurrently rather than evicting, so a resident model is usually not
# contention at all -- and tying this to the call timeout meant an idle model
# left over from a previous command stalled the next one for ten minutes and
# then failed it. Waiting briefly still lets a genuinely-busy short call finish.
_CONTENTION_WAIT_SECONDS = 30.0
_CONTENTION_WAIT_ENV = "DISTILL_OLLAMA_CONTENTION_WAIT"
# Opt-in for a shared box where disturbing another workload is worse than
# failing this one. Off by default: refusing the user's run to protect a
# hypothetical other run is the wrong default on a personal machine.
_STRICT_SLOT_ENV = "DISTILL_OLLAMA_STRICT_SLOT"
_CONTENTION_MAX_BACKOFF_SECONDS = 10.0

type RunningModelsFn = Callable[[float], Awaitable[tuple[str, ...] | None]]

__all__ = ["wait_for_model_slot"]


async def wait_for_model_slot(
    model: str,
    timeout: int,
    *,
    running_models: RunningModelsFn,
) -> None:
    """Wait until Ollama is free or already has the requested model loaded.

    Poll ``/api/ps`` with bounded backoff, then proceed. The wait is a short
    courtesy in case another model is mid-call; it is deliberately *not* the
    call timeout, because a model left resident by keep-alive is idle, not
    busy, and blocking on it stalled an unrelated run for the full timeout
    before failing it outright.

    Proceeding is safe: the runtime decides whether to hold both models or
    evict, and it is better placed to make that call than a fixed wait here.
    Set ``DISTILL_OLLAMA_STRICT_SLOT=1`` on a shared machine to keep the old
    refuse-rather-than-disturb behavior. Older or unavailable ``/api/ps``
    endpoints let the call proceed as before.
    """

    wait_limit = min(max(float(timeout), 0.0), _contention_wait_seconds())
    deadline = time.monotonic() + wait_limit
    backoff = _CONTENTION_INITIAL_BACKOFF_SECONDS
    first_wait = True
    last_running: tuple[str, ...] | None = None

    while True:
        remaining = deadline - time.monotonic()
        if last_running is not None and remaining <= 0:
            _resolve_contention(model, last_running, wait_limit)
            return

        running = await running_models(max(remaining, 0.0))
        if (
            running is None
            or not running
            or any(
                _canonical_model_name(model) == _canonical_model_name(running_model)
                for running_model in running
            )
        ):
            return

        last_running = running
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            _resolve_contention(model, running, wait_limit)
            return

        active = ", ".join(running)
        sleep_for = min(backoff, remaining)
        if first_wait:
            logger.warning(
                "Ollama is running %s; waiting up to %gs for requested model '%s'. "
                "No model will be substituted.",
                active,
                wait_limit,
                model,
            )
            first_wait = False
        logger.info(
            "Ollama is still running %s; checking again in %.1fs (%.1fs remaining)",
            active,
            sleep_for,
            remaining,
        )
        await asyncio.sleep(sleep_for)
        backoff = min(backoff * 2, _CONTENTION_MAX_BACKOFF_SECONDS)


def _contention_wait_seconds() -> float:
    """Operator ceiling on the courtesy wait, in seconds."""
    raw = os.environ.get(_CONTENTION_WAIT_ENV, "").strip()
    parsed = parse_ascii_uint(raw)
    return float(parsed) if parsed is not None else _CONTENTION_WAIT_SECONDS


def _resolve_contention(
    model: str,
    running: tuple[str, ...],
    wait_limit: float,
) -> None:
    """Proceed past a resident model, or refuse when strict mode is set."""
    if os.environ.get(_STRICT_SLOT_ENV, "").strip() in {"1", "true", "yes"}:
        raise ProviderBusyTimeoutError(
            provider="Ollama",
            requested_model=model,
            active_models=running,
            timeout_seconds=wait_limit,
        )
    logger.warning(
        "Ollama still has %s resident after %.0fs; proceeding with '%s' and "
        "letting the runtime manage memory. Set %s=1 to refuse instead.",
        ", ".join(running),
        wait_limit,
        model,
        _STRICT_SLOT_ENV,
    )

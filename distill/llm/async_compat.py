# pyright: strict
"""Portable sync execution of coroutines across Linux, macOS, and Windows."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from concurrent.futures import ThreadPoolExecutor
from typing import Any

__all__ = ["run_coroutine_sync"]


def run_coroutine_sync[T](coro: Coroutine[Any, Any, T]) -> T:
    """Run a coroutine from synchronous pipeline code on any platform.

    Uses ``asyncio.run`` when no loop is active. When a loop is already running
    (some test harnesses and embedded hosts), runs the coroutine in a dedicated
    thread to avoid nested-loop failures on Windows and Unix alike.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(asyncio.run, coro)
        return future.result()

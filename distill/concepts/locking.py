"""Topic-scoped transaction lock for concept state mutations."""

# pyright: strict

from __future__ import annotations

import contextlib
from collections.abc import Generator
from pathlib import Path

from distill.library.locking import exclusive_path_lock

_CONCEPT_TRANSACTION_TIMEOUT_SECONDS = 610.0


@contextlib.contextmanager
def concept_transaction(topic_dir: Path) -> Generator[None]:
    """Serialize a complete concept mutation transaction for one topic."""

    lock_path = topic_dir / ".concepts" / "transaction.lock"
    with exclusive_path_lock(
        lock_path,
        timeout_seconds=_CONCEPT_TRANSACTION_TIMEOUT_SECONDS,
        timeout_message=f"Timed out waiting for concept state under {topic_dir}",
    ):
        yield

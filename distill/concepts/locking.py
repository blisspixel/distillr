"""Topic-scoped transaction lock for concept state mutations."""

# pyright: strict

from __future__ import annotations

import contextlib
import os
import threading
from collections.abc import Generator
from pathlib import Path

from distill.library.confined_state import ensure_confined_parent
from distill.library.locking import exclusive_path_lock

_CONCEPT_TRANSACTION_TIMEOUT_SECONDS = 610.0


class _TransactionState(threading.local):
    """Track topic transactions already held by the current thread."""

    held: set[str]

    def __init__(self) -> None:
        self.held = set()


_TRANSACTIONS = _TransactionState()


@contextlib.contextmanager
def concept_transaction(topic_dir: Path) -> Generator[None]:
    """Serialize a complete concept mutation transaction for one topic."""

    key = os.path.normcase(str(topic_dir.absolute()))
    if key in _TRANSACTIONS.held:
        yield
        return
    lock_path = topic_dir / ".distill-concepts-transaction.lock"
    ensure_confined_parent(lock_path, topic_dir, create=False)
    with exclusive_path_lock(
        lock_path,
        timeout_seconds=_CONCEPT_TRANSACTION_TIMEOUT_SECONDS,
        timeout_message=f"Timed out waiting for concept state under {topic_dir}",
    ):
        _TRANSACTIONS.held.add(key)
        try:
            yield
        finally:
            _TRANSACTIONS.held.remove(key)

# pyright: strict
"""Topic-scoped transaction locking for claim extraction state."""

from __future__ import annotations

import contextlib
from collections.abc import Generator
from pathlib import Path

from distill.library.confined_state import ensure_confined_parent
from distill.library.locking import exclusive_path_lock

_CLAIMS_TRANSACTION_TIMEOUT_SECONDS = 610.0


@contextlib.contextmanager
def claims_transaction(topic_dir: Path) -> Generator[None]:
    """Serialize the pending decision, model work, and persistence for a topic."""

    lock_path = topic_dir / ".distill-claims-transaction.lock"
    ensure_confined_parent(lock_path, topic_dir, create=False)
    with exclusive_path_lock(
        lock_path,
        timeout_seconds=_CLAIMS_TRANSACTION_TIMEOUT_SECONDS,
        timeout_message=f"Timed out waiting for claim state under {topic_dir}",
    ):
        yield

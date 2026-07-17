"""Internal immutable records for the host-session worker queue."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class BoundRoot:
    path: Path
    identity: tuple[int, int]


@dataclass(frozen=True)
class PendingTask:
    task_id: str
    workload: str
    prompt: str
    prompt_hash: str
    task_path: Path
    task_bytes: bytes
    result_path: Path
    max_tokens: int
    max_result_bytes: int
    timeout_seconds: int
    created_at: str

    @property
    def stem(self) -> str:
        return self.task_path.stem


@dataclass(frozen=True)
class Claim:
    task_id: str
    prompt_hash: str
    token_hash: str
    host: str
    worker_id: str
    workspace_name: str
    claimed_at: datetime
    lease_expires_at: datetime
    prompt_sha256: str
    task_sha256: str
    raw_bytes: bytes

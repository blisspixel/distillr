# pyright: strict
"""Disposable workspace marker for the workflow-replay worker."""

from __future__ import annotations

import json
import secrets
from collections.abc import Generator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

MARKER_NAME = "workflow-replay-workspace.json"
MARKER_SCHEMA = "workflow-replay-workspace.v1"


@dataclass(frozen=True, slots=True)
class ReplayWorkspace:
    root: Path
    library_root: Path
    worker_token: str

    def write_marker(self) -> None:
        payload: dict[str, Any] = {
            "schema_version": MARKER_SCHEMA,
            "worker_token": self.worker_token,
        }
        (self.root / MARKER_NAME).write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )


def load_workspace(root: Path, worker_token: str) -> ReplayWorkspace:
    marker = root / MARKER_NAME
    loaded: object = json.loads(marker.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError("workflow replay workspace marker is not an object")
    raw = cast("Mapping[str, object]", loaded)
    if raw.get("schema_version") != MARKER_SCHEMA:
        raise ValueError("workflow replay workspace marker has the wrong schema")
    if raw.get("worker_token") != worker_token:
        raise ValueError("workflow replay worker token does not match")
    library = root / "library"
    if not library.is_dir():
        raise ValueError("workflow replay workspace is missing its library")
    return ReplayWorkspace(root=root, library_root=library, worker_token=worker_token)


@contextmanager
def temporary_workspace() -> Generator[ReplayWorkspace]:
    import tempfile

    with tempfile.TemporaryDirectory(prefix="distill-workflow-replay-") as temporary:
        root = Path(temporary)
        library = root / "library"
        library.mkdir()
        workspace = ReplayWorkspace(
            root=root,
            library_root=library,
            worker_token=secrets.token_urlsafe(24),
        )
        workspace.write_marker()
        yield workspace

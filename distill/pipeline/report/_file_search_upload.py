# pyright: strict
"""Shared upload and indexing helpers for Gemini File Search stores."""

from __future__ import annotations

import contextlib
import tempfile
import time
from collections.abc import Callable, Sequence
from pathlib import Path

from google import genai
from google.genai import types

from distill._console import console

Document = tuple[str, str]


def upload_documents(
    client: genai.Client,
    store_name: str,
    files: Sequence[Document],
    *,
    failure_prefix: str = "Failed to upload",
    progress_every: int | None = None,
    safe_display: Callable[[object], str] = str,
) -> int:
    """Upload Markdown documents to a File Search store and wait for indexing."""
    pending_ops: list[types.Operation] = []
    temp_paths: list[Path] = []
    total = len(files)

    try:
        for index, (label, content) in enumerate(files, start=1):
            tmp_path: Path | None = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="w", suffix=".md", delete=False, encoding="utf-8"
                ) as tmp:
                    tmp.write(content)
                    tmp_path = Path(tmp.name)
                temp_paths.append(tmp_path)

                op = client.file_search_stores.upload_to_file_search_store(
                    file=str(tmp_path),
                    file_search_store_name=store_name,
                    config={"display_name": label[:200], "mime_type": "text/markdown"},
                )
                pending_ops.append(op)
                if progress_every and (index % progress_every == 0 or index == total):
                    console.print(f"  [dim]Uploaded {index}/{total}...[/dim]")
            except Exception as exc:
                console.print(
                    f"  [yellow]{failure_prefix} {safe_display(label[:50])}: "
                    f"{safe_display(exc)}[/yellow]"
                )
                if tmp_path is not None:
                    with contextlib.suppress(ValueError):
                        temp_paths.remove(tmp_path)
                    with contextlib.suppress(Exception):
                        tmp_path.unlink(missing_ok=True)

        return _wait_for_indexing(client, pending_ops)
    finally:
        for tmp_path in temp_paths:
            with contextlib.suppress(Exception):
                tmp_path.unlink(missing_ok=True)


def _wait_for_indexing(client: genai.Client, pending_ops: list[types.Operation]) -> int:
    if not pending_ops:
        return 0

    console.print(f"  [dim]Waiting for indexing ({len(pending_ops)} docs)...[/dim]")
    indexed = 0
    wait_rounds = 0
    max_wait_rounds = 60
    while wait_rounds < max_wait_rounds:
        still_pending: list[types.Operation] = []
        for op in pending_ops:
            try:
                refreshed = client.operations.get(op)
                if refreshed.done is True:
                    if getattr(refreshed, "error", None) is None:
                        indexed += 1
                    else:
                        console.print("  [yellow]A File Search document failed indexing[/yellow]")
                else:
                    still_pending.append(refreshed)
            except Exception:
                still_pending.append(op)
        if not still_pending:
            break
        pending_ops = still_pending
        if wait_rounds % 6 == 0:
            console.print(f"  [dim]Still indexing... {len(still_pending)} remaining[/dim]")
        time.sleep(5)
        wait_rounds += 1

    if wait_rounds >= max_wait_rounds:
        console.print(
            f"  [yellow]Indexing timeout - {len(pending_ops)} documents were not verified[/yellow]"
        )
    return indexed

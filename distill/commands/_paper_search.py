# pyright: strict
"""Present paper discovery coverage without certifying exhaustive research."""

from __future__ import annotations

import json
from pathlib import Path

from distill._console import console
from distill.ingestors.papers.arxiv import PaperRecord
from distill.ingestors.papers.search_receipts import SearchReceipt
from distill.library.paper_revisions import captured_revision_dates
from distill.pipeline.summary import RunSummary


def report_search_coverage(receipts: tuple[SearchReceipt, ...], summary: RunSummary) -> None:
    summary.set_metadata(search_receipts=json.dumps([r.to_row() for r in receipts]))
    if not receipts:
        console.print("[yellow]Discovery coverage unknown: no saved search receipts.[/yellow]")
        return
    failed = [r for r in receipts if r.status == "failed"]
    console.print(
        f"[dim]Discovery: {len(receipts) - len(failed)}/{len(receipts)} bounded queries "
        "checked; this does not establish exhaustive topic coverage.[/dim]"
    )
    for receipt in failed:
        console.print(f"Search failed: {receipt.query}: {receipt.reason}", markup=False)
        summary.add_issue("paper-search", receipt.reason, context=receipt.query, severity="warning")
    if failed:
        console.print(
            "[yellow]Incomplete discovery: failed searches may hide relevant papers.[/yellow]"
        )


def report_revision_candidates(papers: list[PaperRecord], *, topic_dir: Path | None = None) -> bool:
    updates = [p for p in papers if p.revision_status in ("update", "unknown")]
    dates = captured_revision_dates(topic_dir) if updates and topic_dir is not None else {}
    for paper in updates:
        captured = "; ".join(
            f"{identity} (revision date: {dates.get(identity, ('unknown', 'unknown'))[0]}, captured: {dates.get(identity, ('unknown', 'unknown'))[1]})"
            for identity in paper.captured_revisions
        )
        console.print(
            f"Revision {paper.revision_status}: {paper.paper_id}; captured: "
            f"{captured}; discovered update: {paper.updated_at or 'unknown'}; published: {paper.published_at or 'unknown'}. "
            "Preview only; existing work is not additional independent evidence.",
            markup=False,
        )
    return bool(updates)

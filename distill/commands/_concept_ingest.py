"""Post-ingest concept playbook helpers."""

from __future__ import annotations

from distill._console import console
from distill.commands._helpers import get_config
from distill.pipeline.costs import CostTracker

__all__ = ["run_concepts_after_ingest"]


def run_concepts_after_ingest(
    topic: str,
    *,
    tracker: CostTracker | None = None,
) -> None:
    """Run the concept playbook over a topic after an ingest succeeds."""
    from distill.concepts import run_concepts
    from distill.llm import RouterConfig

    config = get_config()
    topic_dir = config.topic_dir(topic)
    if not topic_dir.exists():
        console.print(f"[dim]--concepts skipped (topic dir missing: {topic_dir})[/dim]")
        return
    console.print("\n[bold]Concept playbook[/bold]")
    try:
        summary = run_concepts(topic=topic, topic_dir=topic_dir, rc=RouterConfig(), tracker=tracker)
    except Exception as exc:
        console.print(f"[yellow]Concept extraction failed: {exc}[/yellow]")
        return
    console.print(
        f"  scanned={summary.insights_scanned} "
        f"extracted={summary.insights_extracted} "
        f"mentions+={summary.mentions_added} "
        f"notes={summary.notes_written} (concepts={summary.concepts_written}, entities={summary.entities_written}, unchanged={summary.concepts_unchanged})"
    )

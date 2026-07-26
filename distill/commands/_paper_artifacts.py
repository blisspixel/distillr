"""Paper artifact writing helpers shared by CLI and MCP workflows."""

# pyright: strict

from __future__ import annotations

import json
from pathlib import Path

from distill._console import console
from distill.config import DistillConfig
from distill.ingestors.papers.arxiv import PaperRecord, build_paper_document
from distill.library.paths import (
    artifact_filename,
    base_frontmatter,
    tags_for,
    write_markdown_artifact,
)
from distill.pipeline.verify import resolve_verify_mode, run_verify_hook

__all__ = ["write_paper_artifacts"]


def write_paper_artifacts(
    topic: str,
    paper: PaperRecord,
    config: DistillConfig,
    insights: str,
    document: str | None = None,
) -> Path:
    paper_dir = config.paper_dir(topic, paper.title, paper.paper_id)
    paper_dir.mkdir(parents=True, exist_ok=True)
    (paper_dir / "metadata.json").write_text(
        json.dumps(paper.metadata(), indent=2),
        encoding="utf-8",
    )
    paper_doc = document if document is not None else build_paper_document(paper)
    paper_frontmatter = base_frontmatter(
        artifact_type="paper",
        title=paper.title,
        topic=topic,
        source=paper.source,
        source_id=paper.paper_id,
        url=paper.abs_url,
        date=paper.published_at,
        authors=paper.authors,
        tags=[*tags_for(topic, paper.source), *paper.categories],
        synthesis_scope="source-content",
        extra={
            "paper_id": paper.paper_id,
            "doi": paper.doi,
            "pdf_url": paper.pdf_url,
            "updated_at": paper.updated_at,
            "categories": paper.categories,
            "legacy_filename": "paper.md",
        },
    )
    write_markdown_artifact(paper_dir, "paper", paper_doc, frontmatter=paper_frontmatter)
    # Write-time verify hook: ground insight numeric claims against the paper
    # text receipt before committing it. Strict mode refuses the write.
    outcome = run_verify_hook(
        paper_dir,
        insights,
        paper_doc,
        mode=resolve_verify_mode(config.distill_verify),
        insight_name=artifact_filename(paper_dir.name, "insights"),
        source_name=artifact_filename(paper_dir.name, "paper"),
    )
    if outcome is not None and outcome.has_flags:
        style = "red" if outcome.refused else "yellow"
        console.print(f"    [{style}]{outcome.summary_line}[/{style}]")
    if outcome is not None and outcome.refused:
        return paper_dir

    write_markdown_artifact(
        paper_dir,
        "insights",
        insights,
        frontmatter={
            **paper_frontmatter,
            "type": "insights",
            "synthesis_scope": "single-paper",
            "legacy_filename": "insights.md",
        },
    )
    return paper_dir

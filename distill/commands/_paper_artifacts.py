"""Paper artifact writing helpers shared by CLI and MCP workflows."""

# pyright: strict

from __future__ import annotations

from pathlib import Path

from distill._console import console
from distill.config import DistillConfig
from distill.ingestors.papers.arxiv import PaperRecord, build_paper_document
from distill.library.insights import insight_content_sha256, insight_has_body, receipt_body_sha256
from distill.library.paper_inputs import archive_paper_receipt, prepare_paper_input_evidence
from distill.library.paths import (
    artifact_filename,
    atomic_write_json,
    base_frontmatter,
    find_artifact,
    render_markdown_artifact,
    tags_for,
    text_write_lock,
    write_markdown_artifact,
    write_text_artifact,
)
from distill.pipeline.verify import resolve_verify_mode, run_verify_hook, write_verified_artifact

__all__ = ["write_paper_artifacts"]


class PaperPublicationRefusedError(ValueError):
    """The receipt was retained but the candidate insight was not accepted."""


def write_paper_artifacts(
    topic: str,
    paper: PaperRecord,
    config: DistillConfig,
    insights: str,
    document: str | None = None,
) -> Path:
    paper_dir = config.paper_dir(topic, paper.title, paper.paper_id)
    paper_dir.mkdir(parents=True, exist_ok=True)
    with text_write_lock(paper_dir / ".paper-publication"):
        return _write_paper_artifacts_locked(
            topic, paper, config, insights, document, paper_dir=paper_dir
        )


def _write_paper_artifacts_locked(
    topic: str,
    paper: PaperRecord,
    config: DistillConfig,
    insights: str,
    document: str | None,
    *,
    paper_dir: Path,
) -> Path:
    paper_doc = document if document is not None else build_paper_document(paper)
    source_body_digest = receipt_body_sha256(render_markdown_artifact("paper", paper_doc))
    archive_paper_receipt(paper_dir, find_artifact(paper_dir, "paper"))
    atomic_write_json(paper_dir / "metadata.json", paper.metadata())
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
            "receipt_sha256": source_body_digest,
        },
    )
    write_markdown_artifact(paper_dir, "paper", paper_doc, frontmatter=paper_frontmatter)
    existing_insights = find_artifact(paper_dir, "insights")
    has_existing_insights = existing_insights.exists() and existing_insights.stat().st_size > 0
    if not insight_has_body(insights):
        console.print("    [red]empty analysis[/red]")
        raise PaperPublicationRefusedError("Paper analysis produced no usable insight")
    insights = prepare_paper_input_evidence(paper_dir, insights, source_document=paper_doc)
    insights = render_markdown_artifact(
        "insights",
        insights,
        frontmatter={
            **paper_frontmatter,
            "type": "insights",
            "synthesis_scope": "single-paper",
            "legacy_filename": "insights.md",
            "paper_receipt_body_sha256": source_body_digest,
        },
    )
    # Write-time verify hook: ground insight numeric claims against the paper
    # text receipt before committing it. Strict mode refuses the write. When
    # an earlier insight already exists, defer the sidecar so a refusal cannot
    # rebind the previous file's verification record.
    outcome = run_verify_hook(
        paper_dir,
        insights,
        paper_doc,
        mode=resolve_verify_mode(config.distill_verify),
        insight_name=artifact_filename(paper_dir.name, "insights"),
        source_name=artifact_filename(paper_dir.name, "paper"),
        publish_sidecar=not has_existing_insights,
        insight_sha256=insight_content_sha256(insights),
    )
    if outcome is not None:
        style = "red" if outcome.refused else "yellow"
        console.print(f"    [{style}]{outcome.summary_line}[/{style}]")
    if outcome is not None and outcome.refused:
        raise PaperPublicationRefusedError(outcome.summary_line)

    if outcome is None:
        write_text_artifact(paper_dir, "insights", insights)
    else:
        write_verified_artifact(
            paper_dir,
            paper_dir / artifact_filename(paper_dir.name, "insights"),
            insights,
            outcome=outcome,
            verify_identity=paper_dir.name,
            source_name=artifact_filename(paper_dir.name, "paper"),
        )
    return paper_dir

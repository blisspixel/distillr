# pyright: strict
"""GitHub repository ingest orchestration.

The repo counterpart to ``ingest_tweet`` / ``ingest_local_file``: capture the
repository's primary-source material (metadata + README + recent releases)
into a ``Repo.md`` receipt, analyze it into a structured ``_Insights.md`` --
extraction, not concatenation: the open-source field stops at packing files
into prompts (Repomix, Gitingest); the structured-understanding shape exists
only in closed products -- and run the write-time verify hook against the
receipt before the insight is committed.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from distill._console import console
from distill.config import DistillConfig
from distill.ingestors.github import RepoRecord, fetch_repo, parse_github_url
from distill.library.insights import insight_has_body, receipt_body_sha256
from distill.library.paths import (
    ProvenanceFields,
    artifact_path,
    base_frontmatter,
    slugify_title,
    tags_for,
    write_markdown_artifact,
)
from distill.llm import call as llm_call
from distill.llm.router import RouterConfig
from distill.pipeline.costs import CostTracker, TokenUsage
from distill.prompts.github import repo_insight_prompt
from distill.prompts.registry import PROMPT_IDS

__all__ = ["RepoIngestResult", "ingest_repo"]

PROMPT_ID = PROMPT_IDS["analysis.github_repo"]


@dataclass(slots=True)
class RepoIngestResult:
    """Paths and metadata from a repository ingest."""

    repo_path: Path
    insights_path: Path | None
    record: RepoRecord
    skipped_reasons: list[str]


def _repo_markdown(record: RepoRecord) -> str:
    """Render the capture receipt: verifiable metadata, README, releases."""
    parts = [
        f"# {record.full_name}",
        "",
        record.description or "_(no description)_",
        "",
        "## Metadata",
        "",
        record.metadata_block(),
    ]
    releases = record.releases_block()
    if releases:
        parts += ["", "## Recent releases", "", releases]
    parts += ["", "## README", "", record.readme or "_(no README found)_", ""]
    return "\n".join(parts)


def ingest_repo(
    url: str,
    *,
    topic: str,
    config: DistillConfig,
    analyze: bool = True,
    tracker: CostTracker | None = None,
) -> RepoIngestResult:
    """Ingest one GitHub repository into ``topic``.

    Files under ``library/topics/<topic>/repos/<slug>/`` with the standard
    receipt + insight pair; cost-tracked; verify-gated.
    """
    parsed = parse_github_url(url)
    if parsed is None:
        raise ValueError(f"Not a recognizable GitHub repository URL: {url!r}")
    owner, repo = parsed
    record = fetch_repo(owner, repo)
    skipped: list[str] = []

    slug = slugify_title(record.full_name.replace("/", " "), source_id=repo)
    repo_dir = config.topic_dir(topic) / "repos" / slug
    repo_md = _repo_markdown(record)
    receipt_sha256 = receipt_body_sha256(repo_md)
    repo_name = artifact_path(repo_dir, "repo", identity=slug).name
    frontmatter = base_frontmatter(
        artifact_type="repo",
        title=record.full_name,
        topic=topic,
        source="github",
        source_id=record.full_name,
        url=record.url,
        date=record.pushed_at,
        tags=tags_for(topic, "github"),
        extra={
            "stars": record.stars,
            "language": record.language,
            "license": record.license_name,
            "archived": record.archived,
            "receipt_sha256": receipt_sha256,
        },
    )
    repo_path = write_markdown_artifact(
        repo_dir, "repo", repo_md, identity=slug, frontmatter=frontmatter
    )

    insights_path: Path | None = None
    if analyze:
        rc = RouterConfig()
        response = llm_call(
            rc,
            workload_tag="site",
            prompt=repo_insight_prompt(
                full_name=record.full_name,
                url=record.url,
                description=record.description,
                metadata_block=record.metadata_block(),
                readme=record.readme,
                releases_block=record.releases_block(),
            ),
            call_type="repo_analysis",
            usage_tracker=tracker,
        )
        if tracker is not None:
            tracker.record(TokenUsage.from_response(response, call_type="repo_analysis"))

        # Write-time verify hook: ground numeric claims against the receipt
        # *before* committing; strict mode refuses the write.
        from distill.pipeline.verify import resolve_verify_mode, run_verify_hook

        if not insight_has_body(response.text):
            console.print("  [red]empty analysis[/red]")
            skipped.append("Empty analysis")
            outcome = None
        else:
            outcome = run_verify_hook(
                repo_dir,
                response.text,
                repo_md,
                mode=resolve_verify_mode(config.distill_verify),
                identity=slug,
                insight_name=artifact_path(repo_dir, "insights", identity=slug).name,
                source_name=repo_name,
            )
        if outcome is not None and outcome.has_flags:
            style = "red" if outcome.refused else "yellow"
            console.print(f"  [{style}]{outcome.summary_line}[/{style}]")
        if outcome is not None and outcome.refused:
            skipped.append(outcome.summary_line)
        elif insight_has_body(response.text):
            insights_path = write_markdown_artifact(
                repo_dir,
                "insights",
                response.text,
                identity=slug,
                frontmatter=base_frontmatter(
                    artifact_type="insights",
                    title=record.full_name,
                    topic=topic,
                    source="github",
                    source_id=record.full_name,
                    url=record.url,
                    date=record.pushed_at,
                    tags=tags_for(topic, "github"),
                    synthesis_scope="single-source",
                    extra={
                        "stars": record.stars,
                        "language": record.language,
                        "source_receipt": repo_name,
                        "source_receipt_sha256": receipt_sha256,
                    },
                    provenance=ProvenanceFields(
                        model=response.model,
                        model_version=response.model,
                        temperature=0.0,
                        prompt_id=PROMPT_ID,
                    ),
                ),
            )

    return RepoIngestResult(
        repo_path=repo_path,
        insights_path=insights_path,
        record=record,
        skipped_reasons=skipped,
    )

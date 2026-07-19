# pyright: strict
"""Website ingest helpers shared by CLI and MCP site workflows."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from hashlib import sha1, sha256
from pathlib import Path

from rich.markup import escape

import distill.cli_shared as cli_shared
from distill._console import console
from distill.commands._helpers import resolve_intent
from distill.commands._site_page_storage import (
    OwnedSitePageDirectory,
    remove_absent_attachments,
    remove_absent_transcript,
    reserve_site_page_directory,
)
from distill.config import DistillConfig
from distill.ingestors.net import url_for_diagnostic
from distill.ingestors.sites._site_urls import (
    canonicalize_url,
    site_attachment_context_for_persistence,
    site_embedded_url_for_persistence,
    site_url_for_persistence,
    site_url_list_for_persistence,
)
from distill.ingestors.sites.attachments import (
    AttachmentRecord,
    collect_page_attachments,
    ingest_page_attachments,
    write_attachment_manifest,
)
from distill.ingestors.sites.scraper import (
    SitePage,
    SiteSeed,
    build_page_document,
    crawl_site,
)
from distill.library.paths import (
    base_frontmatter,
    find_artifact,
    site_name_from_url,
    tags_for,
    write_markdown_artifact,
    write_text_artifact,
)
from distill.llm.cost_policy import CostPolicyError
from distill.llm.errors import ProviderBusyTimeoutError
from distill.pipeline.analysis.site import analyze_site_page, synthesize_site
from distill.pipeline.costs import BudgetExceededError, CostTracker
from distill.pipeline.dashboard_data import build_site_section_state as _build_site_section_state
from distill.pipeline.dashboard_data import load_site_manifest
from distill.pipeline.dashboard_records import (
    JsonObject,
    SiteManifest,
    SiteSectionState,
    json_object,
)
from distill.pipeline.summary import RunSummary

__all__ = [
    "SiteIngestResult",
    "content_hash",
    "process_site_seed",
    "site_ingest_status_phase",
    "site_section_change_summary",
]


@dataclass(frozen=True)
class SiteIngestResult:
    site_name: str
    page_count: int
    analyzed_pages: int = 0
    skipped_pages: int = 0
    scrape_only: bool = False

    def __iter__(self):
        yield self.site_name
        yield self.page_count


def site_ingest_status_phase(result: object) -> str:
    if not isinstance(result, SiteIngestResult):
        return "done"
    if result.page_count <= 0:
        return "skipped (empty crawl)"
    if result.scrape_only:
        return f"done ({result.page_count} scraped)"
    if result.skipped_pages and result.analyzed_pages:
        return f"done ({result.analyzed_pages} analyzed, {result.skipped_pages} unchanged)"
    if result.skipped_pages:
        return f"skipped ({result.skipped_pages} unchanged)"
    if result.analyzed_pages:
        return f"done ({result.analyzed_pages} analyzed)"
    return "done"


def site_section_change_summary(
    previous: SiteManifest, current_sections: Sequence[SiteSectionState]
) -> list[str]:
    previous_sections = {item["section"]: item for item in previous["sections"] if item["section"]}
    messages: list[str] = []
    for item in current_sections:
        name = item["section"]
        prev = previous_sections.get(name)
        if prev is None:
            messages.append(f"{name} added ({item['page_count']} pages)")
            continue
        prev_urls = set(prev["urls"])
        curr_urls = set(item["urls"])
        if curr_urls != prev_urls:
            added = len(curr_urls - prev_urls)
            removed = len(prev_urls - curr_urls)
            bits: list[str] = []
            if added:
                bits.append(f"+{added}")
            if removed:
                bits.append(f"-{removed}")
            messages.append(f"{name} changed ({', '.join(bits)})")
    for name, prev in previous_sections.items():
        if name not in {item["section"] for item in current_sections}:
            messages.append(f"{name} missing (was {prev['page_count']} pages)")
    return messages[:8]


def content_hash(text: str) -> str:
    # SHA-1 used for change-detection/deduplication only, not security.
    return sha1(text.encode("utf-8"), usedforsecurity=False).hexdigest()


@dataclass(frozen=True)
class _PreparedSitePage:
    page: SitePage
    owner: OwnedSitePageDirectory


def _sanitize_attachment_records(
    page_dir: Path,
    attachments: Sequence[AttachmentRecord],
) -> list[AttachmentRecord]:
    sanitized: list[AttachmentRecord] = []
    for attachment in attachments:
        safe_url = site_embedded_url_for_persistence(attachment.url)
        if safe_url == "<invalid-url>":
            safe_url = url_for_diagnostic(attachment.url)
        note = (
            attachment.note.replace(attachment.url, safe_url) if attachment.url else attachment.note
        )
        text_path = attachment.text_path
        if text_path and Path(text_path).name == text_path:
            original = page_dir / "attachments" / text_path
            if original.exists():
                suffix = original.suffix or ".txt"
                digest = sha256(
                    b"distill-site-attachment-v1\0"
                    + canonicalize_url(attachment.url).encode("utf-8")
                ).hexdigest()
                target = original.with_name(f"attachment-{digest}{suffix}")
                if original != target:
                    original.replace(target)
                text_path = target.name
        sanitized.append(
            replace(
                attachment,
                url=safe_url,
                note=note,
                text_path=text_path,
            )
        )
    return sanitized


def _sanitize_site_page(
    page: SitePage,
    *,
    attachment_context: str,
    attachments: Sequence[AttachmentRecord],
) -> SitePage:
    context = site_attachment_context_for_persistence(
        attachment_context,
        [attachment.url for attachment in attachments],
    )
    return replace(
        page,
        url=site_url_for_persistence(page.url),
        final_url=site_url_for_persistence(page.final_url),
        canonical_url=site_url_for_persistence(page.canonical_url),
        source_url=site_url_for_persistence(page.source_url),
        links=site_url_list_for_persistence(page.links),
        pdf_links=site_url_list_for_persistence(page.pdf_links),
        video_links=site_url_list_for_persistence(page.video_links),
        attachment_context=context,
    )


def process_site_seed(  # noqa: C901 - legacy site ingest helper
    seed: SiteSeed,
    config: DistillConfig,
    tracker: CostTracker,
    summary: RunSummary,
    scrape_only: bool = False,
    ingest_attachments: bool = False,
) -> SiteIngestResult:
    raw_derived_site_name = site_name_from_url(seed.url)
    safe_derived_site_name = site_name_from_url(url_for_diagnostic(seed.url))
    site_name = (
        safe_derived_site_name
        if not seed.site_name or seed.site_name == raw_derived_site_name
        else seed.site_name
    )
    mode_label = "scrape-only" if scrape_only else "full"
    safe_seed_url = site_url_for_persistence(seed.url)
    console.print(f"\n[bold]Site: {escape(site_name)}[/bold]")
    boundary = f" | crawl_prefix={escape(seed.crawl_prefix)}" if seed.crawl_prefix else ""
    console.print(
        f"[dim]Seed: {escape(url_for_diagnostic(seed.url))} | max_pages={seed.max_pages} "
        f"depth={seed.max_depth}{boundary} mode={mode_label} | "
        f"attachments={'on' if ingest_attachments else 'inventory-only'}[/dim]"
    )

    raw_pages = crawl_site(seed)
    if not raw_pages:
        summary.add_issue(
            "site-crawl",
            "No pages were extracted from the site.",
            context=url_for_diagnostic(seed.url),
            details={"site": site_name, "topic": seed.topic, "scrape_only": scrape_only},
        )
        return SiteIngestResult(site_name=site_name, page_count=0, scrape_only=scrape_only)

    site_dir = config.site_dir(seed.topic, site_name)
    pages_dir = config.site_pages_dir(seed.topic, site_name)
    pages_dir.mkdir(parents=True, exist_ok=True)
    prepared_pages: list[_PreparedSitePage] = []
    for index, raw_page in enumerate(raw_pages, 1):
        console.print(f"  [{index}/{len(raw_pages)}] [bold]{escape(raw_page.title)}[/bold]")
        owned_page = reserve_site_page_directory(
            config,
            seed.topic,
            site_name,
            raw_page,
        )
        page_dir = owned_page.path
        attachment_context = raw_page.attachment_context
        if ingest_attachments:
            raw_attachments, fetched_context = ingest_page_attachments(
                raw_page,
                page_dir,
                config,
                tracker=tracker,
            )
            if fetched_context:
                attachment_context = fetched_context
        else:
            raw_attachments = collect_page_attachments(raw_page)
        if not raw_attachments:
            raw_attachments = collect_page_attachments(raw_page)

        attachments = _sanitize_attachment_records(page_dir, raw_attachments)
        safe_page = _sanitize_site_page(
            raw_page,
            attachment_context=attachment_context,
            attachments=raw_attachments,
        )
        if not attachments:
            remove_absent_attachments(page_dir)
        attachment_manifest = write_attachment_manifest(page_dir, attachments)
        if attachment_manifest:
            summary.add_output(attachment_manifest)
            for item in attachments:
                if item.text_path:
                    summary.add_output(page_dir / "attachments" / item.text_path)
        prepared_pages.append(_PreparedSitePage(page=safe_page, owner=owned_page))

    pages = [prepared.page for prepared in prepared_pages]
    site_manifest_path = site_dir / "site.json"
    previous_manifest = load_site_manifest(site_manifest_path)
    crawled_at = datetime.now().isoformat(timespec="seconds")
    section_state = _build_site_section_state(pages)
    for section in section_state:
        section["last_crawled_at"] = crawled_at
    section_changes = site_section_change_summary(previous_manifest, section_state)
    manifest = {
        "seed_url": safe_seed_url,
        "site_name": site_name,
        "page_count": len(pages),
        "max_depth": seed.max_depth,
        "max_pages": seed.max_pages,
        "crawl_prefix": seed.crawl_prefix,
        "same_section_only": seed.same_section_only,
        "scrape_only": scrape_only,
        "ingest_attachments": ingest_attachments,
        "generated_at": crawled_at,
        "sections": section_state,
        "section_changes": section_changes,
    }
    site_manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    summary.add_output(site_manifest_path)
    if section_changes:
        update_lines = [
            f"# Site Update: {site_name}",
            "",
            f"- Seed: {safe_seed_url}",
            f"- Generated: {crawled_at}",
            "",
            "## Section Changes",
        ]
        update_lines.extend(f"- {item}" for item in section_changes)
        update_path = write_markdown_artifact(
            site_dir,
            "site_update",
            "\n".join(update_lines),
            identity=f"{seed.topic}_{site_name}",
            frontmatter=base_frontmatter(
                artifact_type="site_update",
                title=f"Site Update: {site_name}",
                topic=seed.topic,
                source="website",
                url=safe_seed_url,
                tags=tags_for(seed.topic, "website", "update"),
                synthesis_scope="operational",
                extra={"site": site_name, "legacy_filename": "site_update.md"},
            ),
        )
        summary.add_output(update_path)

    analyzed_pages = 0
    skipped_pages = 0
    for prepared_page in prepared_pages:
        page_obj = prepared_page.page
        owned_page = prepared_page.owner
        page_dir = owned_page.path
        page_document = build_page_document(page_obj)
        page_content_hash = content_hash(page_document)
        previous_metadata: JsonObject = {}
        metadata_path = page_dir / "metadata.json"
        if metadata_path.exists():
            try:
                previous_metadata = json_object(
                    json.loads(metadata_path.read_text(encoding="utf-8"))
                )
            except (OSError, json.JSONDecodeError):
                previous_metadata = {}
        page_meta = page_obj.metadata()
        page_meta["content_hash"] = page_content_hash
        metadata_path = page_dir / "metadata.json"
        metadata_path.write_text(json.dumps(page_meta, indent=2), encoding="utf-8")
        summary.add_output(metadata_path)
        page_frontmatter = base_frontmatter(
            artifact_type="content",
            title=page_obj.title,
            topic=seed.topic,
            source="website",
            source_id=owned_page.source_id,
            url=page_obj.final_url or page_obj.url,
            date=page_obj.published_at,
            authors=page_obj.authors,
            tags=[*tags_for(seed.topic, "website"), *page_obj.tags],
            synthesis_scope="source-content",
            extra={
                "site": page_obj.site_name,
                "page_type": page_obj.page_type,
                "canonical_url": page_meta.get("canonical_url", ""),
                "section": page_meta.get("section", ""),
                "legacy_filename": "content.md",
            },
        )
        content_path = write_markdown_artifact(
            page_dir,
            "content",
            page_document,
            frontmatter=page_frontmatter,
        )
        summary.add_output(content_path)
        if page_obj.transcript.strip():
            transcript_path = write_text_artifact(
                page_dir,
                "transcript",
                page_obj.transcript,
                extension="txt",
            )
            summary.add_output(transcript_path)
        else:
            remove_absent_transcript(page_dir)
        if scrape_only:
            continue
        insights_path = find_artifact(page_dir, "insights")
        if previous_metadata.get("content_hash") == page_content_hash and insights_path.exists():
            skipped_pages += 1
            summary.add_output(insights_path)
            console.print("    [dim]unchanged page - reusing existing insights[/dim]")
            continue
        try:
            insights = analyze_site_page(
                page_obj, config, tracker=tracker, intent=resolve_intent(config, seed.topic)
            )

            from distill.pipeline.verify import resolve_verify_mode, run_verify_hook

            outcome = run_verify_hook(
                page_dir,
                insights,
                page_document,
                mode=resolve_verify_mode(config.distill_verify),
                insight_name=insights_path.name,
                source_name=content_path.name,
            )
            if outcome is not None and not outcome.report.ok:
                style = "red" if outcome.refused else "yellow"
                console.print(f"  [{style}]{outcome.summary_line}[/{style}]")
            if outcome is not None and outcome.refused:
                summary.add_issue(
                    "verify",
                    outcome.summary_line,
                    context=url_for_diagnostic(page_obj.url),
                )
                continue

            insights_path = write_markdown_artifact(
                page_dir,
                "insights",
                insights,
                frontmatter={
                    **page_frontmatter,
                    "type": "insights",
                    "synthesis_scope": "single-source",
                    "legacy_filename": "insights.md",
                },
            )
            summary.add_output(insights_path)
            analyzed_pages += 1
        except (BudgetExceededError, CostPolicyError, ProviderBusyTimeoutError):
            raise
        except Exception as exc:
            console.print(f"  [red]Insight extraction failed: {escape(str(exc))}[/red]")
            cli_shared.record_exception_issue(
                summary,
                stage="site-page-analysis",
                exc=exc,
                context=url_for_diagnostic(page_obj.url),
                details={"site": site_name, "topic": seed.topic, "title": page_obj.title},
            )

    if scrape_only:
        return SiteIngestResult(
            site_name=site_name,
            page_count=len(pages),
            scrape_only=True,
        )

    manifest["analyzed_pages"] = analyzed_pages
    manifest["skipped_pages"] = skipped_pages
    site_manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    result = SiteIngestResult(
        site_name=site_name,
        page_count=len(pages),
        analyzed_pages=analyzed_pages,
        skipped_pages=skipped_pages,
    )
    console.print(f"  [dim]site result: {site_ingest_status_phase(result)}[/dim]")

    try:
        synthesis = synthesize_site(seed.topic, site_name, config, tracker=tracker)
        if synthesis:
            summary.add_output(
                find_artifact(
                    config.site_dir(seed.topic, site_name),
                    "site_synthesis",
                    identity=f"{seed.topic}_{site_name}",
                )
            )
    except (BudgetExceededError, CostPolicyError, ProviderBusyTimeoutError):
        raise
    except Exception as exc:
        cli_shared.record_exception_issue(
            summary,
            stage="site-synthesis",
            exc=exc,
            context=url_for_diagnostic(seed.url),
            details={"site": site_name, "topic": seed.topic},
        )

    return result

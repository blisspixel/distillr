# pyright: strict
"""Multi-topic research briefings via Gemini Deep Research.

Where `distill report <topic>` runs a 4-phase strategic report scoped to one
topic, and `distill brief <topic>` produces a lightweight Grok-based topic
brief, `distill research-brief` runs a single Gemini Deep Research call
grounded on one or more topics' paper/video/site insights, with a user-supplied
context block (`--context` or `--context-file`) that shapes the prompt for a
specific audience or decision. Output lands in `output/briefing-{name}.md`.

The context file IS the prompt. Distill just handles file gathering, File
Search store management, Deep Research invocation, and output. This keeps the
prompt engineering in the user's hands and makes briefings reusable for
arbitrary purposes (multi-topic literature review, decision briefing for a
specific stakeholder, architectural grounding for a downstream agent, etc.)."""

from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING

from distill._console import console
from distill.config import DistillConfig
from distill.library.paths import atomic_write_text, find_artifact, workspace_output_path
from distill.library.wikilinks import emit_wiki_link
from distill.llm.cost_policy import require_route_allowed
from distill.parsing import read_local_utf8_text
from distill.pipeline.citation_refs import unresolved_numbered_citation_reason
from distill.pipeline.costs import CostTracker
from distill.pipeline.report._file_search_metadata import metadata_str, read_metadata
from distill.pipeline.report._file_search_upload import upload_documents
from distill.pipeline.report._interactions import (
    await_interaction,
    file_search_grounding_reason,
    interaction_text,
    preflight_metered_interaction,
    require_cost_tracker,
    submit_metered_interaction,
)
from distill.pipeline.report.file_search import cleanup_created_store, delete_store

if TYPE_CHECKING:
    from google import genai

__all__ = [
    "compose_prompt",
    "gather_topic_files",
    "run_research_brief",
]

DEEP_RESEARCH_MODEL = "deep-research-preview-04-2026"
MAX_DOC_CHARS = 500_000


def __getattr__(name: str) -> object:
    """Lazily expose ``genai`` so importing this module stays cheap.

    The google-genai SDK costs roughly a second of import time, so it is
    imported only when a research brief actually runs. Tests that patch
    ``distill.pipeline.report.brief.genai.Client`` keep working: this hook
    resolves ``genai`` to the real module on first attribute access.
    """
    if name == "genai":
        from google import genai

        return genai
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def gather_topic_files(  # noqa: C901 - legacy orchestration kept intact
    topics: list[str], config: DistillConfig
) -> list[tuple[str, str]]:
    """Collect (label, content) pairs across the given topics.

    Pulls paper, topic, and corpus synthesis artifacts, plus bundled per-paper /
    per-video / per-page insights where present.
    """
    files: list[tuple[str, str]] = []

    for topic in topics:
        topic_dir = config.topic_dir(topic)
        if not topic_dir.exists():
            console.print(f"[yellow]Topic '{topic}' not found, skipping[/yellow]")
            continue

        for artifact_type, label_stem in [
            ("paper_synthesis", "paper-synthesis"),
            ("topic_synthesis", "topic-synthesis"),
            ("corpus_synthesis", "corpus-synthesis"),
        ]:
            synth = find_artifact(topic_dir, artifact_type, identity=topic)
            if synth.exists():
                link = emit_wiki_link(
                    f"{label_stem.replace('-', ' ').title()}: {topic}",
                    topic,
                    artifact_type,
                )
                body = read_local_utf8_text(synth)
                if body is None:
                    continue
                files.append(
                    (
                        f"{label_stem}-{topic}",
                        f"# {label_stem.replace('-', ' ').title()}: {topic}\n"
                        f"Source: {link}\n\n" + body,
                    )
                )

        papers_dir = config.papers_dir(topic)
        if papers_dir.exists():
            files.extend(_bundle_insights(papers_dir, f"{topic}-papers", topic, kind="paper"))

        channels_dir = topic_dir / "channels"
        if channels_dir.exists():
            for ch_dir in sorted(channels_dir.iterdir()):
                if not ch_dir.is_dir():
                    continue
                videos_dir = ch_dir / "videos"
                if videos_dir.exists():
                    files.extend(
                        _bundle_insights(
                            videos_dir,
                            f"{topic}-{ch_dir.name}-videos",
                            topic,
                            kind="video",
                        )
                    )

        sites_dir = config.sites_dir(topic)
        if sites_dir.exists():
            for site_dir in sorted(sites_dir.iterdir()):
                if not site_dir.is_dir():
                    continue
                pages_dir = site_dir / "pages"
                if pages_dir.exists():
                    files.extend(
                        _bundle_insights(
                            pages_dir,
                            f"{topic}-{site_dir.name}-pages",
                            topic,
                            kind="page",
                        )
                    )

    return files


def _bundle_insights(
    source_dir: Path, label_stem: str, topic: str, kind: str
) -> list[tuple[str, str]]:
    """Bundle per-item insight artifacts under source_dir into MAX_DOC_CHARS chunks."""
    bundles: list[tuple[str, str]] = []
    parts: list[str] = []
    chars = 0
    num = 1

    for item_dir in sorted(source_dir.iterdir()):
        if not item_dir.is_dir():
            continue
        insights_file = find_artifact(item_dir, "insights")
        insights_text = read_local_utf8_text(insights_file)
        if insights_text is None:
            continue
        metadata_file = item_dir / "metadata.json"
        title = item_dir.name
        url = ""
        source_id = item_dir.name
        if metadata_file.exists():
            meta = read_metadata(metadata_file)
            title = metadata_str(meta, "title", title)
            url = metadata_str(meta, "abs_url") or metadata_str(meta, "url")
            source_id = metadata_str(meta, "video_id") or metadata_str(meta, "paper_id", source_id)
        link = emit_wiki_link(title, source_id, "insights")
        entry = f"\n\n---\n\n## [{kind}] {title}\nURL: {url}\nSource: {link}\n\n" + insights_text
        if chars + len(entry) > MAX_DOC_CHARS and parts:
            bundles.append(
                (
                    f"{label_stem}-part{num}",
                    f"# {topic} {kind} insights (part {num})\n" + "".join(parts),
                )
            )
            parts = []
            chars = 0
            num += 1
        parts.append(entry)
        chars += len(entry)
    if parts:
        label = label_stem if num == 1 else f"{label_stem}-part{num}"
        bundles.append((label, f"# {topic} {kind} insights (part {num})\n" + "".join(parts)))
    return bundles


def compose_prompt(context: str) -> str:
    """Wrap the user context with a minimal Deep Research preamble."""
    return (
        "You are producing a research briefing. A File Search corpus of source "
        "material has been attached; treat it as the primary ground truth and "
        "supplement with external web sources only where the corpus itself "
        "points to gaps or where recency matters. Cite sources specifically.\n\n"
        "=== BRIEFING CONTEXT AND INSTRUCTIONS ===\n\n" + context.strip() + "\n"
    )


def run_research_brief(
    topics: list[str],
    context: str,
    name: str,
    config: DistillConfig,
    tracker: CostTracker | None = None,
) -> Path | None:
    """Run a multi-topic Deep Research briefing; write output/briefing-{name}.md."""
    if not config.gemini_api_key:
        console.print("[red]GEMINI_API_KEY not set in .env[/red]")
        return None

    require_route_allowed(
        cost_mode=config.distill_cost_mode,
        provider="gemini",
        workload="research-brief",
    )
    tracker = require_cost_tracker(tracker)
    preflight_metered_interaction(tracker=tracker, model=DEEP_RESEARCH_MODEL)

    from google import genai

    client = genai.Client(api_key=config.gemini_api_key.get_secret_value())

    console.print(f"[cyan]Gathering files across {len(topics)} topic(s)...[/cyan]")
    files = gather_topic_files(topics, config)
    if not files:
        console.print("[red]No content found across the given topics[/red]")
        return None
    console.print(f"  {len(files)} documents to upload")

    store = client.file_search_stores.create(
        config={"display_name": f"distill-briefing-{name}-{int(time.time())}"}
    )
    store_name = ""
    active_error: BaseException | None = None
    # The store is a paid remote resource; everything from here is inside the
    # try so the finally deletes it even if upload or submission raises.
    try:
        store_name = store.name or ""
        if not store_name:
            console.print("[red]Failed to create File Search store[/red]")
            return None
        console.print(f"  [dim]Created store: {store_name}[/dim]")

        uploaded = _upload_files(client, store_name, files)
        console.print(f"  [green]Indexed {uploaded}/{len(files)} documents[/green]")
        if uploaded == 0:
            console.print("[red]No documents completed File Search indexing[/red]")
            return None

        prompt = compose_prompt(context)

        console.print("\n[cyan]Submitting to Gemini Deep Research...[/cyan]")
        console.print(f"  Agent: {DEEP_RESEARCH_MODEL}")
        console.print(f"  Grounded on {uploaded} docs. Expect 5-15 minutes.\n")

        interaction = submit_metered_interaction(
            lambda: client.interactions.create(
                input=prompt,
                agent=DEEP_RESEARCH_MODEL,
                background=True,
                tools=[
                    {
                        "type": "file_search",
                        "file_search_store_names": [store_name],
                    }
                ],
            ),
            tracker=tracker,
            model=DEEP_RESEARCH_MODEL,
        )
        interaction_id = interaction.id
        console.print(f"  [dim]Job ID: {interaction_id}[/dim]")

        completed = await_interaction(client, interaction_id, console, label="Research")
        if completed is None:
            return None

        grounding_refusal = file_search_grounding_reason(completed)
        if grounding_refusal:
            console.print(f"[red]Briefing refused:[/red] {grounding_refusal}")
            return None
        result_text = interaction_text(completed)
        if not result_text:
            console.print("[red]Research completed but no output received[/red]")
            return None
        refusal = unresolved_numbered_citation_reason(result_text)
        if refusal:
            console.print(f"[red]Briefing refused:[/red] {refusal}")
            return None

        output_path = workspace_output_path(config.library_dir, f"briefing-{name}.md")
        atomic_write_text(output_path, result_text)
        console.print(f"\n[green]Briefing saved to:[/green] {output_path}")
        console.print(f"[dim]Size: {len(result_text):,} chars[/dim]")
        return output_path
    except BaseException as exc:
        active_error = exc
        raise
    finally:
        cleanup_created_store(
            client,
            store,
            store_name,
            delete_fn=delete_store,
            active_error=active_error,
        )


def _upload_files(client: genai.Client, store_name: str, files: list[tuple[str, str]]) -> int:
    return upload_documents(client, store_name, files, failure_prefix="Upload failed for")

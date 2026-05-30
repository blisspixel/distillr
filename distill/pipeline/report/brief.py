"""Multi-topic research briefings via Gemini Deep Research.

Where `distill report <topic>` runs a 4-phase strategic report scoped to one
topic, and `distill brief <topic>` produces a lightweight Grok-based topic
brief, `distill research-brief` runs a single Gemini Deep Research call
grounded on one or more topics' paper/video/site insights, with a user-supplied
context block (`--context` or `--context-file`) that shapes the prompt for a
specific audience or decision. Output lands in `output/briefing-{name}.md`.

The context file IS the prompt — distill just handles file gathering, File
Search store management, Deep Research invocation, and output. This keeps the
prompt engineering in the user's hands and makes briefings reusable for
arbitrary purposes (multi-topic literature review, decision briefing for a
specific stakeholder, architectural grounding for a downstream agent, etc.)."""

from __future__ import annotations

import contextlib
import json
import tempfile
import time
from pathlib import Path

from google import genai
from rich.console import Console

from distill.config import DistillConfig
from distill.library.paths import find_artifact
from distill.library.wikilinks import emit_wiki_link
from distill.pipeline.costs import CostTracker
from distill.pipeline.report.file_search import delete_store

__all__ = [
    "compose_prompt",
    "gather_topic_files",
    "run_research_brief",
]

console = Console()

DEEP_RESEARCH_MODEL = "deep-research-preview-04-2026"
MAX_DOC_CHARS = 500_000


def gather_topic_files(topics: list[str], config: DistillConfig) -> list[tuple[str, str]]:  # noqa: C901 — legacy, will refactor
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
                files.append(
                    (
                        f"{label_stem}-{topic}",
                        f"# {label_stem.replace('-', ' ').title()}: {topic}\n"
                        f"Source: {link}\n\n" + synth.read_text(encoding="utf-8"),
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
        if not insights_file.exists():
            continue
        metadata_file = item_dir / "metadata.json"
        title = item_dir.name
        url = ""
        source_id = item_dir.name
        if metadata_file.exists():
            try:
                meta = json.loads(metadata_file.read_text(encoding="utf-8"))
                title = meta.get("title", title)
                url = meta.get("abs_url") or meta.get("url", "")
                source_id = meta.get("video_id") or meta.get("paper_id") or source_id
            except (json.JSONDecodeError, OSError):
                pass
        link = emit_wiki_link(title, source_id, "insights")
        entry = (
            f"\n\n---\n\n## [{kind}] {title}\nURL: {url}\nSource: {link}\n\n"
            + insights_file.read_text(encoding="utf-8")
        )
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
    store_name: str = store.name or ""
    if not store_name:
        console.print("[red]Failed to create File Search store[/red]")
        return None
    console.print(f"  [dim]Created store: {store_name}[/dim]")

    uploaded = _upload_files(client, store_name, files)
    console.print(f"  [green]Indexed {uploaded}/{len(files)} documents[/green]")

    prompt = compose_prompt(context)

    console.print("\n[cyan]Submitting to Gemini Deep Research...[/cyan]")
    console.print(f"  Agent: {DEEP_RESEARCH_MODEL}")
    console.print(f"  Grounded on {uploaded} docs. Expect 5-15 minutes.\n")

    try:
        interaction = client.interactions.create(
            input=prompt,
            agent=DEEP_RESEARCH_MODEL,
            background=True,
            tools=[
                {
                    "type": "file_search",
                    "file_search_store_names": [store_name],
                }
            ],
        )
        interaction_id = interaction.id
        if tracker:
            tracker.record_gemini_query(DEEP_RESEARCH_MODEL)
        console.print(f"  [dim]Job ID: {interaction_id}[/dim]")

        poll = 0
        while True:
            interaction = client.interactions.get(interaction_id)
            status = interaction.status
            poll += 1
            if status == "completed":
                console.print(f"\n[green]Research complete ({poll * 15}s elapsed)[/green]")
                break
            if status == "failed":
                err = getattr(interaction, "error", "Unknown error")
                console.print(f"\n[red]Research failed: {err}[/red]")
                return None
            if poll % 4 == 0:
                console.print(f"  [dim]Still researching... ({poll * 15}s, status: {status})[/dim]")
            time.sleep(15)

        result_text = interaction.outputs[-1].text if interaction.outputs else ""
        if not result_text:
            console.print("[red]Research completed but no output received[/red]")
            return None

        output_path = Path("output") / f"briefing-{name}.md"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(result_text, encoding="utf-8")
        console.print(f"\n[green]Briefing saved to:[/green] {output_path}")
        console.print(f"[dim]Size: {len(result_text):,} chars[/dim]")
        return output_path
    finally:
        delete_store(client, store_name)


def _upload_files(client: genai.Client, store_name: str, files: list[tuple[str, str]]) -> int:
    uploaded = 0
    pending: list = []
    temp_paths: list[Path] = []
    try:
        for label, content in files:
            tmp_path = None
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
                    config={
                        "display_name": label[:200],
                        "mime_type": "text/markdown",
                    },
                )
                pending.append(getattr(op, "name", None) or getattr(op, "id", None) or op)
                uploaded += 1
            except Exception as exc:
                console.print(f"  [yellow]Upload failed for {label[:50]}: {exc}[/yellow]")

        console.print(f"  [dim]Waiting for indexing ({len(pending)} docs)...[/dim]")
        rounds = 0
        while rounds < 60:
            still = []
            for op in pending:
                try:
                    refreshed = client.operations.get(op)
                    if refreshed.done is not True:
                        still.append(
                            getattr(refreshed, "name", None)
                            or getattr(refreshed, "id", None)
                            or refreshed
                        )
                except Exception:
                    still.append(op)
            if not still:
                break
            pending = still
            if rounds % 6 == 0:
                console.print(f"  [dim]Still indexing... {len(still)} remaining[/dim]")
            time.sleep(5)
            rounds += 1
    finally:
        for tmp_path in temp_paths:
            with contextlib.suppress(Exception):
                tmp_path.unlink(missing_ok=True)
    return uploaded

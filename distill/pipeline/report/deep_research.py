"""Deep Research -- Gemini Deep Research for validated intelligence."""

import json
from pathlib import Path

from google import genai
from rich.console import Console

from distill.config import DistillConfig
from distill.library.paths import (
    ProvenanceFields,
    artifact_path,
    base_frontmatter,
    find_artifact,
    tags_for,
    write_markdown_artifact,
)
from distill.pipeline.costs import CostTracker
from distill.pipeline.report._interactions import await_interaction, interaction_text
from distill.pipeline.report.file_search import create_research_store, delete_store
from distill.prompts.report import deep_research_prompt

__all__ = [
    "run_deep_research",
]

console = Console()

DEEP_RESEARCH_MODEL = "deep-research-preview-04-2026"
MAX_CORPUS_CHARS = 350_000


def run_deep_research(
    topic: str,
    config: DistillConfig,
    scope: str = "topic",
    channel_name: str | None = None,
    focus: str | None = None,
    test: bool = False,
    tracker: CostTracker | None = None,
) -> str | None:
    """Run Gemini Deep Research on the corpus using File Search grounding."""
    client = genai.Client(api_key=config.gemini_api_key.get_secret_value())

    console.print("[cyan]Preparing research corpus...[/cyan]")
    store_name, file_count = create_research_store(client, topic, config, scope, channel_name)

    if file_count == 0:
        console.print("[red]No content found for research scope[/red]")
        delete_store(client, store_name)
        return None

    prompt = deep_research_prompt(topic, corpus_summary="", focus=focus)

    console.print("[cyan]Submitting to Gemini Deep Research...[/cyan]")
    console.print(
        f"[dim]Grounded on {file_count} documents via File Search. This typically takes 5-15 minutes.[/dim]"
    )

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
        console.print(f"[dim]Job ID: {interaction_id}[/dim]")

        completed = await_interaction(client, interaction_id, console, label="Research")
        if completed is None:
            return None

        result_text = interaction_text(completed)
        if not result_text:
            console.print("[red]Research completed but no output received[/red]")
            return None

        output_path = _write_report_artifact(result_text, topic, config, scope, channel_name)
        console.print(f"[green]Findings saved to {output_path}[/green]")
        return result_text
    except Exception as exc:
        console.print(f"[red]Deep research error: {exc}[/red]")
        return None
    finally:
        delete_store(client, store_name)


def _gather_corpus_condensed(  # noqa: C901 — legacy, will refactor
    topic: str,
    config: DistillConfig,
    scope: str,
    channel_name: str | None,
) -> str:
    """Gather a condensed corpus for deep research."""
    parts: list[str] = []

    if scope == "channel" and channel_name:
        channels = [(topic, channel_name)]
    elif scope == "topic":
        topic_dir = config.topic_dir(topic) / "channels"
        channels = (
            [(topic, d.name) for d in sorted(topic_dir.iterdir()) if d.is_dir()]
            if topic_dir.exists()
            else []
        )
    else:
        channels = []
        topics_root = config.topics_dir()
        if topics_root.exists():
            for t_dir in sorted(topics_root.iterdir()):
                if not t_dir.is_dir():
                    continue
                ch_dir = t_dir / "channels"
                if ch_dir.exists():
                    for d in sorted(ch_dir.iterdir()):
                        if d.is_dir():
                            channels.append((t_dir.name, d.name))

    for t, ch in channels:
        ctx_file = config.channel_dir(t, ch) / "channel_context.md"
        if ctx_file.exists():
            parts.append(f"\n# Channel: {ch}\n{ctx_file.read_text(encoding='utf-8')}")

        synth_file = find_artifact(
            config.channel_dir(t, ch),
            "synthesis",
            identity=f"{t}_{ch}",
        )
        if synth_file.exists():
            parts.append(f"\n## Channel Synthesis\n{synth_file.read_text(encoding='utf-8')}")

        videos_dir = config.videos_dir(t, ch)
        if videos_dir.exists():
            video_count = 0
            for vid_dir in sorted(videos_dir.iterdir()):
                if not vid_dir.is_dir():
                    continue
                meta_file = vid_dir / "metadata.json"
                title = vid_dir.name
                date = ""
                if meta_file.exists():
                    meta = json.loads(meta_file.read_text(encoding="utf-8"))
                    title = meta.get("title", vid_dir.name)
                    date = meta.get("upload_date", "")
                insights_file = find_artifact(vid_dir, "insights")
                if insights_file.exists():
                    content = insights_file.read_text(encoding="utf-8")
                    if content.startswith("---"):
                        fm_parts = content.split("---", 2)
                        if len(fm_parts) >= 3:
                            content = fm_parts[2].strip()
                    parts.append(f"\n### [{date}] {title}\n{content}")
                    video_count += 1
            console.print(f"  [dim]{ch}: {video_count} video insights loaded[/dim]")

    topics_for_sites = [topic] if scope == "topic" else []
    if scope == "all":
        topics_root = config.topics_dir()
        if topics_root.exists():
            topics_for_sites = [
                t_dir.name for t_dir in sorted(topics_root.iterdir()) if t_dir.is_dir()
            ]

    for site_topic in topics_for_sites:
        sites_dir = config.sites_dir(site_topic)
        if not sites_dir.exists():
            continue
        for site_dir in sorted(sites_dir.iterdir()):
            if not site_dir.is_dir():
                continue
            synth_file = find_artifact(
                site_dir,
                "site_synthesis",
                identity=f"{site_topic}_{site_dir.name}",
            )
            if synth_file.exists():
                parts.append(
                    f"\n## Site Synthesis: {site_dir.name}\n{synth_file.read_text(encoding='utf-8')}"
                )
            pages_dir = site_dir / "pages"
            if not pages_dir.exists():
                continue
            for page_dir in sorted(pages_dir.iterdir()):
                if not page_dir.is_dir():
                    continue
                insights_file = find_artifact(page_dir, "insights")
                meta_file = page_dir / "metadata.json"
                if not insights_file.exists():
                    continue
                title = page_dir.name
                url = ""
                page_type = "page"
                if meta_file.exists():
                    try:
                        meta = json.loads(meta_file.read_text(encoding="utf-8"))
                        title = meta.get("title", title)
                        url = meta.get("url", "")
                        page_type = meta.get("page_type", page_type)
                    except (json.JSONDecodeError, OSError):
                        pass
                parts.append(
                    f"\n### [{page_type}] {title}\nURL: {url}\n{insights_file.read_text(encoding='utf-8')}"
                )

    topics_for_papers = [topic] if scope == "topic" else []
    if scope == "all":
        topics_root = config.topics_dir()
        if topics_root.exists():
            topics_for_papers = [
                t_dir.name for t_dir in sorted(topics_root.iterdir()) if t_dir.is_dir()
            ]

    for paper_topic in topics_for_papers:
        papers_dir = config.papers_dir(paper_topic)
        if not papers_dir.exists():
            continue
        for paper_dir in sorted(papers_dir.iterdir()):
            if not paper_dir.is_dir():
                continue
            insights_file = find_artifact(paper_dir, "insights")
            meta_file = paper_dir / "metadata.json"
            if not insights_file.exists():
                continue
            title = paper_dir.name
            abs_url = ""
            if meta_file.exists():
                try:
                    meta = json.loads(meta_file.read_text(encoding="utf-8"))
                    title = meta.get("title", title)
                    abs_url = meta.get("abs_url", "")
                except (json.JSONDecodeError, OSError):
                    pass
            parts.append(
                f"\n### [paper] {title}\nURL: {abs_url}\n{insights_file.read_text(encoding='utf-8')}"
            )

    if scope == "topic":
        topic_synth = find_artifact(config.topic_dir(topic), "topic_synthesis", identity=topic)
        if topic_synth.exists():
            parts.append(
                f"\n## Topic Synthesis: {topic}\n{topic_synth.read_text(encoding='utf-8')}"
            )
        paper_synth = find_artifact(config.topic_dir(topic), "paper_synthesis", identity=topic)
        if paper_synth.exists():
            parts.append(
                f"\n## Paper Synthesis: {topic}\n{paper_synth.read_text(encoding='utf-8')}"
            )
        corpus_synth = find_artifact(config.topic_dir(topic), "corpus_synthesis", identity=topic)
        if corpus_synth.exists():
            parts.append(
                f"\n## Corpus Synthesis: {topic}\n{corpus_synth.read_text(encoding='utf-8')}"
            )
    elif scope == "all":
        topics_root = config.topics_dir()
        if topics_root.exists():
            for t_dir in sorted(topics_root.iterdir()):
                if not t_dir.is_dir():
                    continue
                topic_synth = find_artifact(
                    t_dir,
                    "topic_synthesis",
                    identity=t_dir.name,
                )
                if topic_synth.exists():
                    parts.append(
                        f"\n## Topic Synthesis: {t_dir.name}\n{topic_synth.read_text(encoding='utf-8')}"
                    )
                paper_synth = find_artifact(
                    t_dir,
                    "paper_synthesis",
                    identity=t_dir.name,
                )
                if paper_synth.exists():
                    parts.append(
                        f"\n## Paper Synthesis: {t_dir.name}\n{paper_synth.read_text(encoding='utf-8')}"
                    )
                corpus_synth = find_artifact(
                    t_dir,
                    "corpus_synthesis",
                    identity=t_dir.name,
                )
                if corpus_synth.exists():
                    parts.append(
                        f"\n## Corpus Synthesis: {t_dir.name}\n{corpus_synth.read_text(encoding='utf-8')}"
                    )

    return "\n".join(parts)


def _get_report_path(
    topic: str,
    config: DistillConfig,
    scope: str,
    channel_name: str | None,
) -> Path:
    if scope == "channel" and channel_name:
        return artifact_path(
            config.channel_dir(topic, channel_name),
            "report",
            identity=f"{topic}_{channel_name}",
        )
    if scope == "topic":
        return artifact_path(config.topic_dir(topic), "report", identity=topic)
    return artifact_path(config.library_dir, "report", identity="library")


def _write_report_artifact(
    content: str,
    topic: str,
    config: DistillConfig,
    scope: str,
    channel_name: str | None,
) -> Path:
    if scope == "channel" and channel_name:
        directory = config.channel_dir(topic, channel_name)
        identity = f"{topic}_{channel_name}"
        title = f"Channel report: {channel_name}"
        extra = {"channel": channel_name, "legacy_filename": "report.md"}
    elif scope == "topic":
        directory = config.topic_dir(topic)
        identity = topic
        title = f"Topic report: {topic}"
        extra = {"legacy_filename": "report.md"}
    else:
        directory = config.library_dir
        identity = "library"
        title = "Library report"
        extra = {"legacy_filename": "report.md"}
    directory.mkdir(parents=True, exist_ok=True)
    return write_markdown_artifact(
        directory,
        "report",
        content,
        identity=identity,
        frontmatter=base_frontmatter(
            artifact_type="report",
            title=title,
            topic=topic if scope != "all" else "",
            source="distill",
            tags=tags_for(topic, "report") if scope != "all" else tags_for("", "report"),
            synthesis_scope="interpretation",
            extra=extra,
            provenance=ProvenanceFields(
                model=DEEP_RESEARCH_MODEL,
                model_version=DEEP_RESEARCH_MODEL,
                temperature=0.0,
                prompt_id="report.deep_research.v1",
            ),
        ),
    )

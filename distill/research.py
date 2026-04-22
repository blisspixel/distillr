"""Deep Research -- Gemini Deep Research for validated intelligence."""

import json
import time
from pathlib import Path

from google import genai
from rich.console import Console

from distill.config import DistillConfig
from distill.file_search import create_research_store, delete_store
from distill.prompts import deep_research_prompt

console = Console()

DEEP_RESEARCH_MODEL = "deep-research-pro-preview-12-2025"
MAX_CORPUS_CHARS = 350_000


def run_deep_research(
    topic: str,
    config: DistillConfig,
    scope: str = "topic",
    channel_name: str | None = None,
    focus: str | None = None,
    test: bool = False,
) -> str | None:
    """Run Gemini Deep Research on the corpus using File Search grounding."""
    client = genai.Client(api_key=config.gemini_api_key)

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
        console.print(f"[dim]Job ID: {interaction_id}[/dim]")

        poll_count = 0
        while True:
            interaction = client.interactions.get(interaction_id)
            status = interaction.status
            poll_count += 1

            if status == "completed":
                console.print(f"[green]Research complete! ({poll_count * 15}s elapsed)[/green]")
                break
            if status == "failed":
                error = getattr(interaction, "error", "Unknown error")
                console.print(f"[red]Research failed: {error}[/red]")
                delete_store(client, store_name)
                return None

            if poll_count % 4 == 0:
                console.print(
                    f"  [dim]Still researching... ({poll_count * 15}s, status: {status})[/dim]"
                )
            time.sleep(15)

        result_text = interaction.outputs[-1].text if interaction.outputs else ""
        if not result_text:
            console.print("[red]Research completed but no output received[/red]")
            delete_store(client, store_name)
            return None

        output_path = _get_report_path(topic, config, scope, channel_name)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(result_text, encoding="utf-8")
        console.print(f"[green]Findings saved to {output_path}[/green]")
        return result_text
    except Exception as exc:
        console.print(f"[red]Deep research error: {exc}[/red]")
        return None
    finally:
        delete_store(client, store_name)


def _gather_corpus_condensed(
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

        synth_file = config.channel_dir(t, ch) / "synthesis.md"
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
                insights_file = vid_dir / "insights.md"
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
            synth_file = site_dir / "synthesis.md"
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
                insights_file = page_dir / "insights.md"
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
            insights_file = paper_dir / "insights.md"
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
        topic_synth = config.topic_dir(topic) / "topic_synthesis.md"
        if topic_synth.exists():
            parts.append(
                f"\n## Topic Synthesis: {topic}\n{topic_synth.read_text(encoding='utf-8')}"
            )
        paper_synth = config.topic_dir(topic) / "paper_synthesis.md"
        if paper_synth.exists():
            parts.append(
                f"\n## Paper Synthesis: {topic}\n{paper_synth.read_text(encoding='utf-8')}"
            )
        corpus_synth = config.topic_dir(topic) / "corpus_synthesis.md"
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
                topic_synth = t_dir / "topic_synthesis.md"
                if topic_synth.exists():
                    parts.append(
                        f"\n## Topic Synthesis: {t_dir.name}\n{topic_synth.read_text(encoding='utf-8')}"
                    )
                paper_synth = t_dir / "paper_synthesis.md"
                if paper_synth.exists():
                    parts.append(
                        f"\n## Paper Synthesis: {t_dir.name}\n{paper_synth.read_text(encoding='utf-8')}"
                    )
                corpus_synth = t_dir / "corpus_synthesis.md"
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
        return config.channel_dir(topic, channel_name) / "report.md"
    if scope == "topic":
        return config.topic_dir(topic) / "report.md"
    return config.library_dir / "report.md"

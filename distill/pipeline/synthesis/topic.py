"""Synthesis -- per-channel and per-topic knowledge bases."""

import json
import logging

from rich.console import Console

from distill.config import DistillConfig
from distill.library.paths import (
    ProvenanceFields,
    base_frontmatter,
    find_artifact,
    tags_for,
    write_markdown_artifact,
)
from distill.library.wikilinks import emit_wiki_link
from distill.llm import call as llm_call
from distill.llm.router import RouterConfig
from distill.pipeline.costs import CostTracker, TokenUsage
from distill.prompts.synthesis import channel_synthesis_prompt, topic_synthesis_prompt

logger = logging.getLogger(__name__)

__all__ = [
    "synthesize_channel",
    "synthesize_topic",
]

console = Console()


def synthesize_channel(
    topic: str,
    channel_name: str,
    config: DistillConfig,
    tracker: CostTracker | None = None,
) -> str:
    """Generate channel-level synthesis from all video insights."""
    channel_dir = config.channel_dir(topic, channel_name)
    videos_dir = channel_dir / "videos"

    if not videos_dir.exists():
        console.print(f"  [yellow]No videos directory for {channel_name}[/yellow]")
        return ""

    context_file = channel_dir / "channel_context.md"
    channel_context = context_file.read_text(encoding="utf-8") if context_file.exists() else ""

    insight_parts: list[str] = []
    insight_files = [
        (video_dir, path)
        for video_dir in sorted(videos_dir.iterdir())
        if video_dir.is_dir()
        for path in [find_artifact(video_dir, "insights")]
        if path.exists()
    ]

    if not insight_files:
        console.print(f"  [yellow]No insights found for {channel_name}[/yellow]")
        return ""

    for video_dir, f in insight_files:
        # Build wiki-link reference for this source artifact
        meta_file = video_dir / "metadata.json"
        title = video_dir.name
        source_id = video_dir.name
        if meta_file.exists():
            try:
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
                if isinstance(meta, dict):
                    title = meta.get("title", title)
                    source_id = meta.get("video_id", source_id)
            except (json.JSONDecodeError, OSError):
                pass
        link = emit_wiki_link(title, source_id, "insights")
        insight_parts.append(f"\n\n---\nSource: {link}\n{f.read_text(encoding='utf-8')}")

    all_insights = "".join(insight_parts)
    console.print(f"  [cyan]Synthesizing {len(insight_files)} videos for {channel_name}...[/cyan]")

    try:
        rc = RouterConfig()
        prompt = channel_synthesis_prompt(channel_name, channel_context, all_insights)
        response = llm_call(
            rc, workload_tag="synthesis", prompt=prompt, call_type="channel_synthesis"
        )
        synthesis = response.text
        if tracker:
            tracker.record(
                TokenUsage(
                    prompt_tokens=response.input_tokens,
                    completion_tokens=response.output_tokens,
                    model=response.model,
                    call_type="channel_synthesis",
                )
            )
    except Exception as e:
        console.print(f"  [red]Channel synthesis API error: {e}[/red]")
        return ""

    output_file = write_markdown_artifact(
        channel_dir,
        "synthesis",
        synthesis,
        identity=f"{topic}_{channel_dir.name}",
        frontmatter=base_frontmatter(
            artifact_type="channel-synthesis",
            title=f"Channel synthesis: {channel_name}",
            topic=topic,
            source="distill",
            tags=tags_for(topic, "youtube"),
            synthesis_scope="corpus-consensus",
            extra={"channel": channel_name, "legacy_filename": "synthesis.md"},
            provenance=ProvenanceFields(
                model=response.model,
                model_version=response.model,
                temperature=0.0,
                prompt_id="synthesis.channel.v1",
            ),
        ),
    )
    console.print(f"  [green]Saved {output_file}[/green]")

    return synthesis


def synthesize_topic(
    topic: str,
    config: DistillConfig,
    tracker: CostTracker | None = None,
    *,
    style: str = "",
) -> str:
    """Generate topic-level synthesis from all channel syntheses.

    ``style`` selects an optional register (see ``prompts.synthesis.STYLE_GUIDANCE``).
    """
    topic_dir = config.topic_dir(topic)
    channels_dir = topic_dir / "channels"

    if not channels_dir.exists():
        return ""

    channel_syntheses = {}
    for channel_dir in sorted(channels_dir.iterdir()):
        if not channel_dir.is_dir():
            continue
        synth_file = find_artifact(channel_dir, "synthesis", identity=f"{topic}_{channel_dir.name}")
        if synth_file.exists():
            # Emit wiki-link for the channel synthesis artifact
            link = emit_wiki_link(
                f"Channel synthesis: {channel_dir.name}",
                f"{topic}_{channel_dir.name}",
                "synthesis",
            )
            channel_syntheses[channel_dir.name] = f"Source: {link}\n" + synth_file.read_text(
                encoding="utf-8"
            )

    if len(channel_syntheses) < 2:
        console.print(
            f"  [dim]Only {len(channel_syntheses)} channel(s) -- skipping topic synthesis[/dim]"
        )
        return ""

    console.print(
        f"  [cyan]Synthesizing topic '{topic}' across {len(channel_syntheses)} channels...[/cyan]"
    )

    try:
        rc = RouterConfig()
        prompt = topic_synthesis_prompt(topic, channel_syntheses, style=style)
        response = llm_call(
            rc, workload_tag="synthesis", prompt=prompt, call_type="topic_synthesis"
        )
        synthesis = response.text
        if tracker:
            tracker.record(
                TokenUsage(
                    prompt_tokens=response.input_tokens,
                    completion_tokens=response.output_tokens,
                    model=response.model,
                    call_type="topic_synthesis",
                )
            )
    except Exception as e:
        console.print(f"  [red]Topic synthesis API error: {e}[/red]")
        return ""

    output_file = write_markdown_artifact(
        topic_dir,
        "topic_synthesis",
        synthesis,
        identity=topic,
        frontmatter=base_frontmatter(
            artifact_type="topic-synthesis",
            title=f"Topic synthesis: {topic}",
            topic=topic,
            source="distill",
            tags=tags_for(topic, "youtube"),
            synthesis_scope="corpus-consensus",
            extra={"legacy_filename": "topic_synthesis.md"},
            provenance=ProvenanceFields(
                model=response.model,
                model_version=response.model,
                temperature=0.0,
                prompt_id="synthesis.topic.v1",
            ),
        ),
    )
    console.print(f"  [green]Saved {output_file}[/green]")

    # Refresh the agent-orientation CLAUDE.md for this topic + the library index.
    # Best-effort: pure templating over what we just wrote, but a failure here
    # must never fail an otherwise-successful synthesis.
    try:
        from distill.library import claude_md

        claude_md.refresh_for_topic(config.library_dir, topic_dir, topic)
    except Exception as exc:
        console.print(f"  [dim]CLAUDE.md refresh skipped: {exc}[/dim]")

    return synthesis

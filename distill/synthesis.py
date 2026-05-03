"""Synthesis -- per-channel and per-topic knowledge bases."""

from rich.console import Console

from distill.artifacts import base_frontmatter, find_artifact, tags_for, write_markdown_artifact
from distill.config import DistillConfig, router_config_from_distill
from distill.costs import CostTracker, TokenUsage
from distill.llm import call as llm_call
from distill.prompts import channel_synthesis_prompt, topic_synthesis_prompt

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

    all_insights = ""
    insight_files = [
        path
        for video_dir in sorted(videos_dir.iterdir())
        if video_dir.is_dir()
        for path in [find_artifact(video_dir, "insights")]
        if path.exists()
    ]

    if not insight_files:
        console.print(f"  [yellow]No insights found for {channel_name}[/yellow]")
        return ""

    for f in insight_files:
        all_insights += f"\n\n---\n{f.read_text(encoding='utf-8')}"

    console.print(f"  [cyan]Synthesizing {len(insight_files)} videos for {channel_name}...[/cyan]")

    try:
        rc = router_config_from_distill(config)
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
            confidence="corpus-consensus",
            extra={"channel": channel_name, "legacy_filename": "synthesis.md"},
        ),
    )
    console.print(f"  [green]Saved {output_file}[/green]")

    return synthesis


def synthesize_topic(
    topic: str,
    config: DistillConfig,
    tracker: CostTracker | None = None,
) -> str:
    """Generate topic-level synthesis from all channel syntheses."""
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
            channel_syntheses[channel_dir.name] = synth_file.read_text(encoding="utf-8")

    if len(channel_syntheses) < 2:
        console.print(
            f"  [dim]Only {len(channel_syntheses)} channel(s) -- skipping topic synthesis[/dim]"
        )
        return ""

    console.print(
        f"  [cyan]Synthesizing topic '{topic}' across {len(channel_syntheses)} channels...[/cyan]"
    )

    try:
        rc = router_config_from_distill(config)
        prompt = topic_synthesis_prompt(topic, channel_syntheses)
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
            confidence="corpus-consensus",
            extra={"legacy_filename": "topic_synthesis.md"},
        ),
    )
    console.print(f"  [green]Saved {output_file}[/green]")

    return synthesis

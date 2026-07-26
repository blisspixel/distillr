# pyright: strict
"""Lightweight briefing built from learned insights."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import cast

from distill.config import DistillConfig
from distill.library.insights import discover_insights, read_discovered_insight
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
from distill.pipeline.citation_refs import unresolved_numbered_citation_reason
from distill.pipeline.costs import CostTracker, TokenUsage
from distill.prompts.registry import PROMPT_IDS
from distill.prompts.report import topic_brief_prompt

__all__ = [
    "generate_topic_brief",
]

logger = logging.getLogger(__name__)


def _read_video_metadata(meta_file: Path) -> tuple[str | None, str | None]:
    try:
        raw_meta: object = json.loads(meta_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        logger.debug("failed to read video metadata from %s", meta_file, exc_info=True)
        return None, None
    if not isinstance(raw_meta, dict):
        return None, None

    meta = cast("dict[str, object]", raw_meta)
    title = meta.get("title")
    source_id = meta.get("video_id")
    return (
        title if isinstance(title, str) and title else None,
        source_id if isinstance(source_id, str) and source_id else None,
    )


def generate_topic_brief(  # noqa: C901 - legacy orchestration kept intact
    topic: str,
    config: DistillConfig,
    tracker: CostTracker | None = None,
) -> Path | None:
    topic_dir = config.topic_dir(topic)
    topic_dir.mkdir(parents=True, exist_ok=True)

    synthesis_context = ""
    for artifact_type in ("topic_synthesis", "corpus_synthesis", "paper_synthesis"):
        synth_file = find_artifact(topic_dir, artifact_type, identity=topic)
        if synth_file.exists():
            synthesis_context = synth_file.read_text(encoding="utf-8")
            break

    insight_parts: list[str] = []
    included_insights: set[Path] = set()
    channels_dir = topic_dir / "channels"
    if channels_dir.exists():
        for channel_dir in sorted(channels_dir.iterdir()):
            videos_dir = channel_dir / "videos"
            if not videos_dir.exists():
                continue
            for video_dir in sorted(videos_dir.iterdir(), reverse=True):
                insight_file = find_artifact(video_dir, "insights")
                if insight_file.exists():
                    # Build wiki-link for this source artifact
                    meta_file = video_dir / "metadata.json"
                    title = video_dir.name
                    source_id = video_dir.name
                    if meta_file.exists():
                        meta_title, meta_source_id = _read_video_metadata(meta_file)
                        title = meta_title or title
                        source_id = meta_source_id or source_id
                    link = emit_wiki_link(title, source_id, "insights")
                    insight_parts.append(
                        f"## {channel_dir.name} / {video_dir.name}\nSource: {link}\n"
                        + insight_file.read_text(encoding="utf-8")
                    )
                    included_insights.add(insight_file)
                if len(insight_parts) >= 6:
                    break
            if len(insight_parts) >= 6:
                break

    for ref in discover_insights(topic_dir, confinement_root=config.library_dir):
        if len(insight_parts) >= 6:
            break
        if ref.path in included_insights:
            continue
        content = read_discovered_insight(ref, config.library_dir)
        if content is None:
            continue
        title = ref.path.parent.name
        link = emit_wiki_link(title, ref.source_id, "insights")
        insight_parts.append(f"## {ref.artifact_path}\nSource: {link}\n" + content)

    if not synthesis_context and not insight_parts:
        return None

    rc = RouterConfig()
    prompt = topic_brief_prompt(topic, synthesis_context, "\n\n---\n\n".join(insight_parts))
    response = llm_call(
        rc,
        workload_tag="brief",
        prompt=prompt,
        max_tokens=4096,
        call_type="topic_brief",
        usage_tracker=tracker,
    )

    if tracker:
        tracker.record(TokenUsage.from_response(response, call_type="topic_brief"))

    content = response.text
    if not content:
        return None
    refusal = unresolved_numbered_citation_reason(content)
    if refusal:
        logger.warning("Refused topic brief for %s: %s", topic, refusal)
        return None

    return write_markdown_artifact(
        topic_dir,
        "brief",
        content,
        identity=topic,
        frontmatter=base_frontmatter(
            artifact_type="brief",
            title=f"Topic brief: {topic}",
            topic=topic,
            source="distill",
            tags=tags_for(topic, "brief"),
            synthesis_scope="interpretation",
            extra={"legacy_filename": "brief.md"},
            provenance=ProvenanceFields(
                model=response.model,
                model_version=response.model,
                temperature=0.0,
                prompt_id=PROMPT_IDS["brief.topic"],
            ),
        ),
    )

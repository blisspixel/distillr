# pyright: strict
"""Analysis pipeline - per-source analysis orchestration."""

from distill.pipeline.analysis.paper import analyze_paper, synthesize_papers
from distill.pipeline.analysis.site import (
    analyze_site_page,
    synthesize_site,
    synthesize_site_topic,
)
from distill.pipeline.analysis.video import (
    analyze_scan,
    analyze_short,
    analyze_video,
    generate_channel_context,
    generate_watch_instructions,
)

__all__ = [
    "analyze_paper",
    "analyze_scan",
    "analyze_short",
    "analyze_site_page",
    "analyze_video",
    "generate_channel_context",
    "generate_watch_instructions",
    "synthesize_papers",
    "synthesize_site",
    "synthesize_site_topic",
]

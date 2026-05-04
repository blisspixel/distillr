"""Topic routes — list and detail views."""

import contextlib
import json

from fastapi import APIRouter, Request

from distill.config import DistillConfig
from distill.library import Library
from distill.library.paths import artifact_exists, find_artifact

router = APIRouter()


def _topic_summary(config: DistillConfig, lib: Library, topic: str) -> dict:
    channels = lib.get_channels(topic)
    video_count = 0
    for ch in channels:
        vdir = config.channel_dir(topic, ch.name) / "videos"
        if vdir.exists():
            video_count += sum(
                1 for d in vdir.iterdir() if d.is_dir() and artifact_exists(d, "insights")
            )
    site_count = 0
    sites_dir = config.sites_dir(topic)
    if sites_dir.exists():
        site_count = sum(1 for d in sites_dir.iterdir() if d.is_dir())
    paper_count = 0
    papers_dir = config.papers_dir(topic)
    if papers_dir.exists():
        paper_count = sum(
            1 for d in papers_dir.iterdir() if d.is_dir() and artifact_exists(d, "paper")
        )
    topic_dir = config.topic_dir(topic)
    has_synthesis = artifact_exists(topic_dir, "topic_synthesis", identity=topic)
    has_report = artifact_exists(topic_dir, "report", identity=topic)
    has_brief = artifact_exists(topic_dir, "brief", identity=topic)
    return {
        "name": topic,
        "channels": channels,
        "channel_count": len(channels),
        "video_count": video_count,
        "site_count": site_count,
        "paper_count": paper_count,
        "has_synthesis": has_synthesis,
        "has_report": has_report,
        "has_brief": has_brief,
    }


@router.get("/topics")
async def topic_list(request: Request):
    config = request.app.state.config
    templates = request.app.state.templates
    lib = Library(config)
    topics = [_topic_summary(config, lib, t) for t in lib.get_topics()]
    return templates.TemplateResponse(
        request, "topic_list.html", {"request": request, "topics": topics}
    )


@router.get("/topics/{topic}")
async def topic_detail(request: Request, topic: str):  # noqa: C901 — legacy, will refactor
    config = request.app.state.config
    templates = request.app.state.templates
    lib = Library(config)
    summary = _topic_summary(config, lib, topic)
    topic_dir = config.topic_dir(topic)

    synthesis = ""
    synthesis_path = find_artifact(topic_dir, "topic_synthesis", identity=topic)
    if synthesis_path.exists():
        synthesis = synthesis_path.read_text(encoding="utf-8")

    brief = ""
    brief_path = find_artifact(topic_dir, "brief", identity=topic)
    if brief_path.exists():
        brief = brief_path.read_text(encoding="utf-8")

    # Gather sites
    sites = []
    sites_dir = config.sites_dir(topic)
    if sites_dir.exists():
        for site_dir in sites_dir.iterdir():
            if not site_dir.is_dir():
                continue
            page_count = 0
            pages_dir = site_dir / "pages"
            if pages_dir.exists():
                page_count = sum(
                    1 for p in pages_dir.iterdir() if p.is_dir() and artifact_exists(p, "content")
                )
            sites.append({"name": site_dir.name, "page_count": page_count})

    # Gather papers
    papers = []
    papers_dir = config.papers_dir(topic)
    if papers_dir.exists():
        for paper_dir in papers_dir.iterdir():
            if not paper_dir.is_dir():
                continue
            meta_path = paper_dir / "metadata.json"
            meta = {}
            with contextlib.suppress(OSError, json.JSONDecodeError):
                if meta_path.exists():
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
            papers.append(
                {
                    "slug": paper_dir.name,
                    "title": meta.get("title", paper_dir.name),
                }
            )

    return templates.TemplateResponse(
        request,
        "topic_detail.html",
        {
            "request": request,
            "topic": summary,
            "synthesis": synthesis,
            "brief": brief,
            "sites": sites,
            "papers": papers,
        },
    )

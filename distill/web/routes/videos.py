"""Video routes — individual video detail."""

import contextlib
import json

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/topics/{topic}/channels/{channel}/videos/{slug}")
async def video_detail(request: Request, topic: str, channel: str, slug: str):
    config = request.app.state.config
    templates = request.app.state.templates

    vid_dir = config.videos_dir(topic, channel) / slug
    meta = {}
    meta_path = vid_dir / "metadata.json"
    with contextlib.suppress(OSError, json.JSONDecodeError):
        if meta_path.exists():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))

    insights = ""
    insights_path = vid_dir / "insights.md"
    if insights_path.exists():
        insights = insights_path.read_text(encoding="utf-8")

    transcript = ""
    transcript_path = vid_dir / "transcript.txt"
    if transcript_path.exists():
        transcript = transcript_path.read_text(encoding="utf-8")

    return templates.TemplateResponse(
        request,
        "video_detail.html",
        {
            "request": request,
            "topic": topic,
            "channel": channel,
            "slug": slug,
            "meta": meta,
            "insights": insights,
            "transcript": transcript,
        },
    )

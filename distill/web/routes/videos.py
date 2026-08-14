"""Video routes — individual video detail."""

import contextlib
import json

from fastapi import APIRouter, HTTPException, Request

from distill.library.paths import find_artifact
from distill.parsing import LENIENT_LOCAL_JSON_ERRORS, read_local_utf8_text

router = APIRouter()


@router.get("/topics/{topic}/channels/{channel}/videos/{slug}")
async def video_detail(request: Request, topic: str, channel: str, slug: str):
    config = request.app.state.config
    templates = request.app.state.templates

    # slug is a raw URL path param; confine it under the channel's videos/ dir
    # so a percent-encoded "../" cannot read arbitrary filesystem locations.
    base = config.videos_dir(topic, channel).resolve()
    vid_dir = (base / slug).resolve()
    if vid_dir != base and base not in vid_dir.parents:
        raise HTTPException(status_code=404)
    meta: dict = {}
    meta_path = vid_dir / "metadata.json"
    with contextlib.suppress(*LENIENT_LOCAL_JSON_ERRORS):
        if meta_path.exists():
            raw = json.loads(meta_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                meta = raw

    insights = read_local_utf8_text(find_artifact(vid_dir, "insights")) or ""
    transcript = read_local_utf8_text(find_artifact(vid_dir, "transcript", extension="txt")) or ""

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

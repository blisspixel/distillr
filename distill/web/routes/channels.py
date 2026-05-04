"""Channel routes — channel detail with video list."""

import json

from fastapi import APIRouter, Request

from distill.config import DistillConfig
from distill.library import Library
from distill.library.paths import artifact_exists, find_artifact

router = APIRouter()


def _collect_videos(config: DistillConfig, topic: str, channel: str) -> list[dict]:
    videos_dir = config.videos_dir(topic, channel)
    if not videos_dir.exists():
        return []
    vid_list = []
    for vid_dir in videos_dir.iterdir():
        if not vid_dir.is_dir():
            continue
        meta_file = vid_dir / "metadata.json"
        if not meta_file.exists():
            continue
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        meta["_slug"] = vid_dir.name
        meta["_has_insights"] = artifact_exists(vid_dir, "insights")
        meta["_has_transcript"] = artifact_exists(vid_dir, "transcript", extension="txt")
        vid_list.append(meta)
    vid_list.sort(key=lambda v: v.get("upload_date", ""), reverse=True)
    return vid_list


@router.get("/topics/{topic}/channels/{channel}")
async def channel_detail(request: Request, topic: str, channel: str):
    config = request.app.state.config
    templates = request.app.state.templates
    lib = Library(config)

    ch_info = lib.get_channel_by_name(topic, channel)
    videos = _collect_videos(config, topic, channel)
    channel_dir = config.channel_dir(topic, channel)

    synthesis = ""
    synth_path = find_artifact(channel_dir, "synthesis", identity=f"{topic}_{channel}")
    if synth_path.exists():
        synthesis = synth_path.read_text(encoding="utf-8")

    context = ""
    ctx_path = channel_dir / "channel_context.md"
    if ctx_path.exists():
        context = ctx_path.read_text(encoding="utf-8")

    return templates.TemplateResponse(
        request,
        "channel_detail.html",
        {
            "request": request,
            "topic": topic,
            "channel": channel,
            "ch_info": ch_info,
            "videos": videos,
            "synthesis": synthesis,
            "context": context,
            "video_count": len(videos),
        },
    )

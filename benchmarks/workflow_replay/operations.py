# pyright: strict
"""Real Distill workflows driven by frozen receipts and a stub model."""

from __future__ import annotations

import email.utils
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch

from pydantic import SecretStr

from benchmarks.workflow_replay.fixtures import (
    CHANNEL,
    PAPER_ID,
    PAPER_INSIGHT_BODY,
    PAPER_PDF_TEXT,
    PAPER_TITLE,
    PROFILE_PAYLOAD,
    REPORT_CONTEXT,
    REPORT_SYNTHESIS_BODY,
    SITE_INSIGHT_BODY,
    SYNTHESIS_BODY,
    TOPIC,
    VERIFY_INSIGHT,
    VERIFY_SOURCE,
    VIDEO_ID,
    VIDEO_INSIGHT_BODY,
    VIDEO_TITLE,
    VIDEO_TRANSCRIPT,
    paper_record,
    site_page,
)
from benchmarks.workflow_replay.measure import json_digest
from benchmarks.workflow_replay.stub import ReplayCallLog, make_llm_call
from distill.config import DistillConfig
from distill.ingestors.podcasts.feed import PodcastEpisode, PodcastFeed
from distill.ingestors.youtube.discovery import VideoInfo
from distill.library.insights import insight_content_sha256
from distill.library.paths import find_artifact, strip_frontmatter
from distill.library.profiles import ResearchProfile
from distill.llm.router import RouterConfig
from distill.pipeline.analysis.paper import analyze_paper, synthesize_papers
from distill.pipeline.analysis.site import analyze_site_page
from distill.pipeline.analysis.video import analyze_video
from distill.pipeline.profile_execution import CommandExecution
from distill.pipeline.profile_preview import ProfilePreviewResult, build_profile_preview
from distill.pipeline.profile_run import run_profile_preview
from distill.pipeline.report.synthesize import run_synthesis
from distill.pipeline.verify import run_verify_hook

OPERATION_NAMES = (
    "paper_analyze",
    "video_analyze",
    "site_analyze",
    "paper_synthesize",
    "verify_numeric",
    "profile_preview",
    "profile_run",
    "report_synthesize",
)

type ReplayOperation = Callable[[], tuple[object, int, int]]


def _config(library_root: Path) -> DistillConfig:
    return DistillConfig(
        xai_api_key=SecretStr("distill-replay-inert"),
        gemini_api_key=SecretStr(""),
        anthropic_api_key=SecretStr(""),
        openai_api_key=SecretStr(""),
        distill_output_dir=library_root,
        distill_verify="warn",
        distill_cost_mode="auto",
    )


def _router() -> RouterConfig:
    return RouterConfig(
        xai_api_key="distill-replay-inert",
        gemini_api_key="",
        anthropic_api_key="",
        openai_api_key="",
        provider="xai",
        cost_mode="auto",
    )


def _patches(
    *,
    paper_llm: object | None = None,
    video_llm: object | None = None,
    site_llm: object | None = None,
    report_llm: object | None = None,
) -> list[Any]:
    def frozen_pdf(_url: str) -> str:
        return PAPER_PDF_TEXT

    patches: list[Any] = [
        patch("distill.pipeline.analysis.paper.fetch_paper_pdf_text", frozen_pdf),
        patch("distill.pipeline.verify._entailment_checker", lambda: None),
    ]
    if paper_llm is not None:
        patches.append(patch("distill.pipeline.analysis.paper.llm_call", paper_llm))
    if video_llm is not None:
        patches.append(patch("distill.pipeline.analysis.video.llm_call", video_llm))
    if site_llm is not None:
        patches.append(patch("distill.pipeline.analysis.site.llm_call", site_llm))
    if report_llm is not None:
        patches.append(patch("distill.pipeline.report.synthesize.llm_call", report_llm))
        patches.append(
            patch("distill.pipeline.report.synthesize._synthesis_model_available", lambda: True)
        )
    return patches


def _apply(patches: list[Any]) -> None:
    for item in patches:
        item.start()


def _stop(patches: list[Any]) -> None:
    for item in reversed(patches):
        item.stop()


def _recent_rfc() -> str:
    return email.utils.format_datetime(datetime.now(UTC) - timedelta(hours=1), usegmt=True)


def _frozen_feed(_url: str) -> PodcastFeed:
    return PodcastFeed(
        title="Replay Feed",
        link="https://example.test",
        description="",
        episodes=[
            PodcastEpisode(
                title="Replay episode",
                guid="replay-episode-1",
                published=_recent_rfc(),
                audio_url="https://example.test/episode.mp3",
                audio_type="audio/mpeg",
                duration_s=600,
                description="",
                link="https://example.test/episode",
            )
        ],
    )


def _frozen_youtube(_channel_url: str, **_kwargs: object) -> list[VideoInfo]:
    day = datetime.now(UTC).strftime("%Y%m%d")
    return [
        VideoInfo(
            video_id=VIDEO_ID,
            title=VIDEO_TITLE,
            upload_date=day,
            duration=600,
            url=f"https://www.youtube.com/watch?v={VIDEO_ID}",
            channel_name="Replay Channel",
            published_at=datetime.now(UTC).replace(microsecond=0).isoformat(),
        )
    ]


def _stable_preview(result: ProfilePreviewResult) -> dict[str, object]:
    rows = [
        {
            "command": candidate.command,
            "identity": candidate.identity,
            "kind": candidate.kind,
            "source": candidate.source,
            "title": candidate.title,
            "url": candidate.url,
        }
        for candidate in result.candidates
    ]
    return {
        "candidate_count": len(rows),
        "candidates": rows,
        "cost_mode": result.cost_mode,
        "profile": result.profile,
        "topic": result.topic,
        "warning_count": len(result.warnings),
    }


def _noop_executor(
    command: list[str],
    timeout_seconds: int,
    environment: Mapping[str, str] | None = None,
) -> CommandExecution:
    del command, timeout_seconds, environment
    return CommandExecution(0, 0.01)


def _op_profile_preview() -> tuple[object, int, int]:
    profile = ResearchProfile.model_validate(PROFILE_PAYLOAD)
    preview = build_profile_preview(
        profile,
        fetch_sources=True,
        feed_fetcher=_frozen_feed,
        youtube_discoverer=_frozen_youtube,
    )
    value = _stable_preview(preview)
    count = value["candidate_count"]
    if not isinstance(count, int):
        raise TypeError("profile preview candidate_count must be int")
    return value, count, 0


def _op_profile_run(library_root: Path) -> tuple[object, int, int]:
    profile = ResearchProfile.model_validate(PROFILE_PAYLOAD)
    preview = build_profile_preview(
        profile,
        fetch_sources=True,
        feed_fetcher=_frozen_feed,
        youtube_discoverer=_frozen_youtube,
    )
    result = run_profile_preview(
        preview,
        library_dir=library_root,
        approved=True,
        executor=_noop_executor,
    )
    commands = [
        {
            "key": item.key,
            "kind": item.kind,
            "status": item.status,
            "command": item.command,
        }
        for item in result.commands
    ]
    value = {
        "approved": result.approved,
        "busy": result.busy,
        "command_count": len(commands),
        "commands": commands,
        "executed": result.executed,
        "succeeded_count": result.succeeded_count,
    }
    return value, len(commands), 0


def _op_report_synthesize(library_root: Path, wait_ns: int) -> tuple[object, int, int]:
    config = _config(library_root)
    paper_dir = config.paper_dir(TOPIC, PAPER_TITLE, PAPER_ID)
    paper_dir.mkdir(parents=True, exist_ok=True)
    (paper_dir / "insights.md").write_text(PAPER_INSIGHT_BODY, encoding="utf-8")
    log = ReplayCallLog()
    stub = make_llm_call(log, body=REPORT_SYNTHESIS_BODY, wait_ns=wait_ns)
    started = _patches(report_llm=stub)
    _apply(started)
    resolved: Path | None = None
    try:
        written = run_synthesis([TOPIC], REPORT_CONTEXT, "replay", config)
        if written is not None:
            resolved = written.resolve()
    finally:
        _stop(started)
    if resolved is None:
        raise RuntimeError("report_synthesize produced no artifact")
    body = resolved.read_text(encoding="utf-8")
    value = {
        "body_sha256": json_digest(body),
        "llm_calls": log.calls,
        "matches_fixture": body == REPORT_SYNTHESIS_BODY,
        "relative_parent": resolved.parent.name,
        "under_workspace": resolved.is_relative_to(library_root.parent.resolve()),
    }
    return value, 1, log.provider_wait_ns


def operations(library_root: Path, *, wait_ns: int) -> list[tuple[str, ReplayOperation]]:
    def paper() -> tuple[object, int, int]:
        log = ReplayCallLog()
        stub = make_llm_call(log, body=PAPER_INSIGHT_BODY, wait_ns=wait_ns)
        started = _patches(paper_llm=stub)
        _apply(started)
        try:
            insights, document = analyze_paper(
                paper_record(),
                _config(library_root),
                router_config=_router(),
            )
        finally:
            _stop(started)
        value = {
            "document_sha256": json_digest(document),
            "insight_sha256": insight_content_sha256(insights),
            "llm_calls": log.calls,
            "source_mode": "full_pdf" if "source_mode: full_pdf" in insights else "other",
        }
        return value, 1, log.provider_wait_ns

    def video() -> tuple[object, int, int]:
        log = ReplayCallLog()
        stub = make_llm_call(log, body=VIDEO_INSIGHT_BODY, wait_ns=wait_ns)
        started = _patches(video_llm=stub)
        _apply(started)
        try:
            insights = analyze_video(
                VIDEO_TITLE,
                "20260212",
                CHANNEL,
                VIDEO_TRANSCRIPT,
                _config(library_root),
                router_config=_router(),
            )
        finally:
            _stop(started)
        value = {
            "insight_sha256": insight_content_sha256(insights),
            "llm_calls": log.calls,
        }
        return value, log.calls, log.provider_wait_ns

    def site() -> tuple[object, int, int]:
        log = ReplayCallLog()
        stub = make_llm_call(log, body=SITE_INSIGHT_BODY, wait_ns=wait_ns)
        started = _patches(site_llm=stub)
        _apply(started)
        try:
            insights = analyze_site_page(
                site_page(),
                _config(library_root),
                router_config=_router(),
            )
        finally:
            _stop(started)
        value = {
            "insight_sha256": insight_content_sha256(insights),
            "llm_calls": log.calls,
        }
        return value, 1, log.provider_wait_ns

    def synthesize() -> tuple[object, int, int]:
        config = _config(library_root)
        paper_dir = config.paper_dir(TOPIC, PAPER_TITLE, PAPER_ID)
        paper_dir.mkdir(parents=True, exist_ok=True)
        (paper_dir / "insights.md").write_text(PAPER_INSIGHT_BODY, encoding="utf-8")
        log = ReplayCallLog()
        stub = make_llm_call(log, body=SYNTHESIS_BODY, wait_ns=wait_ns)
        started = _patches(paper_llm=stub)
        _apply(started)
        try:
            body = synthesize_papers(TOPIC, config)
        finally:
            _stop(started)
        topic_dir = config.topic_dir(TOPIC)
        output = find_artifact(topic_dir, "paper_synthesis", identity=TOPIC)
        value = {
            "body_sha256": json_digest(strip_frontmatter(output.read_text(encoding="utf-8"))),
            "llm_calls": log.calls,
            "sidecar_exists": any(topic_dir.glob("*Verify.json")),
            "synthesis_matches": body == SYNTHESIS_BODY,
        }
        return value, 1, log.provider_wait_ns

    def verify() -> tuple[object, int, int]:
        started = _patches()
        _apply(started)
        try:
            outcome = run_verify_hook(
                library_root,
                VERIFY_INSIGHT,
                VERIFY_SOURCE,
                mode="warn",
                identity="replay-verify",
                insight_name="replay.md",
                source_name="frozen-receipts",
            )
        finally:
            _stop(started)
        if outcome is None:
            raise RuntimeError("verify_numeric produced no outcome")
        value = {
            "checked": outcome.report.checked,
            "refused": outcome.refused,
            "sidecar_exists": outcome.sidecar.is_file(),
            "unsupported": len(outcome.report.unsupported),
        }
        return value, outcome.report.checked, 0

    return [
        ("paper_analyze", paper),
        ("video_analyze", video),
        ("site_analyze", site),
        ("paper_synthesize", synthesize),
        ("verify_numeric", verify),
        ("profile_preview", _op_profile_preview),
        ("profile_run", lambda: _op_profile_run(library_root)),
        ("report_synthesize", lambda: _op_report_synthesize(library_root, wait_ns)),
    ]


def operation_by_name(
    library_root: Path,
    name: str,
    *,
    wait_ns: int,
) -> ReplayOperation:
    mapping = dict(operations(library_root, wait_ns=wait_ns))
    try:
        return mapping[name]
    except KeyError as exc:
        raise ValueError(f"unknown workflow replay operation: {name}") from exc

"""Bounded professional editorial passes with durable reviewable outputs."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from distill.editorial.budget import EditorialTracker, WeeklyLedger
from distill.editorial.perspective import Perspective
from distill.editorial.prompts import BASE, STAGES
from distill.editorial.retonr import check_revision
from distill.editorial.review import Review, structural_issues, verify_review
from distill.editorial.routing import select_routes
from distill.editorial.sources import (
    SourceReceipt,
    collect_sources,
    evidence_packet,
    load_receipts,
    save_receipts,
)
from distill.library.paths import atomic_write_json, atomic_write_text
from distill.llm.router import RouterConfig, call


class EditorialReviewError(ValueError):
    """Saved editorial work did not pass the bounded publication-readiness review."""


def _history(workspace: Path) -> list[str]:
    titles = []
    for path in sorted((workspace / "runs").glob("*/article.md"))[-20:]:
        with path.open(encoding="utf-8") as stream:
            titles.append(stream.readline(1000).strip().removeprefix("# "))
    return titles


def _capture(
    perspective: Perspective, receipt_dir: Path | None
) -> tuple[list[SourceReceipt], list[dict[str, str]]]:
    if receipt_dir is not None:
        return load_receipts(receipt_dir, perspective.sources), []
    return collect_sources(perspective.sources)


def _read_review(
    stage: Callable[[str, str, str], str],
    packet: dict[str, object],
    article: str,
    sources: list[SourceReceipt],
    revision: int,
) -> tuple[Review, list[str]]:
    raw = stage("review", "critic", f"review-{revision}.json")
    review = Review.model_validate_json(raw.removeprefix("```json\n").removesuffix("\n```"))
    issues = verify_review(review, article, sources)
    if any(issue.startswith("Reviewer") for issue in issues):
        # Repair the critic's copied evidence before spending on an article
        # rewrite. Both reports remain visible and the same checks run again.
        packet["invalid_review"] = review.model_dump()
        packet["review_copy_errors"] = issues
        try:
            raw = stage("repair_review", "critic", f"review-{revision}-repair.json")
            review = Review.model_validate_json(raw.removeprefix("```json\n").removesuffix("\n```"))
            issues = verify_review(review, article, sources)
        finally:
            packet.pop("invalid_review")
            packet.pop("review_copy_errors")
    return review, issues


def _review_and_revise(
    stage: Callable[[str, str, str], str],
    packet: dict[str, object],
    sources: list[SourceReceipt],
    directory: Path,
    max_rounds: int,
) -> tuple[str, Path]:
    article = stage("refine", "refiner", "rewrite.md")
    candidate = directory / "rewrite.md"
    packet["review_schema"] = Review.model_json_schema()
    for revision in range(max_rounds + 1):
        packet["article"] = article
        packet["structural_issues"] = structural_issues(article, sources)
        review, issues = _read_review(stage, packet, article, sources, revision)
        atomic_write_json(
            directory / f"checks-{revision}.json",
            {"accepted": review.accepted and not issues, "issues": issues},
        )
        if review.accepted and not issues:
            return article, candidate
        if revision == max_rounds:
            break
        packet["critique"] = review.model_dump()
        packet["structural_issues"] = issues
        article = stage("revise", "refiner", f"revision-{revision + 1}.md")
        candidate = directory / f"revision-{revision + 1}.md"
    raise EditorialReviewError(
        "Article did not pass review within the revision limit; inspect saved drafts and critiques"
    )


def build_article(
    perspective: Perspective,
    workspace: Path,
    base: RouterConfig,
    *,
    paid_only: bool = False,
    receipt_dir: Path | None = None,
    retonr_executable: Path | None = None,
    progress: Callable[[str], None] | None = None,
) -> Path:
    """Read, ideate, plan, draft, independently rewrite, critique, revise and export.

    No publication or corpus promotion occurs. Every attempt has a new directory;
    interrupted work and failed reviews remain inspectable without being final.
    """
    routes, reason = select_routes(perspective, base, paid_only=paid_only)
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:12]
    directory = workspace / "runs" / run_id
    directory.mkdir(parents=True, exist_ok=False)
    tracker = EditorialTracker(
        WeeklyLedger(workspace / "budget.jsonl"),
        weekly_usd=perspective.budget.weekly_usd,
        per_run_usd=perspective.budget.per_run_usd,
        run_id=run_id,
    )
    manifest: dict[str, object] = {
        "schema_version": 1,
        "run_id": run_id,
        "status": "running",
        "started_at": datetime.now(UTC).isoformat(),
        "perspective_sha256": hashlib.sha256(perspective.model_dump_json().encode()).hexdigest(),
        "routing_reason": reason,
        "routes": {role: list(config.resolve("report")) for role, config in routes.items()},
        "budget": perspective.budget.model_dump(),
        "published": False,
    }
    atomic_write_json(directory / "manifest.json", manifest)
    try:
        if progress:
            progress("Capturing current publisher receipts")
        sources, failures = _capture(perspective, receipt_dir)
        save_receipts(directory / "receipts", sources)
        manifest["source_failures"] = failures
        manifest["source_count"] = len(sources)
        if not sources:
            raise EditorialReviewError(
                "No current source receipts were captured; no article was drafted"
            )
        packet: dict[str, object] = {
            "as_of": datetime.now(UTC).isoformat(),
            "lookback_days": perspective.sources.lookback_days,
            "topics": perspective.topics,
            "author": perspective.author.model_dump(),
            "target_words": perspective.target_words,
            "sources": evidence_packet(sources, perspective.sources.excerpt_chars),
            "capture_failures": failures,
            "previous_titles": _history(workspace),
        }
        # The private snapshot makes later review possible without depending on
        # a perspective file that may have changed after the run.
        atomic_write_json(directory / "brief.json", packet)

        def stage(name: str, role: str, filename: str) -> str:
            if progress:
                progress(name.replace("_", " ").capitalize())
            # The critic judges the actual article against receipts, without
            # anchoring on the writer's earlier reasoning or abandoned drafts.
            stage_packet = {
                key: value
                for key, value in packet.items()
                if name not in {"review", "repair_review"}
                or key not in {"reading", "ideas", "outline", "critique"}
            }
            prompt = (
                BASE
                + "\nTASK\n"
                + STAGES[name]
                + "\nDATA\n"
                + json.dumps(stage_packet, ensure_ascii=False)
            )
            response = call(
                routes[role],
                "report",
                prompt,
                max_tokens=8192,
                retries=0,
                call_type=f"editorial_{name}",
                ops_dir=str(directory / "telemetry"),
                run_id=run_id,
                usage_tracker=tracker,
            )
            result = response.text.strip()
            if not result or len(result) > 80000:
                raise EditorialReviewError(f"Invalid or oversized output from {name}")
            atomic_write_text(directory / filename, result + "\n")
            atomic_write_json(directory / "usage.json", tracker.summary_dict())
            if response.finish_reason and response.finish_reason != "stop":
                raise EditorialReviewError(
                    f"Incomplete {name} response; finish reason: {response.finish_reason}"
                )
            return result

        for name in ("reading", "ideas", "outline"):
            packet[name] = stage(name, "research", f"{name}.md")
        packet["article"] = stage("draft", "writer", "draft.md")
        original = directory / "draft.md"
        article, candidate = _review_and_revise(
            stage, packet, sources, directory, perspective.max_revision_rounds
        )
        if retonr_executable is not None:
            check_revision(retonr_executable, original, candidate, directory / "retonr.json")
        # Export to staging filenames, then expose the final pair only on success.
        from distill.library.article_export import export_article

        md_path = directory / "approved.md"
        atomic_write_text(md_path, article + "\n")
        docx_path = export_article(md_path)
        docx_path.replace(directory / "article.docx")
        md_path.replace(directory / "article.md")
        manifest["status"] = "ready_for_review"
        manifest["article_sha256"] = hashlib.sha256((article + "\n").encode()).hexdigest()
        return directory
    except BaseException as exc:
        manifest["status"] = "failed"
        manifest["error_type"] = type(exc).__name__
        # Do not persist provider error strings that might contain credentials.
        raise
    finally:
        manifest["finished_at"] = datetime.now(UTC).isoformat()
        manifest["cost_usd"] = tracker.total_cost
        atomic_write_json(directory / "usage.json", tracker.summary_dict())
        atomic_write_json(directory / "manifest.json", manifest)

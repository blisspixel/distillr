# pyright: strict
"""File Search store management for Gemini Deep Research grounding."""

from __future__ import annotations

import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict

from distill._console import console
from distill.config import DistillConfig
from distill.library.confined import list_confined_directories, read_confined_text
from distill.library.paths import find_artifact
from distill.pipeline.report._file_search_metadata import metadata_str, read_metadata
from distill.pipeline.report._file_search_upload import upload_documents

if TYPE_CHECKING:
    from google import genai

__all__ = [
    "cleanup_created_store",
    "cleanup_stores",
    "create_research_store",
    "delete_store",
    "gather_corpus_documents",
    "list_stores",
]

_INTERRUPTED_CLEANUP_NOTE = (
    "File Search store cleanup was interrupted while preserving the active error."
)
_MISSING_CLEANUP_IDENTITY_NOTE = (
    "File Search store cleanup could not recover the remote resource identity."
)
_MAX_CORPUS_ARTIFACT_BYTES = 4 * 1024 * 1024
_MAX_CORPUS_DIRECTORY_ENTRIES = 10_000


class _StoreRecord(TypedDict):
    name: str | None
    display_name: str


def _optional_str_attr(value: object, attr_name: str) -> str | None:
    attr_value = getattr(value, attr_name, None)
    return attr_value if isinstance(attr_value, str) and attr_value else None


def _str_attr(value: object, attr_name: str, default: str = "") -> str:
    return _optional_str_attr(value, attr_name) or default


def _display_safe(value: object) -> str:
    """Render console text safely for legacy Windows encodings."""
    text = str(value)
    encoding = sys.stdout.encoding or "utf-8"
    return text.encode(encoding, errors="replace").decode(encoding, errors="replace")


def _corpus_text(path: Path, config: DistillConfig) -> str | None:
    return read_confined_text(
        path,
        config.library_dir,
        max_bytes=_MAX_CORPUS_ARTIFACT_BYTES,
    )


def _corpus_directories(directory: Path, config: DistillConfig) -> list[Path]:
    directories = list_confined_directories(
        directory,
        config.library_dir,
        max_entries=_MAX_CORPUS_DIRECTORY_ENTRIES,
        max_directories=_MAX_CORPUS_DIRECTORY_ENTRIES,
    )
    return directories or []


def create_research_store(
    client: genai.Client,
    topic: str,
    config: DistillConfig,
    scope: str,
    channel_name: str | None,
) -> tuple[str, int]:
    """Create a File Search store and upload all relevant insights."""
    store = client.file_search_stores.create(
        config={"display_name": f"distill-{topic}-{scope}-{int(time.time())}"}
    )
    store_name = ""

    # Ownership starts immediately after the provider returns the resource id.
    # A normal return transfers cleanup to the caller. Every exceptional exit
    # attempts deletion first, including process-control interruptions.
    try:
        store_name = store.name or ""
        console.print(f"  [dim]Created store: {store_name}[/dim]")
        files = _gather_files(topic, config, scope, channel_name)
        if not files:
            console.print("[yellow]No files to upload to store[/yellow]")
            return store_name, 0

        console.print(f"  [cyan]Uploading {len(files)} documents to File Search store...[/cyan]")
        total = len(files)
        uploaded = upload_documents(
            client,
            store_name,
            files,
            progress_every=50,
            safe_display=_display_safe,
        )
        console.print(f"  [green]Indexed {uploaded}/{total} documents[/green]")
        return store_name, uploaded
    except BaseException as active_error:
        cleanup_created_store(
            client,
            store,
            store_name,
            delete_fn=delete_store,
            active_error=active_error,
        )
        raise


def cleanup_created_store(
    client: genai.Client,
    store: object,
    store_name: str,
    *,
    delete_fn: Callable[[genai.Client, str], None],
    active_error: BaseException | None,
) -> None:
    """Delete an acquired store without replacing an active terminal error."""
    if not store_name:
        try:
            recovered_name = getattr(store, "name", None)
        except BaseException:
            if active_error is None:
                raise
            active_error.add_note(_MISSING_CLEANUP_IDENTITY_NOTE)
            return
        store_name = recovered_name if isinstance(recovered_name, str) else ""
    if not store_name:
        if active_error is not None:
            active_error.add_note(_MISSING_CLEANUP_IDENTITY_NOTE)
        return
    try:
        delete_fn(client, store_name)
    except BaseException:
        if active_error is None:
            raise
        active_error.add_note(_INTERRUPTED_CLEANUP_NOTE)


def delete_store(client: genai.Client, store_name: str) -> None:
    """Delete a File Search store and all its contents."""
    try:
        client.file_search_stores.delete(name=store_name, config={"force": True})
        console.print(f"  [dim]Cleaned up store: {store_name}[/dim]")
    except Exception as exc:
        console.print(f"  [yellow]Store cleanup failed: {exc}[/yellow]")


def list_stores(client: genai.Client) -> list[_StoreRecord]:
    """List all File Search stores (for auditing/cleanup)."""
    stores: list[_StoreRecord] = []
    for store in client.file_search_stores.list():
        stores.append(
            {
                "name": _optional_str_attr(store, "name"),
                "display_name": _str_attr(store, "display_name", "(unnamed)"),
            }
        )
    return stores


def cleanup_stores(client: genai.Client, prefix: str = "distill") -> int:
    """Delete all File Search stores matching prefix. Returns count deleted."""
    deleted = 0
    for store in client.file_search_stores.list():
        display = _str_attr(store, "display_name")
        name = _optional_str_attr(store, "name")
        if display.startswith(prefix):
            if not name:
                console.print(f"  [yellow]Skipped unnamed File Search store: {display}[/yellow]")
                continue
            try:
                client.file_search_stores.delete(name=name, config={"force": True})
                console.print(f"  [dim]Deleted: {display} ({name})[/dim]")
                deleted += 1
            except Exception as exc:
                console.print(f"  [yellow]Failed to delete {name}: {exc}[/yellow]")
    return deleted


def _gather_files(  # noqa: C901 - legacy orchestration kept intact
    topic: str,
    config: DistillConfig,
    scope: str,
    channel_name: str | None,
) -> list[tuple[str, str]]:
    """Gather (label, content) pairs for documents to upload."""
    files: list[tuple[str, str]] = []
    max_doc_chars = 500_000

    if scope == "channel" and channel_name:
        channels: list[tuple[str, str]] = [(topic, channel_name)]
    elif scope == "topic":
        ch_dir = config.topic_dir(topic) / "channels"
        channels = [(topic, directory.name) for directory in _corpus_directories(ch_dir, config)]
    else:
        channels = []
        topics_root = config.topics_dir()
        for t_dir in _corpus_directories(topics_root, config):
            ch_dir = t_dir / "channels"
            channels.extend(
                (t_dir.name, directory.name) for directory in _corpus_directories(ch_dir, config)
            )

    for t, ch in channels:
        meta_parts: list[str] = []
        ctx_file = config.channel_dir(t, ch) / "channel_context.md"
        context_content = _corpus_text(ctx_file, config)
        if context_content is not None:
            meta_parts.append(f"# Channel Context: {ch}\n\n{context_content}")
        synth_file = find_artifact(
            config.channel_dir(t, ch),
            "synthesis",
            identity=f"{t}_{ch}",
        )
        synthesis_content = _corpus_text(synth_file, config)
        if synthesis_content is not None:
            meta_parts.append(f"# Channel Synthesis: {ch}\n\n{synthesis_content}")
        if meta_parts:
            files.append((f"channel-meta-{ch}", "\n\n---\n\n".join(meta_parts)))

        videos_dir = config.videos_dir(t, ch)
        video_count = 0
        current_bundle: list[str] = []
        current_chars = 0
        bundle_num = 1
        for vid_dir in _corpus_directories(videos_dir, config):
            insights_file = find_artifact(vid_dir, "insights")
            insights_content = _corpus_text(insights_file, config)
            if insights_content is None:
                continue
            meta_file = vid_dir / "metadata.json"
            title = vid_dir.name
            date = ""
            meta = read_metadata(meta_file, root=config.library_dir)
            if meta:
                title = metadata_str(meta, "title", vid_dir.name)
                date = metadata_str(meta, "upload_date")
            entry = f"\n\n---\n\n## [{date}] {title}\n\n{insights_content}"
            if current_chars + len(entry) > max_doc_chars and current_bundle:
                files.append(
                    (
                        f"{ch}-insights-part{bundle_num}",
                        f"# {ch} Video Insights (Part {bundle_num})\n" + "".join(current_bundle),
                    )
                )
                current_bundle = []
                current_chars = 0
                bundle_num += 1
            current_bundle.append(entry)
            current_chars += len(entry)
            video_count += 1
        if current_bundle:
            label = f"{ch}-insights" if bundle_num == 1 else f"{ch}-insights-part{bundle_num}"
            files.append(
                (label, f"# {ch} Video Insights (Part {bundle_num})\n" + "".join(current_bundle))
            )
        console.print(
            f"  [dim]{_display_safe(ch)}: {video_count} video insights in {bundle_num} document(s)[/dim]"
        )

    topics_for_sites: list[str] = []
    if scope == "topic":
        topics_for_sites = [topic]
    elif scope == "all":
        topics_for_sites = [
            directory.name for directory in _corpus_directories(config.topics_dir(), config)
        ]

    for site_topic in topics_for_sites:
        sites_dir = config.sites_dir(site_topic)
        for site_dir in _corpus_directories(sites_dir, config):
            synth_file = find_artifact(
                site_dir,
                "site_synthesis",
                identity=f"{site_topic}_{site_dir.name}",
            )
            synthesis_content = _corpus_text(synth_file, config)
            if synthesis_content is not None:
                files.append(
                    (
                        f"site-synthesis-{site_dir.name}",
                        f"# Site Synthesis: {site_dir.name}\n\n{synthesis_content}",
                    )
                )
            pages_dir = site_dir / "pages"
            bundle_parts: list[str] = []
            bundle_chars = 0
            bundle_num = 1
            for page_dir in _corpus_directories(pages_dir, config):
                insights_file = find_artifact(page_dir, "insights")
                metadata_file = page_dir / "metadata.json"
                insights_content = _corpus_text(insights_file, config)
                if insights_content is None:
                    continue
                title = page_dir.name
                url = ""
                meta = read_metadata(metadata_file, root=config.library_dir)
                if meta:
                    title = metadata_str(meta, "title", title)
                    url = metadata_str(meta, "url")
                entry = f"\n\n---\n\n## {title}\nURL: {url}\n\n{insights_content}"
                if bundle_chars + len(entry) > max_doc_chars and bundle_parts:
                    files.append(
                        (
                            f"{site_dir.name}-pages-part{bundle_num}",
                            f"# {site_dir.name} Page Insights (Part {bundle_num})\n"
                            + "".join(bundle_parts),
                        )
                    )
                    bundle_parts = []
                    bundle_chars = 0
                    bundle_num += 1
                bundle_parts.append(entry)
                bundle_chars += len(entry)
            if bundle_parts:
                label = (
                    f"{site_dir.name}-pages"
                    if bundle_num == 1
                    else f"{site_dir.name}-pages-part{bundle_num}"
                )
                files.append(
                    (
                        label,
                        f"# {site_dir.name} Page Insights (Part {bundle_num})\n"
                        + "".join(bundle_parts),
                    )
                )

    topics_for_papers: list[str] = []
    if scope == "topic":
        topics_for_papers = [topic]
    elif scope == "all":
        topics_for_papers = [
            directory.name for directory in _corpus_directories(config.topics_dir(), config)
        ]

    for paper_topic in topics_for_papers:
        papers_dir = config.papers_dir(paper_topic)
        bundle_parts: list[str] = []
        bundle_chars = 0
        bundle_num = 1
        for paper_dir in _corpus_directories(papers_dir, config):
            insights_file = find_artifact(paper_dir, "insights")
            metadata_file = paper_dir / "metadata.json"
            insights_content = _corpus_text(insights_file, config)
            if insights_content is None:
                continue
            title = paper_dir.name
            abs_url = ""
            meta = read_metadata(metadata_file, root=config.library_dir)
            if meta:
                title = metadata_str(meta, "title", title)
                abs_url = metadata_str(meta, "abs_url")
            entry = f"\n\n---\n\n## {title}\nURL: {abs_url}\n\n{insights_content}"
            if bundle_chars + len(entry) > max_doc_chars and bundle_parts:
                files.append(
                    (
                        f"{paper_topic}-papers-part{bundle_num}",
                        f"# {paper_topic} Paper Insights (Part {bundle_num})\n"
                        + "".join(bundle_parts),
                    )
                )
                bundle_parts = []
                bundle_chars = 0
                bundle_num += 1
            bundle_parts.append(entry)
            bundle_chars += len(entry)
        if bundle_parts:
            label = (
                f"{paper_topic}-papers"
                if bundle_num == 1
                else f"{paper_topic}-papers-part{bundle_num}"
            )
            files.append(
                (
                    label,
                    f"# {paper_topic} Paper Insights (Part {bundle_num})\n" + "".join(bundle_parts),
                )
            )

    if scope in ("topic", "all"):
        topics_to_check = (
            [topic]
            if scope == "topic"
            else [directory.name for directory in _corpus_directories(config.topics_dir(), config)]
        )
        for t in topics_to_check:
            topic_synth = find_artifact(config.topic_dir(t), "topic_synthesis", identity=t)
            topic_content = _corpus_text(topic_synth, config)
            if topic_content is not None:
                files.append(
                    (
                        f"topic-synthesis-{t}",
                        f"# Topic Synthesis: {t}\n\n{topic_content}",
                    )
                )
            paper_synth = find_artifact(config.topic_dir(t), "paper_synthesis", identity=t)
            paper_content = _corpus_text(paper_synth, config)
            if paper_content is not None:
                files.append(
                    (
                        f"paper-synthesis-{t}",
                        f"# Paper Synthesis: {t}\n\n{paper_content}",
                    )
                )
            corpus_synth = find_artifact(config.topic_dir(t), "corpus_synthesis", identity=t)
            corpus_content = _corpus_text(corpus_synth, config)
            if corpus_content is not None:
                files.append(
                    (
                        f"corpus-synthesis-{t}",
                        f"# Corpus Synthesis: {t}\n\n{corpus_content}",
                    )
                )

    return files


def gather_corpus_documents(
    topic: str,
    config: DistillConfig,
    scope: str = "topic",
    channel_name: str | None = None,
) -> list[tuple[str, str]]:
    """Gather bounded local corpus documents without creating remote resources."""

    return _gather_files(topic, config, scope, channel_name)

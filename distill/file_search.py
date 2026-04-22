"""File Search store management for Gemini Deep Research grounding."""

import contextlib
import json
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from google import genai
from rich.console import Console

from distill.config import DistillConfig

console = Console()


def _operation_ref(operation: Any) -> Any:
    """Normalize SDK operation objects to the identifier expected by client.operations.get."""
    return getattr(operation, "name", None) or getattr(operation, "id", None) or operation


def _display_safe(value: object) -> str:
    """Render console text safely for legacy Windows encodings."""
    text = str(value)
    encoding = sys.stdout.encoding or "utf-8"
    return text.encode(encoding, errors="replace").decode(encoding, errors="replace")


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
    store_name = store.name
    console.print(f"  [dim]Created store: {store_name}[/dim]")

    files = _gather_files(topic, config, scope, channel_name)
    if not files:
        console.print("[yellow]No files to upload to store[/yellow]")
        return store_name, 0

    console.print(f"  [cyan]Uploading {len(files)} documents to File Search store...[/cyan]")
    uploaded = 0
    pending_ops: list[Any] = []
    temp_paths: list[Path] = []
    total = len(files)

    try:
        for i, (label, content) in enumerate(files):
            tmp_path: Path | None = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="w", suffix=".md", delete=False, encoding="utf-8"
                ) as tmp:
                    tmp.write(content)
                    tmp_path = Path(tmp.name)
                temp_paths.append(tmp_path)

                op = client.file_search_stores.upload_to_file_search_store(
                    file=str(tmp_path),
                    file_search_store_name=store_name,
                    config={"display_name": label[:200], "mime_type": "text/markdown"},
                )
                pending_ops.append(_operation_ref(op))
                uploaded += 1
                if (i + 1) % 50 == 0 or (i + 1) == total:
                    console.print(f"  [dim]Uploaded {i + 1}/{total}...[/dim]")
            except Exception as exc:
                console.print(
                    f"  [yellow]Failed to upload {_display_safe(label[:50])}: {_display_safe(exc)}[/yellow]"
                )
                if tmp_path is not None:
                    with contextlib.suppress(ValueError):
                        temp_paths.remove(tmp_path)
                    with contextlib.suppress(Exception):
                        tmp_path.unlink(missing_ok=True)

        if pending_ops:
            console.print(f"  [dim]Waiting for indexing ({len(pending_ops)} docs)...[/dim]")
            wait_rounds = 0
            max_wait_rounds = 60
            while wait_rounds < max_wait_rounds:
                still_pending = []
                for op in pending_ops:
                    try:
                        refreshed = client.operations.get(op)
                        if refreshed.done is not True:
                            still_pending.append(_operation_ref(refreshed))
                    except Exception:
                        still_pending.append(op)
                if not still_pending:
                    break
                pending_ops = still_pending
                if wait_rounds % 6 == 0:
                    console.print(f"  [dim]Still indexing... {len(still_pending)} remaining[/dim]")
                time.sleep(5)
                wait_rounds += 1

            if wait_rounds >= max_wait_rounds:
                console.print(
                    f"  [yellow]Indexing timeout — {len(pending_ops)} docs may still be processing[/yellow]"
                )
    finally:
        for tmp_path in temp_paths:
            with contextlib.suppress(Exception):
                tmp_path.unlink(missing_ok=True)

    console.print(f"  [green]Indexed {uploaded}/{total} documents[/green]")
    return store_name, uploaded


def delete_store(client: genai.Client, store_name: str):
    """Delete a File Search store and all its contents."""
    try:
        client.file_search_stores.delete(name=store_name, config={"force": True})
        console.print(f"  [dim]Cleaned up store: {store_name}[/dim]")
    except Exception as exc:
        console.print(f"  [yellow]Store cleanup failed: {exc}[/yellow]")


def list_stores(client: genai.Client) -> list[dict]:
    """List all File Search stores (for auditing/cleanup)."""
    stores = []
    for store in client.file_search_stores.list():
        stores.append(
            {
                "name": store.name,
                "display_name": getattr(store, "display_name", None) or "(unnamed)",
            }
        )
    return stores


def cleanup_stores(client: genai.Client, prefix: str = "distill") -> int:
    """Delete all File Search stores matching prefix. Returns count deleted."""
    deleted = 0
    for store in client.file_search_stores.list():
        display = getattr(store, "display_name", "") or ""
        if display.startswith(prefix):
            try:
                client.file_search_stores.delete(name=store.name, config={"force": True})
                console.print(f"  [dim]Deleted: {display} ({store.name})[/dim]")
                deleted += 1
            except Exception as exc:
                console.print(f"  [yellow]Failed to delete {store.name}: {exc}[/yellow]")
    return deleted


def _gather_files(
    topic: str,
    config: DistillConfig,
    scope: str,
    channel_name: str | None,
) -> list[tuple[str, str]]:
    """Gather (label, content) pairs for documents to upload."""
    files: list[tuple[str, str]] = []
    max_doc_chars = 500_000

    if scope == "channel" and channel_name:
        channels = [(topic, channel_name)]
    elif scope == "topic":
        ch_dir = config.topic_dir(topic) / "channels"
        channels = (
            [(topic, d.name) for d in sorted(ch_dir.iterdir()) if d.is_dir()]
            if ch_dir.exists()
            else []
        )
    else:
        channels = []
        topics_root = config.topics_dir()
        if topics_root.exists():
            for t_dir in sorted(topics_root.iterdir()):
                if not t_dir.is_dir():
                    continue
                ch_dir = t_dir / "channels"
                if ch_dir.exists():
                    channels.extend(
                        (t_dir.name, d.name) for d in sorted(ch_dir.iterdir()) if d.is_dir()
                    )

    for t, ch in channels:
        meta_parts = []
        ctx_file = config.channel_dir(t, ch) / "channel_context.md"
        if ctx_file.exists():
            meta_parts.append(f"# Channel Context: {ch}\n\n{ctx_file.read_text(encoding='utf-8')}")
        synth_file = config.channel_dir(t, ch) / "synthesis.md"
        if synth_file.exists():
            meta_parts.append(
                f"# Channel Synthesis: {ch}\n\n{synth_file.read_text(encoding='utf-8')}"
            )
        if meta_parts:
            files.append((f"channel-meta-{ch}", "\n\n---\n\n".join(meta_parts)))

        videos_dir = config.videos_dir(t, ch)
        if not videos_dir.exists():
            continue
        video_count = 0
        current_bundle: list[str] = []
        current_chars = 0
        bundle_num = 1
        for vid_dir in sorted(videos_dir.iterdir()):
            if not vid_dir.is_dir():
                continue
            insights_file = vid_dir / "insights.md"
            if not insights_file.exists():
                continue
            meta_file = vid_dir / "metadata.json"
            title = vid_dir.name
            date = ""
            if meta_file.exists():
                try:
                    meta = json.loads(meta_file.read_text(encoding="utf-8"))
                    title = meta.get("title", vid_dir.name)
                    date = meta.get("upload_date", "")
                except (json.JSONDecodeError, OSError):
                    pass
            entry = f"\n\n---\n\n## [{date}] {title}\n\n{insights_file.read_text(encoding='utf-8')}"
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
    elif scope == "all" and config.topics_dir().exists():
        topics_for_sites = [
            t_dir.name for t_dir in sorted(config.topics_dir().iterdir()) if t_dir.is_dir()
        ]

    for site_topic in topics_for_sites:
        sites_dir = config.sites_dir(site_topic)
        if not sites_dir.exists():
            continue
        for site_dir in sorted(sites_dir.iterdir()):
            if not site_dir.is_dir():
                continue
            synth_file = site_dir / "synthesis.md"
            if synth_file.exists():
                files.append(
                    (
                        f"site-synthesis-{site_dir.name}",
                        f"# Site Synthesis: {site_dir.name}\n\n{synth_file.read_text(encoding='utf-8')}",
                    )
                )
            pages_dir = site_dir / "pages"
            if not pages_dir.exists():
                continue
            bundle_parts: list[str] = []
            bundle_chars = 0
            bundle_num = 1
            for page_dir in sorted(pages_dir.iterdir()):
                if not page_dir.is_dir():
                    continue
                insights_file = page_dir / "insights.md"
                metadata_file = page_dir / "metadata.json"
                if not insights_file.exists():
                    continue
                title = page_dir.name
                url = ""
                if metadata_file.exists():
                    try:
                        meta = json.loads(metadata_file.read_text(encoding="utf-8"))
                        title = meta.get("title", title)
                        url = meta.get("url", "")
                    except (json.JSONDecodeError, OSError):
                        pass
                entry = f"\n\n---\n\n## {title}\nURL: {url}\n\n{insights_file.read_text(encoding='utf-8')}"
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
    elif scope == "all" and config.topics_dir().exists():
        topics_for_papers = [
            t_dir.name for t_dir in sorted(config.topics_dir().iterdir()) if t_dir.is_dir()
        ]

    for paper_topic in topics_for_papers:
        papers_dir = config.papers_dir(paper_topic)
        if not papers_dir.exists():
            continue
        bundle_parts: list[str] = []
        bundle_chars = 0
        bundle_num = 1
        for paper_dir in sorted(papers_dir.iterdir()):
            if not paper_dir.is_dir():
                continue
            insights_file = paper_dir / "insights.md"
            metadata_file = paper_dir / "metadata.json"
            if not insights_file.exists():
                continue
            title = paper_dir.name
            abs_url = ""
            if metadata_file.exists():
                try:
                    meta = json.loads(metadata_file.read_text(encoding="utf-8"))
                    title = meta.get("title", title)
                    abs_url = meta.get("abs_url", "")
                except (json.JSONDecodeError, OSError):
                    pass
            entry = f"\n\n---\n\n## {title}\nURL: {abs_url}\n\n{insights_file.read_text(encoding='utf-8')}"
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
            else [t_dir.name for t_dir in sorted(config.topics_dir().iterdir()) if t_dir.is_dir()]
            if config.topics_dir().exists()
            else []
        )
        for t in topics_to_check:
            topic_synth = config.topic_dir(t) / "topic_synthesis.md"
            if topic_synth.exists():
                files.append(
                    (
                        f"topic-synthesis-{t}",
                        f"# Topic Synthesis: {t}\n\n{topic_synth.read_text(encoding='utf-8')}",
                    )
                )
            paper_synth = config.topic_dir(t) / "paper_synthesis.md"
            if paper_synth.exists():
                files.append(
                    (
                        f"paper-synthesis-{t}",
                        f"# Paper Synthesis: {t}\n\n{paper_synth.read_text(encoding='utf-8')}",
                    )
                )
            corpus_synth = config.topic_dir(t) / "corpus_synthesis.md"
            if corpus_synth.exists():
                files.append(
                    (
                        f"corpus-synthesis-{t}",
                        f"# Corpus Synthesis: {t}\n\n{corpus_synth.read_text(encoding='utf-8')}",
                    )
                )

    return files

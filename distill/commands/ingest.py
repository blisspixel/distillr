"""``distill ingest <target>`` — adaptive single-target ingestion entry point.

Routes by target. A local file path (PDF / Markdown / text / saved HTML) is
extracted and analyzed through the local-file pipeline; otherwise the target is
treated as a URL and dispatched by host to the appropriate hardened adapter
(today X / Twitter). Unknown hosts fall through with a clear message pointing at
the existing ``distill site`` / ``distill latest`` / ``distill paper`` commands.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

import typer
from rich.console import Console

from distill.commands._logic import get_config
from distill.ingestors.github import GitHubFetchError, parse_github_url
from distill.ingestors.local import LocalExtractionError
from distill.ingestors.x.syndication import parse_tweet_url
from distill.pipeline.analysis.local import ingest_local_file
from distill.pipeline.analysis.repo import ingest_repo
from distill.pipeline.analysis.tweet import ingest_tweet
from distill.pipeline.costs import CostTracker

__all__ = ["ingest_cmd", "register"]

console = Console()


def _host(url: str) -> str:
    return urlparse(url).netloc.lower().removeprefix("www.")


def ingest_cmd(
    url: str = typer.Argument(
        help="URL (x.com / twitter.com) or a local file path (.pdf / .md / .txt / .html)."
    ),
    topic: str = typer.Option("inbox", "--topic", "-t", help="Topic to file under"),
    no_transcribe: bool = typer.Option(
        False,
        "--no-transcribe",
        help="Skip Whisper transcription even if a video is attached.",
    ),
    no_analyze: bool = typer.Option(
        False,
        "--no-analyze",
        help="Skip insight extraction (just capture raw + transcript).",
    ),
):
    """Ingest a single URL or local file into the library, picking the right adapter."""
    config = get_config()
    tracker = CostTracker()

    # Local file path takes precedence: if the target exists on disk, ingest it
    # through the local-file pipeline rather than treating it as a URL.
    local_path = Path(url).expanduser()
    if local_path.is_file():
        _ingest_local(local_path, topic, config, tracker, analyze=not no_analyze)
        return

    host = _host(url)
    if host in {"x.com", "twitter.com", "mobile.twitter.com"}:
        _ingest_tweet_url(
            url, topic, config, tracker, transcribe=not no_transcribe, analyze=not no_analyze
        )
        return
    if host == "github.com":
        _ingest_github(url, topic, config, tracker, analyze=not no_analyze)
        return

    console.print(
        f"[yellow]No dedicated adapter for host {host!r} yet.[/yellow] "
        "Use `distill site` for arbitrary websites, `distill latest`/`distill video` "
        "for YouTube, or `distill paper` for arXiv."
    )
    raise typer.Exit(2)


def _spend_line(tracker: CostTracker) -> None:
    console.print(f"\n  [dim]LLM spend: {tracker.format_cost()}[/dim]")


def _ingest_local(local_path: Path, topic: str, config, tracker: CostTracker, *, analyze: bool):
    try:
        local = ingest_local_file(
            local_path, topic=topic, config=config, analyze=analyze, tracker=tracker
        )
    except LocalExtractionError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(2) from None
    console.print("")
    console.print(
        f"  [green]Document[/green]  "
        f"{local.document_path.relative_to(config.library_dir)} [dim]({local.kind})[/dim]"
    )
    if local.insights_path:
        console.print(
            f"  [green]Insights[/green]  {local.insights_path.relative_to(config.library_dir)}"
        )
    _spend_line(tracker)


def _ingest_tweet_url(
    url: str, topic: str, config, tracker: CostTracker, *, transcribe: bool, analyze: bool
):
    if not parse_tweet_url(url):
        console.print(
            f"[red]Could not parse a tweet id from {url!r}.[/red] "
            "Expected something like https://x.com/<user>/status/<id>."
        )
        raise typer.Exit(2)
    result = ingest_tweet(
        url, topic=topic, config=config, transcribe=transcribe, analyze=analyze, tracker=tracker
    )
    console.print("")
    console.print(
        f"  [green]Tweet[/green]      {result.tweet_path.relative_to(config.library_dir)}"
    )
    if result.transcript_path:
        console.print(
            f"  [green]Transcript[/green] "
            f"{result.transcript_path.relative_to(config.library_dir)} "
            f"({len(result.transcript_text.split())} words)"
        )
    if result.insights_path:
        console.print(
            f"  [green]Insights[/green]   {result.insights_path.relative_to(config.library_dir)}"
        )
    for note in result.skipped_reasons:
        console.print(f"  [yellow]skipped[/yellow]    {note}")
    _spend_line(tracker)


def _ingest_github(url: str, topic: str, config, tracker: CostTracker, *, analyze: bool):
    if parse_github_url(url) is None:
        console.print(
            f"[red]Could not parse an owner/repo from {url!r}.[/red] "
            "Expected something like https://github.com/<owner>/<repo>."
        )
        raise typer.Exit(2)
    try:
        result = ingest_repo(url, topic=topic, config=config, analyze=analyze, tracker=tracker)
    except GitHubFetchError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(2) from None
    console.print("")
    console.print(
        f"  [green]Repo[/green]      "
        f"{result.repo_path.relative_to(config.library_dir)} "
        f"[dim]({result.record.stars:,} stars)[/dim]"
    )
    if result.insights_path:
        console.print(
            f"  [green]Insights[/green]  {result.insights_path.relative_to(config.library_dir)}"
        )
    for note in result.skipped_reasons:
        console.print(f"  [yellow]skipped[/yellow]    {note}")
    _spend_line(tracker)


def register(app: typer.Typer) -> None:
    """Register ``ingest`` on the given app."""
    app.command(name="ingest", rich_help_panel="Discover")(ingest_cmd)

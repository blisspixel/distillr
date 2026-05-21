"""``distill ingest <url>`` — adaptive single-URL ingestion entry point.

Detects the source type from the URL host and dispatches to the
appropriate hardened adapter. Today this routes X (Twitter) posts to
the new X adapter; unknown hosts fall through with a clear message
pointing at the existing ``distill site`` / ``distill latest`` /
``distill paper`` commands. This is the seed of the unified
``distill ingest`` surface the 0.9 roadmap milestone scopes for local
files — the dispatcher pattern is identical for URL vs. path.
"""

from __future__ import annotations

from urllib.parse import urlparse

import typer
from rich.console import Console

from distill.commands._logic import get_config
from distill.ingestors.x.syndication import parse_tweet_url
from distill.pipeline.analysis.tweet import ingest_tweet
from distill.pipeline.costs import CostTracker

__all__ = ["ingest_cmd", "register"]

console = Console()


def _host(url: str) -> str:
    return urlparse(url).netloc.lower().removeprefix("www.")


def ingest_cmd(
    url: str = typer.Argument(help="URL to ingest. Currently supports x.com / twitter.com."),
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
    """Ingest a single URL into the library, picking the right adapter by host."""
    config = get_config()
    host = _host(url)
    tracker = CostTracker()

    if host in {"x.com", "twitter.com", "mobile.twitter.com"}:
        tweet_id = parse_tweet_url(url)
        if not tweet_id:
            console.print(
                f"[red]Could not parse a tweet id from {url!r}.[/red] "
                "Expected something like https://x.com/<user>/status/<id>."
            )
            raise typer.Exit(2)
        result = ingest_tweet(
            url,
            topic=topic,
            config=config,
            transcribe=not no_transcribe,
            analyze=not no_analyze,
            tracker=tracker,
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
        console.print(f"\n  [dim]LLM spend: {tracker.format_cost()}[/dim]")
        return

    console.print(
        f"[yellow]No dedicated adapter for host {host!r} yet.[/yellow] "
        "Use `distill site` for arbitrary websites, `distill latest`/`distill video` "
        "for YouTube, or `distill paper` for arXiv."
    )
    raise typer.Exit(2)


def register(app: typer.Typer) -> None:
    """Register ``ingest`` on the given app."""
    app.command(name="ingest", rich_help_panel="Discover")(ingest_cmd)

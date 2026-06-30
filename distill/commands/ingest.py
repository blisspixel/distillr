# pyright: strict
"""``distill ingest <target>`` -- adaptive single-target ingestion entry point.

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

from distill._console import console
from distill.commands._helpers import budgeted_cost_tracker, get_config
from distill.config import DistillConfig
from distill.ingestors.github import GitHubFetchError, parse_github_url
from distill.ingestors.local import LocalExtractionError
from distill.ingestors.podcasts import PodcastFetchError, fetch_feed, looks_like_feed_url
from distill.ingestors.x.syndication import parse_tweet_url
from distill.pipeline.analysis.local import ingest_local_file
from distill.pipeline.analysis.media import ingest_media_file, is_media_file
from distill.pipeline.analysis.newsletter import feed_is_newsletter, ingest_newsletter
from distill.pipeline.analysis.podcast import ingest_podcast
from distill.pipeline.analysis.repo import ingest_repo
from distill.pipeline.analysis.tweet import ingest_tweet
from distill.pipeline.costs import CostTracker

__all__ = ["ingest_cmd", "register"]


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
    rss: bool = typer.Option(
        False,
        "--rss",
        help="Treat the URL as a podcast RSS feed (auto-detected for .rss/.xml/feed paths).",
    ),
    episodes: int = typer.Option(
        1,
        "--episodes",
        help="For podcast feeds: how many of the latest episodes to ingest (default 1).",
    ),
) -> None:
    """Ingest a single URL or local file into the library, picking the right adapter.

    Examples:
      distill ingest https://github.com/example/project --topic repos
      distill ingest private/research.pdf --topic papers
      distill ingest https://example.com/feed.xml --rss --episodes 3 --topic feeds
    """
    config = get_config()
    tracker = budgeted_cost_tracker(config, "ingest")

    # Local file path takes precedence: if the target exists on disk, ingest it
    # through the media pipeline (audio/video -> transcript -> insight) or the
    # local-document pipeline, rather than treating it as a URL.
    local_path = Path(url).expanduser()
    if local_path.is_file():
        if is_media_file(local_path):
            _ingest_media(local_path, topic, config, tracker, analyze=not no_analyze)
        else:
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
    if rss or looks_like_feed_url(url):
        _ingest_feed(
            url,
            topic,
            config,
            tracker,
            episodes=episodes,
            transcribe=not no_transcribe,
            analyze=not no_analyze,
        )
        return

    console.print(
        f"[yellow]No dedicated adapter for host {host!r} yet.[/yellow] "
        "Use `distill site` for arbitrary websites, `distill latest`/`distill video` "
        "for YouTube, `distill paper` for arXiv, or pass --rss for a podcast feed."
    )
    raise typer.Exit(2)


def _spend_line(tracker: CostTracker) -> None:
    console.print(f"\n  [dim]LLM spend: {tracker.format_cost()}[/dim]")


def _ingest_local(
    local_path: Path, topic: str, config: DistillConfig, tracker: CostTracker, *, analyze: bool
) -> None:
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
    url: str,
    topic: str,
    config: DistillConfig,
    tracker: CostTracker,
    *,
    transcribe: bool,
    analyze: bool,
) -> None:
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


def _ingest_media(
    local_path: Path, topic: str, config: DistillConfig, tracker: CostTracker, *, analyze: bool
) -> None:
    result = ingest_media_file(
        local_path, topic=topic, config=config, analyze=analyze, tracker=tracker
    )
    console.print("")
    if result.transcript_path:
        console.print(
            f"  [green]Transcript[/green] {result.transcript_path.relative_to(config.library_dir)}"
        )
    if result.insights_path:
        console.print(
            f"  [green]Insights[/green]   {result.insights_path.relative_to(config.library_dir)}"
        )
    for note in result.skipped_reasons:
        console.print(f"  [yellow]skipped[/yellow]    {note}")
    _spend_line(tracker)


def _ingest_feed(
    url: str,
    topic: str,
    config: DistillConfig,
    tracker: CostTracker,
    *,
    episodes: int,
    transcribe: bool,
    analyze: bool,
) -> None:
    """One fetch, then route: enclosures mean a podcast, post bodies a newsletter."""
    try:
        feed = fetch_feed(url)
        if feed_is_newsletter(feed):
            nl = ingest_newsletter(
                url,
                topic=topic,
                config=config,
                posts=episodes,
                analyze=analyze,
                tracker=tracker,
                feed=feed,
            )
            console.print("")
            console.print(f"  [green]Publication[/green] {nl.feed_title}")
            for path in nl.content_paths:
                console.print(
                    f"  [green]Post[/green]        {path.relative_to(config.library_dir)}"
                )
            for path in nl.insight_paths:
                console.print(
                    f"  [green]Insights[/green]    {path.relative_to(config.library_dir)}"
                )
            for note in nl.skipped_reasons:
                console.print(f"  [yellow]skipped[/yellow]      {note}")
            _spend_line(tracker)
            return
        result = ingest_podcast(
            url,
            topic=topic,
            config=config,
            episodes=episodes,
            transcribe=transcribe,
            analyze=analyze,
            tracker=tracker,
            feed=feed,
        )
    except PodcastFetchError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(2) from None
    console.print("")
    console.print(f"  [green]Show[/green]      {result.feed_title}")
    for path in result.episode_paths:
        console.print(f"  [green]Episode[/green]   {path.relative_to(config.library_dir)}")
    for path in result.insight_paths:
        console.print(f"  [green]Insights[/green]  {path.relative_to(config.library_dir)}")
    for note in result.skipped_reasons:
        console.print(f"  [yellow]skipped[/yellow]    {note}")
    _spend_line(tracker)


def _ingest_github(
    url: str, topic: str, config: DistillConfig, tracker: CostTracker, *, analyze: bool
) -> None:
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

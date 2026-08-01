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
from rich.markup import escape

from distill._console import console
from distill.commands._helpers import (
    budgeted_cost_tracker,
    get_config,
    set_command_cost_metadata,
)
from distill.commands._json import ExitCode, exit_with_refusal
from distill.config import DistillConfig
from distill.ingestors.github import GitHubFetchError, parse_github_url
from distill.ingestors.local import LocalExtractionError
from distill.ingestors.net import url_for_diagnostic
from distill.ingestors.podcasts import (
    PodcastFetchError,
    fetch_feed,
    looks_like_feed_url,
    select_feed_episode,
)
from distill.ingestors.x.syndication import parse_tweet_url
from distill.pipeline.analysis.local import ingest_local_file
from distill.pipeline.analysis.media import ingest_media_file, is_media_file
from distill.pipeline.analysis.newsletter import feed_is_newsletter, ingest_newsletter
from distill.pipeline.analysis.podcast import ingest_podcast
from distill.pipeline.analysis.repo import ingest_repo
from distill.pipeline.analysis.tweet import ingest_tweet
from distill.pipeline.costs import CostTracker, save_run_log
from distill.target_safety import is_http_url, require_local_filesystem_target

__all__ = ["ingest_cmd", "register"]


def _host(url: str) -> str:
    try:
        host = urlparse(url).hostname or ""
    except (UnicodeError, ValueError):
        return ""
    return host.casefold().rstrip(".").removeprefix("www.")


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
    force: bool = typer.Option(
        False,
        "--force",
        help="Reanalyze an unchanged completed X post instead of reusing its artifacts.",
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
    episode_id: str = typer.Option(
        "",
        "--episode-id",
        help="Ingest one exact feed item identity emitted by profile preview.",
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
    source_type = "unknown"

    try:
        try:
            require_local_filesystem_target(url)
        except ValueError as exc:
            console.print(f"[red]Invalid target: {exc}.[/red]")
            raise typer.Exit(2) from None

        # Local file path takes precedence: if the target exists on disk, ingest it
        # through the media pipeline (audio/video -> transcript -> insight) or the
        # local-document pipeline, rather than treating it as a URL.
        local_path = None if is_http_url(url) else Path(url).expanduser()
        if local_path is not None and local_path.is_file():
            if is_media_file(local_path):
                source_type = "media"
                set_command_cost_metadata(tracker, topic=topic, source_type=source_type)
                _ingest_media(local_path, topic, config, tracker, analyze=not no_analyze)
            else:
                source_type = "local"
                set_command_cost_metadata(tracker, topic=topic, source_type=source_type)
                _ingest_local(local_path, topic, config, tracker, analyze=not no_analyze)
            return

        if local_path is not None:
            exit_with_refusal(
                f"Local file not found: {local_path.name}",
                code=ExitCode.NOT_FOUND,
                reason="not_found",
                action="ingest",
                limit={"kind": "local_file", "name": local_path.name},
            )

        host = _host(url)
        if host in {"x.com", "twitter.com", "mobile.twitter.com"}:
            source_type = "x"
            set_command_cost_metadata(tracker, topic=topic, source_type=source_type)
            if force:
                _ingest_tweet_url(
                    url,
                    topic,
                    config,
                    tracker,
                    transcribe=not no_transcribe,
                    analyze=not no_analyze,
                    force=True,
                )
            else:
                _ingest_tweet_url(
                    url,
                    topic,
                    config,
                    tracker,
                    transcribe=not no_transcribe,
                    analyze=not no_analyze,
                )
            return
        if host == "github.com":
            source_type = "github"
            set_command_cost_metadata(tracker, topic=topic, source_type=source_type)
            _ingest_github(url, topic, config, tracker, analyze=not no_analyze)
            return
        if rss or looks_like_feed_url(url):
            source_type = "feed"
            set_command_cost_metadata(tracker, topic=topic, source_type=source_type)
            _ingest_feed(
                url,
                topic,
                config,
                tracker,
                episodes=episodes,
                episode_id=episode_id,
                transcribe=not no_transcribe,
                analyze=not no_analyze,
            )
            return

        console.print(
            f"[yellow]No dedicated adapter for host {escape(host)!r} yet.[/yellow] "
            "Use `distill site` for arbitrary websites, `distill latest`/`distill video` "
            "for YouTube, `distill paper` for arXiv, or pass --rss for a podcast feed."
        )
        raise typer.Exit(2)
    finally:
        _save_ingest_cost(config, tracker, topic=topic, source_type=source_type)


def _save_ingest_cost(
    config: DistillConfig,
    tracker: CostTracker,
    *,
    topic: str,
    source_type: str,
) -> None:
    """Persist every recorded ingest usage row, including zero-dollar local work."""
    if getattr(tracker, "budget_failure_logged", False):
        return
    if not (tracker.entries or tracker.gemini_queries or tracker.transcriptions):
        return
    save_run_log(
        config.library_dir,
        "ingest",
        tracker,
        metadata={"topic": topic, "workflow": "ingest", "source_type": source_type},
    )


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
    force: bool = False,
) -> None:
    if not parse_tweet_url(url):
        displayed_url = escape(url_for_diagnostic(url))
        console.print(
            f"[red]Could not parse a tweet id from {displayed_url}.[/red] "
            "Expected something like https://x.com/<user>/status/<id>."
        )
        raise typer.Exit(2)
    result = ingest_tweet(
        url,
        topic=topic,
        config=config,
        transcribe=transcribe,
        analyze=analyze,
        tracker=tracker,
        force=force,
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
    episode_id: str = "",
) -> None:
    """One fetch, then route: enclosures mean a podcast, post bodies a newsletter."""
    try:
        feed = fetch_feed(url)
        if episode_id:
            feed = select_feed_episode(url, feed, episode_id)
            episodes = 1
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
        console.print(f"[red]{escape(str(exc))}[/red]")
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
        displayed_url = escape(url_for_diagnostic(url))
        console.print(
            f"[red]Could not parse an owner/repo from {displayed_url}.[/red] "
            "Expected something like https://github.com/<owner>/<repo>."
        )
        raise typer.Exit(2)
    try:
        result = ingest_repo(url, topic=topic, config=config, analyze=analyze, tracker=tracker)
    except GitHubFetchError as exc:
        console.print(f"[red]{escape(str(exc))}[/red]")
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

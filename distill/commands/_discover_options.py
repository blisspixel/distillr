# pyright: strict
from __future__ import annotations

import typer

GOAL_ARGUMENT = typer.Argument(
    "",
    help='Research goal, e.g. "help an AI compose great music". Omit if using --goal-file.',
)

GOAL_FILE_OPTION = typer.Option(
    None,
    "--goal-file",
    help="Path to a markdown file whose contents become the goal. Enables reusable, "
    "goal-driven topic refreshes. Overrides the positional argument if both are provided.",
)

PAPERS_ONLY_OPTION = typer.Option(
    False,
    "--papers-only",
    help="Skip videos entirely (equivalent to --video-limit 0). Use when the topic "
    "has thin or unrigorous YouTube coverage and you only want academic sources.",
)

VIDEOS_ONLY_OPTION = typer.Option(
    False,
    "--videos-only",
    help="Skip papers entirely (equivalent to --paper-limit 0). Use when the topic "
    "is better covered by talks/lectures than by formal papers.",
)

DAYS_OPTION = typer.Option(
    365,
    "--days",
    "-d",
    help="YouTube recency window in days (default: 365)",
)

SHORTS_OPTION = typer.Option(
    False,
    "--shorts/--no-shorts",
    help="Include short-form videos under 3 minutes",
)

INGEST_ATTACHMENTS_OPTION = typer.Option(
    False,
    "--ingest-attachments",
    help="For selected site seeds, pull PDF text and supported embedded video transcripts into the page corpus",
)

FROM_GAPS_OPTION = typer.Option(
    False,
    "--from-gaps",
    help="Derive the goal from an existing topic's coverage gaps (requires --topic). "
    "Turns research_gaps into auto-generated discover queries.",
)

RIGOR_OPTION = typer.Option(
    "balanced",
    "--rigor",
    help="Quality bar for the reranked shortlist: strict | balanced | loose. "
    "Drops candidates whose rerank score is below the level's threshold.",
)

LENS_OPTION = typer.Option(
    "",
    "--lens",
    help="Analysis lens for per-source insights: research | practitioner | competitive | "
    "academic | general. Default: general; the goal still shapes analysis. Persisted as the "
    "topic's intent so later ingests inherit it.",
)

VERIFY_OPTION = typer.Option(
    "",
    "--verify",
    help="Claim-grounding mode for this run: warn | strict | off "
    "(default: the DISTILL_VERIFY setting, else warn).",
)

PREVIEW_OPTION = typer.Option(
    False,
    "--preview",
    help="Show the goal-ranked plan without ingesting",
)

FROM_PREVIEW_OPTION = typer.Option(
    "",
    "--from-preview",
    help="Replay and ingest the exact set saved by an earlier --preview run, by its id. "
    "Skips query-generation and the rerank, so you commit to precisely what you saw.",
)

SIZE_OPTION = typer.Option(
    False,
    "--size",
    help="Force the size-then-approve menu (excellent / good / everything, each with its "
    "spend) even on a topic that already has artifacts. On a fresh topic this is the default.",
)

SITE_SEEDS_OPTION = typer.Option(
    None,
    "--site-seeds",
    help="Optional JSON/TXT seed file of curated website URLs to include in the goal-aware rerank",
)

TRUSTED_SITE_OPTION = typer.Option(
    None,
    "--trusted-site",
    help="Trusted domain or section URL to enumerate website page candidates from. May repeat.",
)

SITE_LIMIT_OPTION = typer.Option(
    10,
    "--site-limit",
    help="Max website seeds to ingest when --site-seeds or --trusted-site is provided (default: 10)",
)

SITE_CRAWL_DEPTH_OPTION = typer.Option(
    0,
    "--site-crawl-depth",
    help="For selected website candidates, follow this many link hops. Default 0 keeps exact-page ingest.",
)

SITE_CRAWL_PAGES_OPTION = typer.Option(
    1,
    "--site-crawl-pages",
    help="Max pages to crawl per selected website candidate when --site-crawl-depth is above 0.",
)

SITE_CRAWL_PREFIX_OPTION = typer.Option(
    "",
    "--crawl-prefix",
    help="When crawling, only follow same-host links under this path prefix.",
)

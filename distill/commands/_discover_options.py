from __future__ import annotations

import typer

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

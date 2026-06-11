"""GitHub repository ingestion (REST API; no auth required, token optional)."""

from distill.ingestors.github.fetch import (
    GitHubFetchError,
    RepoRecord,
    fetch_repo,
    parse_github_url,
)

__all__ = ["GitHubFetchError", "RepoRecord", "fetch_repo", "parse_github_url"]

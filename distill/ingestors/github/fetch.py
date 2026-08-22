"""Fetch a GitHub repository's primary-source material via the public REST API.

Adapter-contract capture: deterministic function of public input (same repo ->
same bytes modulo upstream changes), no login walls, no scraping. Three GET
requests against the fixed ``https://api.github.com`` base -- repo metadata,
README, recent releases -- through :func:`safe_urlopen` (scheme validation,
retry/backoff). Unauthenticated works at low rate; a ``GITHUB_TOKEN`` env var
lifts the limit when present, and is never required.
"""

from __future__ import annotations

import base64
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

from distill.ingestors.net import NetworkError, safe_urlopen
from distill.parsing import parse_ascii_uint, strict_json_loads

__all__ = ["GitHubFetchError", "RepoRecord", "fetch_repo", "parse_github_url"]

_API_BASE = "https://api.github.com"
_MAX_README_CHARS = 60_000
_MAX_RELEASE_BODY_CHARS = 2_000
_MAX_RESPONSE_BYTES = 2_000_000

# github.com/<owner>/<repo>, tolerating a trailing path (/tree/main, .git, ...).
# Owner/repo segment rules per GitHub: alphanumeric plus - . _ (repo) and
# alphanumeric plus - (owner). Reserved top-level paths are rejected.
_OWNER_RE = r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?"
_REPO_RE = r"[A-Za-z0-9._-]+"
_RESERVED_OWNERS = frozenset(
    {"orgs", "topics", "collections", "trending", "marketplace", "sponsors", "settings", "apps"}
)


class GitHubFetchError(RuntimeError):
    """A repo could not be fetched (bad URL, missing repo, rate limit, network)."""


@dataclass(frozen=True)
class RepoRecord:
    """Everything captured about one repository, ready for artifact emission."""

    full_name: str  # "owner/repo"
    url: str  # html_url
    description: str
    stars: int
    forks: int
    open_issues: int
    language: str
    license_name: str
    topics: list[str] = field(default_factory=list)
    created_at: str = ""
    pushed_at: str = ""
    archived: bool = False
    default_branch: str = ""
    readme: str = ""
    releases: list[dict] = field(default_factory=list)  # {tag, name, published_at, body}

    def metadata_block(self) -> str:
        """Render the verifiable facts as a compact block for prompts/artifacts."""
        lines = [
            f"- Stars: {self.stars:,} | Forks: {self.forks:,} | Open issues: {self.open_issues:,}",
            f"- Language: {self.language or 'unspecified'} | License: {self.license_name or 'none stated'}",
            f"- Created: {self.created_at[:10]} | Last push: {self.pushed_at[:10]}"
            f" | Archived: {'yes' if self.archived else 'no'}",
        ]
        if self.topics:
            lines.append(f"- Topics: {', '.join(self.topics[:15])}")
        return "\n".join(lines)

    def releases_block(self) -> str:
        lines = []
        for r in self.releases:
            head = f"### {r.get('tag', '')} {r.get('name', '')}".strip()
            lines.append(f"{head} ({str(r.get('published_at', ''))[:10]})")
            body = (r.get("body") or "").strip()
            if body:
                lines.append(body)
            lines.append("")
        return "\n".join(lines).strip()


def parse_github_url(url: str) -> tuple[str, str] | None:
    """Extract ``(owner, repo)`` from a github.com URL, or ``None``.

    Accepts plain repo URLs and deep links (``/tree/...``, ``/blob/...``);
    rejects gists, reserved top-level paths, and anything not github.com.
    """
    parsed = urllib.parse.urlparse(url if "://" in url else f"https://{url}")
    if parsed.username or parsed.password:
        return None
    host = (parsed.hostname or "").lower().removeprefix("www.")
    if host != "github.com":
        return None
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) < 2:
        return None
    owner, repo = parts[0], parts[1]
    repo = repo.removesuffix(".git")
    if owner.lower() in _RESERVED_OWNERS:
        return None
    if not re.fullmatch(_OWNER_RE, owner) or not re.fullmatch(_REPO_RE, repo):
        return None
    return owner, repo


def _json_uint(value: object) -> int:
    """Parse a non-negative GitHub count without crashing on malformed JSON."""

    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value if value >= 0 else 0
    if isinstance(value, str):
        parsed = parse_ascii_uint(value)
        return parsed if parsed is not None else 0
    return 0


def _get_json(path: str) -> dict | list:
    """GET an api.github.com path and parse JSON, with optional token auth."""
    request = urllib.request.Request(
        f"{_API_BASE}{path}",
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "distillr",
            "X-GitHub-Api-Version": "2022-11-28",
            **(
                {"Authorization": f"Bearer {token}"}
                if (token := os.environ.get("GITHUB_TOKEN", "").strip())
                else {}
            ),
        },
    )
    try:
        with safe_urlopen(request, timeout=30) as resp:
            raw = resp.read(_MAX_RESPONSE_BYTES)
    except NetworkError as exc:
        # safe_urlopen wraps every failure (including HTTP status errors) in
        # NetworkError, carrying the original status code when there was one.
        if exc.status_code == 404:
            raise GitHubFetchError(f"Not found on GitHub: {path}") from exc
        if exc.status_code in {403, 429}:
            raise GitHubFetchError(
                "GitHub API rate limit hit. Set GITHUB_TOKEN to lift it, or retry later."
            ) from exc
        if exc.status_code:
            raise GitHubFetchError(f"GitHub API error {exc.status_code} for {path}") from exc
        raise GitHubFetchError(f"Network error fetching {path}: {exc}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        # Raw read-time errors that escape safe_urlopen's retry wrapper.
        raise GitHubFetchError(f"Network error fetching {path}: {exc}") from exc
    try:
        loaded = strict_json_loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, RecursionError, ValueError) as exc:
        raise GitHubFetchError(f"GitHub returned unparseable JSON for {path}") from exc
    if not isinstance(loaded, (dict, list)):
        raise GitHubFetchError(f"GitHub returned unparseable JSON for {path}")
    return loaded


def fetch_repo(owner: str, repo: str) -> RepoRecord:
    """Fetch metadata + README + recent releases for one repository."""
    meta = _get_json(f"/repos/{owner}/{repo}")
    if not isinstance(meta, dict):
        raise GitHubFetchError(f"Unexpected metadata shape for {owner}/{repo}")

    readme = ""
    try:
        readme_data = _get_json(f"/repos/{owner}/{repo}/readme")
        if isinstance(readme_data, dict) and readme_data.get("content"):
            readme = base64.b64decode(readme_data["content"]).decode("utf-8", errors="replace")
    except GitHubFetchError:
        readme = ""  # a repo without a README is unusual but legal; capture what exists

    releases: list[dict] = []
    try:
        releases_data = _get_json(f"/repos/{owner}/{repo}/releases?per_page=5")
        if isinstance(releases_data, list):
            releases = [
                {
                    "tag": str(r.get("tag_name", "")),
                    "name": str(r.get("name", "") or ""),
                    "published_at": str(r.get("published_at", "") or ""),
                    "body": str(r.get("body", "") or "")[:_MAX_RELEASE_BODY_CHARS],
                }
                for r in releases_data
                if isinstance(r, dict)
            ]
    except GitHubFetchError:
        releases = []  # releases are optional signal, never fatal

    license_info = meta.get("license") or {}
    return RepoRecord(
        full_name=str(meta.get("full_name", f"{owner}/{repo}")),
        url=str(meta.get("html_url", f"https://github.com/{owner}/{repo}")),
        description=str(meta.get("description", "") or ""),
        stars=_json_uint(meta.get("stargazers_count")),
        forks=_json_uint(meta.get("forks_count")),
        open_issues=_json_uint(meta.get("open_issues_count")),
        language=str(meta.get("language", "") or ""),
        license_name=str(license_info.get("spdx_id", "") or "")
        if isinstance(license_info, dict)
        else "",
        topics=[str(t) for t in (meta.get("topics") or []) if isinstance(t, str)],
        created_at=str(meta.get("created_at", "") or ""),
        pushed_at=str(meta.get("pushed_at", "") or ""),
        archived=bool(meta.get("archived", False)),
        default_branch=str(meta.get("default_branch", "") or ""),
        readme=readme[:_MAX_README_CHARS],
        releases=releases,
    )

"""The prompt-version registry: single source of truth for ``prompt_id`` floors.

Every artifact's frontmatter records the ``prompt_id`` that produced it
(invariant 4). Stale-detection compares that recorded id against the *current*
version of the same prompt family -- and the comparison is only trustworthy if
the floor table cannot drift from what the writers actually stamp. So both
sides import from here: writers stamp ``PROMPT_IDS[family]``, and the audit's
staleness pass reads the same dict. Bumping a prompt version is a one-line
change in this file.

Family naming: everything before the trailing ``.vN`` (``analysis.podcast``,
``synthesis.paper``, ``ask``). 1.0 formalizes the policy: prompts are
versioned, not frozen -- the id is the only required stability.
"""

# pyright: strict

from __future__ import annotations

import re

from distill.parsing import parse_ascii_uint

__all__ = ["PROMPT_IDS", "current_version", "parse_prompt_id"]

PROMPT_IDS: dict[str, str] = {
    # Per-source analysis
    "analysis.local": "analysis.local.v1",
    "analysis.media": "analysis.media.v1",
    "analysis.podcast": "analysis.podcast.v1",
    "analysis.github_repo": "analysis.github_repo.v1",
    "analysis.newsletter": "analysis.newsletter.v1",
    "analysis.x_tweet": "analysis.x_tweet.v1",
    "analysis.paper": "analysis.paper.v3",
    # Synthesis
    "synthesis.paper": "synthesis.paper.v3",
    "synthesis.site": "synthesis.site.v1",
    "synthesis.site_topic": "synthesis.site_topic.v1",
    "synthesis.corpus": "synthesis.corpus.v1",
    "synthesis.channel": "synthesis.channel.v1",
    "synthesis.topic": "synthesis.topic.v1",
    # Knowledge layers
    "claims.extract": "claims.extract.v1",
    "claims.synthesis": "claims.synthesis.v3",
    "concepts.extract": "concepts.extract.v1",
    # Reports / briefs / answers
    "report.dossier": "report.dossier.v1",
    "report.accordion": "report.accordion.v1",
    "report.deep_research": "report.deep_research.v1",
    "brief.topic": "brief.topic.v1",
    "ask": "ask.v1",
}

_MAX_PROMPT_ID_CHARS = 256
_PROMPT_ID_RE = re.compile(
    r"^(?P<family>[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*)\.v"
    r"(?P<version>[1-9][0-9]{0,3})$"
)


def parse_prompt_id(prompt_id: str) -> tuple[str, int] | None:
    """Split ``"analysis.podcast.v1"`` into ``("analysis.podcast", 1)``; ``None`` if unparseable."""
    normalized = prompt_id.strip()
    if len(normalized) > _MAX_PROMPT_ID_CHARS:
        return None
    match = _PROMPT_ID_RE.fullmatch(normalized)
    if not match:
        return None
    version = parse_ascii_uint(match.group("version"))
    return (match.group("family"), version) if version is not None else None


def current_version(family: str) -> int | None:
    """The registry's current version number for *family*, or ``None`` if unknown."""
    current = PROMPT_IDS.get(family)
    if current is None:
        return None
    parsed = parse_prompt_id(current)
    return parsed[1] if parsed else None

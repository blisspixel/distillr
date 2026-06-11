"""Prompt templates for GitHub repository analysis."""

from __future__ import annotations

from distill.prompts.shared import UNTRUSTED_CONTENT_RULES

__all__ = ["repo_insight_prompt"]


def repo_insight_prompt(
    *,
    full_name: str,
    url: str,
    description: str,
    metadata_block: str,
    readme: str,
    releases_block: str = "",
) -> str:
    """Single-pass extraction prompt for a GitHub repository.

    For any OSS tool the repo itself is the primary source -- not the
    marketing page. The structured value distill adds over concatenation
    tools (Repomix, Gitingest) is the insight shape: what it is, how mature
    it is, when to use it, and what its own README admits it can't do.
    """
    releases_section = f"\n\nRECENT RELEASES:\n{releases_block}" if releases_block else ""

    return f"""You are extracting intelligence from a GitHub repository for a
research corpus. Treat the repository's own statements as primary source
material and produce a structured insights document grounded only in what
the metadata, README, and release notes actually say.

SECURITY: {UNTRUSTED_CONTENT_RULES}

REPOSITORY: {full_name}
URL: {url}
DESCRIPTION: {description}

METADATA:
{metadata_block}

README:
{readme}{releases_section}

Generate a structured insight document with these sections:

## Summary
2-3 sentences: what this project is, who it is for, and the single most
load-bearing claim it makes about itself.

## What It Does & How
The core capabilities and the architecture/approach as the README describes
them. Capture any enumerated feature lists, pipelines, or design principles
in full. Preserve exact names of components, commands, formats, and
protocols.

## Maturity & Activity Signals
Ground these in the metadata and releases only: stars/forks, license, age,
last push, release cadence and latest version, archived/active status, and
anything the README says about stability, roadmap, or production readiness.
Numbers must come from the data above -- never estimate.

## When To Use It (and when not)
The use cases the project claims, stated prerequisites/dependencies, and the
alternatives or non-goals the README itself names. Mark anything that is the
author's positioning rather than verifiable fact.

## Limits, Risks & Open Questions
What the README admits it cannot do, known issues called out in release
notes, missing pieces a researcher should check (no tests mentioned? no
license? single maintainer?), and claims made without evidence.

## Underlying Sources Referenced
Papers, specs, other repositories, or products the README points at, each
with whatever identifying detail was given.

## Confidence
One short paragraph: how much of this document rests on verifiable metadata
versus the project's self-description.

Ground every claim in the provided material. Do not browse, do not infer
beyond it, and do not import outside knowledge about this project."""

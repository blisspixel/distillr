"""Model editorial verdicts with exact receipt and artifact checks."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import Field

from distill.editorial.perspective import EditorialModel, Text
from distill.editorial.sources import SourceReceipt

# Literal output policy, not a semantic writing-quality classifier.
_EMOJI = re.compile("[\U0001f000-\U0001faff\u2600-\u27bf\ufe0f\u20e3]")
LINK = re.compile(r"\[([^\]\n]+)\]\((https://[^\s)]+)\)")


class Verdict(EditorialModel):
    verdict: Literal["pass", "revise", "abstain"]
    reason: Text


class ClaimEvidence(EditorialModel):
    claim: Text
    source_id: str
    quote: Text


class Review(EditorialModel):
    grounding: Verdict
    freshness: Verdict
    perspective: Verdict
    usefulness: Verdict
    structure: Verdict
    style: Verdict
    coverage: Verdict
    claims: list[ClaimEvidence] = Field(min_length=1, max_length=50)
    revision_instructions: str = Field(max_length=12000)

    @property
    def accepted(self) -> bool:
        return all(
            getattr(self, name).verdict == "pass"
            for name in (
                "grounding",
                "freshness",
                "perspective",
                "usefulness",
                "structure",
                "style",
                "coverage",
            )
        )


def structural_issues(article: str, sources: list[SourceReceipt]) -> list[str]:
    issues = []
    if not article.startswith("# ") or len(re.findall(r"^# ", article, flags=re.M)) != 1:
        issues.append("Use exactly one opening Markdown H1 title.")
    if any(
        re.search(r"[^\w\s]", heading) for heading in re.findall(r"^#{1,3} (.+)$", article, re.M)
    ):
        issues.append(
            "Use descriptive words, numbers and spaces in titles and headings, without punctuation."
        )
    if "\u2014" in article or _EMOJI.search(article):
        issues.append("Remove em dashes and emoji characters.")
    urls = {source.url for source in sources}
    links = LINK.findall(article)
    if not links:
        issues.append("Add inline Markdown links to the captured sources.")
    if any(url not in urls for _, url in links):
        issues.append("Cite only exact captured source URLs.")
    if "```" in article or re.search(r"^\s*(?:<|\||!\[)", article, flags=re.M):
        issues.append(
            "Use prose, headings, lists and inline links, without HTML, tables, images or fences."
        )
    return issues


def verify_review(review: Review, article: str, sources: list[SourceReceipt]) -> list[str]:
    issues = structural_issues(article, sources)
    receipts = {source.id: source for source in sources}
    for claim in review.claims:
        source = receipts.get(claim.source_id)
        if claim.claim not in article:
            issues.append("Reviewer claim must be an exact substring of the article.")
        if source is None or claim.quote not in source.text:
            issues.append(
                "Reviewer evidence must be an exact substring of its named source receipt."
            )
        elif source.url not in {url for _, url in LINK.findall(article)}:
            issues.append("The article must link the source used for a checked claim.")
    return list(dict.fromkeys(issues))

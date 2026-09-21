# pyright: strict
"""Typed capture outcomes for site crawling.

A crawl that only returns the pages it managed to read cannot tell an operator
why the other URLs are missing. "The page genuinely has no text", "the renderer
never finished", and "the site refused automated access" are different facts,
and a corpus that verifies claims against receipts has to keep them apart. Every
URL a crawl visits therefore leaves either a page or a :class:`CaptureFailure`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Any, Final, cast

from distill.ingestors.net import url_for_persistence

__all__ = [
    "CAPTURE_FAILURE_DETAIL_CHARS",
    "CAPTURE_OUTCOMES",
    "WHOLE_CRAWL_OUTCOMES",
    "CaptureFailure",
    "capture_failure_from_worker",
    "summarize_capture_failures",
]

# Ordered by how far the capture got before it stopped.
CAPTURE_OUTCOMES: Final = (
    # Navigation raised or timed out; nothing was rendered.
    "navigation-failed",
    # The page loaded but the bounded extractor could not evaluate.
    "extraction-failed",
    # The page rendered with no usable body text.
    "empty",
    # The landing URL left the seed's allowed scope after redirects.
    "out-of-scope",
    # The crawl stopped at its wall-clock, memory, or worker boundary.
    "budget-exhausted",
    # The worker produced output the parent refused to trust.
    "worker-failed",
)

# Outcomes that stop the whole crawl rather than describe one page. A crawl that
# ends at its resource boundary, or whose worker produced untrusted output, did
# not finish the work it was asked to do, so the run is genuinely partial. A
# single page that would not load is a recorded fact about that page, not a
# failed run, and must not flip an otherwise clean crawl's outcome.
WHOLE_CRAWL_OUTCOMES: Final = frozenset({"budget-exhausted", "worker-failed"})

CAPTURE_FAILURE_DETAIL_CHARS: Final = 500
_MAX_URL_CHARS: Final = 2_048

# Browser exception text routinely quotes the URL it was navigating to, and that
# URL can carry a session token in its query. Find URL-shaped runs so they can be
# reduced to the same scheme/host/path view every other persisted URL gets.
_URL_IN_TEXT = re.compile(r"https?://[^\s\"'<>)\]]+")


@dataclass(frozen=True)
class CaptureFailure:
    """One URL a crawl visited but could not turn into a page."""

    url: str
    outcome: str
    detail: str = ""
    status: int = 0
    depth: int = 0

    def __post_init__(self) -> None:
        if self.outcome not in CAPTURE_OUTCOMES:
            raise ValueError(f"unknown capture outcome: {self.outcome}")

    @property
    def stopped_the_crawl(self) -> bool:
        """Whether this outcome ended the crawl rather than described one page."""
        return self.outcome in WHOLE_CRAWL_OUTCOMES

    def redacted(self) -> CaptureFailure:
        """Return this failure with every URL reduced to its persistence view.

        A crawl can follow a link whose query carries a session token, and
        browser exception text quotes the URL it was navigating to. Receipts are
        written to the manifest and the run summary, so they cross the same
        persistence boundary as every other stored URL and get the same
        treatment: scheme, host, explicit port, and path only.
        """
        return replace(
            self,
            url=url_for_persistence(self.url) if self.url else "",
            detail=_URL_IN_TEXT.sub(
                lambda match: url_for_persistence(match.group(0)),
                self.detail,
            )[:CAPTURE_FAILURE_DETAIL_CHARS],
        )

    def metadata(self) -> dict[str, Any]:
        """Render as a manifest row. ``status`` is omitted when unknown."""
        row: dict[str, Any] = {
            "url": self.url,
            "outcome": self.outcome,
            "depth": self.depth,
        }
        if self.detail:
            row["detail"] = self.detail
        if self.status:
            row["status"] = self.status
        return row


def capture_failure_from_worker(row: object) -> CaptureFailure:
    """Parse one untrusted worker failure row into a :class:`CaptureFailure`."""
    if not isinstance(row, dict):
        raise ValueError("browser worker returned a malformed capture failure")
    raw = cast("dict[object, object]", row)
    typed: dict[str, object] = {str(key): value for key, value in raw.items()}
    url: object = typed.get("url", "")
    outcome: object = typed.get("outcome", "")
    detail: object = typed.get("detail", "")
    status: object = typed.get("status", 0)
    depth: object = typed.get("depth", 0)
    if not isinstance(url, str) or len(url) > _MAX_URL_CHARS:
        raise ValueError("browser worker returned an invalid capture failure url")
    if not isinstance(outcome, str) or outcome not in CAPTURE_OUTCOMES:
        raise ValueError("browser worker returned an invalid capture outcome")
    if not isinstance(detail, str) or len(detail) > CAPTURE_FAILURE_DETAIL_CHARS:
        raise ValueError("browser worker returned an invalid capture failure detail")
    if isinstance(status, bool) or not isinstance(status, int) or not 0 <= status <= 599:
        raise ValueError("browser worker returned an invalid capture failure status")
    if isinstance(depth, bool) or not isinstance(depth, int) or not 0 <= depth <= 4:
        raise ValueError("browser worker returned an invalid capture failure depth")
    return CaptureFailure(url=url, outcome=outcome, detail=detail, status=status, depth=depth)


def summarize_capture_failures(failures: list[CaptureFailure]) -> dict[str, int]:
    """Count failures by outcome, for manifests and console rollups."""
    counts: dict[str, int] = {}
    for failure in failures:
        counts[failure.outcome] = counts.get(failure.outcome, 0) + 1
    return dict(sorted(counts.items()))

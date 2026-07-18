# pyright: strict
"""Shared public-HTTPS request guard for browser ingestion contexts."""

from __future__ import annotations

import urllib.parse
from dataclasses import dataclass
from typing import Any

from distill.ingestors import net

__all__ = ["BrowserRequestBudget", "install_public_web_route"]

_ALLOWED_RESOURCE_TYPES = frozenset({"document", "fetch", "script", "stylesheet", "xhr"})
_MAX_BROWSER_URL_CHARS = 8_192


@dataclass
class BrowserRequestBudget:
    """Per-navigation outbound request ceiling for an untrusted page."""

    max_requests: int = 128
    consumed: int = 0

    def reset(self) -> None:
        self.consumed = 0

    def consume(self) -> bool:
        if self.consumed >= self.max_requests:
            return False
        self.consumed += 1
        return True


def install_public_web_route(context: Any) -> BrowserRequestBudget:
    """Abort unsafe, unnecessary, or over-budget browser requests."""

    budget = BrowserRequestBudget()

    def guard(route: Any, request: Any) -> None:
        url = request.url
        resource_type = getattr(request, "resource_type", "document")
        if (
            isinstance(url, str)
            and len(url) <= _MAX_BROWSER_URL_CHARS
            and resource_type in _ALLOWED_RESOURCE_TYPES
            and budget.consume()
            and urllib.parse.urlparse(url).scheme.lower() == "https"
            and net.is_public_web_url(url)
        ):
            route.continue_()
            return
        route.abort()

    context.route("**/*", guard)
    return budget

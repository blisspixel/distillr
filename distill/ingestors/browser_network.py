# pyright: strict
"""Shared public-HTTPS request guard for browser ingestion contexts."""

from __future__ import annotations

import urllib.parse
from typing import Any

from distill.ingestors import net

__all__ = ["install_public_web_route"]


def install_public_web_route(context: Any) -> None:
    """Abort browser requests unless they target a public HTTPS address."""

    def guard(route: Any, request: Any) -> None:
        url = request.url
        if (
            isinstance(url, str)
            and urllib.parse.urlparse(url).scheme.lower() == "https"
            and net.is_public_web_url(url)
        ):
            route.continue_()
            return
        route.abort()

    context.route("**/*", guard)

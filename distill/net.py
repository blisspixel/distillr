"""Small shared networking utilities used across ingestion modules.

Centralizes URL-scheme validation for the ``urllib.request.urlopen`` calls
scattered across the codebase, so every open goes through a single checked
entry point. Callers should still only pass URLs built from trusted bases
(e.g. the arXiv API endpoint, a hard-coded YouTube search URL constructor).
"""

from __future__ import annotations

import urllib.parse
import urllib.request

_ALLOWED_SCHEMES = frozenset({"https"})


def safe_urlopen(url_or_request: str | urllib.request.Request, timeout: int = 30):
    """Open an HTTP(S) URL or prepared ``Request`` after scheme validation.

    Raises ``ValueError`` on any scheme other than ``https``. Mitigates the
    implicit risk that ``urllib.request.urlopen`` will happily open ``file://``,
    ``ftp://``, or custom schemes if a caller accidentally constructs one.
    """
    target_url = (
        url_or_request.full_url
        if isinstance(url_or_request, urllib.request.Request)
        else url_or_request
    )
    parsed = urllib.parse.urlparse(target_url)
    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise ValueError(f"Refusing to open URL with scheme {parsed.scheme!r}: {target_url}")
    # Scheme validated immediately above; nosec silences bandit B310 for this
    # single trusted entry point.
    return urllib.request.urlopen(url_or_request, timeout=timeout)  # nosec B310

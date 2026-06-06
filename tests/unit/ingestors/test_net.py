"""Tests for distill.ingestors.net SSRF guards."""

from __future__ import annotations

import pytest

from distill.ingestors.net import is_public_web_url, safe_urlopen


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1/",  # loopback
        "https://169.254.169.254/latest/meta-data/",  # cloud metadata (link-local)
        "http://localhost/",  # loopback name
        "https://10.0.0.5/",  # RFC1918
        "https://192.168.1.1/",  # RFC1918
        "file:///etc/passwd",  # non-http scheme
        "gopher://x/",  # non-http scheme
    ],
)
def test_is_public_web_url_rejects_internal_and_nonhttp(url: str) -> None:
    assert is_public_web_url(url) is False


def test_safe_urlopen_refuses_non_public_target() -> None:
    # Even with an allowed (https) scheme, a host resolving to a non-public IP
    # must be refused before any connection.
    with pytest.raises(ValueError, match="non-public"):
        safe_urlopen("https://127.0.0.1/")
    with pytest.raises(ValueError, match="non-public"):
        safe_urlopen("https://169.254.169.254/x")


def test_safe_urlopen_refuses_nonhttps_scheme() -> None:
    with pytest.raises(ValueError, match="scheme"):
        safe_urlopen("http://example.com/")

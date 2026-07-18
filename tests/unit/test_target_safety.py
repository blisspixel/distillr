from __future__ import annotations

import pytest

from distill.target_safety import (
    is_http_url,
    is_remote_filesystem_path,
    require_local_filesystem_target,
)


@pytest.mark.parametrize(
    "value",
    [
        r"\\attacker.invalid\share\payload.md",
        r"//attacker.invalid/share/payload.md",
        r"\\?\UNC\attacker.invalid\share\payload.md",
        r"\\.\PIPE\attacker",
    ],
)
def test_remote_filesystem_forms_are_rejected_without_io(value: str) -> None:
    assert is_remote_filesystem_path(value)
    with pytest.raises(ValueError, match="remote filesystem"):
        require_local_filesystem_target(value)


@pytest.mark.parametrize(
    "value",
    [
        "notes/report.md",
        r"C:\Users\example\report.md",
        "https://example.com/report.md",
    ],
)
def test_local_paths_and_http_urls_remain_supported(value: str) -> None:
    assert not is_remote_filesystem_path(value)
    require_local_filesystem_target(value)


def test_http_url_classification_is_scheme_exact() -> None:
    assert is_http_url("https://example.com")
    assert is_http_url("HTTP://example.com")
    assert not is_http_url("https-example.com")
    assert not is_http_url(r"C:\https\example.txt")


def test_null_byte_is_rejected_before_path_io() -> None:
    with pytest.raises(ValueError, match="null byte"):
        require_local_filesystem_target("report.md\x00https://example.com")

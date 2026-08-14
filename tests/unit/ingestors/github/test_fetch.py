"""Tests for distill.ingestors.github.fetch (URL parsing + REST capture)."""

from __future__ import annotations

import base64
import io
import json

import pytest

from distill.ingestors.github import fetch as fetch_mod
from distill.ingestors.github import fetch_repo, parse_github_url
from distill.ingestors.net import NetworkError


class TestParseGitHubUrl:
    @pytest.mark.parametrize(
        "url",
        [
            "https://github.com/blisspixel/distillr",
            "https://www.github.com/blisspixel/distillr",
            "github.com/blisspixel/distillr",
            "https://github.com/blisspixel/distillr.git",
            "https://github.com/blisspixel/distillr/tree/main/docs",
        ],
    )
    def test_accepts_repo_url_shapes(self, url):
        assert parse_github_url(url) == ("blisspixel", "distillr")

    @pytest.mark.parametrize(
        "url",
        [
            "https://gist.github.com/karpathy/442a6bf",
            "https://github.com/blisspixel",  # owner only
            "https://github.com/orgs/anthropics/repositories",  # reserved path
            "https://example.com/blisspixel/distillr",
            "https://github.com/bad owner/repo",
        ],
    )
    def test_rejects_non_repo_urls(self, url):
        assert parse_github_url(url) is None


class _FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _fake_api(monkeypatch, responses: dict[str, object]):
    """Map api path suffixes to JSON payloads (or HTTP status codes).

    Status codes surface as ``NetworkError`` carrying ``status_code`` — the way
    the real ``safe_urlopen`` wraps every HTTP/network failure. (It never lets a
    raw ``urllib.error.HTTPError`` escape, so mocking that would test a path that
    cannot occur in production.)
    """

    def fake_urlopen(request, timeout=30):
        path = request.full_url.removeprefix("https://api.github.com")
        for suffix, payload in responses.items():
            if path == suffix:
                if isinstance(payload, int):
                    raise NetworkError(f"HTTP {payload} from {path}: err", status_code=payload)
                return _FakeResponse(json.dumps(payload).encode("utf-8"))
        raise NetworkError(f"HTTP 404 from {path}: not found", status_code=404)

    monkeypatch.setattr(fetch_mod, "safe_urlopen", fake_urlopen)


_META = {
    "full_name": "o/r",
    "html_url": "https://github.com/o/r",
    "description": "A tool",
    "stargazers_count": 1234,
    "forks_count": 56,
    "open_issues_count": 7,
    "language": "Python",
    "license": {"spdx_id": "MIT"},
    "topics": ["ai", "research"],
    "created_at": "2025-01-02T00:00:00Z",
    "pushed_at": "2026-06-10T00:00:00Z",
    "archived": False,
    "default_branch": "main",
}


class TestFetchRepo:
    def test_happy_path_assembles_record(self, monkeypatch):
        readme_b64 = base64.b64encode(b"# Title\n\nDoes 3 things.").decode()
        _fake_api(
            monkeypatch,
            {
                "/repos/o/r": _META,
                "/repos/o/r/readme": {"content": readme_b64},
                "/repos/o/r/releases?per_page=5": [
                    {
                        "tag_name": "v1.0",
                        "name": "First",
                        "published_at": "2026-01-01T00:00:00Z",
                        "body": "notes",
                    }
                ],
            },
        )

        record = fetch_repo("o", "r")

        assert record.full_name == "o/r"
        assert record.stars == 1234
        assert record.license_name == "MIT"
        assert "Does 3 things" in record.readme
        assert record.releases[0]["tag"] == "v1.0"
        assert "Stars: 1,234" in record.metadata_block()
        assert "v1.0 First" in record.releases_block()

    def test_missing_readme_and_releases_are_not_fatal(self, monkeypatch):
        _fake_api(monkeypatch, {"/repos/o/r": _META, "/repos/o/r/readme": 404})
        record = fetch_repo("o", "r")
        assert record.readme == ""
        assert record.releases == []

    def test_missing_repo_raises_clean_error(self, monkeypatch):
        _fake_api(monkeypatch, {"/repos/o/r": 404})
        with pytest.raises(fetch_mod.GitHubFetchError, match="Not found"):
            fetch_repo("o", "r")

    def test_rate_limit_suggests_token(self, monkeypatch):
        _fake_api(monkeypatch, {"/repos/o/r": 403})
        with pytest.raises(fetch_mod.GitHubFetchError, match="GITHUB_TOKEN"):
            fetch_repo("o", "r")

    def test_token_header_attached_when_env_set(self, monkeypatch):
        seen = {}

        def fake_urlopen(request, timeout=30):
            seen["auth"] = request.headers.get("Authorization", "")
            return _FakeResponse(json.dumps(_META).encode("utf-8"))

        monkeypatch.setattr(fetch_mod, "safe_urlopen", fake_urlopen)
        monkeypatch.setenv("GITHUB_TOKEN", "tok123")
        fetch_repo("o", "r")
        assert seen["auth"] == "Bearer tok123"

    def test_malformed_counts_do_not_crash(self, monkeypatch):
        meta = dict(_META)
        meta["stargazers_count"] = "1,234"
        meta["forks_count"] = True
        meta["open_issues_count"] = -3
        _fake_api(monkeypatch, {"/repos/o/r": meta})

        record = fetch_repo("o", "r")

        assert record.stars == 0
        assert record.forks == 0
        assert record.open_issues == 0

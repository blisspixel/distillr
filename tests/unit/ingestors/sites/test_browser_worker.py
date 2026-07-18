from __future__ import annotations

import io
import json
import sys
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

import pytest

from distill.ingestors.sites import _browser_worker as worker
from distill.ingestors.sites.scraper import SitePage, SiteSeed


def _seed() -> SiteSeed:
    return SiteSeed(
        url="https://example.com/docs",
        topic="web",
        max_depth=0,
        max_pages=1,
    )


def test_browser_worker_writes_bounded_structured_result(monkeypatch, tmp_path: Path) -> None:
    input_path = tmp_path / "seed.json"
    output_path = tmp_path / "pages.json"
    input_path.write_text(json.dumps(asdict(_seed())), encoding="utf-8")
    page = SitePage(
        url="https://example.com/docs",
        title="Docs",
        site_name="example.com",
        page_type="page",
        text="body",
    )
    monkeypatch.setattr(worker, "crawl_site_in_browser_worker", lambda seed: [page])
    monkeypatch.setattr(sys, "argv", ["worker", str(input_path), str(output_path)])
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(buffer=io.BytesIO(b"1")))

    assert worker.main() == 0
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert payload["pages"][0]["title"] == "Docs"


def test_browser_worker_requires_control_handshake(monkeypatch, tmp_path: Path) -> None:
    input_path = tmp_path / "seed.json"
    input_path.write_text(json.dumps(asdict(_seed())), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["worker", str(input_path), str(tmp_path / "out.json")])
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(buffer=io.BytesIO(b"0")))
    monkeypatch.setattr(
        worker,
        "crawl_site_in_browser_worker",
        lambda seed: pytest.fail("crawl must not start without handshake"),
    )

    assert worker.main() == 3


def test_browser_worker_rejects_seed_schema_expansion() -> None:
    payload = asdict(_seed())
    payload["unexpected"] = "value"

    with pytest.raises(ValueError, match="fields"):
        worker._seed_from_payload(payload)


def test_browser_worker_enforces_result_byte_limit(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(worker, "BROWSER_WORKER_RESULT_BYTES", 8)

    with pytest.raises(ValueError, match="byte limit"):
        worker._write_result(tmp_path / "out.json", [{"text": "too large"}])

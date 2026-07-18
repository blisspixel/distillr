from __future__ import annotations

import pytest
import typer

from distill.commands import discover


def test_explicit_website_ramp_rejects_unc_before_path_probe(monkeypatch) -> None:
    monkeypatch.setattr(
        discover.Path,
        "exists",
        lambda _path: (_ for _ in ()).throw(AssertionError("remote target reached filesystem I/O")),
    )

    with pytest.raises(typer.BadParameter, match="remote filesystem"):
        discover.ramp_up(
            target=r"\\attacker.invalid\share\seeds.txt",
            topic="",
            source="website",
            report=False,
            days=14,
            limit=10,
            seed_only=True,
            scrape_only=False,
            ingest_attachments=False,
            test=False,
        )

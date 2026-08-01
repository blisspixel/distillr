"""Render docs/assets/cli-papers-demo.html to a README screenshot PNG.

Usage (repo root):
  python docs/assets/render_cli_demo.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
HTML = HERE / "cli-papers-demo.html"
OUT = HERE / "cli-papers-demo.png"


def main() -> None:
    uri = HTML.as_uri()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(
            viewport={"width": 980, "height": 820},
            device_scale_factor=2,
        )
        page.goto(uri, wait_until="networkidle")
        page.locator("#terminal").screenshot(path=str(OUT), omit_background=True)
        browser.close()
    sys.stdout.write(f"wrote {OUT} ({OUT.stat().st_size} bytes)\n")


if __name__ == "__main__":
    main()

"""Distill local web server — read-only dashboard over the file-based library."""

import threading
import webbrowser
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from distill.cli_shared import duration_str, format_date, strip_frontmatter
from distill.config import DistillConfig
from distill.pipeline.dashboard_data import format_run_timestamp

WEB_DIR = Path(__file__).parent


def create_app(config: DistillConfig) -> FastAPI:
    app = FastAPI(title="Distill", docs_url=None, redoc_url=None)
    app.state.config = config

    app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")

    templates = Jinja2Templates(directory=WEB_DIR / "templates")

    # Register template filters.
    #
    # Artifact bodies are derived from untrusted ingested sources (a malicious
    # page or transcript could carry raw HTML, or an LLM could echo an injected
    # ``<script>`` into an insight). Templates render this through ``|markdown|
    # safe``, so the rendered HTML MUST be sanitized first -- otherwise it is a
    # stored-XSS vector in the dashboard. Sanitize the rendered output with nh3
    # (allowlist), per Python-Markdown's own guidance to sanitize output rather
    # than trust the renderer. If a sanitizer or renderer is unavailable, fail
    # safe by escaping everything.
    def _escape_all(text: str) -> str:
        escaped = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        return f"<pre>{escaped}</pre>"

    try:
        import markdown as md_lib
        import nh3

        def md_filter(text: str) -> str:
            html = md_lib.markdown(text, extensions=["tables", "fenced_code"])
            return nh3.clean(html)

    except ImportError:
        md_filter = _escape_all

    templates.env.filters["markdown"] = md_filter
    templates.env.filters["format_date"] = format_date
    templates.env.filters["duration"] = duration_str
    templates.env.filters["format_timestamp"] = format_run_timestamp
    templates.env.filters["strip_frontmatter"] = strip_frontmatter

    app.state.templates = templates

    from distill.web.routes import channels, costs, dashboard, topics, videos, watchlist

    app.include_router(dashboard.router)
    app.include_router(topics.router)
    app.include_router(channels.router)
    app.include_router(videos.router)
    app.include_router(costs.router)
    app.include_router(watchlist.router)

    return app


def run_server(config: DistillConfig, host: str, port: int, open_browser: bool):
    app = create_app(config)
    if open_browser:
        threading.Timer(1.0, lambda: webbrowser.open(f"http://{host}:{port}")).start()
    uvicorn.run(app, host=host, port=port, log_level="warning")

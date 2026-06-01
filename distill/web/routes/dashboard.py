"""Dashboard route — main overview page."""

from fastapi import APIRouter, Request

from distill.pipeline.dashboard_data import dashboard_snapshot

router = APIRouter()


@router.get("/")
async def index(request: Request):
    config = request.app.state.config
    templates = request.app.state.templates
    snapshot = dashboard_snapshot(config)

    from importlib.metadata import version

    ver = "dev"
    for dist in ("distillr", "distill"):
        try:
            found = version(dist)
        except Exception:  # never let version lookup 500 the dashboard
            continue
        if found:
            ver = found
            break

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {"request": request, "version": ver, **snapshot},
    )

"""Dashboard route — main overview page."""

from fastapi import APIRouter, Request

from distill.dashboard_data import dashboard_snapshot

router = APIRouter()


@router.get("/")
async def index(request: Request):
    config = request.app.state.config
    templates = request.app.state.templates
    snapshot = dashboard_snapshot(config)

    try:
        from importlib.metadata import version

        ver = version("distill")
    except Exception:
        ver = "dev"

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {"request": request, "version": ver, **snapshot},
    )

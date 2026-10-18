# pyright: strict
"""Read theme data and accept explicitly selected local theme files."""

from __future__ import annotations

import secrets
from typing import cast

from fastapi import APIRouter, HTTPException, Request
from starlette.responses import JSONResponse, Response

from distill.parsing import strict_json_loads
from distill.web.theme import THEME_MAX_BYTES, load_themes, theme_css
from distill.web.theme_install import install_theme_data

router = APIRouter()


@router.get("/themes")
async def themes() -> JSONResponse:
    collection = load_themes()
    return JSONResponse(
        {**collection.to_row(), "css": theme_css(collection)}, headers={"Cache-Control": "no-store"}
    )


@router.get("/themes.css")
async def stylesheet() -> Response:
    return Response(theme_css(), media_type="text/css", headers={"Cache-Control": "no-store"})


@router.post("/themes/import")
async def import_theme(request: Request) -> JSONResponse:
    token = request.headers.get("x-distill-theme-token", "")
    expected: object = request.app.state.theme_token
    if not isinstance(expected, str) or not secrets.compare_digest(token, expected):
        raise HTTPException(403, "Theme import requires the local page token")
    origin = request.headers.get("origin")
    if origin and origin != str(request.base_url).rstrip("/"):
        raise HTTPException(403, "Theme import requires the same origin")
    payload = bytearray()
    async for chunk in request.stream():
        payload.extend(chunk)
        if len(payload) > THEME_MAX_BYTES * 6 + 64:
            raise HTTPException(413, "Theme import exceeds the size limit")
    try:
        decoded: object = strict_json_loads(payload.decode("utf-8"))
        if not isinstance(decoded, dict):
            raise ValueError("Theme import requires a JSON object")
        data = cast(dict[str, object], decoded)
        if set(data) != {"content"} or not isinstance(data["content"], str):
            raise ValueError("Theme import requires only a text content field")
        report = install_theme_data(data["content"])
    except (OSError, ValueError) as exc:
        raise HTTPException(422, f"Theme not loaded: {exc}") from exc
    return JSONResponse({"installed": list(report.installed)})

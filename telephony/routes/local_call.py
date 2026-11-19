"""Local dummy-call UI + API (TELEPHONY_PROVIDER=local)."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

from telephony.local_calls import (
    active_local_count,
    end_local_call,
    get_local_call,
    local_call_public,
    local_turn,
)
from telephony.log import setup_logging

log = setup_logging()

_HTML = Path(__file__).resolve().parent.parent / "static" / "local_call.html"


async def local_call_page(session_id: str):
    call = get_local_call(session_id)
    if not call:
        return HTMLResponse(
            "<h1>Local call not found</h1><p>Start Call Saathi now from the app first. "
            "Sessions expire after a few hours.</p>",
            status_code=404,
        )
    if not _HTML.exists():
        return HTMLResponse("<h1>local_call.html missing</h1>", status_code=500)
    html = _HTML.read_text(encoding="utf-8").replace("{{SESSION_ID}}", session_id)
    return HTMLResponse(html)


async def local_call_status(session_id: str):
    call = get_local_call(session_id)
    if not call:
        return JSONResponse({"error": "local call not found"}, status_code=404)
    return JSONResponse(local_call_public(call))


async def local_call_turn(session_id: str, request: Request):
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid JSON"}, status_code=400)
    text = (body.get("text") or body.get("message") or "").strip()
    if not text:
        return JSONResponse({"error": "text required"}, status_code=400)
    speak = body.get("speak", True)
    if isinstance(speak, str):
        speak = speak.lower() not in ("0", "false", "no")
    result = await local_turn(session_id, text, speak=bool(speak))
    if result.get("error"):
        return JSONResponse(result, status_code=int(result.get("status") or 400))
    return JSONResponse(result)


async def local_call_end(session_id: str):
    result = await end_local_call(session_id)
    if result.get("error"):
        return JSONResponse(result, status_code=int(result.get("status") or 400))
    return JSONResponse(result)


def register(app: FastAPI) -> None:
    app.get("/local-call/{session_id}")(local_call_page)
    app.get("/api/local-call/{session_id}")(local_call_status)
    app.post("/api/local-call/{session_id}/turn")(local_call_turn)
    app.post("/api/local-call/{session_id}/end")(local_call_end)
    log.info(f"Local-call routes registered (active={active_local_count()})")

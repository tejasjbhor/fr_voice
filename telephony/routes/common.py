"""Shared HTTP routes (health, outbound dial, mobile demo)."""

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from core.database import normalize_phone, recordings_info, upsert_demo_user
from core.db_engine import get_engine, resolve_database_url
from telephony.auth import can_access_phone, forbid, open_dialer, require_account
from telephony.call_slots import active_calls, capacity_snapshot, max_concurrent_calls
from telephony.config import (
    APP_ENV,
    EXOTEL_VIRTUAL_NUMBER,
    TELEPHONY_PROVIDER,
    TWILIO_PHONE_NUMBER,
)
from telephony.local_calls import active_local_count, start_local_call
from telephony.log import setup_logging
from telephony.outbound import place_outbound_call, resolve_outbound_provider

log = setup_logging()

_DEMO_HTML = Path(__file__).resolve().parent.parent / "static" / "demo.html"
_MOBILE_WWW = Path(__file__).resolve().parent.parent.parent / "mobile" / "www"
_ALLOWED_LANGS = {"hi-IN", "mr-IN", "en-IN", "es-ES", "fr-FR"}


async def health():
    db_ok = False
    db_backend = "unknown"
    try:
        url = resolve_database_url()
        if url.startswith("sqlite"):
            db_backend = "sqlite"
        elif "postgres" in url:
            db_backend = "postgres"
        else:
            db_backend = "other"
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        db_ok = True
    except Exception as e:
        log.warning(f"Health DB check failed: {e}")

    capacity = capacity_snapshot()
    if max_concurrent_calls() > 0 and capacity.get("backend") == "postgres":
        try:
            n = await active_calls()
            capacity["active"] = n
            capacity["available"] = max(0, max_concurrent_calls() - n)
        except Exception as e:
            log.warning(f"Capacity check failed: {e}")

    return {
        "status": "ok" if db_ok else "degraded",
        "service": "AI Sathi Call Server v9",
        "telephony_provider": TELEPHONY_PROVIDER,
        "outbound_provider": resolve_outbound_provider(),
        "app_env": APP_ENV,
        "database": {"ok": db_ok, "backend": db_backend},
        "capacity": capacity,
        "recordings": recordings_info(),
        "local_calls_active": active_local_count() if TELEPHONY_PROVIDER == "local" else 0,
    }


async def demo_page():
    """Mobile-friendly dialer: outbound + inbound helpline."""
    if not _DEMO_HTML.exists():
        return HTMLResponse("<h1>Dialer page missing</h1>", status_code=500)
    return HTMLResponse(_DEMO_HTML.read_text(encoding="utf-8"))


async def call_info():
    """Numbers and mode for the dialer UI (inbound helpline + outbound)."""
    helpline = (TWILIO_PHONE_NUMBER or EXOTEL_VIRTUAL_NUMBER or "").strip()
    return {
        "helpline": helpline,
        "helpline_display": helpline,
        "outbound_provider": resolve_outbound_provider(),
        "telephony_provider": TELEPHONY_PROVIDER,
        "open_dialer": open_dialer(),
    }


async def hangup_call(request: Request):
    """End an outbound Twilio call started from the dialer (needs call_sid)."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid JSON"}, status_code=400)
    call_sid = (body.get("call_sid") or "").strip()
    if not call_sid:
        return JSONResponse({"error": "call_sid required"}, status_code=400)
    if not open_dialer():
        acc, err = require_account(request)
        if err:
            return err
    from telephony.adapters.twilio import hangup_twilio_call

    ok = hangup_twilio_call(call_sid)
    if not ok:
        return JSONResponse({"error": "hangup_failed"}, status_code=500)
    return JSONResponse({"status": "ended", "call_sid": call_sid})


async def trigger_outbound(request: Request):
    """
    Trigger outbound call via active TELEPHONY_PROVIDER.

    Body:
      { "to_number": "+91...", "name": "Anagha", "language": "hi-IN" }
      optional: "user_id" (ignored for demo upsert path)
    """
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid JSON"}, status_code=400)

    to_number = normalize_phone(body.get("to_number", ""))
    if not to_number:
        return JSONResponse({"error": "to_number required (E.164, e.g. +9198...)"}, status_code=400)

    if not open_dialer():
        acc, err = require_account(request)
        if err:
            return err
        if not can_access_phone(acc, to_number):
            return forbid("you can only call your own number or a person you added")

    name = (body.get("name") or "").strip()
    language = (body.get("language") or "hi-IN").strip()
    if language not in _ALLOWED_LANGS:
        return JSONResponse(
            {"error": f"language must be one of {sorted(_ALLOWED_LANGS)}"},
            status_code=400,
        )

    user = None
    if name:
        user = upsert_demo_user(name=name, phone=to_number, language=language)
        if not user:
            return JSONResponse({"error": "could not save demo user"}, status_code=400)
        log.info(
            f"Demo user ready | id={user.get('id')} | {user.get('name')} | "
            f"{user.get('language')} | {user.get('phone')}"
        )
    else:
        from core.database import get_user_by_phone
        user = get_user_by_phone(to_number)
        log.warning(
            f"Outbound without name — caller {to_number} must already exist in DB "
            f"(or APP_ENV=development default user will be used)"
        )

    provider = resolve_outbound_provider()

    if provider == "local":
        if not user:
            return JSONResponse(
                {"error": "local mode needs a known user — pass name or add the person first"},
                status_code=400,
            )
        started = start_local_call(user, language=language)
        log.info(f"Outbound (local) → {to_number} | {started['local_call_url']}")
        return JSONResponse({
            "status": "dialing",
            "to": to_number,
            "provider": "local",
            "session_id": started["session_id"],
            "local_call_url": started["local_call_url"],
            "message": "Open local_call_url on this PC to talk. Then Refresh last call in the app.",
            "user": started.get("user"),
        })

    ok, err, call_sid = await place_outbound_call(to_number, provider=provider)

    if ok:
        log.info(f"Outbound ({provider}) → {to_number} | sid={call_sid or '-'}")
        return JSONResponse({
            "status": "dialing",
            "to": to_number,
            "provider": provider,
            "call_sid": call_sid,
            "user": {
                "id": user.get("id"),
                "name": user.get("name"),
                "language": user.get("language"),
                "phone": user.get("phone"),
            } if user else None,
        })
    if err == "capacity_full":
        from telephony.call_slots import active_calls, max_concurrent_calls
        return JSONResponse(
            {
                "error": "capacity_full",
                "message": "All lines are busy — try again when a call ends",
                "max_concurrent_calls": max_concurrent_calls(),
                "active": await active_calls(),
            },
            status_code=503,
        )
    return JSONResponse(
        {"error": err or "Failed to trigger call"},
        status_code=500,
    )


def register(app: FastAPI) -> None:
    app.get("/health")(health)
    app.get("/demo")(demo_page)
    app.get("/call/info")(call_info)
    app.post("/call/outbound")(trigger_outbound)
    app.post("/call/hangup")(hangup_call)


def mount_mobile_ui(app: FastAPI) -> None:
    """Serve mobile/www last so /health, /api, and websockets keep matching first."""
    if not _MOBILE_WWW.is_dir():
        log.warning("mobile/www missing — falling back to /demo for GET /")
        app.get("/")(demo_page)
        return
    app.mount("/", StaticFiles(directory=str(_MOBILE_WWW), html=True), name="mobile_ui")

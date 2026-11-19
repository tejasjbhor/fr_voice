"""Exotel telephony adapter: outbound dial + HTTP/WS routes."""

import asyncio
import json
import re
import uuid

import requests
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from telephony.audio_utils import is_placeholder
from telephony.config import (
    EXOTEL_API_KEY,
    EXOTEL_API_TOKEN,
    EXOTEL_SID,
    EXOTEL_SUBDOMAIN,
    EXOTEL_VIRTUAL_NUMBER,
    PROVIDER_HANGUP_ENABLED,
    SERVER_PUBLIC_URL,
)
from telephony.log import setup_logging
from telephony.session import handle_call_session
from telephony.user_resolver import resolve_user

log = setup_logging()


def _digits(phone: str) -> str:
    return re.sub(r"\D", "", phone or "")


def _exotel_from_number(phone: str) -> str:
    d = _digits(phone)
    if d.startswith("91") and len(d) == 12:
        return f"+{d}"
    if len(d) == 10:
        return f"+91{d}"
    if d.startswith("0") and len(d) == 11:
        return f"+91{d[1:]}"
    return phone.strip()


def _exotel_caller_id(phone: str) -> str:
    d = _digits(phone)
    if d.startswith("91") and len(d) == 12:
        return f"0{d[2:]}"
    if len(d) == 10:
        return f"0{d}"
    if d.startswith("0") and len(d) >= 10:
        return d
    return phone.strip()


def exotel_websocket_url() -> str:
    public = SERVER_PUBLIC_URL.rstrip("/")
    ws = public.replace("https://", "wss://").replace("http://", "ws://")
    return f"{ws}/call/audio"


def make_exotel_outbound_call(to_number: str, ws_url: str) -> bool:
    if not all([EXOTEL_SID, EXOTEL_API_KEY, EXOTEL_API_TOKEN, EXOTEL_VIRTUAL_NUMBER]) or any(
        is_placeholder(v)
        for v in (EXOTEL_SID, EXOTEL_API_KEY, EXOTEL_API_TOKEN, EXOTEL_VIRTUAL_NUMBER)
    ):
        log.error("Exotel credentials missing in .env")
        return False

    from_number = _exotel_from_number(to_number)
    caller_id = _exotel_caller_id(EXOTEL_VIRTUAL_NUMBER)

    if _digits(from_number) == _digits(EXOTEL_VIRTUAL_NUMBER) or _digits(from_number) == _digits(caller_id):
        log.error(
            "Exotel 'From' cannot be your ExoPhone. "
            "Set USER_PHONE / to_number to YOUR mobile (the phone that should ring), "
            f"not EXOTEL_VIRTUAL_NUMBER ({EXOTEL_VIRTUAL_NUMBER})."
        )
        return False

    url = (
        f"https://{EXOTEL_API_KEY}:{EXOTEL_API_TOKEN}"
        f"@{EXOTEL_SUBDOMAIN}/v1/Accounts/{EXOTEL_SID}/Calls/connect"
    )
    payload = {
        "From": from_number,
        "CallerId": caller_id,
        "StreamUrl": ws_url,
        "StreamType": "bidirectional",
        "StatusCallback": f"{SERVER_PUBLIC_URL.rstrip('/')}/call/status",
        "StatusCallbackEvents[]": "terminal",
    }
    log.info(f"Exotel dial | From={from_number} | CallerId={caller_id}")
    try:
        resp = requests.post(url, data=payload, timeout=15)
        if resp.status_code in (200, 201):
            call_sid = ""
            try:
                body = resp.json()
                call_sid = (
                    body.get("Call", {}).get("Sid")
                    or body.get("call", {}).get("sid")
                    or ""
                )
            except Exception:
                m = re.search(r"<Sid>([^<]+)</Sid>", resp.text or "")
                if m:
                    call_sid = m.group(1)
            log.info(f"Exotel outbound | SID={call_sid or '?'} | to={from_number}")
            return True
        log.error(f"Exotel API error: {resp.status_code} — {resp.text}")
        return False
    except Exception as e:
        log.error(f"Exotel outbound failed: {e}")
        return False


def _hangup(call_sid: str) -> None:
    """
    Terminate the PSTN leg through Exotel's REST API.

    Closing the WebSocket should already do this; this is the belt-and-braces
    path behind PROVIDER_HANGUP_ENABLED, for when the provider is slow to tear
    the leg down. Blocking requests call — run it off the event loop.
    """
    if not call_sid:
        return
    url = (
        f"https://{EXOTEL_API_KEY}:{EXOTEL_API_TOKEN}"
        f"@{EXOTEL_SUBDOMAIN}/v1/Accounts/{EXOTEL_SID}/Calls/{call_sid}.json"
    )
    try:
        resp = requests.post(url, data={"Status": "completed"}, timeout=10)
        if resp.status_code in (200, 201, 204):
            log.info(f"Exotel hangup sent | SID={call_sid}")
        elif resp.status_code in (403, 404):
            # Exotel answers "Method not allowed" (403) or 404 when the leg is
            # already gone, which is the normal case: closing the socket usually
            # tears the call down a good second before this request goes out.
            # This is the belt to that pair of braces, so a leg that has already
            # dropped is a success, not a failure worth a warning.
            log.info(
                f"Exotel hangup no-op ({resp.status_code}) — leg already down | "
                f"SID={call_sid}"
            )
        else:
            log.warning(f"Exotel hangup returned {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        log.warning(f"Exotel hangup failed: {e}")


async def websocket_audio(ws: WebSocket):
    await ws.accept()
    session_id = str(uuid.uuid4())
    log.info(f"Exotel WS connected | session={session_id[:16]}")

    stream_sid = ""
    call_sid = ""
    caller = ""
    params = dict(ws.query_params)
    caller = params.get("From") or params.get("from", "")
    # Fallback for the REST hang-up: Exotel puts CallSid on the query string of
    # the Voicebot URL, and the start event has been seen without it.
    call_sid = params.get("CallSid") or params.get("call_sid", "")

    try:
        while True:
            text = await asyncio.wait_for(ws.receive_text(), timeout=30.0)
            try:
                obj = json.loads(text)
            except json.JSONDecodeError:
                continue
            event = obj.get("event", "")
            if event == "connected":
                continue
            if event == "start":
                start = obj.get("start") or {}
                stream_sid = str(start.get("stream_sid") or obj.get("stream_sid") or "")
                call_sid = str(
                    start.get("call_sid") or obj.get("call_sid") or call_sid or ""
                )
                caller = str(start.get("from") or caller or "")
                # call_sid is logged because it is the one thing the REST
                # hang-up cannot work without, and its absence is invisible
                # until the call fails to drop at the end.
                log.info(
                    f"Exotel stream started | sid={stream_sid[:16] if stream_sid else '-'} | "
                    f"call_sid={call_sid[:16] if call_sid else '-'} | from={caller}"
                )
                break
            if event == "stop":
                log.info("Exotel stream stopped before start")
                await ws.close()
                return
    except (asyncio.TimeoutError, WebSocketDisconnect):
        log.warning("Exotel WS: no start event — closing")
        try:
            await ws.close()
        except Exception:
            pass
        return

    if not stream_sid:
        log.error("Exotel stream_sid missing — closing")
        await ws.close()
        return

    user = resolve_user(caller)
    if not user:
        log.error("No user found — closing WebSocket")
        await ws.close()
        return

    try:
        await handle_call_session(
            ws, user, session_id, provider="exotel", stream_sid=stream_sid,
        )
    except WebSocketDisconnect:
        log.info("Call ended by Exotel")
    except Exception as e:
        log.error(f"Call error: {e}", exc_info=True)
    finally:
        # handle_call_session already closed the socket the moment her last
        # words finished playing; this is a no-op on the normal path.
        try:
            await ws.close()
        except Exception:
            pass
        if PROVIDER_HANGUP_ENABLED:
            if call_sid:
                await asyncio.to_thread(_hangup, call_sid)
            else:
                # Silently skipping here looks exactly like the hang-up not
                # working, so say which half is missing.
                log.warning(
                    "PROVIDER_HANGUP_ENABLED is on but no call_sid arrived — "
                    "the PSTN leg is left to Exotel's own teardown"
                )
        log.info(f"Session {session_id[:16]} closed")


async def call_status(request: Request):
    try:
        body = await request.form()
        data = dict(body)
    except Exception:
        data = {}
    log.info(
        f"Exotel status: {data.get('Status')} | "
        f"From={data.get('From')} | Duration={data.get('ConversationDuration')}s"
    )
    return JSONResponse({"status": "received"})


def register(app: FastAPI) -> None:
    app.websocket("/call/audio")(websocket_audio)
    app.post("/call/status")(call_status)

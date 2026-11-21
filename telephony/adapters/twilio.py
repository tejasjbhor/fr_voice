"""Twilio Media Streams telephony adapter."""

import asyncio
import json
import uuid

import requests
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, Response
from xml.sax.saxutils import escape as xml_escape

from telephony.audio_utils import is_placeholder
from telephony.config import (
    PROVIDER_HANGUP_ENABLED,
    SERVER_PUBLIC_URL,
    TWILIO_ACCOUNT_SID,
    TWILIO_AUTH_TOKEN,
    TWILIO_PHONE_NUMBER,
)
from telephony.log import setup_logging
from telephony.session import handle_call_session
from telephony.user_resolver import resolve_user

log = setup_logging()


def _busy_twiml(
    message: str = (
        "All lines are busy right now. This is a Twilio system message, "
        "not Sathi. Please try again later."
    ),
) -> str:
    # Refuse before <Connect><Stream> so we never open a WebSocket we cannot serve.
    # language=en-US makes it obvious this is Twilio <Say>, not Sarvam Priya.
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response>"
        f'<Say language="en-US">{xml_escape(message)}</Say>'
        "<Hangup/>"
        "</Response>"
    )


async def twilio_voice(request: Request):
    try:
        form = await request.form()
        data = dict(form)
    except Exception:
        data = {}

    direction = str(data.get("Direction") or "")
    from_number = str(data.get("From") or "")
    to_number = str(data.get("To") or "")
    caller = to_number if direction == "outbound-api" else (from_number or to_number)

    if not SERVER_PUBLIC_URL or is_placeholder(SERVER_PUBLIC_URL):
        log.error("SERVER_PUBLIC_URL missing — cannot build Twilio Stream URL")
        twiml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            "<Response>"
            '<Say language="en-US">'
            "Server misconfigured. This is a Twilio system message, not Sathi. "
            "Check SERVER PUBLIC URL and ngrok."
            "</Say>"
            "</Response>"
        )
        return Response(content=twiml, media_type="application/xml")

    from telephony.call_slots import has_capacity

    # Soft check before <Connect><Stream>. The media WebSocket takes the
    # durable slot; if two calls race the last seat, the loser closes there.
    if not await has_capacity():
        log.warning(f"Twilio busy-out | from={caller}")
        return Response(content=_busy_twiml(), media_type="application/xml")

    public = SERVER_PUBLIC_URL.rstrip("/")
    ws = public.replace("https://", "wss://").replace("http://", "ws://")
    stream_url = f"{ws}/twilio/media-stream"

    twiml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response>"
        "<Connect>"
        f'<Stream url="{xml_escape(stream_url)}">'
        f'<Parameter name="from" value="{xml_escape(caller)}" />'
        "</Stream>"
        "</Connect>"
        "</Response>"
    )
    log.info(
        f"Twilio voice TwiML | direction={direction} | from={from_number} | "
        f"to={to_number} | stream={stream_url}"
    )
    return Response(content=twiml, media_type="application/xml")


async def twilio_status(request: Request):
    try:
        form = await request.form()
        data = dict(form)
    except Exception:
        data = {}
    log.info(
        f"Twilio status: {data.get('CallStatus')} | "
        f"From={data.get('From')} | To={data.get('To')} | "
        f"Duration={data.get('CallDuration')}s | Sid={data.get('CallSid')}"
    )
    return JSONResponse({"status": "received"})


def _hangup(call_sid: str) -> None:
    """
    Terminate the PSTN leg through Twilio's REST API.

    Closing the WebSocket returns control to the TwiML document, and with
    <Connect><Stream> as the last verb that already ends the call; this is the
    belt-and-braces path behind PROVIDER_HANGUP_ENABLED. Blocking requests
    call — run it off the event loop.
    """
    if not call_sid or not TWILIO_ACCOUNT_SID or not TWILIO_AUTH_TOKEN:
        return
    url = (
        f"https://api.twilio.com/2010-04-01/Accounts/"
        f"{TWILIO_ACCOUNT_SID}/Calls/{call_sid}.json"
    )
    try:
        resp = requests.post(
            url, data={"Status": "completed"},
            auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN), timeout=10,
        )
        if resp.status_code in (200, 201, 204):
            log.info(f"Twilio hangup sent | SID={call_sid}")
        else:
            log.warning(f"Twilio hangup returned {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        log.warning(f"Twilio hangup failed: {e}")


async def twilio_media_stream(ws: WebSocket):
    await ws.accept()
    session_id = str(uuid.uuid4())
    log.info(f"Twilio WS connected | session={session_id[:16]}")

    stream_sid = ""
    call_sid = ""
    caller = ""

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
                stream_sid = str(start.get("streamSid") or "")
                call_sid = str(start.get("callSid") or "")
                custom = start.get("customParameters") or {}
                caller = str(custom.get("from") or custom.get("From") or "")
                log.info(
                    f"Twilio stream started | sid={stream_sid[:16] if stream_sid else '-'} | "
                    f"from={caller}"
                )
                break
            if event == "stop":
                log.info("Twilio stream stopped before start")
                await ws.close()
                return
    except (asyncio.TimeoutError, WebSocketDisconnect):
        log.warning("Twilio WS: no start event — closing")
        try:
            await ws.close()
        except Exception:
            pass
        return

    if not stream_sid:
        log.error("Twilio streamSid missing — closing")
        await ws.close()
        return

    user = resolve_user(caller)
    if not user:
        log.error("No user found — closing Twilio WebSocket")
        await ws.close()
        return

    from telephony.call_slots import release_slot, try_acquire_slot

    if not await try_acquire_slot():
        log.warning(f"Twilio stream refused — capacity full | from={caller}")
        try:
            await ws.close()
        except Exception:
            pass
        if PROVIDER_HANGUP_ENABLED and call_sid:
            await asyncio.to_thread(_hangup, call_sid)
        return

    try:
        await handle_call_session(
            ws, user, session_id, provider="twilio", stream_sid=stream_sid,
        )
    except WebSocketDisconnect:
        log.info("Call ended by Twilio")
    except RuntimeError as e:
        if "not connected" in str(e).lower():
            log.info("Call ended (WebSocket closed during TTS)")
        else:
            log.error(f"Twilio call error: {e}", exc_info=True)
    except Exception as e:
        log.error(f"Twilio call error: {e}", exc_info=True)
    finally:
        await release_slot()
        # handle_call_session already closed the socket the moment her last
        # words finished playing; this is a no-op on the normal path.
        try:
            await ws.close()
        except Exception:
            pass
        if PROVIDER_HANGUP_ENABLED and call_sid:
            await asyncio.to_thread(_hangup, call_sid)
        log.info(f"Twilio session {session_id[:16]} closed")


def make_twilio_outbound_call(to_number: str) -> bool:
    if not all([TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER]) or any(
        is_placeholder(v)
        for v in (TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER)
    ):
        log.error("Twilio credentials missing in .env")
        return False
    if not SERVER_PUBLIC_URL or is_placeholder(SERVER_PUBLIC_URL):
        log.error("SERVER_PUBLIC_URL missing — Twilio needs a public voice URL")
        return False

    public = SERVER_PUBLIC_URL.rstrip("/")
    voice_url = f"{public}/twilio/voice"
    status_url = f"{public}/twilio/status"
    api_url = (
        f"https://api.twilio.com/2010-04-01/Accounts/"
        f"{TWILIO_ACCOUNT_SID}/Calls.json"
    )
    payload = {
        "From": TWILIO_PHONE_NUMBER,
        "To": to_number,
        "Url": voice_url,
        "StatusCallback": status_url,
        "StatusCallbackEvent": ["initiated", "ringing", "answered", "completed"],
    }
    try:
        resp = requests.post(
            api_url,
            data=payload,
            auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN),
            timeout=15,
        )
        if resp.status_code in (200, 201):
            call_sid = resp.json().get("sid", "")
            log.info(f"Twilio outbound | SID={call_sid} | to={to_number}")
            return True
        log.error(f"Twilio API error: {resp.status_code} — {resp.text}")
        return False
    except Exception as e:
        log.error(f"Twilio outbound failed: {e}")
        return False


def register(app: FastAPI) -> None:
    app.post("/twilio/voice")(twilio_voice)
    app.post("/twilio/status")(twilio_status)
    app.websocket("/twilio/media-stream")(twilio_media_stream)

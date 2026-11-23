"""Plivo Audio Streaming telephony adapter."""

import asyncio
import json
import uuid
from urllib.parse import parse_qs
from xml.sax.saxutils import escape as xml_escape

import requests
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, Response

from telephony.audio_utils import is_placeholder
from telephony.config import (
    PLIVO_AUTH_ID,
    PLIVO_AUTH_TOKEN,
    PLIVO_PHONE_NUMBER,
    PROVIDER_HANGUP_ENABLED,
    SERVER_PUBLIC_URL,
)
from telephony.log import setup_logging
from telephony.session import handle_call_session
from telephony.user_resolver import resolve_user

log = setup_logging()


def _busy_xml(
    message: str = (
        "All lines are busy right now. Please try again later."
    ),
) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response>"
        f"<Speak>{xml_escape(message)}</Speak>"
        "<Hangup/>"
        "</Response>"
    )


def _form_dict(request_form) -> dict:
    data = {}
    for k, v in dict(request_form).items():
        data[str(k)] = str(v) if v is not None else ""
    return data


async def _request_params(request: Request) -> dict:
    """Plivo may POST form or query; merge both."""
    data = {}
    try:
        form = await request.form()
        data.update(_form_dict(form))
    except Exception:
        pass
    try:
        data.update({k: str(v) for k, v in request.query_params.items()})
    except Exception:
        pass
    if not data:
        try:
            raw = await request.body()
            if raw:
                text = raw.decode("utf-8", errors="replace")
                if text.lstrip().startswith("{"):
                    data.update({str(k): str(v) for k, v in json.loads(text).items()})
                else:
                    for k, vals in parse_qs(text, keep_blank_values=True).items():
                        data[k] = vals[0] if vals else ""
        except Exception:
            pass
    return data


def _caller_from_params(data: dict) -> str:
    direction = (data.get("Direction") or data.get("direction") or "").lower()
    from_number = data.get("From") or data.get("from") or ""
    to_number = data.get("To") or data.get("to") or ""
    # Outbound API: we dialled `To`; that person is the elder Saathi talks to.
    if direction in ("outbound", "outgoing"):
        return to_number or from_number
    return from_number or to_number


async def plivo_voice(request: Request):
    data = await _request_params(request)
    direction = data.get("Direction") or data.get("direction") or ""
    from_number = data.get("From") or data.get("from") or ""
    to_number = data.get("To") or data.get("to") or ""
    caller = _caller_from_params(data)

    if not SERVER_PUBLIC_URL or is_placeholder(SERVER_PUBLIC_URL):
        log.error("SERVER_PUBLIC_URL missing — cannot build Plivo Stream URL")
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            "<Response>"
            "<Speak>Server misconfigured. Check SERVER PUBLIC URL.</Speak>"
            "<Hangup/>"
            "</Response>"
        )
        return Response(content=xml, media_type="application/xml")

    from telephony.call_slots import has_capacity

    if not await has_capacity():
        log.warning(f"Plivo busy-out | from={caller}")
        return Response(content=_busy_xml(), media_type="application/xml")

    public = SERVER_PUBLIC_URL.rstrip("/")
    ws = public.replace("https://", "wss://").replace("http://", "ws://")
    stream_url = f"{ws}/plivo/media-stream"
    # Pass caller into the WebSocket start event via extraHeaders.
    extra = f"from={xml_escape(caller)}" if caller else ""

    attrs = [
        'bidirectional="true"',
        'keepCallAlive="true"',
        'contentType="audio/x-mulaw;rate=8000"',
    ]
    if extra:
        attrs.append(f'extraHeaders="{extra}"')

    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response>"
        f"<Stream {' '.join(attrs)}>"
        f"{xml_escape(stream_url)}"
        "</Stream>"
        "</Response>"
    )
    log.info(
        f"Plivo voice XML | direction={direction} | from={from_number} | "
        f"to={to_number} | stream={stream_url}"
    )
    return Response(content=xml, media_type="application/xml")


async def plivo_hangup(request: Request):
    data = await _request_params(request)
    log.info(
        f"Plivo hangup | CallUUID={data.get('CallUUID') or data.get('call_uuid')} | "
        f"From={data.get('From')} | To={data.get('To')} | "
        f"Duration={data.get('Duration') or data.get('CallDuration')}"
    )
    return Response(content="OK", media_type="text/plain")


def _hangup(call_uuid: str) -> None:
    if not call_uuid or not PLIVO_AUTH_ID or not PLIVO_AUTH_TOKEN:
        return
    url = (
        f"https://api.plivo.com/v1/Account/{PLIVO_AUTH_ID}/Call/{call_uuid}/"
    )
    try:
        resp = requests.delete(
            url, auth=(PLIVO_AUTH_ID, PLIVO_AUTH_TOKEN), timeout=10,
        )
        if resp.status_code in (200, 201, 202, 204):
            log.info(f"Plivo hangup sent | UUID={call_uuid}")
        else:
            log.warning(f"Plivo hangup returned {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        log.warning(f"Plivo hangup failed: {e}")


def _parse_extra_headers(raw) -> dict:
    out = {}
    if isinstance(raw, dict):
        return {str(k): str(v) for k, v in raw.items()}
    if not raw:
        return out
    text = str(raw)
    for pair in text.split(";"):
        if "=" not in pair:
            continue
        k, v = pair.split("=", 1)
        out[k.strip()] = v.strip()
    return out


async def plivo_media_stream(ws: WebSocket):
    await ws.accept()
    session_id = str(uuid.uuid4())
    log.info(f"Plivo WS connected | session={session_id[:16]}")

    stream_sid = ""
    call_uuid = ""
    caller = ""

    try:
        while True:
            text = await asyncio.wait_for(ws.receive_text(), timeout=30.0)
            try:
                obj = json.loads(text)
            except json.JSONDecodeError:
                continue
            event = obj.get("event", "")
            if event == "start":
                start = obj.get("start") or {}
                stream_sid = str(
                    start.get("streamId")
                    or start.get("stream_id")
                    or start.get("streamSid")
                    or ""
                )
                call_uuid = str(
                    start.get("callId")
                    or start.get("call_id")
                    or start.get("callUUID")
                    or start.get("call_uuid")
                    or ""
                )
                headers = _parse_extra_headers(
                    start.get("extraHeaders")
                    or start.get("extra_headers")
                    or obj.get("extra_headers")
                    or obj.get("extraHeaders")
                )
                caller = str(
                    headers.get("from")
                    or headers.get("From")
                    or start.get("from")
                    or start.get("From")
                    or ""
                )
                log.info(
                    f"Plivo stream started | sid={stream_sid[:16] if stream_sid else '-'} | "
                    f"from={caller}"
                )
                break
            if event in ("stop", "stopped"):
                log.info("Plivo stream stopped before start")
                await ws.close()
                return
    except (asyncio.TimeoutError, WebSocketDisconnect):
        log.warning("Plivo WS: no start event — closing")
        try:
            await ws.close()
        except Exception:
            pass
        return

    if not stream_sid:
        # Some Plivo builds still stream media without a stable streamId;
        # synthesize one so the player can clearAudio.
        stream_sid = session_id
        log.warning("Plivo streamId missing — using session id")

    user = resolve_user(caller)
    if not user:
        log.error("No user found — closing Plivo WebSocket")
        await ws.close()
        return

    from telephony.call_slots import release_slot, try_acquire_slot

    if not await try_acquire_slot():
        log.warning(f"Plivo stream refused — capacity full | from={caller}")
        try:
            await ws.close()
        except Exception:
            pass
        if PROVIDER_HANGUP_ENABLED and call_uuid:
            await asyncio.to_thread(_hangup, call_uuid)
        return

    try:
        await handle_call_session(
            ws, user, session_id, provider="plivo", stream_sid=stream_sid,
        )
    except WebSocketDisconnect:
        log.info("Call ended by Plivo")
    except RuntimeError as e:
        if "not connected" in str(e).lower():
            log.info("Call ended (WebSocket closed during TTS)")
        else:
            log.error(f"Plivo call error: {e}", exc_info=True)
    except Exception as e:
        log.error(f"Plivo call error: {e}", exc_info=True)
    finally:
        await release_slot()
        try:
            await ws.close()
        except Exception:
            pass
        if PROVIDER_HANGUP_ENABLED and call_uuid:
            await asyncio.to_thread(_hangup, call_uuid)
        log.info(f"Plivo session {session_id[:16]} closed")


def make_plivo_outbound_call(to_number: str) -> str | None:
    """Place outbound call. Returns Plivo Call UUID on success, else None."""
    if not all([PLIVO_AUTH_ID, PLIVO_AUTH_TOKEN, PLIVO_PHONE_NUMBER]) or any(
        is_placeholder(v)
        for v in (PLIVO_AUTH_ID, PLIVO_AUTH_TOKEN, PLIVO_PHONE_NUMBER)
    ):
        log.error("Plivo credentials missing in .env")
        return None
    if not SERVER_PUBLIC_URL or is_placeholder(SERVER_PUBLIC_URL):
        log.error("SERVER_PUBLIC_URL missing — Plivo needs a public answer URL")
        return None

    public = SERVER_PUBLIC_URL.rstrip("/")
    answer_url = f"{public}/plivo/voice"
    hangup_url = f"{public}/plivo/hangup"
    api_url = f"https://api.plivo.com/v1/Account/{PLIVO_AUTH_ID}/Call/"
    payload = {
        "from": PLIVO_PHONE_NUMBER,
        "to": to_number,
        "answer_url": answer_url,
        "answer_method": "POST",
        "hangup_url": hangup_url,
        "hangup_method": "POST",
    }
    try:
        resp = requests.post(
            api_url,
            json=payload,
            auth=(PLIVO_AUTH_ID, PLIVO_AUTH_TOKEN),
            timeout=15,
        )
        if resp.status_code in (200, 201, 202):
            body = resp.json() if resp.content else {}
            call_uuid = (
                (body.get("request_uuid") if isinstance(body, dict) else None)
                or (body.get("call_uuid") if isinstance(body, dict) else None)
                or ""
            )
            # Plivo often returns request_uuid; fetch may list call_uuid later.
            if isinstance(body.get("calls"), list) and body["calls"]:
                call_uuid = body["calls"][0].get("call_uuid") or call_uuid
            log.info(f"Plivo outbound | UUID={call_uuid or body} | to={to_number}")
            return call_uuid or "ok"
        log.error(f"Plivo API error: {resp.status_code} — {resp.text[:400]}")
        return None
    except Exception as e:
        log.error(f"Plivo outbound failed: {e}")
        return None


def hangup_plivo_call(call_uuid: str) -> bool:
    if not call_uuid or call_uuid == "ok":
        return False
    if not PLIVO_AUTH_ID or not PLIVO_AUTH_TOKEN:
        return False
    try:
        _hangup(call_uuid)
        return True
    except Exception as e:
        log.warning(f"Plivo hangup via API failed: {e}")
        return False


def register(app: FastAPI) -> None:
    app.post("/plivo/voice")(plivo_voice)
    app.get("/plivo/voice")(plivo_voice)
    app.post("/plivo/hangup")(plivo_hangup)
    app.get("/plivo/hangup")(plivo_hangup)
    app.websocket("/plivo/media-stream")(plivo_media_stream)

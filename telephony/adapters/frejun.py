"""FreJun Teler telephony adapter."""

import uuid

from fastapi import Body, FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from telephony.audio_utils import frejun_stream_flow_payload, is_placeholder
from telephony.config import (
    FREJUN_API_KEY,
    FREJUN_FROM_NUMBER,
    FREJUN_RECORD,
    SERVER_PUBLIC_URL,
    TELEPHONY_PROVIDER,
)
from telephony.log import setup_logging
from telephony.session import handle_call_session
from telephony.user_resolver import resolve_user

log = setup_logging()

# call_id → caller context (set in /frejun/flow)
_call_context: dict[str, dict] = {}


async def frejun_flow(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}

    call_id = str(body.get("call_id") or body.get("callId") or "")
    from_number = str(body.get("from_number") or body.get("from") or "")
    to_number = str(body.get("to_number") or body.get("to") or "")

    caller_phone = to_number if TELEPHONY_PROVIDER == "frejun" else from_number
    if not caller_phone:
        caller_phone = to_number or from_number

    if call_id:
        _call_context[call_id] = {
            "from_number": from_number,
            "to_number": to_number,
            "phone": caller_phone,
        }

    public = SERVER_PUBLIC_URL.rstrip("/")
    ws = public.replace("https://", "wss://").replace("http://", "ws://")
    qs = f"?call_id={call_id}" if call_id else ""
    if caller_phone:
        qs += ("&" if qs else "?") + f"from={caller_phone}"
    ws_url = f"{ws}/frejun/media-stream{qs}"

    flow = frejun_stream_flow_payload(ws_url)
    log.info(f"FreJun flow | call_id={call_id[:16] if call_id else '-'} | ws={ws_url}")
    return JSONResponse(flow)


async def frejun_webhook(data: dict = Body(default={})):
    log.info(f"FreJun webhook: {data}")
    call_id = str(data.get("call_id") or data.get("callId") or "")
    if call_id and data.get("status") in ("completed", "failed", "busy", "no-answer"):
        _call_context.pop(call_id, None)
    return JSONResponse({"status": "received"})


async def frejun_media_stream(ws: WebSocket):
    await ws.accept()
    session_id = str(uuid.uuid4())
    log.info(f"FreJun WS connected | session={session_id[:16]}")

    params = dict(ws.query_params)
    call_id = params.get("call_id", "")
    caller = params.get("from") or params.get("From", "")

    if not caller and call_id and call_id in _call_context:
        caller = _call_context[call_id].get("phone", "")

    user = resolve_user(caller)
    if not user:
        log.error("No user found — closing FreJun WebSocket")
        await ws.close()
        return

    try:
        await handle_call_session(ws, user, session_id, provider="frejun")
    except WebSocketDisconnect:
        log.info("Call ended by FreJun")
    except Exception as e:
        log.error(f"FreJun call error: {e}", exc_info=True)
    finally:
        if call_id:
            _call_context.pop(call_id, None)
        try:
            await ws.close()
        except Exception:
            pass
        log.info(f"FreJun session {session_id[:16]} closed")


async def make_frejun_outbound_call(to_number: str) -> bool:
    if not FREJUN_API_KEY or is_placeholder(FREJUN_API_KEY):
        log.error("FREJUN_API_KEY / TELER_API_KEY missing in .env")
        return False
    if not FREJUN_FROM_NUMBER or is_placeholder(FREJUN_FROM_NUMBER):
        log.error("FREJUN_FROM_NUMBER missing in .env")
        return False
    if not SERVER_PUBLIC_URL or is_placeholder(SERVER_PUBLIC_URL):
        log.error("SERVER_PUBLIC_URL missing — FreJun needs a public flow_url")
        return False

    public = SERVER_PUBLIC_URL.rstrip("/")
    flow_url = f"{public}/frejun/flow"
    status_url = f"{public}/frejun/webhook"

    try:
        from teler import AsyncClient
        async with AsyncClient(api_key=FREJUN_API_KEY, timeout=15) as client:
            call = await client.calls.create(
                from_number=FREJUN_FROM_NUMBER,
                to_number=to_number,
                flow_url=flow_url,
                status_callback_url=status_url,
                record=FREJUN_RECORD,
            )
            log.info(f"FreJun outbound created: {call}")
            return True
    except ImportError:
        log.error("teler package not installed — run: pip install teler")
        return False
    except Exception as e:
        log.error(f"FreJun outbound failed: {e}")
        return False


def register(app: FastAPI) -> None:
    app.post("/frejun/flow")(frejun_flow)
    app.post("/frejun/webhook")(frejun_webhook)
    app.websocket("/frejun/media-stream")(frejun_media_stream)

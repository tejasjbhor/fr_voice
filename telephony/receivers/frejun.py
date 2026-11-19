"""FreJun inbound media receiver."""

import asyncio
import base64
import json
from typing import Optional

from fastapi import WebSocket, WebSocketDisconnect


async def receive_pcm_from_frejun(ws: WebSocket) -> Optional[bytes]:
    """
    FreJun sends JSON text frames:
      {"type":"audio","data":{"audio_b64":"..."}}
    """
    msg = await asyncio.wait_for(ws.receive(), timeout=30.0)
    if msg.get("type") == "websocket.disconnect":
        raise WebSocketDisconnect()

    text = msg.get("text")
    raw = msg.get("bytes")

    if raw:
        return bytes(raw)

    if not text:
        return b""

    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        return b""

    mtype = obj.get("type", "")
    if mtype in ("stop", "hangup", "end"):
        raise WebSocketDisconnect()

    if mtype != "audio":
        return b""

    b64 = None
    data = obj.get("data")
    if isinstance(data, dict):
        b64 = data.get("audio_b64") or data.get("audio_base_64")
    if not b64:
        b64 = obj.get("audio_b64") or obj.get("audio_base_64")
    if not b64:
        return b""
    try:
        return base64.b64decode(b64)
    except Exception:
        return b""

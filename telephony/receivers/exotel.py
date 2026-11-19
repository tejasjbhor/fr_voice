"""Exotel inbound media receiver."""

import asyncio
import base64
import json
import time
from typing import Optional

from fastapi import WebSocket, WebSocketDisconnect

from telephony.config import CHUNK_SIZE, SAMPLE_WIDTH, LISTEN_SETTLE_S
from telephony.log import setup_logging

log = setup_logging()


async def receive_pcm_from_exotel(ws: WebSocket) -> Optional[bytes]:
    """Legacy helper — prefer ExotelPcmReceiver for JSON media frames."""
    data = await asyncio.wait_for(ws.receive_bytes(), timeout=30.0)
    return bytes(data)


class ExotelPcmReceiver:
    """Exotel AgentStream sends JSON media with base64 16-bit PCM @ 8 kHz."""

    def __init__(self):
        self._buf = bytearray()

    def flush(self):
        self._buf.clear()

    async def __call__(self, ws: WebSocket) -> Optional[bytes]:
        return await self.receive(ws)

    async def receive(self, ws: WebSocket) -> Optional[bytes]:
        while True:
            if len(self._buf) >= CHUNK_SIZE:
                out = bytes(self._buf[:CHUNK_SIZE])
                del self._buf[:CHUNK_SIZE]
                return out

            text = await asyncio.wait_for(ws.receive_text(), timeout=30.0)
            try:
                obj = json.loads(text)
            except json.JSONDecodeError:
                continue

            event = obj.get("event", "")
            if event == "stop":
                raise WebSocketDisconnect()
            if event in ("connected", "start", "mark", "dtmf"):
                continue
            if event != "media":
                continue

            media = obj.get("media") or {}
            b64 = media.get("payload")
            if not b64:
                continue
            try:
                self._buf.extend(base64.b64decode(b64))
            except Exception:
                continue

    async def discard_pending(self, ws: WebSocket, settle_s: float = LISTEN_SETTLE_S):
        self.flush()
        drained = 0
        while True:
            try:
                text = await asyncio.wait_for(ws.receive_text(), timeout=0.01)
            except asyncio.TimeoutError:
                break
            except (WebSocketDisconnect, RuntimeError):
                raise WebSocketDisconnect()
            try:
                obj = json.loads(text)
            except json.JSONDecodeError:
                continue
            if obj.get("event") == "stop":
                raise WebSocketDisconnect()
            if obj.get("event") == "media":
                drained += 1
            if drained > 8000:
                break
        end = time.monotonic() + settle_s
        while time.monotonic() < end:
            try:
                text = await asyncio.wait_for(ws.receive_text(), timeout=0.05)
            except asyncio.TimeoutError:
                continue
            except (WebSocketDisconnect, RuntimeError):
                raise WebSocketDisconnect()
            try:
                obj = json.loads(text)
            except json.JSONDecodeError:
                continue
            if obj.get("event") == "stop":
                raise WebSocketDisconnect()
        self.flush()
        if drained:
            log.info(f"Exotel flushed {drained} inbound frames before listen")

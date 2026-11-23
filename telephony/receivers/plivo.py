"""Plivo Audio Streaming inbound receiver (μ-law → PCM)."""

import asyncio
import audioop
import base64
import json
import time
from typing import Optional

from fastapi import WebSocket, WebSocketDisconnect

from telephony.config import CHUNK_SIZE, LISTEN_SETTLE_S, SAMPLE_WIDTH
from telephony.log import setup_logging

log = setup_logging()


class PlivoPcmReceiver:
    """Plivo sends ~20 ms μ-law frames. Buffer to ~100 ms PCM for VAD."""

    def __init__(self):
        self._buf = bytearray()
        self._inbound_frames = 0
        self._logged_first = False

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
            if event in ("stop", "stopped"):
                raise WebSocketDisconnect()
            if event == "start":
                start = obj.get("start") or {}
                log.info(
                    f"Plivo media start | stream={start.get('streamId') or start.get('stream_id')} | "
                    f"fmt={start.get('mediaFormat') or start.get('media_format')}"
                )
                continue
            if event in ("playedStream", "clearedAudio", "checkpoint", "dtmf"):
                continue
            if event != "media":
                continue

            media = obj.get("media") or {}
            b64 = media.get("payload")
            if not b64:
                continue
            try:
                mulaw = base64.b64decode(b64)
                pcm = audioop.ulaw2lin(mulaw, SAMPLE_WIDTH)
                self._buf.extend(pcm)
                self._inbound_frames += 1
                if not self._logged_first:
                    self._logged_first = True
                    peak = max((abs(int.from_bytes(pcm[i:i + 2], "little", signed=True))
                                for i in range(0, min(len(pcm), 320), 2)), default=0)
                    log.info(
                        f"Plivo inbound audio OK | mulaw={len(mulaw)}B | peak={peak}"
                    )
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
            try:
                obj = json.loads(text)
            except json.JSONDecodeError:
                continue
            if obj.get("event") in ("stop", "stopped"):
                raise WebSocketDisconnect()
            drained += 1
            if drained > 8000:
                break
        deadline = time.monotonic() + settle_s
        while time.monotonic() < deadline:
            try:
                text = await asyncio.wait_for(ws.receive_text(), timeout=0.05)
            except asyncio.TimeoutError:
                continue
            try:
                obj = json.loads(text)
            except json.JSONDecodeError:
                continue
            if obj.get("event") in ("stop", "stopped"):
                raise WebSocketDisconnect()
            drained += 1
        self.flush()
        if drained:
            log.info(f"Plivo flushed {drained} inbound frames before listen")

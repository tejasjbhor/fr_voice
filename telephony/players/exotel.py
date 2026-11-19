"""Exotel AgentStream audio player."""

import asyncio
import base64
import json
import time

from fastapi import WebSocket, WebSocketDisconnect

from telephony.audio_utils import wav_bytes_to_pcm_8k
from telephony.config import PHONE_SAMPLE_RATE, SAMPLE_WIDTH, PLAYBACK_TAIL_PAD_S
from telephony.log import setup_logging

log = setup_logging()

# Exotel requires chunks ≥ 3.2 KB (100 ms @ 8 kHz 16-bit mono), multiple of 320.
# Smaller frames cause silence / distortion on the caller's handset.
EXOTEL_FRAME_BYTES = 3200  # 100 ms
EXOTEL_FRAME_MS = 100


class ExotelAudioPlayer:
    """Send base64 linear PCM 8 kHz frames to Exotel AgentStream (Voicebot)."""

    def __init__(self, websocket: WebSocket, stream_sid: str):
        self._ws = websocket
        self._stream_sid = stream_sid
        self._queue = asyncio.Queue()
        self._task = None
        self._playback_done_at = 0.0
        self._frames_sent_total = 0

    async def start(self):
        self._task = asyncio.create_task(self._send_loop())

    async def enqueue(self, wav_bytes: bytes):
        await self._queue.put(wav_bytes)

    async def drain(self):
        await self._queue.join()
        deadline = max(time.monotonic(), self._playback_done_at) + PLAYBACK_TAIL_PAD_S
        while time.monotonic() < deadline:
            if self._ws.client_state.name != "CONNECTED":
                raise WebSocketDisconnect()
            await asyncio.sleep(0.05)

    async def stop(self):
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _send_loop(self):
        frame = EXOTEL_FRAME_BYTES
        frame_s = EXOTEL_FRAME_MS / 1000.0
        while True:
            try:
                wav_bytes = await asyncio.wait_for(self._queue.get(), timeout=0.1)
                pcm_8k = wav_bytes_to_pcm_8k(wav_bytes)
                if not pcm_8k:
                    log.warning("Exotel TTS empty after PCM convert — skipping")
                    self._queue.task_done()
                    continue

                # Pad to multiple of 320 (Exotel requirement)
                rem = len(pcm_8k) % 320
                if rem:
                    pcm_8k = pcm_8k + b"\x00" * (320 - rem)

                duration = len(pcm_8k) / float(PHONE_SAMPLE_RATE * SAMPLE_WIDTH)
                now = time.monotonic()
                start = max(now, self._playback_done_at)
                self._playback_done_at = start + duration

                frames_sent = 0
                for i in range(0, len(pcm_8k), frame):
                    chunk = pcm_8k[i:i + frame]
                    if len(chunk) < frame:
                        # Final partial chunk — pad to ≥ 3200 or exact multiple of 320
                        if len(chunk) < 320:
                            chunk = chunk + b"\x00" * (320 - len(chunk))
                        elif len(chunk) % 320:
                            chunk = chunk + b"\x00" * (320 - (len(chunk) % 320))
                        # If still under Exotel's 3.2 KB minimum, pad to 3200
                        if 0 < len(chunk) < EXOTEL_FRAME_BYTES:
                            chunk = chunk + b"\x00" * (EXOTEL_FRAME_BYTES - len(chunk))

                    payload = {
                        "event": "media",
                        "stream_sid": self._stream_sid,
                        "media": {
                            "payload": base64.b64encode(chunk).decode("ascii"),
                        },
                    }
                    try:
                        await self._ws.send_text(json.dumps(payload))
                    except Exception as e:
                        log.warning(f"Exotel WS send error: {e}")
                        break
                    frames_sent += 1
                    self._frames_sent_total += 1
                    # Real-time pacing so Exotel can play without dropping
                    await asyncio.sleep(frame_s)

                log.info(
                    f"Exotel played {frames_sent} frames "
                    f"({duration:.2f}s audio, total_sent={self._frames_sent_total})"
                )
                self._queue.task_done()
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

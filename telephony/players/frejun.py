"""FreJun Teler audio player."""

import asyncio
import base64
import json

from fastapi import WebSocket

from telephony.audio_utils import wav_bytes_to_pcm_8k
from telephony.config import CHUNK_SIZE, FREJUN_CHUNK_SIZE, PHONE_SAMPLE_RATE, SAMPLE_WIDTH
from telephony.log import setup_logging

log = setup_logging()


class FreJunAudioPlayer:
    """Send base64 L16/8kHz JSON audio frames to FreJun Teler."""

    def __init__(self, websocket: WebSocket):
        self._ws = websocket
        self._queue = asyncio.Queue()
        self._task = None
        self._chunk_id = 1

    async def start(self):
        self._task = asyncio.create_task(self._send_loop())

    async def enqueue(self, wav_bytes: bytes):
        await self._queue.put(wav_bytes)

    async def drain(self):
        await self._queue.join()

    async def stop(self):
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _send_loop(self):
        frame_bytes = max(
            CHUNK_SIZE,
            int(PHONE_SAMPLE_RATE * SAMPLE_WIDTH * FREJUN_CHUNK_SIZE / 1000),
        )
        while True:
            try:
                wav_bytes = await asyncio.wait_for(self._queue.get(), timeout=0.1)
                pcm_8k = wav_bytes_to_pcm_8k(wav_bytes)
                for i in range(0, len(pcm_8k), frame_bytes):
                    chunk = pcm_8k[i:i + frame_bytes]
                    payload = {
                        "type": "audio",
                        "audio_b64": base64.b64encode(chunk).decode("ascii"),
                        "chunk_id": self._chunk_id,
                    }
                    self._chunk_id += 1
                    try:
                        await self._ws.send_text(json.dumps(payload))
                    except Exception as e:
                        log.warning(f"FreJun WS send error: {e}")
                        break
                self._queue.task_done()
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

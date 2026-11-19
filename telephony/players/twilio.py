"""Twilio Media Streams audio player."""

import asyncio
import audioop
import base64
import json
import time

from fastapi import WebSocket, WebSocketDisconnect

from telephony.audio_utils import wav_bytes_to_pcm_8k
from telephony.config import PHONE_SAMPLE_RATE, SAMPLE_WIDTH, TWILIO_MULAW_FRAME, PLAYBACK_TAIL_PAD_S
from telephony.log import setup_logging

log = setup_logging()


class TwilioAudioPlayer:
    """Send μ-law 8 kHz Media Stream frames to Twilio."""

    def __init__(self, websocket: WebSocket, stream_sid: str):
        self._ws = websocket
        self._stream_sid = stream_sid
        self._queue = asyncio.Queue()
        self._task = None
        self._playback_done_at = 0.0
        # Bumped by clear(); the send loop drops whatever it is sending.
        self._gen = 0
        self.play_started = 0.0
        # True while a BargeInMonitor owns the socket's receive side.
        self.external_reader = False

    async def start(self):
        self._task = asyncio.create_task(self._send_loop())

    async def enqueue(self, wav_bytes: bytes):
        await self._queue.put(wav_bytes)

    async def enqueue_pcm(self, pcm_8k: bytes):
        """Raw 8 kHz 16-bit mono PCM — the streaming TTS path, no WAV header."""
        await self._queue.put(("pcm", pcm_8k))

    def is_playing(self) -> bool:
        return time.monotonic() < self._playback_done_at

    async def clear(self):
        """Stop her mid-sentence: drop queued audio and Twilio's buffer."""
        self._gen += 1
        while True:
            try:
                self._queue.get_nowait()
                self._queue.task_done()
            except asyncio.QueueEmpty:
                break
        self._playback_done_at = time.monotonic()
        try:
            await self._ws.send_text(json.dumps({
                "event": "clear",
                "streamSid": self._stream_sid,
            }))
        except Exception as e:
            log.warning(f"Twilio clear failed: {e}")

    async def drain(self):
        gen = self._gen
        await self._queue.join()
        deadline = max(time.monotonic(), self._playback_done_at) + PLAYBACK_TAIL_PAD_S
        if self.external_reader:
            while time.monotonic() < deadline and self._gen == gen:
                if self._ws.client_state.name != "CONNECTED":
                    raise WebSocketDisconnect()
                await asyncio.sleep(0.05)
            return
        while time.monotonic() < deadline:
            if self._ws.client_state.name != "CONNECTED":
                raise WebSocketDisconnect()
            try:
                text = await asyncio.wait_for(self._ws.receive_text(), timeout=0.05)
            except asyncio.TimeoutError:
                continue
            except (WebSocketDisconnect, RuntimeError) as e:
                raise WebSocketDisconnect() from e
            try:
                obj = json.loads(text)
            except json.JSONDecodeError:
                continue
            if obj.get("event") == "stop":
                raise WebSocketDisconnect()

    async def stop(self):
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _send_loop(self):
        while True:
            try:
                item = await asyncio.wait_for(self._queue.get(), timeout=0.1)
                gen = self._gen
                if isinstance(item, tuple):
                    pcm_8k = item[1]
                else:
                    pcm_8k = wav_bytes_to_pcm_8k(item)
                mulaw = audioop.lin2ulaw(pcm_8k, SAMPLE_WIDTH)
                duration = len(mulaw) / float(PHONE_SAMPLE_RATE)
                now = time.monotonic()
                if self._playback_done_at <= now:
                    self.play_started = now
                start = max(now, self._playback_done_at)
                self._playback_done_at = start + duration

                frames_sent = 0
                for i in range(0, len(mulaw), TWILIO_MULAW_FRAME):
                    if self._gen != gen:
                        self._playback_done_at = time.monotonic()
                        break
                    chunk = mulaw[i:i + TWILIO_MULAW_FRAME]
                    payload = {
                        "event": "media",
                        "streamSid": self._stream_sid,
                        "media": {
                            "payload": base64.b64encode(chunk).decode("ascii"),
                        },
                    }
                    try:
                        await self._ws.send_text(json.dumps(payload))
                    except Exception as e:
                        log.warning(f"Twilio WS send error: {e}")
                        break
                    frames_sent += 1
                    if frames_sent % 10 == 0:
                        await asyncio.sleep(0)
                self._queue.task_done()
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

"""Phone barge-in: keep reading the caller's audio while she speaks."""

import asyncio
import os
import time
from collections import deque

from fastapi import WebSocket, WebSocketDisconnect

from telephony.audio_utils import rms
from telephony.log import setup_logging

log = setup_logging()

PHONE_BARGE_IN_ENABLED = (
    os.getenv("PHONE_BARGE_IN_ENABLED", os.getenv("BARGE_IN_ENABLED", "true"))
    .lower() == "true"
)
# RMS of one 100 ms chunk of 8 kHz caller audio. Line noise sits well under
# the VAD threshold (350); normal speech on a mobile is roughly 1000-5000.
PHONE_BARGE_IN_THRESHOLD = int(os.getenv("PHONE_BARGE_IN_THRESHOLD", "1000"))
# Loud 100 ms chunks needed before she stops. 3 = 0.3 s — a cough or "hm"
# should not cut her off.
PHONE_BARGE_IN_CONFIRM_CHUNKS = int(os.getenv("PHONE_BARGE_IN_CONFIRM_CHUNKS", "3"))
# Ignore the first moments of her audio, where line echo is worst.
PHONE_BARGE_IN_GRACE_S = float(os.getenv("PHONE_BARGE_IN_GRACE_S", "0.4"))


class BargeInMonitor:
    """
    Sole reader of the Twilio socket while she is speaking.

    Starlette allows one receiver per socket, so while this runs the player's
    drain() must not read (player.external_reader). Once it fires it has
    already told Twilio to drop buffered audio, and it keeps capturing what the
    caller says so the next turn starts with their first words intact.
    """

    def __init__(self, websocket: WebSocket, receiver, player):
        self._ws = websocket
        self._rx = receiver
        self._player = player
        self._task: asyncio.Task | None = None
        self._stopping = False
        self.fired = asyncio.Event()
        self.disconnected = False
        self._captured = bytearray()
        self._pre: deque = deque(maxlen=3)
        self._loud = 0
        self._misses = 0

    @property
    def active(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self):
        self.fired = asyncio.Event()
        self.disconnected = False
        self._captured = bytearray()
        self._pre.clear()
        self._loud = 0
        self._misses = 0
        self._stopping = False
        self._player.external_reader = True
        self._task = asyncio.create_task(self._run())

    def _armed(self) -> bool:
        p = self._player
        return p.is_playing() and (time.monotonic() - p.play_started) >= PHONE_BARGE_IN_GRACE_S

    async def _run(self):
        try:
            # Python 3.11's wait_for can swallow a cancel when a frame lands at
            # the same moment — Twilio sends one every 20 ms, so it nearly
            # always does. The flag is what actually ends the loop.
            while not self._stopping:
                chunk = await self._rx.receive(self._ws)
                if not chunk:
                    continue
                if self.fired.is_set():
                    self._captured.extend(chunk)
                    continue

                if self._armed() and rms(chunk) >= PHONE_BARGE_IN_THRESHOLD:
                    if self._loud == 0:
                        self._captured = bytearray(b"".join(self._pre))
                    self._loud += 1
                    self._misses = 0
                    self._captured.extend(chunk)
                    if self._loud >= PHONE_BARGE_IN_CONFIRM_CHUNKS:
                        log.info("Barge-in — caller spoke over her, stopping playback")
                        await self._player.clear()
                        self.fired.set()
                    continue

                # One soft chunk inside a word should not reset the count.
                if self._loud and self._misses == 0:
                    self._misses = 1
                    self._captured.extend(chunk)
                    continue
                self._loud = 0
                self._misses = 0
                self._captured = bytearray()
                self._pre.append(chunk)
        except asyncio.CancelledError:
            raise
        except (WebSocketDisconnect, RuntimeError, asyncio.TimeoutError):
            self.disconnected = True
            self.fired.set()

    async def stop(self) -> bytes | None:
        """Stop reading. Returns captured caller audio if barge-in fired."""
        self._stopping = True
        task = self._task
        if task is not None and not task.done():
            task.cancel()
            await asyncio.wait({task}, timeout=2.0)
            if not task.done():
                log.warning("Barge-in monitor did not stop in time")
        self._task = None
        self._player.external_reader = False
        if self.disconnected:
            raise WebSocketDisconnect()
        if self.fired.is_set() and self._captured:
            return bytes(self._captured)
        return None


async def run_until_barge(aw, monitor: "BargeInMonitor | None") -> bool:
    """Await `aw`; if the caller barges in first, cancel it and return True."""
    if monitor is None or not monitor.active:
        await aw
        return False
    main = asyncio.ensure_future(aw)
    fired = asyncio.ensure_future(monitor.fired.wait())
    try:
        done, _ = await asyncio.wait({main, fired}, return_when=asyncio.FIRST_COMPLETED)
    except asyncio.CancelledError:
        main.cancel()
        fired.cancel()
        raise
    if main in done:
        fired.cancel()
        main.result()
        return False
    main.cancel()
    try:
        await main
    except (asyncio.CancelledError, Exception):
        pass
    return True

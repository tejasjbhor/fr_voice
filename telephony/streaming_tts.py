"""Streaming TTS for phone calls: play Fish audio as it is generated."""

import asyncio
import time

from core.fish_service import stream_pcm
from core.tts_service import synthesize_phrase
from telephony.log import setup_logging

log = setup_logging()


class StreamingTtsQueue:
    """
    Drop-in for OrderedTtsQueue on players that accept raw PCM.

    Every phrase starts streaming as soon as it is emitted. The phrase whose
    turn it is plays chunk by chunk as Fish produces it; later phrases hold
    their chunks until every phrase before them has been handed to the player,
    so sentence order is kept while their generation overlaps.
    """

    def __init__(self, player, sample_rate: int = 8000):
        self._player = player
        self._sample_rate = sample_rate
        self._next = 0
        self._turn = asyncio.Condition()
        self.first_enqueued_at: float | None = None

    async def _put(self, item):
        if self.first_enqueued_at is None:
            self.first_enqueued_at = time.time()
        if isinstance(item, tuple):
            await self._player.enqueue(item[1])
        else:
            await self._player.enqueue_pcm(item)

    async def synthesize_and_enqueue(self, seq: int, text: str, language: str, tts_cfg: dict):
        held: list = []
        got_any = False
        try:
            async for pcm in stream_pcm(
                text, language,
                pace=tts_cfg.get("pace"),
                temperature=tts_cfg.get("temperature"),
                sample_rate=self._sample_rate,
            ):
                got_any = True
                if self._next == seq:
                    while held:
                        await self._put(held.pop(0))
                    await self._put(pcm)
                else:
                    held.append(pcm)
            if not got_any:
                wav = await synthesize_phrase(
                    text, language=language,
                    speaker=tts_cfg["speaker"], pace=tts_cfg["pace"],
                    temperature=tts_cfg.get("temperature"),
                )
                if wav:
                    held.append(("wav", wav))
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning(f"Streaming TTS failed for phrase {seq}: {e}")

        async with self._turn:
            await self._turn.wait_for(lambda: self._next == seq)
        for item in held:
            await self._put(item)
        async with self._turn:
            self._next += 1
            self._turn.notify_all()

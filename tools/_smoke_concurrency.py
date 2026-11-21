"""One-shot import/slot check for the concurrency gates."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.concurrency import configured_limit, gated
from telephony.adapters import exotel, twilio  # noqa: F401
from telephony.call_slots import (
    has_capacity,
    max_concurrent_calls,
    release_slot,
    try_acquire_slot,
)
from telephony.outbound import resolve_outbound_provider
from telephony.routes import common  # noqa: F401


async def main():
    print("max_concurrent_calls", max_concurrent_calls())
    print("outbound", resolve_outbound_provider())
    print("stt", configured_limit("x", "SARVAM_STT_MAX_INFLIGHT", 8))
    print("tts", configured_limit("x", "SARVAM_TTS_MAX_INFLIGHT", 8))
    print("claude", configured_limit("x", "CLAUDE_MAX_INFLIGHT", 8))
    assert await has_capacity()
    # Drain any leftover from a previous failed run under the live cap.
    while True:
        from telephony import call_slots as cs
        if cs._memory_active() <= 0:
            break
        await release_slot()
        if cs._memory_active() <= 0:
            break
    assert await try_acquire_slot()
    await release_slot()
    async with gated("smoke", "SARVAM_TTS_MAX_INFLIGHT", 8):
        pass
    # Cap=1 refuse path
    os.environ["MAX_CONCURRENT_CALLS"] = "1"
    assert await try_acquire_slot()
    assert not await try_acquire_slot()
    await release_slot()
    os.environ["MAX_CONCURRENT_CALLS"] = "8"
    print("slots ok")


if __name__ == "__main__":
    asyncio.run(main())

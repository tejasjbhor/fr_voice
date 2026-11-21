"""
Process-local concurrency gates.

Vendor plans (Sarvam, Claude) cap how hard we may hit them. These semaphores
are *our* side of that contract: they keep one process from stampeding past
the account limit and turning every live call into 429s.

Limits come from env so operators can match the dashboard without a code
change. 0 = unlimited (current PoC behaviour).
"""

from __future__ import annotations

import asyncio
import os
from typing import Dict, Tuple


def _env_int(name: str, default: int) -> int:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        return max(0, int(raw))
    except ValueError:
        return default


# Named gates so STT / TTS / Claude do not steal each other's slots.
_semaphores: Dict[str, Tuple[asyncio.AbstractEventLoop, asyncio.Semaphore | None, int]] = {}


def configured_limit(name: str, env_var: str, default: int) -> int:
    """Public so startup banners can print the live caps."""
    return _env_int(env_var, default)


def get_semaphore(name: str, env_var: str, default: int = 0) -> asyncio.Semaphore | None:
    """
    Return a semaphore for `name`, or None when the limit is 0 (unlimited).

    The semaphore is bound to the running event loop — tests that create a
    fresh loop get a fresh gate rather than a dead one from the previous run.
    """
    limit = _env_int(env_var, default)
    loop = asyncio.get_running_loop()
    cached = _semaphores.get(name)
    if cached is not None:
        cached_loop, sem, cached_limit = cached
        if cached_loop is loop and cached_limit == limit:
            return sem
    sem = None if limit <= 0 else asyncio.Semaphore(limit)
    _semaphores[name] = (loop, sem, limit)
    return sem


class gated:
    """
    `async with gated("sarvam_tts", "SARVAM_TTS_MAX_INFLIGHT", 8):`

    No-op when the configured limit is 0.
    """

    def __init__(self, name: str, env_var: str, default: int = 0):
        self._name = name
        self._env_var = env_var
        self._default = default
        self._sem: asyncio.Semaphore | None = None

    async def __aenter__(self):
        self._sem = get_semaphore(self._name, self._env_var, self._default)
        if self._sem is not None:
            await self._sem.acquire()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if self._sem is not None:
            self._sem.release()
        return False

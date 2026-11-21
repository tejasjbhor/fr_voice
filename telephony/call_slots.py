"""
Live-call capacity gate.

Before a WebSocket conversation starts (or before we dial out), acquire a
slot. When every slot is taken, refuse the new call quickly — accepting it
and letting every call go slow is worse than a busy tone.

Backends:
  memory   — one process (default). Fine for a single call_server.
  postgres — shared counter in the DB. Use when several call processes sit
             behind a load balancer and must share one MAX_CONCURRENT_CALLS.

MAX_CONCURRENT_CALLS=0 disables the gate (unlimited).
"""

from __future__ import annotations

import asyncio
import os
import threading
from contextlib import asynccontextmanager
from typing import Optional

from telephony.log import setup_logging

log = setup_logging()


def _env_int(name: str, default: int) -> int:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        return max(0, int(raw))
    except ValueError:
        return default


def max_concurrent_calls() -> int:
    return _env_int("MAX_CONCURRENT_CALLS", 0)


def slots_backend() -> str:
    raw = (os.getenv("CALL_SLOTS_BACKEND") or "memory").strip().lower()
    return raw if raw in ("memory", "postgres") else "memory"


# ── Process-local counter ─────────────────────────────────────────

_lock = threading.Lock()
_active = 0


def _memory_try_acquire(limit: int) -> bool:
    global _active
    with _lock:
        if _active >= limit:
            return False
        _active += 1
        return True


def _memory_release() -> None:
    global _active
    with _lock:
        _active = max(0, _active - 1)


def _memory_active() -> int:
    with _lock:
        return _active


# ── Postgres / SQLite shared counter ──────────────────────────────

_pg_ready = False
_pg_init_lock = asyncio.Lock()


def _ensure_table_sync() -> None:
    from sqlalchemy import text
    from core.db_engine import get_engine

    engine = get_engine()
    dialect = engine.dialect.name
    with engine.begin() as conn:
        if dialect == "sqlite":
            conn.execute(text(
                "CREATE TABLE IF NOT EXISTS call_capacity ("
                "  id INTEGER PRIMARY KEY CHECK (id = 1),"
                "  active INTEGER NOT NULL DEFAULT 0"
                ")"
            ))
            conn.execute(text(
                "INSERT OR IGNORE INTO call_capacity (id, active) VALUES (1, 0)"
            ))
        else:
            conn.execute(text(
                "CREATE TABLE IF NOT EXISTS call_capacity ("
                "  id INTEGER PRIMARY KEY CHECK (id = 1),"
                "  active INTEGER NOT NULL DEFAULT 0"
                ")"
            ))
            conn.execute(text(
                "INSERT INTO call_capacity (id, active) VALUES (1, 0) "
                "ON CONFLICT (id) DO NOTHING"
            ))


async def _ensure_table() -> None:
    global _pg_ready
    if _pg_ready:
        return
    async with _pg_init_lock:
        if _pg_ready:
            return
        await asyncio.to_thread(_ensure_table_sync)
        _pg_ready = True


def _pg_try_acquire_sync(limit: int) -> bool:
    from sqlalchemy import text
    from core.db_engine import get_engine

    engine = get_engine()
    with engine.begin() as conn:
        row = conn.execute(
            text(
                "UPDATE call_capacity SET active = active + 1 "
                "WHERE id = 1 AND active < :limit "
                "RETURNING active"
            ),
            {"limit": limit},
        ).fetchone()
        return row is not None


def _pg_release_sync() -> None:
    from sqlalchemy import text
    from core.db_engine import get_engine

    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text(
            "UPDATE call_capacity SET active = CASE "
            "WHEN active > 0 THEN active - 1 ELSE 0 END "
            "WHERE id = 1"
        ))


def _pg_active_sync() -> int:
    from sqlalchemy import text
    from core.db_engine import get_engine

    engine = get_engine()
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT active FROM call_capacity WHERE id = 1")
        ).fetchone()
        return int(row[0]) if row else 0


# ── Public API ────────────────────────────────────────────────────

async def has_capacity() -> bool:
    """Read-only: True when a new call may be accepted (or gate is off)."""
    limit = max_concurrent_calls()
    if limit <= 0:
        return True
    return (await active_calls()) < limit


async def try_acquire_slot() -> bool:
    """
    Reserve one live-call slot. True = proceed. False = refuse the call.

    Always True when MAX_CONCURRENT_CALLS is 0.
    """
    limit = max_concurrent_calls()
    if limit <= 0:
        return True

    backend = slots_backend()
    if backend == "postgres":
        await _ensure_table()
        ok = await asyncio.to_thread(_pg_try_acquire_sync, limit)
    else:
        ok = _memory_try_acquire(limit)

    if not ok:
        log.warning(
            f"Call refused — capacity full "
            f"(active>={limit}, backend={backend})"
        )
    return ok


async def release_slot() -> None:
    limit = max_concurrent_calls()
    if limit <= 0:
        return
    backend = slots_backend()
    if backend == "postgres":
        await _ensure_table()
        await asyncio.to_thread(_pg_release_sync)
    else:
        _memory_release()


async def active_calls() -> int:
    if max_concurrent_calls() <= 0:
        return _memory_active()
    if slots_backend() == "postgres":
        await _ensure_table()
        return await asyncio.to_thread(_pg_active_sync)
    return _memory_active()


def capacity_snapshot() -> dict:
    """Sync-ish view for /health and the startup banner (memory-fast path)."""
    limit = max_concurrent_calls()
    backend = slots_backend()
    active = _memory_active() if backend == "memory" else None
    return {
        "max_concurrent_calls": limit or None,
        "backend": backend if limit > 0 else "off",
        "active": active,
        "available": (None if limit <= 0 or active is None
                      else max(0, limit - active)),
    }


@asynccontextmanager
async def call_slot():
    """
    Acquire for the lifetime of one conversation.

    If acquire fails, yields False and does not release (nothing was taken).
    Caller must refuse the call when the yielded value is False.
    """
    ok = await try_acquire_slot()
    if not ok:
        yield False
        return
    try:
        yield True
    finally:
        await release_slot()

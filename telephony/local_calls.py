"""In-process local (dummy) calls — no Twilio/Exotel.

When TELEPHONY_PROVIDER=local, POST /call/outbound creates a session and
returns a PC URL. The developer talks (types) on that page; the Android app
refreshes the transcript after hang-up — same DB path as a real call.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from core.alert_engine import analyse
from core.database import (
    get_call_detail,
    save_alert,
    save_api_cost,
    save_conversation,
    save_health_record,
)
from core.extractor import deep_extract
from services.conversation_engine import run_text_turn
from services.session_manager import SessionManager
from shared.lang import load_lang_service
from telephony.config import SERVER_PORT, SERVER_PUBLIC_URL
from telephony.log import setup_logging

log = setup_logging()

_MAX_AGE_S = 2 * 60 * 60


@dataclass
class LocalCall:
    session_id: str
    user: dict
    language: str
    status: str  # active | ended
    session: SessionManager
    lang_service: Any
    greeting: str
    created_at: float = field(default_factory=time.time)
    ended_at: float | None = None


_CALLS: dict[str, LocalCall] = {}


def _purge_stale() -> None:
    now = time.time()
    dead = [k for k, c in _CALLS.items() if now - c.created_at > _MAX_AGE_S]
    for k in dead:
        _CALLS.pop(k, None)


def pc_call_url(session_id: str) -> str:
    """Always open on the developer PC, not the Android emulator host."""
    if SERVER_PUBLIC_URL and "onrender" not in SERVER_PUBLIC_URL.lower():
        base = SERVER_PUBLIC_URL.rstrip("/")
    else:
        base = f"http://127.0.0.1:{SERVER_PORT}"
    return f"{base}/local-call/{session_id}"


def _greeting_for(lang_service, name: str, history_summary) -> str:
    builder = getattr(lang_service, "build_greeting", None)
    if callable(builder):
        try:
            return builder(name, history_summary)
        except Exception:
            pass
    return lang_service.GREETING.format(name=name)


def start_local_call(user: dict, language: str | None = None) -> dict:
    """Create session + greeting; ready for /local-call/{id}."""
    _purge_stale()
    lang = (language or user.get("language") or "hi-IN").strip()
    lang_service = load_lang_service(lang)
    session = SessionManager(user, lang_service)
    name = session.user_name
    greeting = _greeting_for(lang_service, name, session.history_summary)
    session.record_sathi_turn(greeting, tts_chars=0)
    save_conversation(
        user["id"], session.session_id, "sathi", greeting,
        language=session.language, prompt_version=session.prompt_version,
    )
    call = LocalCall(
        session_id=session.session_id,
        user=user,
        language=lang,
        status="active",
        session=session,
        lang_service=lang_service,
        greeting=greeting,
    )
    _CALLS[session.session_id] = call
    url = pc_call_url(session.session_id)
    log.info(f"Local call started | {user.get('name')} | {session.session_id[:8]}… | {url}")
    return {
        "ok": True,
        "session_id": session.session_id,
        "local_call_url": url,
        "greeting": greeting,
        "user": {
            "id": user.get("id"),
            "name": user.get("name"),
            "phone": user.get("phone"),
            "language": lang,
        },
    }


def get_local_call(session_id: str) -> LocalCall | None:
    _purge_stale()
    return _CALLS.get(session_id)


def local_call_public(call: LocalCall) -> dict:
    detail = get_call_detail(call.user["id"], call.session_id) or {}
    return {
        "session_id": call.session_id,
        "status": call.status,
        "greeting": call.greeting,
        "user": {
            "id": call.user.get("id"),
            "name": call.user.get("name"),
            "phone": call.user.get("phone"),
            "language": call.language,
        },
        "turns": detail.get("turns") or [],
        "call_done": call.status == "ended" or call.session.is_call_done(),
        "local_call_url": pc_call_url(call.session_id),
    }


async def local_turn(session_id: str, user_text: str, *, speak: bool = True) -> dict:
    call = get_local_call(session_id)
    if not call:
        return {"error": "local call not found or expired", "status": 404}
    if call.status == "ended":
        return {"error": "call already ended", "status": 400, **local_call_public(call)}

    result = await run_text_turn(call.session, call.lang_service, user_text, speak=speak)
    if result.get("call_done"):
        await end_local_call(session_id)
        call = get_local_call(session_id) or call
    out = {**local_call_public(call), **result}
    out.pop("status", None)
    return out


async def end_local_call(session_id: str) -> dict:
    call = get_local_call(session_id)
    if not call:
        return {"error": "local call not found or expired", "status": 404}
    if call.status == "ended":
        return {"status": "ended", **local_call_public(call)}

    session = call.session
    user = call.user
    lang_svc = call.lang_service
    history = session.history or []
    if any(m.get("role") == "user" for m in history):
        conv_text = "\n".join(
            f"{'User' if m['role'] == 'user' else 'Sathi'}: {m['content']}"
            for m in history
        )
        try:
            health = await deep_extract(conv_text, lang_svc.NAME)
        except Exception as e:
            log.warning(f"Local deep_extract failed: {e}")
            health = {}
    else:
        health = {}

    fast = session.extracted or {}
    final = {**fast, **{k: v for k, v in health.items() if v is not None and v is not False}}
    if final:
        save_health_record(user["id"], session.session_id, final)
        log.info(f"Local call health saved: {final}")

    save_api_cost(
        user["id"], session.session_id,
        session.total_stt_sec, session.total_tts_chars, session.total_tokens,
        llm_cost_inr=session.llm_cost_inr,
        llm_cache_write_tokens=session.llm_cache_write_tokens,
        llm_cache_read_tokens=session.llm_cache_read_tokens,
    )
    level, reason = analyse(user["id"])
    if level in ("yellow", "orange", "red", "emergency"):
        family = user.get("family_name", "Family")
        save_alert(
            user["id"], session.session_id, level, reason,
            message=reason,
            sent_to=user.get("family_contact") or family,
        )

    call.status = "ended"
    call.ended_at = time.time()
    log.info(f"Local call ended | {session.session_id[:8]}… | alert={level}")
    return {"status": "ended", "alert": {"level": level, "reason": reason}, **local_call_public(call)}


def active_local_count() -> int:
    _purge_stale()
    return sum(1 for c in _CALLS.values() if c.status == "active")

"""Append-only JSONL store for inbound query call outcomes."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from inbound import config

_ROOT = Path(__file__).resolve().parent.parent


def _path() -> Path:
    p = Path(config.QUERIES_PATH)
    if not p.is_absolute():
        p = _ROOT / p
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def save_query(record: dict[str, Any]) -> str:
    """
    Append one call record. Returns the path written.
    Never raises to the call loop — failures are logged by the caller.
    """
    row = dict(record)
    row.setdefault("saved_at", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    path = _path()
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return str(path)


def ensure_inbound_guest(phone: str = "", language: str | None = None) -> dict | None:
    """
    Create or reuse a non-healthcare user row for an unknown inbound caller.
    schedule_enabled=False so the daily Saathi dialer never rings them.
    """
    from core.database import get_user_by_phone, normalize_phone, upsert_demo_user

    phone_n = normalize_phone(phone) or ""
    lang = language or config.guess_language(phone_n)
    if lang not in config.SUPPORTED_LANGUAGES:
        lang = config.DEFAULT_LANGUAGE

    if phone_n:
        existing = get_user_by_phone(phone_n)
        if existing:
            # Do not overwrite a real elder's language/name mid-flight.
            if (existing.get("account_role") or "") == "inbound_guest":
                return existing
            return existing

    digits = "".join(c for c in phone_n if c.isdigit())
    tail = digits[-4:] if digits else "guest"
    name = f"Caller {tail}" if phone_n else "Caller"
    # Placeholder E.164 if the carrier sent no CLI — still unique enough for PoC.
    guest_phone = phone_n or f"+1999{int(time.time()) % 10_000_000:07d}"
    return upsert_demo_user(
        name=name,
        phone=guest_phone,
        language=lang,
        account_role="inbound_guest",
        schedule_enabled=False,
        consent_calls=True,
        consent_recording=True,
        consent_health=False,
    )

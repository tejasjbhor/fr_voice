"""
edu/lead_store.py — leads and call dispositions.

Deliberately on its own tables, created here rather than added to
core/models.py. Two reasons:

1. This package is meant to drop into the Saathicare tree without touching it.
   Adding columns to core/models.py means an Alembic revision, and CLAUDE.md
   documents exactly how badly that can go wrong in this repo — `setup_database()`
   can stamp a database as migrated without migrating it, and the whole Alembic
   call is wrapped in a bare except that falls back to `create_all()`, which
   adds missing tables but never missing columns.

2. `create_all()` on new tables is the one thing that fallback DOES handle
   correctly, so a self-contained pair of new tables is the safest possible
   schema change to make here.

When multi-tenancy lands, fold these into core/models.py with a proper
migration and an `institution_id` foreign key on both. The column names below
are already chosen with that in mind.

Uses the engine from core/db_engine.py, so it follows DATABASE_URL and works on
both SQLite and Postgres exactly as the rest of the app does.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    func,
    select,
)

from core.db_engine import get_engine

metadata = MetaData()

# One row per lead. `phone` is the key rather than a foreign key to users.id,
# because an admissions lead is not an account holder — most of them will never
# register for anything.
edu_leads = Table(
    "edu_leads",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("phone", String(32), nullable=False, unique=True, index=True),
    Column("name", String(120)),
    Column("language", String(16), default="en-IN"),
    Column("source", String(64)),           # where the lead came from
    Column("status", String(32), default="new"),
    Column("score", Integer, default=0),
    Column("slots_json", Text),             # accumulated qualification slots
    Column("attempts", Integer, default=0),
    Column("last_attempt_at", DateTime(timezone=True)),
    Column("suppressed", Boolean, default=False),
    Column("suppressed_reason", String(64)),
    Column("consent_source", String(64)),   # how they came to be callable
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
)

# One row per call. Kept separate from `conversations` (which stores turns) so
# a disposition can be revised by a counsellor without touching the transcript.
edu_call_outcomes = Table(
    "edu_call_outcomes",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("phone", String(32), index=True),
    Column("session_id", String(64), index=True),
    Column("language", String(16)),
    Column("prompt_version", String(96), index=True),
    Column("outcome", String(32), index=True),
    Column("score", Integer, default=0),
    Column("turns", Integer, default=0),
    Column("escalation_reason", String(32)),
    Column("unanswered_questions", Integer, default=0),
    Column("slots_json", Text),
    Column("next_action", Text),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
)

_READY = False


def ensure_tables() -> None:
    """Create the two tables if they are absent. Safe to call repeatedly."""
    global _READY
    if _READY:
        return
    metadata.create_all(get_engine())
    _READY = True


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── Leads ─────────────────────────────────────────────────────────


def upsert_lead(phone: str, **fields) -> None:
    if not phone:
        return
    ensure_tables()
    engine = get_engine()
    with engine.begin() as conn:
        existing = conn.execute(
            select(edu_leads.c.id).where(edu_leads.c.phone == phone)
        ).first()
        if existing:
            conn.execute(
                edu_leads.update().where(edu_leads.c.phone == phone).values(**fields)
            )
        else:
            conn.execute(edu_leads.insert().values(phone=phone, **fields))


def get_lead(phone: str) -> dict | None:
    if not phone:
        return None
    ensure_tables()
    with get_engine().connect() as conn:
        row = conn.execute(
            select(edu_leads).where(edu_leads.c.phone == phone)
        ).mappings().first()
    return dict(row) if row else None


def get_lead_history(phone: str) -> dict:
    """Context for the greeting: has this family been called before, and what
    did we learn last time. Shape matches what build_greeting expects."""
    if not phone:
        return {}
    ensure_tables()
    lead = get_lead(phone)
    if not lead:
        return {}
    with get_engine().connect() as conn:
        calls = conn.execute(
            select(edu_call_outcomes.c.outcome)
            .where(edu_call_outcomes.c.phone == phone)
            .order_by(edu_call_outcomes.c.id.desc())
            .limit(5)
        ).scalars().all()
    return {
        "previous_calls": len(calls),
        "last_outcome": calls[0] if calls else None,
        "slots": json.loads(lead.get("slots_json") or "{}"),
        "attempts": lead.get("attempts") or 0,
        "suppressed": bool(lead.get("suppressed")),
    }


def note_attempt(phone: str) -> None:
    """Record that we dialled. Called before the call connects, so a lead that
    rings out still counts against the attempt cap."""
    if not phone:
        return
    ensure_tables()
    lead = get_lead(phone) or {}
    upsert_lead(
        phone,
        attempts=(lead.get("attempts") or 0) + 1,
        last_attempt_at=_now(),
    )


# ── Outcomes ──────────────────────────────────────────────────────


def save_call_outcome(
    *,
    phone: str,
    session_id: str,
    language: str | None,
    prompt_version: str | None,
    result: dict,
) -> None:
    ensure_tables()
    engine = get_engine()
    slots_json = json.dumps(result.get("slots") or {}, ensure_ascii=False)

    with engine.begin() as conn:
        conn.execute(
            edu_call_outcomes.insert().values(
                phone=phone,
                session_id=session_id,
                language=language,
                prompt_version=prompt_version,
                outcome=result.get("outcome"),
                score=result.get("score", 0),
                turns=result.get("turns", 0),
                escalation_reason=result.get("escalation_reason"),
                unanswered_questions=result.get("unanswered_questions", 0),
                slots_json=slots_json,
                next_action=result.get("next_action"),
            )
        )

    fields = {
        "status": result.get("outcome"),
        "score": result.get("score", 0),
        "slots_json": slots_json,
    }
    # A suppression is permanent and must survive any later campaign import.
    if result.get("suppress"):
        fields["suppressed"] = True
        fields["suppressed_reason"] = result.get("outcome")
    upsert_lead(phone, **fields)


def suppress(phone: str, reason: str = "manual") -> None:
    upsert_lead(phone, suppressed=True, suppressed_reason=reason)

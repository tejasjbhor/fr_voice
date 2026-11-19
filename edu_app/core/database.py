"""
database.py — DB operations for AI Sathi (SQLAlchemy + Alembic)

Local default: SQLite via DB_PATH / DATABASE_URL
Production:    PostgreSQL via DATABASE_URL

Schema changes: alembic revision --autogenerate -m "..." && alembic upgrade head
Bootstrap:      python core/database.py   (runs migrations + seeds)
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone as dt_timezone

from colorama import Fore, Style
from dotenv import load_dotenv
from sqlalchemy import func, inspect, select

try:
    from core.console_utf8 import configure_console_utf8
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from core.console_utf8 import configure_console_utf8

from core.db_engine import get_engine, get_session_factory, resolve_database_url
from core.models import Alert, ApiCost, Base, Conversation, HealthRecord, User

# Public re-exports used by dashboard / telephony helpers
__all__ = [
    "setup_database",
    "seed_test_user",
    "sync_user_from_env",
    "get_default_user",
    "get_session_factory",
    "save_conversation",
    "save_health_record",
    "save_api_cost",
    "get_recent_records",
    "get_session_history",
    "get_total_cost_summary",
    "check_alert_needed",
    "get_all_active_users",
    "get_user_by_phone",
    "get_calls_for_user",
    "get_call_detail",
    "normalize_phone",
    "upsert_demo_user",
    "list_users_by_family_contact",
    "update_user_profile",
    "get_alerts_for_user",
    "save_alert",
    "get_all_alerts",
    "get_weekly_history",
    "list_recent_sessions",
    "deactivate_user",
    "mark_last_scheduled",
    "recordings_info",
    "ensure_invite_code",
    "get_user_by_invite_code",
    "accept_invite",
    "refresh_invite_code",
    "invite_url_for",
]

load_dotenv()
configure_console_utf8()

# Back-compat for anything still reading DB_PATH
DB_PATH = os.getenv("DB_PATH", "sathi_poc.db")


def _model_to_dict(obj) -> dict | None:
    if obj is None:
        return None
    data = {c.key: getattr(obj, c.key) for c in obj.__table__.columns}
    for key in ("created_at", "recorded_at", "sent_at", "consent_at", "plan_activated_at", "invite_accepted_at"):
        if key in data and isinstance(data[key], datetime):
            data[key] = data[key]
    # Match old sqlite integer flags for callers that expect 0/1
    for key in (
        "active", "acknowledged", "headache", "dizziness",
        "chest_discomfort", "breathing_ok", "body_pain",
        "has_smartphone", "schedule_enabled",
        "consent_calls", "consent_recording", "consent_health",
    ):
        if key in data and isinstance(data[key], bool):
            data[key] = int(data[key])
    return data


def get_connection():
    """
    Legacy name — returns a SQLAlchemy Session.
    Prefer get_session_factory() for new code.
    """
    return get_session_factory()()


def _alembic_config():
    from alembic.config import Config

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cfg = Config(os.path.join(root, "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", resolve_database_url())
    return cfg


def run_migrations() -> None:
    """Apply Alembic migrations to head (idempotent)."""
    from alembic import command

    command.upgrade(_alembic_config(), "head")


def setup_database():
    """
    Create/upgrade schema via Alembic.
    Existing PoC SQLite DBs (tables present, no alembic_version) are stamped to head.
    Falls back to create_all if Alembic is unavailable.
    """
    import logging

    url = resolve_database_url()
    label = url.split("@")[-1] if "@" in url else url
    print(f"\n{Fore.CYAN}Setting up database ({label})...{Style.RESET_ALL}")

    # Alembic is noisy; keep console clean during call_server startup
    logging.getLogger("alembic").setLevel(logging.WARNING)

    try:
        from alembic import command

        engine = get_engine()
        tables = set(inspect(engine).get_table_names())
        cfg = _alembic_config()

        if "users" in tables and "alembic_version" not in tables:
            command.stamp(cfg, "head")
            print(f"{Fore.GREEN}✅ Existing schema stamped as Alembic head{Style.RESET_ALL}")
        else:
            command.upgrade(cfg, "head")
            print(f"{Fore.GREEN}✅ Migrations applied (Alembic head){Style.RESET_ALL}")
    except Exception as e:
        print(f"{Fore.YELLOW}⚠️  Alembic upgrade failed ({e}); using create_all{Style.RESET_ALL}")
        Base.metadata.create_all(bind=get_engine())
        print(f"{Fore.GREEN}✅ All tables created successfully!{Style.RESET_ALL}")


def seed_test_user():
    """Insert a default test user if none exist."""
    with get_session_factory()() as s:
        count = s.scalar(select(func.count()).select_from(User)) or 0
        if count == 0:
            user_name = os.getenv("USER_NAME", "Ramesh")
            language = os.getenv("USER_LANGUAGE", "fr-FR")
            user = User(
                name=user_name,
                age=70,
                language=language,
                family_name="Priya",
                call_time="09:00",
                active=True,
            )
            s.add(user)
            s.commit()
            print(f"{Fore.GREEN}✅ Test user '{user_name}' created (id={user.id}){Style.RESET_ALL}")
        else:
            print(f"{Fore.YELLOW}ℹ️  Users already exist, skipping seed{Style.RESET_ALL}")


def sync_user_from_env():
    """
    Apply USER_LANGUAGE / USER_NAME / USER_PHONE from .env to the active POC user.
    Reloads .env each call so edits take effect without restarting the process.
    """
    load_dotenv(override=True)

    language = (os.getenv("USER_LANGUAGE") or "fr-FR").strip()
    name = (os.getenv("USER_NAME") or "").strip()
    phone = (os.getenv("USER_PHONE") or "").strip()

    with get_session_factory()() as s:
        user = s.scalar(select(User).where(User.active.is_(True)).order_by(User.id).limit(1))
        if not user:
            return

        old_name, old_lang, old_phone = user.name, user.language, user.phone or ""
        new_name = name or old_name
        new_phone = phone or old_phone
        if new_name == old_name and language == old_lang and new_phone == old_phone:
            return

        user.name = new_name
        user.language = language
        user.phone = new_phone or None
        s.commit()
        phone_lbl = new_phone or "(no phone)"
        print(f"{Fore.GREEN}✅ Synced user from .env → {new_name} | {language} | {phone_lbl}{Style.RESET_ALL}")


def get_default_user():
    """Get first active user for POC."""
    with get_session_factory()() as s:
        user = s.scalar(select(User).where(User.active.is_(True)).order_by(User.id).limit(1))
        return _model_to_dict(user)


def save_conversation(user_id, session_id, role, message,
                      audio_duration=None, char_count=None,
                      language=None, prompt_version=None):
    """
    Save one conversation turn.

    `language` and `prompt_version` identify the pack and prompt that produced
    the turn. Pass them from the language service (lang_svc.CODE /
    lang_svc.PROMPT_VERSION) rather than leaving them to be derived later —
    see the note on the columns in core/models.py.
    """
    if not (message or "").strip():
        return
    with get_session_factory()() as s:
        s.add(Conversation(
            user_id=user_id,
            session_id=session_id,
            role=role,
            message=message,
            audio_duration=audio_duration,
            char_count=char_count,
            language=language,
            prompt_version=prompt_version,
        ))
        s.commit()


def save_health_record(user_id, session_id, data: dict):
    """Save extracted health data from conversation."""
    with get_session_factory()() as s:
        s.add(HealthRecord(
            user_id=user_id,
            session_id=session_id,
            bp_systolic=data.get("bp_systolic"),
            bp_diastolic=data.get("bp_diastolic"),
            sugar_fasting=data.get("sugar_fasting"),
            sugar_pp=data.get("sugar_pp"),
            pulse=data.get("pulse"),
            sleep_quality=data.get("sleep_quality"),
            food_intake=data.get("food_intake"),
            water_intake=data.get("water_intake"),
            energy_level=data.get("energy_level"),
            mood=data.get("mood"),
            headache=bool(data.get("headache", False)),
            dizziness=bool(data.get("dizziness", False)),
            chest_discomfort=bool(data.get("chest_discomfort", False)),
            breathing_ok=bool(data.get("breathing_ok", True)),
            body_pain=bool(data.get("body_pain", False)),
            notes=data.get("notes", "") or "",
        ))
        s.commit()


def save_api_cost(user_id, session_id,
                  stt_seconds=0, tts_chars=0, llm_tokens=0,
                  llm_cost_inr=0,
                  llm_cache_write_tokens=0, llm_cache_read_tokens=0):
    """
    Track API costs per session. llm_cost_inr = Claude cost in ₹.

    The cache figures come straight off the session's UsageMeter. They are
    already included in llm_tokens (which is the whole prompt plus output);
    they are stored separately so a call where the persona cache engaged can be
    told apart from one where it silently did not.
    """
    STT_RATE = 30 / 3600
    TTS_RATE = 30 / 10000

    stt_cost = round(stt_seconds * STT_RATE, 4)
    tts_cost = round(tts_chars * TTS_RATE, 4)
    llm_cost = round(llm_cost_inr, 4)
    total = round(stt_cost + tts_cost + llm_cost, 4)

    with get_session_factory()() as s:
        s.add(ApiCost(
            user_id=user_id,
            session_id=session_id,
            stt_seconds=stt_seconds,
            stt_cost_inr=stt_cost,
            tts_chars=tts_chars,
            tts_cost_inr=tts_cost,
            llm_tokens=llm_tokens,
            llm_cache_write_tokens=llm_cache_write_tokens,
            llm_cache_read_tokens=llm_cache_read_tokens,
            llm_cost_inr=llm_cost,
            total_cost_inr=total,
        ))
        s.commit()
    return {"stt": stt_cost, "tts": tts_cost, "total": total}


def get_recent_records(user_id, days=7):
    """Get last N days of health records for trend analysis."""
    since = datetime.now(dt_timezone.utc) - timedelta(days=days)
    with get_session_factory()() as s:
        rows = s.scalars(
            select(HealthRecord)
            .where(HealthRecord.user_id == user_id, HealthRecord.recorded_at >= since)
            .order_by(HealthRecord.recorded_at.desc())
        ).all()
        return [_model_to_dict(r) for r in rows]


def get_session_history(session_id, user_id):
    """Get conversation history for current session (for LLM context)."""
    with get_session_factory()() as s:
        rows = s.execute(
            select(Conversation.role, Conversation.message)
            .where(Conversation.session_id == session_id, Conversation.user_id == user_id)
            .order_by(Conversation.created_at.asc())
            .limit(20)
        ).all()
        return [{"role": r.role, "message": r.message} for r in rows]


def get_total_cost_summary():
    """Show total API costs spent so far."""
    with get_session_factory()() as s:
        row = s.execute(
            select(
                func.count(func.distinct(ApiCost.session_id)).label("total_sessions"),
                func.coalesce(func.sum(ApiCost.stt_seconds), 0).label("total_stt_seconds"),
                func.coalesce(func.sum(ApiCost.stt_cost_inr), 0).label("total_stt_cost"),
                func.coalesce(func.sum(ApiCost.tts_chars), 0).label("total_tts_chars"),
                func.coalesce(func.sum(ApiCost.tts_cost_inr), 0).label("total_tts_cost"),
                func.coalesce(func.sum(ApiCost.total_cost_inr), 0).label("grand_total"),
            )
        ).one()
        return {
            "total_sessions": row.total_sessions,
            "total_stt_seconds": row.total_stt_seconds,
            "total_stt_cost": row.total_stt_cost,
            "total_tts_chars": row.total_tts_chars,
            "total_tts_cost": row.total_tts_cost,
            "grand_total": row.grand_total,
        }


def check_alert_needed(user_id):
    """
    Check recent records for alert triggers.
    Returns (alert_level, reason) or (None, None).
    """
    records = get_recent_records(user_id, days=7)
    if not records:
        return None, None

    poor_sleep = sum(1 for r in records if r.get("sleep_quality") == "poor")
    skipped_food = sum(1 for r in records if r.get("food_intake") == "skipped")
    low_mood = sum(1 for r in records if r.get("mood") == "low")
    dizziness = sum(1 for r in records if r.get("dizziness"))
    chest = any(r.get("chest_discomfort") for r in records)
    breathing = any(not r.get("breathing_ok", True) for r in records)

    reasons = []

    if chest or breathing:
        return "emergency", "Chest discomfort or breathing issue reported"

    if poor_sleep >= 5 or skipped_food >= 4:
        if poor_sleep >= 5:
            reasons.append(f"{poor_sleep} days poor sleep")
        if skipped_food >= 4:
            reasons.append(f"{skipped_food} days skipped meals")
        return "red", " | ".join(reasons)

    if poor_sleep >= 3 or skipped_food >= 2 or dizziness >= 2:
        if poor_sleep >= 3:
            reasons.append(f"{poor_sleep} days poor sleep")
        if skipped_food >= 2:
            reasons.append(f"{skipped_food} days skipped meals")
        if dizziness >= 2:
            reasons.append(f"{dizziness} days dizziness")
        return "orange", " | ".join(reasons)

    if low_mood >= 3:
        return "yellow", f"{low_mood} days of low mood"

    return "green", "All good"


def get_all_active_users():
    """Get all active users — used by scheduler to trigger daily calls."""
    with get_session_factory()() as s:
        rows = s.scalars(select(User).where(User.active.is_(True)).order_by(User.id)).all()
        return [_model_to_dict(r) for r in rows]


def get_user_by_phone(phone: str):
    """Get user by phone number — used by call_server to identify caller."""
    phone_n = normalize_phone(phone)
    if not phone_n:
        return None
    with get_session_factory()() as s:
        # Prefer exact E.164 match; also try without leading + (Twilio quirks).
        user = s.scalar(
            select(User).where(User.phone == phone_n, User.active.is_(True)).limit(1)
        )
        if user:
            return _model_to_dict(user)
        bare = phone_n.lstrip("+")
        user = s.scalar(
            select(User).where(User.phone == bare, User.active.is_(True)).limit(1)
        )
        return _model_to_dict(user)


_ALLOWED_LANGS = ("fr-FR", "en-IN")


def normalize_phone(phone: str) -> str:
    """Strip spaces; keep leading + and digits only (E.164-ish)."""
    raw = (phone or "").strip().replace(" ", "")
    if not raw:
        return ""
    if raw.startswith("+"):
        digits = "".join(c for c in raw[1:] if c.isdigit())
        return f"+{digits}" if digits else ""
    digits = "".join(c for c in raw if c.isdigit())
    return f"+{digits}" if digits else ""


def upsert_demo_user(
    name: str,
    phone: str,
    language: str = "fr-FR",
    call_time: str | None = None,
    family_name: str | None = None,
    family_contact: str | None = None,
    account_role: str | None = None,
    city: str | None = None,
    has_smartphone: bool | None = None,
    schedule_enabled: bool | None = None,
    timezone: str | None = None,
    days_of_week: str | None = None,
    consent_calls: bool | None = None,
    consent_recording: bool | None = None,
    consent_health: bool | None = None,
) -> dict | None:
    """
    Create or update an active user by phone.
    Name/language are overwritten; family/call_time only if provided so a
    later outbound dial does not wipe a Subscriber link.
    """
    phone_n = normalize_phone(phone)
    name_n = (name or "").strip()
    lang = (language or "fr-FR").strip()
    if lang not in _ALLOWED_LANGS:
        lang = "fr-FR"
    if not phone_n or not name_n:
        return None
    family_phone = normalize_phone(family_contact) if family_contact else ""
    time_n = (call_time or "").strip() or None
    role_n = (account_role or "").strip().lower() or None
    if role_n in ("family",):
        role_n = "subscriber"
    if role_n in ("companion",):
        role_n = "user"
    if role_n not in (None, "subscriber", "user"):
        role_n = "user"
    tz_n = (timezone or "").strip() or None
    days_n = _normalize_days(days_of_week) if days_of_week is not None else None

    with get_session_factory()() as s:
        user = s.scalar(
            select(User).where(User.phone == phone_n).order_by(User.id).limit(1)
        )
        now = datetime.now(dt_timezone.utc)
        consents = any(x is True for x in (consent_calls, consent_recording, consent_health))
        if user:
            user.name = name_n
            user.language = lang
            user.active = True
            if time_n:
                user.call_time = time_n
            if family_name:
                user.family_name = family_name.strip()
            if family_phone:
                user.family_contact = family_phone
            if role_n:
                user.account_role = role_n
            if city is not None:
                user.city = city.strip() or None
            if has_smartphone is not None:
                user.has_smartphone = bool(has_smartphone)
            if schedule_enabled is not None:
                user.schedule_enabled = bool(schedule_enabled)
            if tz_n:
                user.timezone = tz_n
            if days_n:
                user.days_of_week = days_n
            if consent_calls is not None:
                user.consent_calls = bool(consent_calls)
            if consent_recording is not None:
                user.consent_recording = bool(consent_recording)
            if consent_health is not None:
                user.consent_health = bool(consent_health)
            if consents:
                user.consent_at = now
            if (role_n or user.account_role or "user") == "user" and not user.invite_code:
                user.invite_code = _new_invite_code(s)
            s.commit()
            s.refresh(user)
            return _model_to_dict(user)

        user = User(
            name=name_n,
            age=70,
            language=lang,
            phone=phone_n,
            family_name=(family_name or "").strip() or "Family",
            family_contact=family_phone or None,
            call_time=time_n or "09:00",
            active=True,
            account_role=role_n or "user",
            city=(city or "").strip() or None,
            has_smartphone=bool(has_smartphone) if has_smartphone is not None else False,
            schedule_enabled=True if schedule_enabled is None else bool(schedule_enabled),
            timezone=tz_n or "Asia/Kolkata",
            days_of_week=days_n or "1,2,3,4,5,6,7",
            consent_calls=bool(consent_calls),
            consent_recording=bool(consent_recording),
            consent_health=bool(consent_health),
            consent_at=now if consents else None,
            invite_code=_new_invite_code(s) if (role_n or "user") == "user" else None,
        )
        s.add(user)
        s.commit()
        s.refresh(user)
        return _model_to_dict(user)


def _new_invite_code(session) -> str:
    import secrets
    import string

    alphabet = string.ascii_uppercase + string.digits
    for _ in range(20):
        code = "".join(secrets.choice(alphabet) for _ in range(8))
        exists = session.scalar(select(User.id).where(User.invite_code == code).limit(1))
        if not exists:
            return code
    raise RuntimeError("could not allocate invite code")


def ensure_invite_code(user_id: int) -> dict | None:
    """Ensure an elder row has a shareable invite_code."""
    with get_session_factory()() as s:
        user = s.get(User, user_id)
        if not user or not user.active:
            return None
        if (user.account_role or "user") == "subscriber":
            return _model_to_dict(user)
        if not user.invite_code:
            user.invite_code = _new_invite_code(s)
            s.commit()
            s.refresh(user)
        return _model_to_dict(user)


def get_user_by_invite_code(code: str) -> dict | None:
    raw = (code or "").strip().upper()
    if not raw:
        return None
    with get_session_factory()() as s:
        user = s.scalar(
            select(User).where(User.invite_code == raw, User.active.is_(True)).limit(1)
        )
        return _model_to_dict(user)


def accept_invite(code: str, phone: str) -> dict | None:
    """Elder accepts invite: phone must match the person the subscriber added."""
    raw = (code or "").strip().upper()
    phone_n = normalize_phone(phone)
    if not raw or not phone_n:
        return None
    with get_session_factory()() as s:
        user = s.scalar(
            select(User).where(User.invite_code == raw, User.active.is_(True)).limit(1)
        )
        if not user:
            return None
        if normalize_phone(user.phone or "") != phone_n:
            return None
        user.account_role = "user"
        user.has_smartphone = True
        user.invite_accepted_at = datetime.now(dt_timezone.utc)
        s.commit()
        s.refresh(user)
        return _model_to_dict(user)


def refresh_invite_code(user_id: int) -> dict | None:
    """Rotate invite code (old links stop working). Clears accepted flag."""
    with get_session_factory()() as s:
        user = s.get(User, user_id)
        if not user or not user.active:
            return None
        user.invite_code = _new_invite_code(s)
        user.invite_accepted_at = None
        s.commit()
        s.refresh(user)
        return _model_to_dict(user)


def invite_url_for(code: str | None) -> str | None:
    if not code:
        return None
    base = (os.getenv("SERVER_PUBLIC_URL") or "").rstrip("/")
    if not base:
        base = "https://saathicare-plj8.onrender.com"
    return f"{base}/?invite={code}"


def _normalize_days(raw: str | None) -> str:
    parts = []
    for bit in str(raw or "").replace(" ", "").split(","):
        if bit in {"1", "2", "3", "4", "5", "6", "7"}:
            parts.append(bit)
    return ",".join(parts) if parts else "1,2,3,4,5,6,7"


def list_users_by_family_contact(phone: str) -> list[dict]:
    """Elders linked to a Subscriber phone (users.family_contact)."""
    phone_n = normalize_phone(phone)
    if not phone_n:
        return []
    bare = phone_n.lstrip("+")
    with get_session_factory()() as s:
        rows = list(s.scalars(
            select(User)
            .where(
                User.active.is_(True),
                User.family_contact.in_((phone_n, bare, f"+{bare}")),
            )
            .order_by(User.id)
        ).all())
        return [_model_to_dict(r) for r in rows]


def update_user_profile(phone: str, **fields) -> dict | None:
    """Patch name / language / call_time / family_* / schedule / city on an existing user."""
    phone_n = normalize_phone(phone)
    if not phone_n:
        return None
    allowed = {
        "name", "language", "call_time", "family_name", "family_contact", "active",
        "city", "has_smartphone", "schedule_enabled", "timezone", "days_of_week",
        "skip_on", "plan_status", "account_role",
        "consent_calls", "consent_recording", "consent_health",
    }
    with get_session_factory()() as s:
        user = s.scalar(
            select(User).where(User.phone == phone_n).order_by(User.id).limit(1)
        )
        if not user:
            bare = phone_n.lstrip("+")
            user = s.scalar(
                select(User).where(User.phone.in_((bare, f"+{bare}"))).limit(1)
            )
        if not user:
            return None
        for key, value in fields.items():
            if key not in allowed or value is None:
                continue
            if key == "language":
                lang = str(value).strip()
                if lang not in _ALLOWED_LANGS:
                    continue
                user.language = lang
            elif key == "family_contact":
                user.family_contact = normalize_phone(str(value)) or None
            elif key == "name":
                name_n = str(value).strip()
                if name_n:
                    user.name = name_n
            elif key == "call_time":
                raw = str(value).strip()
                user.call_time = raw[:5] if raw else user.call_time
            elif key == "family_name":
                user.family_name = str(value).strip() or user.family_name
            elif key == "active":
                user.active = bool(value)
            elif key == "city":
                user.city = str(value).strip() or None
            elif key == "has_smartphone":
                user.has_smartphone = bool(value)
            elif key == "schedule_enabled":
                user.schedule_enabled = bool(value)
            elif key == "timezone":
                tz = str(value).strip() or "Asia/Kolkata"
                user.timezone = tz
            elif key == "days_of_week":
                user.days_of_week = _normalize_days(str(value))
            elif key == "skip_on":
                user.skip_on = str(value).strip()[:10] or None
            elif key == "plan_status":
                user.plan_status = str(value).strip() or "none"
                if user.plan_status in ("test", "active"):
                    user.plan_activated_at = datetime.now(dt_timezone.utc)
            elif key == "account_role":
                role = str(value).strip().lower()
                if role in ("family",):
                    role = "subscriber"
                if role in ("companion",):
                    role = "user"
                if role in ("subscriber", "user"):
                    user.account_role = role
            elif key in ("consent_calls", "consent_recording", "consent_health"):
                setattr(user, key, bool(value))
                if bool(value):
                    user.consent_at = datetime.now(dt_timezone.utc)
        s.commit()
        s.refresh(user)
        return _model_to_dict(user)


def deactivate_user(phone: str) -> dict | None:
    """Soft-delete: stop calls and hide from lists. History rows stay."""
    return update_user_profile(
        phone,
        active=False,
        schedule_enabled=False,
        plan_status="cancelled",
    )


def mark_last_scheduled(user_id: int, day: str) -> None:
    with get_session_factory()() as s:
        user = s.get(User, user_id)
        if not user:
            return
        user.last_scheduled_on = day
        s.commit()


def recordings_info() -> dict:
    root = os.path.abspath(os.getenv("RECORDINGS_DIR", "recordings"))
    os.makedirs(root, exist_ok=True)
    wavs = 0
    try:
        wavs = sum(1 for n in os.listdir(root) if n.lower().endswith(".wav"))
    except OSError:
        pass
    return {"dir": root, "wav_files": wavs}


def get_alerts_for_user(user_id: int, limit: int = 20) -> list[dict]:
    with get_session_factory()() as s:
        rows = list(s.scalars(
            select(Alert)
            .where(Alert.user_id == user_id)
            .order_by(Alert.sent_at.desc())
            .limit(limit)
        ).all())
        out = []
        for a in rows:
            d = _model_to_dict(a)
            if d and d.get("sent_at"):
                d["sent_at"] = _iso(d["sent_at"])
            out.append(d)
        return out


def _iso(value):
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def get_calls_for_user(user_id: int, limit: int = 20) -> list[dict]:
    """Recent call sessions for one user, newest first."""
    with get_session_factory()() as s:
        grouped = s.execute(
            select(
                Conversation.session_id,
                func.min(Conversation.created_at).label("started_at"),
                func.max(Conversation.created_at).label("ended_at"),
                func.count(Conversation.id).label("turns"),
            )
            .where(Conversation.user_id == user_id)
            .group_by(Conversation.session_id)
            .order_by(func.max(Conversation.created_at).desc())
            .limit(limit)
        ).all()

        out = []
        for row in grouped:
            user_turns = s.scalar(
                select(func.count(Conversation.id)).where(
                    Conversation.user_id == user_id,
                    Conversation.session_id == row.session_id,
                    Conversation.role == "user",
                )
            ) or 0
            preview_row = s.scalar(
                select(Conversation)
                .where(
                    Conversation.user_id == user_id,
                    Conversation.session_id == row.session_id,
                    Conversation.role == "user",
                )
                .order_by(Conversation.created_at.desc())
                .limit(1)
            )
            health = s.scalar(
                select(HealthRecord)
                .where(
                    HealthRecord.user_id == user_id,
                    HealthRecord.session_id == row.session_id,
                )
                .order_by(HealthRecord.recorded_at.desc())
                .limit(1)
            )
            alert = s.scalar(
                select(Alert)
                .where(Alert.user_id == user_id, Alert.session_id == row.session_id)
                .order_by(Alert.sent_at.desc())
                .limit(1)
            )
            out.append({
                "session_id": row.session_id,
                "started_at": _iso(row.started_at),
                "ended_at": _iso(row.ended_at),
                "turns": int(row.turns or 0),
                "user_turns": int(user_turns),
                "preview": (preview_row.message[:140] if preview_row else ""),
                "has_health": health is not None,
                "alert_level": alert.alert_level if alert else None,
            })
        return out


def get_call_detail(user_id: int, session_id: str) -> dict | None:
    """Transcript + health + alert for one session."""
    with get_session_factory()() as s:
        turns = list(s.scalars(
            select(Conversation)
            .where(
                Conversation.user_id == user_id,
                Conversation.session_id == session_id,
            )
            .order_by(Conversation.created_at.asc())
        ).all())
        if not turns:
            return None
        health = s.scalar(
            select(HealthRecord)
            .where(
                HealthRecord.user_id == user_id,
                HealthRecord.session_id == session_id,
            )
            .order_by(HealthRecord.recorded_at.desc())
            .limit(1)
        )
        alert = s.scalar(
            select(Alert)
            .where(Alert.user_id == user_id, Alert.session_id == session_id)
            .order_by(Alert.sent_at.desc())
            .limit(1)
        )
        return {
            "session_id": session_id,
            "started_at": _iso(turns[0].created_at),
            "ended_at": _iso(turns[-1].created_at),
            "turns": [
                {
                    "role": t.role,
                    "message": t.message,
                    "created_at": _iso(t.created_at),
                }
                for t in turns
                if (t.message or "").strip()
            ],
            "health": _model_to_dict(health) if health else None,
            "alert": _model_to_dict(alert) if alert else None,
        }


def save_alert(user_id, session_id, alert_level, trigger_reason, message="", sent_to=None):
    """Persist an alert row (optional helper for production paths)."""
    with get_session_factory()() as s:
        s.add(Alert(
            user_id=user_id,
            session_id=session_id,
            alert_level=alert_level,
            trigger_reason=trigger_reason,
            message=message,
            sent_to=sent_to,
        ))
        s.commit()


def get_all_alerts(limit: int = 50) -> list[dict]:
    with get_session_factory()() as s:
        rows = list(s.scalars(
            select(Alert).order_by(Alert.sent_at.desc()).limit(limit)
        ).all())
        out = []
        for a in rows:
            d = _model_to_dict(a) or {}
            d["sent_at"] = _iso(d.get("sent_at"))
            user = s.get(User, a.user_id) if a.user_id else None
            d["user_name"] = user.name if user else None
            d["user_phone"] = user.phone if user else None
            out.append(d)
        return out


def get_weekly_history(user_id: int, weeks: int = 52) -> list[dict]:
    """Last N weeks of check-ins from health_records (empty days stay empty)."""
    records = get_recent_records(user_id, days=weeks * 7)
    by_day: dict[str, dict] = {}
    for r in records:
        dt = r.get("recorded_at")
        if isinstance(dt, datetime):
            key = dt.astimezone(dt_timezone.utc).date().isoformat()
        else:
            key = str(dt)[:10]
        by_day[key] = r

    today = datetime.now(dt_timezone.utc).date()
    out = []
    for w in range(weeks):
        days = []
        for d in range(6, -1, -1):
            day = today - timedelta(days=w * 7 + d)
            rec = by_day.get(day.isoformat())
            days.append({
                "date": day.isoformat(),
                "has_record": rec is not None,
                "food": bool(rec and rec.get("food_intake") and rec.get("food_intake") != "skipped"),
                "sleep": bool(rec and rec.get("sleep_quality") and rec.get("sleep_quality") != "poor"),
                "bp": bool(rec and rec.get("bp_systolic")),
                "medicines": bool(rec and rec.get("energy_level") and rec.get("energy_level") != "low"),
                "flag": bool(rec and (
                    rec.get("headache") or rec.get("chest_discomfort")
                    or rec.get("dizziness") or rec.get("breathing_ok") == 0
                )),
            })
        out.append({
            "start": days[0]["date"],
            "end": days[-1]["date"],
            "days": days,
        })
    return out


def list_recent_sessions(limit: int = 40) -> list[dict]:
    """Recent call sessions across all users (admin)."""
    with get_session_factory()() as s:
        grouped = s.execute(
            select(
                Conversation.session_id,
                Conversation.user_id,
                func.min(Conversation.created_at).label("started_at"),
                func.max(Conversation.created_at).label("ended_at"),
                func.count(Conversation.id).label("turns"),
            )
            .group_by(Conversation.session_id, Conversation.user_id)
            .order_by(func.max(Conversation.created_at).desc())
            .limit(limit)
        ).all()
        out = []
        for row in grouped:
            user = s.get(User, row.user_id) if row.user_id else None
            alert = s.scalar(
                select(Alert)
                .where(Alert.session_id == row.session_id)
                .order_by(Alert.sent_at.desc())
                .limit(1)
            )
            out.append({
                "session_id": row.session_id,
                "user_id": row.user_id,
                "user_name": user.name if user else None,
                "user_phone": user.phone if user else None,
                "language": user.language if user else None,
                "started_at": _iso(row.started_at),
                "ended_at": _iso(row.ended_at),
                "turns": int(row.turns or 0),
                "alert_level": alert.alert_level if alert else None,
            })
        return out


if __name__ == "__main__":
    print(f"\n{Fore.CYAN}{'='*50}")
    print("  AI Sathi — Database Setup")
    print(f"{'='*50}{Style.RESET_ALL}\n")
    setup_database()
    seed_test_user()
    print(f"\n{Fore.GREEN}✅ Database ready! You can now run main.py{Style.RESET_ALL}\n")

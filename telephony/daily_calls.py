"""Daily Saathi calls from inside the web process (Render has no extra worker).

Also reachable as POST /api/scheduler/tick with CRON_SECRET so a free cron
(cron-job.org) can wake a sleeping instance.

Flexibility per elder:
  call_time, timezone, days_of_week, schedule_enabled, skip_on (YYYY-MM-DD)
Catch-up: if Render slept through the exact minute, still dial within
SCHEDULER_CATCHUP_MINUTES (default 120).
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from core.database import get_all_active_users, mark_last_scheduled
from telephony.log import setup_logging

log = setup_logging()


def _tz(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name or "Asia/Kolkata")
    except Exception:
        return ZoneInfo("Asia/Kolkata")


def _local_now(tz_name: str) -> datetime:
    return datetime.now(timezone.utc).astimezone(_tz(tz_name))


def _truthy(val) -> bool:
    if val in (True, 1, "1", "true", "True"):
        return True
    if val in (False, 0, "0", "false", "False", None):
        return False
    return bool(val)


def user_is_due(user: dict, now_utc: datetime | None = None) -> bool:
    if not _truthy(user.get("active")):
        return False
    if (user.get("account_role") or "user") == "subscriber":
        return False
    if not _truthy(user.get("schedule_enabled") if user.get("schedule_enabled") is not None else True):
        return False
    if not user.get("phone"):
        return False

    tz_name = user.get("timezone") or "Asia/Kolkata"
    now = (now_utc or datetime.now(timezone.utc)).astimezone(_tz(tz_name))
    today = now.strftime("%Y-%m-%d")
    if user.get("last_scheduled_on") == today:
        return False
    if user.get("skip_on") == today:
        return False

    days = str(user.get("days_of_week") or "1,2,3,4,5,6,7").replace(" ", "")
    if str(now.isoweekday()) not in days.split(","):
        return False

    raw = (user.get("call_time") or "09:00")[:5]
    try:
        hh, mm = [int(x) for x in raw.split(":")]
    except ValueError:
        return False
    scheduled = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    catchup = int(os.getenv("SCHEDULER_CATCHUP_MINUTES") or "120")
    delta = (now - scheduled).total_seconds()
    return 0 <= delta <= catchup * 60


def due_users(now_utc: datetime | None = None) -> list[dict]:
    return [u for u in get_all_active_users() if user_is_due(u, now_utc)]


async def tick() -> dict:
    """Place due calls. Safe to run every 30s — last_scheduled_on blocks repeats.

    Pace outbound to OUTBOUND_CPS (calls per second). Carrier accounts reject
    a blast of simultaneous dials even when channels are free. Cap also
    respects MAX_CONCURRENT_CALLS via place_outbound_call.
    """
    import asyncio

    from telephony.routes.app_api import _dial_number

    cps = float(os.getenv("OUTBOUND_CPS") or "2")
    gap = (1.0 / cps) if cps > 0 else 0.0

    due = due_users()
    placed = []
    errors = []
    for i, user in enumerate(due):
        today = _local_now(user.get("timezone") or "Asia/Kolkata").strftime("%Y-%m-%d")
        mark_last_scheduled(user["id"], today)
        ok = False
        try:
            ok = await _dial_number(user["phone"])
        except Exception as e:
            errors.append({"phone": user.get("phone"), "error": str(e)})
            log.warning(f"Scheduled dial failed {user.get('phone')}: {e}")
        placed.append({
            "id": user.get("id"),
            "phone": user.get("phone"),
            "name": user.get("name"),
            "ok": bool(ok),
        })
        log.info(f"Scheduled call → {user.get('name')} {user.get('phone')} ok={ok}")
        if gap > 0 and i + 1 < len(due):
            await asyncio.sleep(gap)
    return {"due": len(due), "placed": placed, "errors": errors}


def scheduler_enabled() -> bool:
    raw = (os.getenv("SCHEDULER_ENABLED") or "1").strip().lower()
    return raw not in ("0", "false", "no", "off")

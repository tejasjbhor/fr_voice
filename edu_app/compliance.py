"""
edu/compliance.py — may we ring this number, right now?

Saathicare's consent model assumes the person asked to be phoned every day:
`consent_calls`, `consent_recording` and `consent_health` are set by someone who
signed up. An admissions lead list carries no such assumption. Outbound calling
to a list a school bought, scraped or collected at an expo is commercial
calling, and in India that sits under TRAI's UCC regulations with DLT
registration, consent scoping and preference-list obligations attached.

This module is a technical gate, not legal advice. It enforces the things code
can enforce — a calling window, an attempt cap, a cooling-off period between
attempts, and a hard suppression list that outlives any campaign import. It
does not and cannot tell you whether a given lead list is lawful to call. Get
that answered before the first campaign, not after the first complaint.

Call `check()` before dialling. Every refusal is a reason string you can log
and report on, because "why did we not call these four hundred leads" is a
question a school will ask.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from edu import config

REFUSALS = (
    "suppressed",
    "outside_window",
    "too_many_attempts",
    "too_soon",
    "no_consent_record",
    "no_phone",
)

HUMAN_READABLE = {
    "suppressed": "This number is on the do-not-call list.",
    "outside_window": "Outside the permitted calling window.",
    "too_many_attempts": "Attempt cap reached for this lead.",
    "too_soon": "Called too recently; cooling-off period not elapsed.",
    "no_consent_record": "No recorded basis for contacting this number.",
    "no_phone": "No phone number on the lead.",
}


def _parse_hhmm(value: str, default: tuple[int, int]) -> tuple[int, int]:
    try:
        hh, mm = value.strip().split(":")
        return int(hh), int(mm)
    except Exception:
        return default


def within_calling_window(now: datetime | None = None) -> bool:
    """Local-time window. `now` should already be in the institution's
    timezone — passing a UTC datetime here is the obvious way to get this
    wrong, so callers must convert first."""
    now = now or datetime.now()
    start_h, start_m = _parse_hhmm(config.CALLING_WINDOW_START, (9, 0))
    end_h, end_m = _parse_hhmm(config.CALLING_WINDOW_END, (20, 0))
    minutes = now.hour * 60 + now.minute
    return (start_h * 60 + start_m) <= minutes <= (end_h * 60 + end_m)


def check(
    lead: dict | None,
    now: datetime | None = None,
    require_consent_record: bool = True,
) -> tuple[bool, str | None]:
    """(allowed, refusal_reason)."""
    if not lead or not lead.get("phone"):
        return False, "no_phone"

    if lead.get("suppressed"):
        return False, "suppressed"

    if require_consent_record and not (lead.get("consent_source") or "").strip():
        return False, "no_consent_record"

    if not within_calling_window(now):
        return False, "outside_window"

    attempts = lead.get("attempts") or 0
    if attempts >= config.MAX_ATTEMPTS_PER_LEAD:
        return False, "too_many_attempts"

    last = lead.get("last_attempt_at")
    if last:
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        gap = datetime.now(timezone.utc) - last
        if gap < timedelta(hours=config.MIN_HOURS_BETWEEN_ATTEMPTS):
            return False, "too_soon"

    return True, None


def explain(reason: str | None) -> str:
    return HUMAN_READABLE.get(reason or "", "")

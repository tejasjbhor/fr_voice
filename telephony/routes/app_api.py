"""JSON APIs for the Saathi Care mobile app (subscriber + user + admin)."""

from datetime import datetime
import os

from fastapi import FastAPI, Query, Request
from fastapi.responses import FileResponse, JSONResponse

from core.alert_engine import analyse
from core.database import (
    accept_invite,
    deactivate_user,
    ensure_invite_code,
    get_alerts_for_user,
    get_all_active_users,
    get_all_alerts,
    get_call_detail,
    get_calls_for_user,
    get_recent_records,
    get_total_cost_summary,
    get_user_by_invite_code,
    get_user_by_phone,
    get_weekly_history,
    invite_url_for,
    list_recent_sessions,
    list_users_by_family_contact,
    normalize_phone,
    recordings_info,
    refresh_invite_code,
    save_alert,
    update_user_profile,
    upsert_demo_user,
)
from telephony.auth import can_access_phone, forbid, open_dialer, require_account, same_phone
from telephony.config import TELEPHONY_PROVIDER
from telephony.log import setup_logging
from telephony.otp import (
    ADMIN_PIN,
    TEST_OTP,
    admin_pin_ok,
    allow_test_otp,
    mint_token,
    request_otp,
    verify_otp,
)

log = setup_logging()

_ALLOWED_LANGS = {"hi-IN", "mr-IN", "en-IN", "es-ES", "fr-FR"}
_ALLOWED_ROLES = {"subscriber", "family", "user", "companion"}


def _jsonable(obj):
    if obj is None:
        return None
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_jsonable(x) for x in obj]
    return obj


def _user_public(user: dict) -> dict:
    code = user.get("invite_code")
    return {
        "id": user.get("id"),
        "name": user.get("name"),
        "phone": user.get("phone"),
        "language": user.get("language"),
        "call_time": user.get("call_time"),
        "family_name": user.get("family_name"),
        "family_contact": user.get("family_contact"),
        "active": user.get("active"),
        "account_role": user.get("account_role") or "user",
        "city": user.get("city"),
        "has_smartphone": bool(user.get("has_smartphone")),
        "schedule_enabled": bool(user.get("schedule_enabled") if user.get("schedule_enabled") is not None else True),
        "timezone": user.get("timezone") or "Asia/Kolkata",
        "days_of_week": user.get("days_of_week") or "1,2,3,4,5,6,7",
        "skip_on": user.get("skip_on"),
        "last_scheduled_on": user.get("last_scheduled_on"),
        "plan_status": user.get("plan_status") or "none",
        "consent_calls": bool(user.get("consent_calls")),
        "consent_recording": bool(user.get("consent_recording")),
        "consent_health": bool(user.get("consent_health")),
        "invite_code": code,
        "invite_url": invite_url_for(code),
        "invite_accepted": bool(user.get("invite_accepted_at")),
    }


def _phone_gate(request: Request, phone: str):
    acc, err = require_account(request)
    if err:
        return None, None, err
    if not can_access_phone(acc, phone):
        return None, None, forbid()
    user, uerr = _require_user(phone)
    if uerr:
        return acc, None, uerr
    return acc, user, None


def _health_public(h: dict | None) -> dict | None:
    if not h:
        return None
    keys = (
        "bp_systolic", "bp_diastolic", "sugar_fasting", "sugar_pp", "pulse",
        "sleep_quality", "food_intake", "water_intake", "energy_level", "mood",
        "headache", "dizziness", "chest_discomfort", "breathing_ok", "body_pain",
        "notes", "recorded_at", "session_id",
    )
    return _jsonable({k: h.get(k) for k in keys})


def _require_user(phone: str):
    phone_n = normalize_phone(phone)
    if not phone_n:
        return None, JSONResponse({"error": "phone required (E.164)"}, status_code=400)
    user = get_user_by_phone(phone_n)
    if not user:
        return None, JSONResponse({"error": "no user for this phone yet"}, status_code=404)
    return user, None


def _parse_json(request_body: dict | None) -> dict:
    return request_body if isinstance(request_body, dict) else {}


async def user_summary(request: Request, phone: str = Query(..., description="E.164 phone of the person who received the call")):
    acc, user, err = _phone_gate(request, phone)
    if err:
        return err
    uid = user["id"]
    calls = get_calls_for_user(uid, limit=12)
    last = None
    if calls:
        last = get_call_detail(uid, calls[0]["session_id"])
        if last:
            last["health"] = _health_public(last.get("health"))
            last["alert"] = _jsonable(last.get("alert"))
            last["turns"] = _jsonable(last.get("turns") or [])
    records = get_recent_records(uid, days=14)
    latest_health = _health_public(records[0]) if records else None
    level, reason = analyse(uid)
    alerts = get_alerts_for_user(uid, limit=8)
    return JSONResponse(_jsonable({
        "user": _user_public(user),
        "alert": {"level": level, "reason": reason},
        "latest_health": latest_health,
        "last_call": last,
        "calls": calls,
        "alerts": alerts,
    }))


async def user_calls(request: Request, phone: str = Query(...)):
    acc, user, err = _phone_gate(request, phone)
    if err:
        return err
    return JSONResponse({"user": _user_public(user), "calls": get_calls_for_user(user["id"], limit=30)})


async def user_call_detail(request: Request, session_id: str, phone: str = Query(...)):
    acc, user, err = _phone_gate(request, phone)
    if err:
        return err
    detail = get_call_detail(user["id"], session_id)
    if not detail:
        return JSONResponse({"error": "call not found"}, status_code=404)
    detail["health"] = _health_public(detail.get("health"))
    detail["alert"] = _jsonable(detail.get("alert"))
    detail["turns"] = _jsonable(detail.get("turns") or [])
    return JSONResponse(_jsonable({"user": _user_public(user), "call": detail}))


async def user_health(request: Request, phone: str = Query(...), days: int = Query(14, ge=1, le=90)):
    acc, user, err = _phone_gate(request, phone)
    if err:
        return err
    rows = get_recent_records(user["id"], days=days)
    return JSONResponse(_jsonable({
        "user": _user_public(user),
        "health": [_health_public(r) for r in rows],
    }))


async def user_alerts(request: Request, phone: str = Query(...)):
    acc, user, err = _phone_gate(request, phone)
    if err:
        return err
    return JSONResponse(_jsonable({
        "user": _user_public(user),
        "alerts": get_alerts_for_user(user["id"], limit=30),
    }))


async def register_account(request: Request):
    """Create a Subscriber or User row. Consent flags are required."""
    try:
        body = _parse_json(await request.json())
    except Exception:
        return JSONResponse({"error": "invalid JSON"}, status_code=400)

    role = (body.get("role") or "user").strip().lower()
    if role not in _ALLOWED_ROLES:
        return JSONResponse({"error": "role must be subscriber or user"}, status_code=400)
    name = (body.get("name") or "").strip()
    phone = normalize_phone(body.get("phone") or "")
    language = (body.get("language") or "hi-IN").strip()
    if language not in _ALLOWED_LANGS:
        language = "hi-IN"
    if not name or not phone:
        return JSONResponse({"error": "name and phone required"}, status_code=400)

    consent_calls = bool(body.get("consent_calls") or body.get("consent"))
    consent_recording = bool(body.get("consent_recording") or body.get("consent"))
    consent_health = bool(body.get("consent_health") or body.get("consent"))
    if not (consent_calls and consent_recording and consent_health):
        return JSONResponse(
            {"error": "consent_calls, consent_recording and consent_health are required"},
            status_code=400,
        )

    acc_role = "subscriber" if role in ("subscriber", "family") else "user"
    user = upsert_demo_user(
        name=name,
        phone=phone,
        language=language,
        family_name=(body.get("family_name") or "").strip() or None,
        family_contact=body.get("family_contact") or body.get("subscriber_phone"),
        account_role=acc_role,
        consent_calls=True,
        consent_recording=True,
        consent_health=True,
    )
    if not user:
        return JSONResponse({"error": "could not save user"}, status_code=400)
    log.info(f"Registered {acc_role} | id={user.get('id')} | {phone}")
    return JSONResponse({"status": "ok", "role": acc_role, "user": _user_public(user)})


async def list_people(request: Request, subscriber_phone: str = Query(...)):
    acc, err = require_account(request)
    if err:
        return err
    phone = normalize_phone(subscriber_phone)
    if not phone:
        return JSONResponse({"error": "subscriber_phone required"}, status_code=400)
    if not same_phone(acc.get("phone"), phone):
        return forbid()
    people = [_user_public(u) for u in list_users_by_family_contact(phone)]
    # Backfill invite codes for people added before this feature.
    out = []
    for p in people:
        if not p.get("invite_code") and p.get("id"):
            refreshed = ensure_invite_code(p["id"])
            out.append(_user_public(refreshed) if refreshed else p)
        else:
            out.append(p)
    return JSONResponse({"subscriber_phone": phone, "people": out})


async def add_person(request: Request):
    """Subscriber adds an elder they care for."""
    try:
        body = _parse_json(await request.json())
    except Exception:
        return JSONResponse({"error": "invalid JSON"}, status_code=400)

    sub_phone = normalize_phone(body.get("subscriber_phone") or "")
    acc, err = require_account(request)
    if err:
        return err
    if not same_phone(acc.get("phone"), sub_phone):
        return forbid()
    sub_name = (body.get("subscriber_name") or body.get("family_name") or "").strip() or "Family"
    name = (body.get("name") or "").strip()
    phone = normalize_phone(body.get("phone") or "")
    language = (body.get("language") or "hi-IN").strip()
    call_time = (body.get("call_time") or "09:00").strip()
    if language not in _ALLOWED_LANGS:
        language = "hi-IN"
    if not sub_phone or not name or not phone:
        return JSONResponse(
            {"error": "subscriber_phone, name and phone required"},
            status_code=400,
        )
    user = upsert_demo_user(
        name=name,
        phone=phone,
        language=language,
        call_time=call_time,
        family_name=sub_name,
        family_contact=sub_phone,
        account_role="user",
        city=(body.get("city") or "").strip() or None,
        has_smartphone=bool(body.get("has_smartphone")),
        timezone=(body.get("timezone") or "Asia/Kolkata").strip(),
        days_of_week=body.get("days_of_week"),
        schedule_enabled=True if body.get("schedule_enabled") is None else bool(body.get("schedule_enabled")),
        consent_calls=True,
        consent_recording=True,
        consent_health=True,
    )
    if not user:
        return JSONResponse({"error": "could not save person"}, status_code=400)
    user = ensure_invite_code(user["id"]) or user
    log.info(f"Linked person {phone} → subscriber {sub_phone} invite={user.get('invite_code')}")
    return JSONResponse({"status": "ok", "user": _user_public(user)})


async def invite_preview(code: str):
    """Public: elder opens shared link — no secrets beyond name/phone to join."""
    user = get_user_by_invite_code(code)
    if not user:
        return JSONResponse({"error": "invite not found or expired"}, status_code=404)
    return JSONResponse(_jsonable({
        "status": "ok",
        "invite_code": user.get("invite_code"),
        "name": user.get("name"),
        "phone": user.get("phone"),
        "language": user.get("language") or "hi-IN",
        "family_name": user.get("family_name") or "Family",
        "invite_accepted": bool(user.get("invite_accepted_at")),
        "invite_url": invite_url_for(user.get("invite_code")),
    }))


async def invite_refresh(request: Request):
    """Subscriber rotates the invite link for one person."""
    try:
        body = _parse_json(await request.json())
    except Exception:
        return JSONResponse({"error": "invalid JSON"}, status_code=400)
    phone = normalize_phone(body.get("phone") or "")
    acc, user, err = _phone_gate(request, phone)
    if err:
        return err
    if (acc.get("role") or "").lower() not in ("subscriber", "family"):
        # Elder can still refresh their own link if they own the phone
        if not same_phone(acc.get("phone"), phone):
            return forbid()
    updated = refresh_invite_code(user["id"])
    if not updated:
        return JSONResponse({"error": "could not refresh invite"}, status_code=400)
    return JSONResponse({"status": "ok", "user": _user_public(updated)})


async def invite_accept(request: Request):
    """Elder signs in with the person phone, then accepts the invite code."""
    try:
        body = _parse_json(await request.json())
    except Exception:
        return JSONResponse({"error": "invalid JSON"}, status_code=400)
    code = (body.get("invite_code") or body.get("code") or "").strip().upper()
    acc, err = require_account(request)
    if err:
        return err
    phone = normalize_phone(body.get("phone") or acc.get("phone") or "")
    if not code:
        return JSONResponse({"error": "invite_code required"}, status_code=400)
    if not same_phone(acc.get("phone"), phone):
        return forbid("sign in with the phone number on the invite")
    consent_calls = bool(body.get("consent_calls") or body.get("consent"))
    consent_recording = bool(body.get("consent_recording") or body.get("consent"))
    consent_health = bool(body.get("consent_health") or body.get("consent"))
    if not (consent_calls and consent_recording and consent_health):
        return JSONResponse(
            {"error": "consent_calls, consent_recording and consent_health are required"},
            status_code=400,
        )
    preview = get_user_by_invite_code(code)
    if not preview:
        return JSONResponse({"error": "invite not found or expired"}, status_code=404)
    # Keep profile in sync (name/language from form if provided)
    name = (body.get("name") or preview.get("name") or "").strip()
    language = (body.get("language") or preview.get("language") or "hi-IN").strip()
    upsert_demo_user(
        name=name or preview.get("name") or "User",
        phone=phone,
        language=language,
        family_name=preview.get("family_name"),
        family_contact=preview.get("family_contact"),
        account_role="user",
        has_smartphone=True,
        consent_calls=True,
        consent_recording=True,
        consent_health=True,
    )
    user = accept_invite(code, phone)
    if not user:
        return JSONResponse(
            {"error": "phone must match the number your family added for you"},
            status_code=403,
        )
    token = mint_token(phone, "user")
    return JSONResponse({
        "status": "ok",
        "role": "user",
        "token": token,
        "user": _user_public(user),
    })


async def update_user(request: Request):
    try:
        body = _parse_json(await request.json())
    except Exception:
        return JSONResponse({"error": "invalid JSON"}, status_code=400)
    phone = body.get("phone") or ""
    acc, user_row, err = _phone_gate(request, phone)
    if err:
        return err
    user = update_user_profile(
        phone,
        name=body.get("name"),
        language=body.get("language"),
        call_time=body.get("call_time"),
        family_name=body.get("family_name"),
        family_contact=body.get("family_contact") or body.get("subscriber_phone"),
        city=body.get("city"),
        has_smartphone=body.get("has_smartphone"),
        schedule_enabled=body.get("schedule_enabled"),
        timezone=body.get("timezone"),
        days_of_week=body.get("days_of_week"),
        skip_on=body.get("skip_on"),
    )
    if not user:
        return JSONResponse({"error": "no user for this phone yet"}, status_code=404)
    return JSONResponse({"status": "ok", "user": _user_public(user)})


async def user_sos(request: Request):
    """Record SOS, notify family by placing a Saathi call to family_contact.

    Does not dial 108. The User/Subscriber app can open the phone dialer for that.
    """
    try:
        body = _parse_json(await request.json())
    except Exception:
        return JSONResponse({"error": "invalid JSON"}, status_code=400)
    phone = normalize_phone(body.get("phone") or "")
    name = (body.get("name") or "").strip() or "User"
    language = (body.get("language") or "hi-IN").strip()
    if not phone:
        return JSONResponse({"error": "phone required"}, status_code=400)
    acc, err = require_account(request)
    if err:
        return err
    if not can_access_phone(acc, phone):
        return forbid()
    user = get_user_by_phone(phone)
    if not user:
        user = upsert_demo_user(name=name, phone=phone, language=language)
    if not user:
        return JSONResponse({"error": "could not save SOS user"}, status_code=400)
    family = normalize_phone(user.get("family_contact") or "")
    save_alert(
        user["id"],
        session_id="sos",
        alert_level="emergency",
        trigger_reason="SOS from the User app",
        message="I need help now",
        sent_to=family or user.get("family_name"),
    )
    family_dialed = False
    if family:
        family_dialed = await _dial_number(family)
        log.warning(f"SOS family dial {family} ok={family_dialed}")
    log.warning(f"SOS | user={user.get('id')} | {phone}")
    return JSONResponse({
        "status": "ok",
        "alert": {"level": "emergency", "reason": "SOS from the User app"},
        "family_contact": family or None,
        "family_dialed": family_dialed,
        "user": _user_public(user),
    })


async def _dial_number(to_number: str) -> bool:
    from telephony.outbound import place_outbound_call, resolve_outbound_provider

    if resolve_outbound_provider() == "local":
        from core.database import get_user_by_phone
        from telephony.local_calls import start_local_call
        user = get_user_by_phone(to_number)
        if not user:
            return False
        start_local_call(user, language=user.get("language"))
        return True
    ok, _err, _sid = await place_outbound_call(to_number)
    return bool(ok)


def _recording_path(session_id: str) -> str | None:
    root = os.path.abspath(os.getenv("RECORDINGS_DIR", "recordings"))
    if not os.path.isdir(root) or not session_id:
        return None
    needle = session_id[:8]
    for name in os.listdir(root):
        if needle in name and name.lower().endswith(".wav"):
            path = os.path.abspath(os.path.join(root, name))
            if path.startswith(root + os.sep) or path == root:
                return path
    return None


async def user_history(request: Request, phone: str = Query(...), weeks: int = Query(52, ge=1, le=52)):
    acc, user, err = _phone_gate(request, phone)
    if err:
        return err
    return JSONResponse(_jsonable({
        "user": _user_public(user),
        "weeks": get_weekly_history(user["id"], weeks=weeks),
    }))


async def user_call_audio(request: Request, session_id: str, phone: str = Query(...)):
    acc, user, err = _phone_gate(request, phone)
    if err:
        return err
    detail = get_call_detail(user["id"], session_id)
    if not detail:
        return JSONResponse({"error": "call not found"}, status_code=404)
    path = _recording_path(session_id)
    if not path:
        return JSONResponse({"error": "no recording file for this call"}, status_code=404)
    return FileResponse(path, media_type="audio/wav", filename=os.path.basename(path))


async def auth_request(request: Request):
    try:
        body = _parse_json(await request.json())
    except Exception:
        return JSONResponse({"error": "invalid JSON"}, status_code=400)
    from telephony.sms import send_otp_sms, sms_configured

    phone, code = request_otp(body.get("phone") or "")
    if not phone:
        return JSONResponse({"error": "phone required"}, status_code=400)

    payload = {
        "status": "ok",
        "phone": phone,
        "message": "Enter the 6-digit code",
        "test_otp_allowed": allow_test_otp(),
        "sms": False,
    }
    if sms_configured():
        ok, detail = send_otp_sms(phone, code)
        payload["sms"] = ok
        if not ok:
            log.warning(f"OTP SMS not sent ({detail})")
            if not allow_test_otp():
                return JSONResponse(
                    {"error": "could not send SMS login code", "detail": detail},
                    status_code=503,
                )
            payload["message"] = "SMS failed; development code still works"
    elif not allow_test_otp():
        return JSONResponse(
            {
                "error": "SMS login is not configured. Set SMS_OTP=true with Twilio, "
                "or ALLOW_TEST_OTP=1 for internal testing.",
            },
            status_code=503,
        )
    log.info(f"OTP for {phone}: {'(sms)' if payload['sms'] else code}")
    if allow_test_otp():
        payload["dev_otp"] = code
    return JSONResponse(payload)


async def auth_verify(request: Request):
    try:
        body = _parse_json(await request.json())
    except Exception:
        return JSONResponse({"error": "invalid JSON"}, status_code=400)
    phone = normalize_phone(body.get("phone") or "")
    code = body.get("otp") or body.get("code") or ""
    role = (body.get("role") or "subscriber").strip().lower()
    if role in ("family",):
        role = "subscriber"
    if role in ("companion",):
        role = "user"
    if not verify_otp(phone, code):
        return JSONResponse({"error": "invalid code"}, status_code=401)
    token = mint_token(phone, role)
    return JSONResponse({
        "status": "ok",
        "token": token,
        "phone": phone,
        "role": role,
        "name": (body.get("name") or "").strip(),
    })


async def auth_mode():
    from telephony.sms import sms_configured

    return JSONResponse({
        "test_otp_allowed": allow_test_otp(),
        "sms_configured": sms_configured(),
        "open_dialer": open_dialer(),
    })


async def me(request: Request):
    acc, err = require_account(request)
    if err:
        return err
    user = get_user_by_phone(acc.get("phone") or "")
    people = list_users_by_family_contact(acc.get("phone") or "")
    return JSONResponse(_jsonable({
        "account": acc,
        "user": _user_public(user) if user else None,
        "people": [_user_public(u) for u in people],
        "recordings": recordings_info(),
    }))


async def billing_test_activate(request: Request):
    """No money moves. Marks this account as a test subscriber so the UI can be exercised."""
    acc, err = require_account(request)
    if err:
        return err
    user = update_user_profile(acc.get("phone") or "", plan_status="test")
    if not user:
        user = upsert_demo_user(
            name=(acc.get("phone") or "Tester"),
            phone=acc.get("phone") or "",
            account_role=acc.get("role") or "subscriber",
            consent_calls=True,
            consent_recording=True,
            consent_health=True,
        )
        if user:
            user = update_user_profile(acc.get("phone") or "", plan_status="test")
    if not user:
        return JSONResponse({"error": "could not activate test plan"}, status_code=400)
    price = int(os.getenv("PLAN_PRICE_INR") or "499")
    return JSONResponse(_jsonable({
        "status": "ok",
        "plan_status": "test",
        "plan_price_inr": price,
        "note": "Test plan — nothing is charged. Razorpay/Stripe can replace this later.",
        "user": _user_public(user),
    }))


async def billing_cancel(request: Request):
    acc, err = require_account(request)
    if err:
        return err
    user = update_user_profile(acc.get("phone") or "", plan_status="cancelled")
    if not user:
        return JSONResponse({"error": "no account"}, status_code=404)
    return JSONResponse({"status": "ok", "plan_status": "cancelled", "user": _user_public(user)})


async def account_delete(request: Request):
    acc, err = require_account(request)
    if err:
        return err
    user = deactivate_user(acc.get("phone") or "")
    if not user:
        return JSONResponse({"error": "no account"}, status_code=404)
    return JSONResponse({"status": "ok", "deleted": True, "user": _user_public(user)})


async def scheduler_tick(request: Request):
    import hmac as hmac_mod

    from telephony.daily_calls import tick

    secret = (os.getenv("CRON_SECRET") or "").strip()
    got = (request.headers.get("x-cron-secret") or request.query_params.get("secret") or "").strip()
    if secret:
        if not hmac_mod.compare_digest(secret, got):
            return JSONResponse({"error": "cron secret required"}, status_code=401)
    else:
        err = _require_admin(request)
        if err:
            return err
    return JSONResponse(await tick())


def _require_admin(request: Request):
    pin = request.headers.get("x-admin-pin") or request.query_params.get("pin") or ""
    if not admin_pin_ok(pin):
        return JSONResponse({"error": "admin pin required"}, status_code=401)
    return None


async def admin_overview(request: Request):
    err = _require_admin(request)
    if err:
        return err
    users = get_all_active_users()
    costs = get_total_cost_summary()
    alerts = get_all_alerts(limit=20)
    subs = {u.get("family_contact") for u in users if u.get("family_contact")}
    hot = [a for a in alerts if a.get("alert_level") in ("orange", "red", "emergency")]
    price = int(os.getenv("PLAN_PRICE_INR") or "499")
    return JSONResponse(_jsonable({
        "users": len(users),
        "subscribers": len(subs),
        "calls": costs.get("total_sessions") or 0,
        "cost_inr": costs.get("grand_total") or 0,
        "mrr_inr": len(users) * price,
        "plan_price_inr": price,
        "escalations": hot[:8],
        "admin_pin_set": bool(ADMIN_PIN),
        "test_otp": TEST_OTP if os.getenv("APP_ENV", "development") != "production" else None,
    }))


async def admin_users(request: Request):
    err = _require_admin(request)
    if err:
        return err
    users = [_user_public(u) for u in get_all_active_users()]
    return JSONResponse({"users": users, "count": len(users)})


async def admin_escalations(request: Request):
    err = _require_admin(request)
    if err:
        return err
    return JSONResponse({"alerts": get_all_alerts(limit=50)})


async def admin_calls(request: Request):
    err = _require_admin(request)
    if err:
        return err
    return JSONResponse({"calls": list_recent_sessions(limit=40)})


async def admin_billing(request: Request):
    err = _require_admin(request)
    if err:
        return err
    users = get_all_active_users()
    costs = get_total_cost_summary()
    price = int(os.getenv("PLAN_PRICE_INR") or "499")
    return JSONResponse(_jsonable({
        "plan_price_inr": price,
        "people": len(users),
        "mrr_inr": len(users) * price,
        "api_costs": costs,
        "note": "₹499/person is displayed for the prototype. Payments are not charged yet.",
    }))


async def admin_languages(request: Request):
    err = _require_admin(request)
    if err:
        return err
    packs = [
        {"code": "hi-IN", "name": "Hindi", "tts": "Sarvam", "status": "live"},
        {"code": "mr-IN", "name": "Marathi", "tts": "Sarvam", "status": "live"},
        {"code": "en-IN", "name": "English", "tts": "Sarvam", "status": "live"},
        {"code": "es-ES", "name": "Spanish", "tts": "ElevenLabs", "status": "experimental"},
        {"code": "fr-FR", "name": "French", "tts": "Fish", "status": "live"},
    ]
    return JSONResponse({"packs": packs})


def register(app: FastAPI) -> None:
    app.get("/api/user/summary")(user_summary)
    app.get("/api/user/calls")(user_calls)
    app.get("/api/user/calls/{session_id}")(user_call_detail)
    app.get("/api/user/calls/{session_id}/audio")(user_call_audio)
    app.get("/api/user/health")(user_health)
    app.get("/api/user/history")(user_history)
    app.get("/api/user/alerts")(user_alerts)
    app.post("/api/register")(register_account)
    app.get("/api/people")(list_people)
    app.post("/api/people")(add_person)
    app.get("/api/invite/{code}")(invite_preview)
    app.post("/api/invite/refresh")(invite_refresh)
    app.post("/api/invite/accept")(invite_accept)
    app.post("/api/user/update")(update_user)
    app.post("/api/user/sos")(user_sos)
    app.post("/api/auth/request-otp")(auth_request)
    app.post("/api/auth/verify")(auth_verify)
    app.get("/api/auth/mode")(auth_mode)
    app.get("/api/me")(me)
    app.post("/api/billing/test-activate")(billing_test_activate)
    app.post("/api/billing/cancel")(billing_cancel)
    app.post("/api/account/delete")(account_delete)
    app.post("/api/scheduler/tick")(scheduler_tick)
    app.get("/api/admin/overview")(admin_overview)
    app.get("/api/admin/users")(admin_users)
    app.get("/api/admin/escalations")(admin_escalations)
    app.get("/api/admin/calls")(admin_calls)
    app.get("/api/admin/billing")(admin_billing)
    app.get("/api/admin/languages")(admin_languages)
    log.info(
        "Mobile APIs: auth, people, invite, summary, calls, audio, history, health, "
        "alerts, sos, billing-test, schedule-tick, admin/*"
    )

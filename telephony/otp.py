"""Test-friendly OTP + signed session tokens for the mobile / admin APIs."""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time

from core.database import normalize_phone

TEST_OTP = (os.getenv("TEST_OTP") or "123456").strip()
ADMIN_PIN = (os.getenv("ADMIN_PIN") or "2499").strip()
_SECRET = (os.getenv("APP_SECRET") or os.getenv("TWILIO_AUTH_TOKEN") or "saathi-dev-secret").encode()
_TTL = 60 * 60 * 24 * 14  # 14 days
_OTP_TTL = 600

# phone -> (otp, expires_at)
_otp_store: dict[str, tuple[str, float]] = {}


def _env_flag(name: str) -> bool:
    return (os.getenv(name) or "").strip().lower() in ("1", "true", "yes")


def is_dev() -> bool:
    return (os.getenv("APP_ENV") or "development").strip().lower() in (
        "development", "dev", "local", "test",
    )


def allow_test_otp() -> bool:
    if _env_flag("ALLOW_TEST_OTP"):
        return True
    return is_dev()


def request_otp(phone: str) -> tuple[str, str]:
    """Store a code. Development reuses TEST_OTP; SMS mode uses a random code."""
    phone_n = normalize_phone(phone)
    if not phone_n:
        return "", ""
    from telephony.sms import sms_configured

    if sms_configured():
        code = f"{secrets.randbelow(1_000_000):06d}"
    elif allow_test_otp():
        code = TEST_OTP or f"{secrets.randbelow(1_000_000):06d}"
    else:
        code = f"{secrets.randbelow(1_000_000):06d}"
    _otp_store[phone_n] = (code, time.time() + _OTP_TTL)
    return phone_n, code


def verify_otp(phone: str, code: str) -> bool:
    phone_n = normalize_phone(phone)
    got = (code or "").strip()
    if not phone_n or not got:
        return False
    row = _otp_store.get(phone_n)
    if row and row[1] >= time.time() and hmac.compare_digest(row[0], got):
        _otp_store.pop(phone_n, None)
        return True
    if allow_test_otp() and TEST_OTP:
        return hmac.compare_digest(TEST_OTP, got)
    return False


def mint_token(phone: str, role: str) -> str:
    phone_n = normalize_phone(phone)
    exp = int(time.time()) + _TTL
    payload = f"{phone_n}|{role}|{exp}"
    sig = hmac.new(_SECRET, payload.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{payload}|{sig}"


def read_token(token: str) -> dict | None:
    raw = (token or "").strip()
    if raw.lower().startswith("bearer "):
        raw = raw[7:].strip()
    parts = raw.split("|")
    if len(parts) != 4:
        return None
    phone, role, exp_s, sig = parts
    try:
        exp = int(exp_s)
    except ValueError:
        return None
    if exp < time.time():
        return None
    payload = f"{phone}|{role}|{exp}"
    expect = hmac.new(_SECRET, payload.encode(), hashlib.sha256).hexdigest()[:32]
    if not hmac.compare_digest(expect, sig):
        return None
    return {"phone": phone, "role": role, "exp": exp}


def admin_pin_ok(pin: str) -> bool:
    return bool(ADMIN_PIN) and hmac.compare_digest(str(pin or "").strip(), ADMIN_PIN)

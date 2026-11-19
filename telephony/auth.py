"""Bearer tokens for mobile APIs. Phone in the query string is not enough."""

from __future__ import annotations

import os

from fastapi import Request
from fastapi.responses import JSONResponse

from core.database import list_users_by_family_contact, normalize_phone
from telephony.otp import read_token


def _flag(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip().lower()


def open_dialer() -> bool:
    return _flag("OPEN_DIALER") in ("1", "true", "yes")


def account_from_request(request: Request) -> dict | None:
    auth = request.headers.get("authorization") or ""
    token = ""
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
    if not token:
        token = (request.headers.get("x-saathi-token") or "").strip()
    return read_token(token)


def require_account(request: Request):
    acc = account_from_request(request)
    if not acc:
        return None, JSONResponse({"error": "sign in required"}, status_code=401)
    return acc, None


def same_phone(a: str | None, b: str | None) -> bool:
    return bool(a) and bool(b) and normalize_phone(a) == normalize_phone(b)


def can_access_phone(account: dict, target_phone: str | None) -> bool:
    target = normalize_phone(target_phone or "")
    if not target:
        return False
    if same_phone(account.get("phone"), target):
        return True
    role = (account.get("role") or "").lower()
    if role in ("subscriber", "family"):
        elders = list_users_by_family_contact(account.get("phone") or "")
        return any(same_phone(u.get("phone"), target) for u in elders)
    return False


def forbid(msg: str = "not allowed for this account"):
    return JSONResponse({"error": msg}, status_code=403)

"""Smoke-test Plivo adapter: credentials, routes, XML — no live dial."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv(override=True)

import requests
from fastapi.testclient import TestClient

from telephony.config import PLIVO_AUTH_ID, PLIVO_AUTH_TOKEN, PLIVO_PHONE_NUMBER
from telephony.adapters import plivo as plivo_ad


def check_account() -> bool:
    if not PLIVO_AUTH_ID or not PLIVO_AUTH_TOKEN:
        print("FAIL credentials missing in .env")
        return False
    url = f"https://api.plivo.com/v1/Account/{PLIVO_AUTH_ID}/"
    r = requests.get(url, auth=(PLIVO_AUTH_ID, PLIVO_AUTH_TOKEN), timeout=20)
    print(f"Plivo Account API: {r.status_code}")
    if r.status_code != 200:
        print(r.text[:300])
        return False
    body = r.json()
    print(f"  account={body.get('account_type') or body.get('auth_id')} "
          f"cash={body.get('cash_credits')} "
          f"currency={body.get('account_type') and body.get('timezone')}")
    print(f"  number configured={PLIVO_PHONE_NUMBER}")
    return True


def check_routes() -> bool:
    # Avoid full DB lifespan side effects: mount only Plivo routes.
    from fastapi import FastAPI

    app = FastAPI()
    plivo_ad.register(app)
    c = TestClient(app)

    r = c.post(
        "/plivo/voice",
        data={
            "From": "+919876543210",
            "To": PLIVO_PHONE_NUMBER or "+912269854791",
            "Direction": "inbound",
            "CallUUID": "test-uuid",
        },
    )
    print(f"POST /plivo/voice → {r.status_code}")
    text = r.text
    ok = (
        r.status_code == 200
        and "<Stream" in text
        and "bidirectional" in text
        and "/plivo/media-stream" in text
    )
    print(f"  XML ok={ok}")
    if not ok:
        print(text[:400])
        return False

    r2 = c.post("/plivo/hangup", data={"CallUUID": "test-uuid", "Duration": "3"})
    print(f"POST /plivo/hangup → {r2.status_code}")
    return r2.status_code == 200


def main() -> int:
    print("=== Plivo smoke ===")
    a = check_account()
    b = check_routes()
    print("PASS" if (a and b) else "FAIL")
    return 0 if (a and b) else 1


if __name__ == "__main__":
    raise SystemExit(main())

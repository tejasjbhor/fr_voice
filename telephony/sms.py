"""Optional SMS OTP. No free India-wide SMS exists that we can ship.

Twilio trial can text *verified* numbers if TWILIO_* is already set and
SMS_OTP=true. Otherwise development keeps TEST_OTP. Production without SMS
refuses to send a code (callers can set ALLOW_TEST_OTP=1 for internal QA).
"""

from __future__ import annotations

import os

import httpx

from telephony.config import TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER
from telephony.log import setup_logging

log = setup_logging()


def sms_configured() -> bool:
    if (os.getenv("SMS_OTP") or "").strip().lower() not in ("1", "true", "yes"):
        return False
    return bool(TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and TWILIO_PHONE_NUMBER)


def send_otp_sms(phone: str, code: str) -> tuple[bool, str]:
    """Return (ok, detail). Never raises."""
    if not sms_configured():
        return False, "SMS_OTP is off (no free SMS provider wired)"
    url = (
        f"https://api.twilio.com/2010-04-01/Accounts/"
        f"{TWILIO_ACCOUNT_SID}/Messages.json"
    )
    try:
        with httpx.Client(timeout=15.0) as client:
            res = client.post(
                url,
                auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN),
                data={
                    "From": TWILIO_PHONE_NUMBER,
                    "To": phone,
                    "Body": f"Saathi Care login code: {code}. Valid 10 minutes.",
                },
            )
        if res.status_code in (200, 201):
            return True, "sent"
        return False, f"Twilio {res.status_code}: {res.text[:180]}"
    except Exception as e:
        log.warning(f"OTP SMS failed: {e}")
        return False, str(e)

"""Resolve the DB user for an incoming call from the caller's phone number."""

from typing import Optional

from core.database import get_default_user, get_user_by_phone
from telephony.config import APP_ENV, IS_PRODUCTION
from telephony.log import setup_logging

log = setup_logging()

# Logged once per process so a misconfigured deployment is obvious in the very
# first call's output rather than buried in every line.
_warned_dev_fallback = False


def resolve_user(phone: str = "") -> Optional[dict]:
    """
    Map a caller's number to their user record.

    Returns None when the caller cannot be identified, which the adapters treat
    as "close the WebSocket".

    Two PoC behaviours used to live here and both are unsafe with more than one
    real user:

      * sync_user_from_env() ran on every single call, rewriting the FIRST
        active user's name, language and phone from .env. With a populated user
        table that silently corrupts somebody's record on every call. It now
        runs only at server start (telephony/startup.py), where it is a
        deliberate single-user PoC convenience.

      * An unidentified caller fell through to get_default_user(), so their
        answers — blood pressure, sugar, mood — were written to user #1's
        health record. Mixing two people's medical history is worse than
        dropping the call, so in production we drop the call.
    """
    global _warned_dev_fallback

    if phone:
        user = get_user_by_phone(phone)
        if user:
            log.info(f"Caller {phone} → {user.get('name')} (id={user.get('id')})")
            return user
        log.warning(f"No active user registered for caller {phone}")
    else:
        log.warning("Call arrived without a caller number")

    if IS_PRODUCTION:
        log.error(
            "Refusing the call: an unidentified caller must not be attached to "
            "another user's health record. Register the number against a user."
        )
        return None

    user = get_default_user()
    if not _warned_dev_fallback:
        _warned_dev_fallback = True
        log.warning(
            f"APP_ENV={APP_ENV}: falling back to the default user "
            f"({user.get('name') if user else 'none'}) for unidentified callers. "
            f"Set APP_ENV=production to refuse these calls instead."
        )
    return user

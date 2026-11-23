"""
Place an outbound phone call on Exotel, Twilio, or Plivo.

TELEPHONY_PROVIDER remains the default. OUTBOUND_PROVIDER can override it
per deployment (twilio | exotel | frejun | plivo | auto). auto = TELEPHONY_PROVIDER.

Both inbound routes stay mounted regardless — a process can answer Twilio
and Plivo at once; only the dial direction needs an explicit choice.
"""

from __future__ import annotations

import os
from typing import Optional

from telephony.config import TELEPHONY_PROVIDER
from telephony.log import setup_logging

log = setup_logging()


def resolve_outbound_provider(override: Optional[str] = None) -> str:
    raw = (override or os.getenv("OUTBOUND_PROVIDER") or "auto").strip().lower()
    if raw in ("", "auto", "default"):
        return TELEPHONY_PROVIDER
    return raw


async def place_outbound_call(
    to_number: str, provider: Optional[str] = None
) -> tuple[bool, str | None, str | None]:
    """
    Dial `to_number` on the chosen carrier.

    Returns `(ok, error_code, call_sid)`.
    `error_code` is None on success, else one of:
      capacity_full | credentials | provider_error | unsupported | unknown_provider
    `call_sid` is set for Twilio when dial succeeds (for hangup from the UI).
    """
    from telephony.call_slots import active_calls, max_concurrent_calls

    limit = max_concurrent_calls()
    if limit > 0:
        active = await active_calls()
        if active >= limit:
            log.warning(
                f"Outbound skipped — capacity full "
                f"(active={active}, max={limit}) → {to_number}"
            )
            return False, "capacity_full", None

    chosen = resolve_outbound_provider(provider)

    if chosen == "twilio":
        from telephony.adapters.twilio import make_twilio_outbound_call
        sid = make_twilio_outbound_call(to_number)
        return (True, None, sid) if sid else (False, "provider_error", None)

    if chosen == "plivo":
        from telephony.adapters.plivo import make_plivo_outbound_call
        sid = make_plivo_outbound_call(to_number)
        return (True, None, sid) if sid else (False, "provider_error", None)

    if chosen == "exotel":
        from telephony.adapters.exotel import (
            exotel_websocket_url,
            make_exotel_outbound_call,
        )
        ok = bool(make_exotel_outbound_call(to_number, exotel_websocket_url()))
        return (True, None, None) if ok else (False, "provider_error", None)

    if chosen == "frejun":
        from telephony.adapters.frejun import make_frejun_outbound_call
        ok = bool(await make_frejun_outbound_call(to_number))
        return (True, None, None) if ok else (False, "provider_error", None)

    if chosen == "local":
        log.error("place_outbound_call does not start local mic sessions")
        return False, "unsupported", None

    log.error(f"Unknown outbound provider: {chosen}")
    return False, "unknown_provider", None

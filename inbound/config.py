"""
inbound/config.py — Inbound helpline product switch + knobs.

PRODUCT=inbound turns this on in telephony/session.py and user_resolver.py.
Unset or "health" leaves Saathicare unchanged. Mutually exclusive with
PRODUCT=education.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_ROOT, ".env"), override=True)

PRODUCT = (os.getenv("PRODUCT") or "health").strip().lower()
IS_INBOUND = PRODUCT in ("inbound", "helpline", "query")

AGENT_NAME = os.getenv("INBOUND_AGENT_NAME", "Sathi")
AGENT_ROLE = os.getenv("INBOUND_AGENT_ROLE", "helpline assistant")
SERVICE_NAME = os.getenv("INBOUND_SERVICE_NAME", "Sathi Helpline")

# One language per call (same limit as edu — STT is fixed for the call).
DEFAULT_LANGUAGE = os.getenv("INBOUND_DEFAULT_LANGUAGE", "hi-IN")
SUPPORTED_LANGUAGES = ("hi-IN", "mr-IN", "en-IN")

# Guess language from dialler country when the guest has no language set.
# +91 → Hindi default; everything else → English. Override per guest later.
def guess_language(phone: str = "") -> str:
    digits = "".join(c for c in (phone or "") if c.isdigit())
    if digits.startswith("91") and len(digits) >= 12:
        return DEFAULT_LANGUAGE if DEFAULT_LANGUAGE in SUPPORTED_LANGUAGES else "hi-IN"
    if len(digits) == 10:
        return DEFAULT_LANGUAGE if DEFAULT_LANGUAGE in SUPPORTED_LANGUAGES else "hi-IN"
    return "en-IN"


MAX_TURNS = int(os.getenv("INBOUND_MAX_CALL_TURNS", "20"))
WIND_DOWN_TURNS = int(os.getenv("INBOUND_WIND_DOWN_TURNS", "2"))
HISTORY_TURNS = int(os.getenv("INBOUND_HISTORY_TURNS", "12"))
MAX_CALL_COST_INR = float(os.getenv("INBOUND_MAX_CALL_COST_INR", "20"))

# Where query records are appended (JSONL). Relative to repo root OK.
QUERIES_PATH = os.getenv("INBOUND_QUERIES_PATH", "inbound/data/queries.jsonl")

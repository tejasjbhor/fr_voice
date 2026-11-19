"""
edu/config.py — Education product configuration.

Single-institution mode: everything here comes from the environment or from the
institution JSON file. When multi-tenancy lands, every value below becomes a
column on an `institutions` / `agent_configs` row and this module becomes the
loader that reads that row instead of os.environ. Keep the shape the same and
that migration is mechanical.

Nothing in this file imports from `edu.*`, so it is safe to import anywhere.
"""

import os

from dotenv import load_dotenv

load_dotenv()

# ── Product switch ────────────────────────────────────────────────
# The one flag telephony/session.py reads to decide which SessionManager and
# which language-pack loader to use. Unset or "health" leaves Saathicare
# behaving exactly as it does today.
PRODUCT = (os.getenv("PRODUCT") or "health").strip().lower()
IS_EDUCATION = PRODUCT in ("education", "edu")

# ── Institution ───────────────────────────────────────────────────
# Path to the institution JSON (see edu/data/institutions/ for the schema and a
# worked example). Everything the agent is allowed to state as fact comes from
# this file and nowhere else.
INSTITUTION_FILE = os.getenv(
    "INSTITUTION_FILE",
    "edu/data/institutions/xyz_international_school.json",
)

# ── Agent identity ────────────────────────────────────────────────
# Overridable per deployment; the institution file can also carry these, and
# the file wins when it sets them (see institution.Institution.agent_*).
AGENT_NAME = os.getenv("EDU_AGENT_NAME", "Aanya")
AGENT_ROLE = os.getenv("EDU_AGENT_ROLE", "admissions counsellor")

# ── Personality knobs ─────────────────────────────────────────────
# These are the dials the SaaS pitch eventually exposes in a UI. They render
# into named clauses in the persona (see edu/persona.py) rather than being
# pasted in as adjectives — "warmth: high" as a bare word in a prompt does
# almost nothing, whereas the sentence it maps to does.
#
#   tone       : warm | professional | energetic
#   formality  : low | medium | high
#   verbosity  : concise | balanced
#   sales      : none | low | medium      (how hard she pushes for the visit)
#   patience   : normal | high
TONE = os.getenv("EDU_TONE", "warm")
FORMALITY = os.getenv("EDU_FORMALITY", "medium")
VERBOSITY = os.getenv("EDU_VERBOSITY", "concise")
SALES_INTENSITY = os.getenv("EDU_SALES_INTENSITY", "low")
PATIENCE = os.getenv("EDU_PATIENCE", "high")

# ── Call shape ────────────────────────────────────────────────────
# Saathicare caps a call at 12 turns because a daily check-in that runs long is
# a worse check-in and costs more. An admissions call is the opposite: a parent
# who is still asking questions at turn 20 is the best lead on the list, and
# cutting them off is the single most expensive thing this system can do.
#
# So the cap here is deliberately high and the real limiter is wall clock plus
# the cost ceiling below. MAX_CALL_SECONDS in services/session_manager.py is
# still honoured; set it in .env.
EDU_MAX_TURNS = int(os.getenv("EDU_MAX_CALL_TURNS", "30"))
EDU_WIND_DOWN_TURNS = int(os.getenv("EDU_WIND_DOWN_TURNS", "3"))

# How many recent exchanges are replayed to the model each turn. Saathicare
# uses 8. A parent who asked about fees on turn 3 and comes back to it on turn
# 18 must not be told something different, so this is wider — and anything
# older than the window is carried by the running summary in
# edu/session_manager.py rather than being forgotten outright.
EDU_HISTORY_TURNS = int(os.getenv("EDU_HISTORY_TURNS", "14"))

# Soft cost ceiling per call, in INR. Checked at turn boundaries, never
# mid-sentence. 0 disables. At the rates in core/llm_service.CLAUDE_COST a
# 25-turn Sonnet call with a cached 3k-token knowledge block lands well under
# this; the ceiling exists to catch a runaway, not to shape normal calls.
EDU_MAX_CALL_COST_INR = float(os.getenv("EDU_MAX_CALL_COST_INR", "25"))

# ── Compliance ────────────────────────────────────────────────────
# Outbound admissions calling is commercial calling. Saathicare's consent model
# assumes the person opted in and asked to be phoned daily; a school's lead list
# does not carry that assumption. See edu/compliance.py.
CALLING_WINDOW_START = os.getenv("EDU_CALL_WINDOW_START", "09:00")
CALLING_WINDOW_END = os.getenv("EDU_CALL_WINDOW_END", "20:00")
MAX_ATTEMPTS_PER_LEAD = int(os.getenv("EDU_MAX_ATTEMPTS_PER_LEAD", "3"))
MIN_HOURS_BETWEEN_ATTEMPTS = int(os.getenv("EDU_MIN_HOURS_BETWEEN_ATTEMPTS", "24"))

# ── Language ──────────────────────────────────────────────────────
# Single institution, so one default language per lead. Mid-call switching is
# NOT supported and cannot be switched on from here — core/stt_service.py sends
# Sarvam a fixed language_code resolved once per call. See edu/README.md.
DEFAULT_LANGUAGE = os.getenv("EDU_DEFAULT_LANGUAGE", "en-IN")
SUPPORTED_LANGUAGES = [
    c.strip()
    for c in os.getenv("EDU_LANGUAGES", "en-IN,hi-IN,mr-IN").split(",")
    if c.strip()
]

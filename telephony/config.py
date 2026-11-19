"""Telephony and phone-bridge configuration from environment."""

import os

from dotenv import load_dotenv

load_dotenv()

TELEPHONY_PROVIDER = (os.getenv("TELEPHONY_PROVIDER") or "exotel").strip().lower()

# Exotel
EXOTEL_SID = os.getenv("EXOTEL_ACCOUNT_SID", "")
EXOTEL_API_KEY = os.getenv("EXOTEL_API_KEY", "")
EXOTEL_API_TOKEN = os.getenv("EXOTEL_API_TOKEN", "")
EXOTEL_VIRTUAL_NUMBER = os.getenv("EXOTEL_VIRTUAL_NUMBER", "")
EXOTEL_SUBDOMAIN = os.getenv("EXOTEL_SUBDOMAIN", "api.in.exotel.com")

# FreJun Teler
FREJUN_API_KEY = os.getenv("FREJUN_API_KEY") or os.getenv("TELER_API_KEY", "")
FREJUN_FROM_NUMBER = os.getenv("FREJUN_FROM_NUMBER") or os.getenv("TELER_FROM_NUMBER", "")
FREJUN_CHUNK_SIZE = int(os.getenv("FREJUN_CHUNK_SIZE", "500"))
FREJUN_RECORD = os.getenv("FREJUN_RECORD", "true").lower() == "true"

# Twilio
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER", "")

# Server
SERVER_PUBLIC_URL = os.getenv("SERVER_PUBLIC_URL", "")
# Cloud hosts (Render, etc.) inject PORT; fall back to SERVER_PORT / 8000.
SERVER_PORT = int(os.getenv("PORT") or os.getenv("SERVER_PORT", "8000"))

# development keeps the single-user PoC conveniences: .env overwrites the first
# active user, and an unrecognised caller is served as that user. Both are wrong
# once real people share the database — see telephony/user_resolver.py.
APP_ENV = (os.getenv("APP_ENV") or "development").strip().lower()
IS_PRODUCTION = APP_ENV not in ("development", "dev", "local", "test")

# Audio (phone bridge uses 8 kHz; Twilio wire format is μ-law)
PHONE_SAMPLE_RATE = 8000
SARVAM_SAMPLE_RATE = 16000
SAMPLE_WIDTH = 2
CHANNELS = 1
CHUNK_DURATION_MS = 100
CHUNK_SIZE = int(PHONE_SAMPLE_RATE * SAMPLE_WIDTH * CHUNK_DURATION_MS / 1000)
TWILIO_MULAW_FRAME = 160

VAD_SILENCE_THRESHOLD = int(os.getenv("SILENCE_THRESHOLD", 350))

# Chunks are CHUNK_DURATION_MS (100ms) each.
#   VAD_SILENCE_CHUNKS    — silence needed before she answers. 10 = 1.0s.
#   VAD_MIN_SPEECH_CHUNKS — speech needed for a turn to count at all. 4 = 0.4s,
#     low enough to catch a one-word answer ("हो", "yes") while still rejecting
#     a single noise blip. These used to be overridden by literal 15 / 8 inside
#     session.py for twilio and exotel, which is where the 1.5s wait came from,
#     and which meant short answers under 0.8s were dropped entirely.
VAD_SILENCE_CHUNKS = int(os.getenv("VAD_SILENCE_CHUNKS", "10"))
VAD_MIN_SPEECH_CHUNKS = int(os.getenv("VAD_MIN_SPEECH_CHUNKS", "4"))

# With Gladia live STT, once Gladia has returned a final transcript the turn
# can end after this much silence instead of the full VAD_SILENCE_CHUNKS.
VAD_LIVE_SILENCE_CHUNKS = int(os.getenv("VAD_LIVE_SILENCE_CHUNKS", "5"))

# If we hear a blip of speech and then a long silence that never reaches
# VAD_MIN_SPEECH_CHUNKS, give up on it and re-arm instead of buffering forever.
VAD_ABANDON_CHUNKS = int(os.getenv("VAD_ABANDON_CHUNKS", "30"))

# A caller who says nothing at all. The consecutive-miss ladder in
# SessionManager cannot see this case — it only counts turns where speech WAS
# heard but STT came back empty — and providers stream silence frames forever,
# so the 30s socket timeout never fires either. Without these two, a silent
# line stayed open indefinitely.
#   SILENCE_PROMPT_CHUNKS — ask "are you still there?" once.  80 = 8s.
#   SILENCE_HANGUP_CHUNKS — no answer to that, so let them go. 200 = 20s.
SILENCE_PROMPT_CHUNKS = int(os.getenv("SILENCE_PROMPT_CHUNKS", "80"))
SILENCE_HANGUP_CHUNKS = int(os.getenv("SILENCE_HANGUP_CHUNKS", "200"))

# Time from the caller falling silent to her first "hmm..." — she now starts
# this clock when they stop speaking, not after STT returns, so the
# acknowledgement lands while the real reply is still being generated.
THINKING_MS = int(os.getenv("THINKING_SOUND_THRESHOLD_MS", "500"))
THINKING_ENABLED = os.getenv("THINKING_SOUND_ENABLED", "true").lower() == "true"

# A slow turn (routinely several seconds on Marathi's Sonnet override, see
# CLAUDE.md) used to go dead silent after that one filler until the real
# reply arrived — indistinguishable from a dropped call. These let the
# watchdog keep speaking a fresh soft filler every few seconds instead.
THINKING_REPEAT_MS = int(os.getenv("THINKING_SOUND_REPEAT_MS", "2500"))
THINKING_MAX_REPEATS = int(os.getenv("THINKING_SOUND_MAX_REPEATS", "2"))

# Padding after her audio finishes, before we listen again.
PLAYBACK_TAIL_PAD_S = float(os.getenv("PLAYBACK_TAIL_PAD_S", "0.25"))
LISTEN_SETTLE_S = float(os.getenv("LISTEN_SETTLE_S", "0.20"))

# Also terminate the call through the provider's REST API after closing the
# WebSocket. Closing the socket SHOULD tear down the PSTN leg on both Twilio and
# Exotel, which is why this defaulted to false — but "should" is doing a lot of
# work there. Exotel in particular can hold the leg up after the stream socket
# goes, and the caller is then sitting on a line that is open, silent, and
# billing. The REST call is one request on a call that is ending anyway, and it
# is a no-op when the leg is already down, so it is now on by default.
#
# Needs the provider's call SID, which arrives on the stream's start event — the
# adapters log a warning if it never showed up.
PROVIDER_HANGUP_ENABLED = os.getenv("PROVIDER_HANGUP_ENABLED", "true").lower() == "true"

# When true, call_server dials USER_PHONE a few seconds after boot (outbound).
AUTO_DIAL_ON_START = os.getenv("AUTO_DIAL_ON_START", "false").lower() in (
    "1", "true", "yes", "on",
)
AUTO_DIAL_DELAY_S = float(os.getenv("AUTO_DIAL_DELAY_S", "3"))
USER_PHONE = (os.getenv("USER_PHONE") or "").strip()


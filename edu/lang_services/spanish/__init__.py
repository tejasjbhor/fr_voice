"""Spanish language pack — EXPERIMENTAL / easy to remove.

Set USER_LANGUAGE=es-ES in .env to test.

STT/TTS use ElevenLabs (see ELEVENLABS_* in .env). Sarvam stays for mr-IN / hi-IN / en-IN.

To remove: delete lang_services/spanish/ and the es-ES branch in shared/lang.py.
"""

from lang_services.spanish.personality import (
    PROMPT_VERSION,
    build_prompt,
    build_system_blocks,
    build_greeting,
    build_closing,
    GREETING,
    CLOSING,
    EMERGENCY,
    EMERGENCY_KEYWORDS,
    EXIT_WORDS,
    SELF_EXIT_WORDS,
    SELF_EXIT_BLOCKERS,
    FALLBACK,
    STILL_THERE,
    prepare_for_tts,
    read_tone,
)
from lang_services.spanish.tts_config import TTS_CONFIG
from lang_services.spanish.extractor_hints import HINTS, CRITICAL_TOPICS

CODE = "es-ES"
NAME = "Spanish"
EXPERIMENTAL = True

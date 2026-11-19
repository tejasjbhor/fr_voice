from lang_services.english.personality import (
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
    UNAVAILABLE_WORDS,
    DECLINE_WORDS,
    WRONG_PERSON_WORDS,
    BEREAVEMENT_WORDS,
    FALLBACK,
    STILL_THERE,
    prepare_for_tts,
    read_tone,
)
from lang_services.english.tts_config import TTS_CONFIG
from lang_services.english.extractor_hints import HINTS, CRITICAL_TOPICS

CODE = "en-IN"
NAME = "English"

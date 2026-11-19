from lang_services.marathi.personality import (
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
    TRAILING_PARTICLES,
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
    fix_honorifics,
    honorific_slips,
)
from lang_services.marathi.tts_config import TTS_CONFIG
from lang_services.marathi.extractor_hints import HINTS, CRITICAL_TOPICS

CODE = "mr-IN"
NAME = "Marathi"

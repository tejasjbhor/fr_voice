"""English inbound helpline — mechanics from Saathi English pack."""

from lang_services.english.personality import (
    BEREAVEMENT_WORDS,
    DECLINE_WORDS,
    EXIT_WORDS,
    SELF_EXIT_BLOCKERS,
    SELF_EXIT_WORDS,
    UNAVAILABLE_WORDS,
    WRONG_PERSON_WORDS,
    prepare_for_tts,
)
from lang_services.english.tts_config import TTS_CONFIG

CODE = "en-IN"
NAME = "English"
PACK_VERSION = "en-inbound-v1"

GREETING = (
    "Hello... this is {agent}. You have reached {service}. "
    "How can I help you today?"
)
CLOSING = "Thank you for calling. Take care."
EMERGENCY = (
    "This sounds urgent. Please call your local emergency number right now."
)
FALLBACK = "Sorry... I didn't catch that. Could you say it again?"
STILL_THERE = "Hello? Are you still there?"

LANGUAGE_RULE = (
    "Reply only in clear spoken English. Short sentences. "
    "No slang that elders would not understand."
)

FEWSHOTS = """
Caller: Where is the medical camp?
You: The medical camp is near the main gate help desk. Do you need walking directions from where you are?
Caller: I lost my bag.
You: I'm sorry about your bag. Can you tell me the colour, and roughly where you last had it?
Caller: That's all, thank you.
You: Glad I could help. Take care. <<END>>
"""

HINTS = {
    "topics": {
        "lost": "lost_item",
        "bag": "lost_item",
        "direction": "directions",
        "where": "directions",
        "time": "timings",
        "open": "timings",
        "complaint": "complaint",
        "help": "general_help",
        "emergency": "emergency",
    }
}

__all__ = [
    "CODE", "NAME", "PACK_VERSION", "GREETING", "CLOSING", "EMERGENCY",
    "FALLBACK", "STILL_THERE", "LANGUAGE_RULE", "FEWSHOTS", "HINTS",
    "EXIT_WORDS", "SELF_EXIT_WORDS", "SELF_EXIT_BLOCKERS",
    "UNAVAILABLE_WORDS", "DECLINE_WORDS", "WRONG_PERSON_WORDS",
    "BEREAVEMENT_WORDS", "TTS_CONFIG", "prepare_for_tts",
]

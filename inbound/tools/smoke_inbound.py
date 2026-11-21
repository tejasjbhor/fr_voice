"""Offline contract check for inbound packs — no API, no telephony."""

from __future__ import annotations

import sys

REQUIRED = (
    "CODE", "NAME", "PROMPT_VERSION", "GREETING", "CLOSING", "EMERGENCY",
    "FALLBACK", "STILL_THERE", "EXIT_WORDS", "SELF_EXIT_WORDS",
    "SELF_EXIT_BLOCKERS", "UNAVAILABLE_WORDS", "DECLINE_WORDS",
    "WRONG_PERSON_WORDS", "BEREAVEMENT_WORDS", "EMERGENCY_KEYWORDS",
    "HINTS", "CRITICAL_TOPICS", "TTS_CONFIG",
    "build_system_blocks", "build_prompt", "build_greeting", "build_closing",
    "prepare_for_tts",
)


def main(code: str = "hi-IN") -> int:
    from inbound.lang_loader import load_inbound_lang_service, reset_cache

    reset_cache()
    pack = load_inbound_lang_service(code)
    missing = [n for n in REQUIRED if not hasattr(pack, n)]
    if missing:
        print(f"FAIL {code}: missing {missing}")
        return 1

    blocks = pack.build_system_blocks("Test", {"turn_number": 1, "extracted_so_far": {}})
    assert isinstance(blocks, list) and blocks[0].get("cache_control")
    greet = pack.build_greeting("Test")
    if not greet or "{agent}" in greet or "{service}" in greet or "{name}" in greet:
        print(f"FAIL {code}: greeting placeholders left: {greet!r}")
        return 1
    tts = pack.prepare_for_tts("Hello. <<END>>")
    assert isinstance(tts, str)
    safe = greet.encode("ascii", "replace").decode("ascii")[:48]
    print(f"OK {code} | {pack.PROMPT_VERSION} | greeting={safe}...")
    return 0


if __name__ == "__main__":
    lang = (sys.argv[1] if len(sys.argv) > 1 else "hi-IN").strip()
    raise SystemExit(main(lang))

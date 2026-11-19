"""Load language service pack by BCP-47 code."""


def load_lang_service(code: str):
    if code == "mr-IN":
        import lang_services.marathi as svc
    elif code == "hi-IN":
        import lang_services.hindi as svc
    elif code in ("fr-FR", "fr-IN", "fr"):
        import lang_services.french as svc
    elif code in ("es-ES", "es-IN", "es"):
        import lang_services.spanish as svc
    elif code == "en-IN":
        import lang_services.english as svc
    else:
        # Unknown / legacy codes → English (safe default for this platform).
        import lang_services.english as svc
    return svc


def voice_language(lang_svc) -> str:
    """BCP-47 code passed to STT/TTS."""
    return lang_svc.CODE


def uses_elevenlabs(lang_svc) -> bool:
    """True when TTS for this pack goes through ElevenLabs."""
    from core.elevenlabs_service import uses_elevenlabs_tts
    return uses_elevenlabs_tts(voice_language(lang_svc))

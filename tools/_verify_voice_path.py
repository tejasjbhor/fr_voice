"""Prove which TTS/STT/pack en-IN uses (no phone needed)."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

from dotenv import load_dotenv
load_dotenv(override=True)

from shared.lang import load_lang_service, voice_language
from core.elevenlabs_service import uses_elevenlabs_tts, uses_fish_tts
from core.gladia_service import is_french_language
from inbound import config as inbound_config
from edu import config as edu_config


def check_lang(code: str):
    print("=" * 50)
    print("PRODUCT", os.getenv("PRODUCT"), "| inbound?", inbound_config.IS_INBOUND, "| edu?", edu_config.IS_EDUCATION)
    if inbound_config.IS_INBOUND:
        from inbound.lang_loader import load_inbound_lang_service
        lang = load_inbound_lang_service(code)
        kind = "INBOUND pack"
    elif edu_config.IS_EDUCATION:
        from edu.lang_loader import load_edu_lang_service
        lang = load_edu_lang_service(code)
        kind = "EDU pack"
    else:
        lang = load_lang_service(code)
        kind = "HEALTH lang_services pack"

    vl = voice_language(lang)
    print(f"{kind}: CODE={getattr(lang,'CODE',None)} PROMPT_VERSION={getattr(lang,'PROMPT_VERSION',None)}")
    print(f"voice_language={vl}")
    print(f"TTS_CONFIG speaker={lang.TTS_CONFIG.get('speaker')} pace={lang.TTS_CONFIG.get('pace')}")
    print(f"uses_fish={uses_fish_tts(vl)} uses_elevenlabs={uses_elevenlabs_tts(vl)} is_french={is_french_language(vl)}")
    greet = lang.build_greeting("Rohit")
    print("greeting:", greet[:120].encode("ascii", "replace").decode())

    # Which synthesize path?
    if uses_fish_tts(vl):
        path = "FISH (not Sarvam)"
    elif uses_elevenlabs_tts(vl):
        path = "ELEVENLABS (not Sarvam)"
    else:
        path = "SARVAM bulbul:v3"
    print("TTS route:", path)
    return lang, vl, path


async def tts_once(lang, vl):
    from core.tts_service import synthesize_phrase
    text = "Hello Rohit ji. This is a Sarvam voice check."
    wav = await synthesize_phrase(
        text,
        language=vl,
        speaker=lang.TTS_CONFIG["speaker"],
        pace=lang.TTS_CONFIG["pace"],
        temperature=lang.TTS_CONFIG.get("temperature"),
    )
    if not wav:
        print("TTS RESULT: FAILED (None) — would sound silent / Twilio Say fallback risk")
        return
    out = os.path.join("recordings", "_sarvam_check_en.wav")
    os.makedirs("recordings", exist_ok=True)
    with open(out, "wb") as f:
        f.write(wav)
    print(f"TTS RESULT: OK wrote {out} ({len(wav)} bytes) — play this file; if natural = Sarvam")


async def main():
    for code in ("en-IN", "hi-IN", "mr-IN"):
        lang, vl, path = check_lang(code)
        print()
    lang, vl, path = check_lang("en-IN")
    if path.startswith("SARVAM"):
        await tts_once(lang, vl)
    else:
        print("Skipping live TTS — not on Sarvam route")


if __name__ == "__main__":
    asyncio.run(main())

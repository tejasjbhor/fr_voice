"""Prove en-IN / hi-IN / mr-IN hit Sarvam bulbul:v3 + language packs."""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv(override=True)

from core.elevenlabs_service import uses_elevenlabs_tts, uses_fish_tts
from core.stt_service import is_spanish_language
from core.gladia_service import is_french_language
from core.tts_service import synthesize_phrase
from shared.lang import load_lang_service, voice_language


async def check(code: str) -> None:
    pack = load_lang_service(code)
    vl = voice_language(pack)
    tts = pack.TTS_CONFIG
    print("=" * 60)
    print(f"CODE={pack.CODE} NAME={pack.NAME}")
    print(f"PROMPT_VERSION={getattr(pack, 'PROMPT_VERSION', None)}")
    print(f"voice_language={vl}")
    print(f"TTS_CONFIG speaker={tts.get('speaker')} pace={tts.get('pace')}")
    print(f"uses_fish={uses_fish_tts(vl)} uses_elevenlabs={uses_elevenlabs_tts(vl)}")
    print(f"is_french={is_french_language(vl)} is_spanish={is_spanish_language(vl)}")
    print(f"route_expected=SARVAM bulbul:v3" if not (
        uses_fish_tts(vl) or uses_elevenlabs_tts(vl)
    ) else "route_expected=NOT SARVAM")

    greet = pack.build_greeting("Rohit")
    print(f"greeting={greet[:80]!r}...")

    wav = await synthesize_phrase(
        "Hello Rohit ji. This is a Sarvam voice check.",
        language=vl,
        speaker=tts["speaker"],
        pace=tts["pace"],
        temperature=tts.get("temperature"),
    )
    if not wav:
        print("TTS RESULT: FAILED (None) — check SARVAM_API_KEY / credits")
        return
    out = os.path.join("recordings", f"sarvam_check_{code.replace('-', '_')}.wav")
    os.makedirs("recordings", exist_ok=True)
    with open(out, "wb") as f:
        f.write(wav)
    print(f"TTS RESULT: OK bytes={len(wav)} wrote={out}")


async def main():
    key = (os.getenv("SARVAM_API_KEY") or "")[:12]
    print(f"SARVAM_API_KEY set={bool(os.getenv('SARVAM_API_KEY'))} prefix={key}...")
    print(f"PRODUCT={os.getenv('PRODUCT')}")
    for code in ("en-IN", "hi-IN", "mr-IN"):
        await check(code)


if __name__ == "__main__":
    asyncio.run(main())

"""Quick check: EN/HI/MR must not be Fish after .env fix."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv(override=True)
from core.elevenlabs_service import uses_fish_tts, uses_elevenlabs_tts

print("TTS_PROVIDER_EN=", os.getenv("TTS_PROVIDER_EN"))
print("TTS_PROVIDER_HI=", os.getenv("TTS_PROVIDER_HI"))
for code in ("en-IN", "hi-IN", "mr-IN"):
    fish = uses_fish_tts(code)
    el = uses_elevenlabs_tts(code)
    route = "SARVAM bulbul:v3" if not fish and not el else ("FISH" if fish else "ELEVENLABS")
    print(f"{code}: fish={fish} eleven={el} -> {route}")

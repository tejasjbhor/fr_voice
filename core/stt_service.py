"""
core/stt_service.py — STT router
  Spanish → ElevenLabs
  French  → Gladia (Solaria-3)
  else    → Sarvam

FIX: _transcribe_sarvam() now reuses a pooled keep-alive aiohttp session
(matching what tts_service.py already does) instead of opening a fresh
TCP+TLS connection on every turn. Saves 100–300 ms per call for HI/MR/EN.
"""

import asyncio
import os
import time

import aiohttp
from colorama import Fore, Style
from dotenv import load_dotenv

from core.elevenlabs_service import is_spanish_language
from core.gladia_service import is_french_language

load_dotenv()

SARVAM_KEY  = os.getenv("SARVAM_API_KEY", "")
STT_URL     = "https://api.sarvam.ai/speech-to-text"
STT_TIMEOUT = int(os.getenv("STT_TIMEOUT", 30))

# Pool size and in-flight gate must both sit at or under the Sarvam plan's
# STT rate limit (Dashboard → Rate Limits). 0 on the semaphore = unlimited.
def _stt_pool_limit() -> int:
    raw = (os.getenv("SARVAM_STT_POOL_LIMIT") or "").strip()
    try:
        # Default 8 matches the PAYG / 2–8 call pilot (was 16).
        return max(1, int(raw)) if raw else 8
    except ValueError:
        return 8

# ── Pooled session — one keep-alive connection to Sarvam per event loop ──
# Opening a fresh ClientSession each call paid a TCP+TLS handshake every
# single turn (~150–300 ms). The TTS side fixed this in an earlier commit
# (see _sarvam_session() in tts_service.py). STT is now aligned.
_stt_session: aiohttp.ClientSession | None = None
_stt_loop = None


def _sarvam_stt_session() -> aiohttp.ClientSession:
    """Shared, keep-alive session for Sarvam STT."""
    global _stt_session, _stt_loop
    loop = asyncio.get_running_loop()
    if _stt_session is None or _stt_session.closed or _stt_loop is not loop:
        _stt_session = aiohttp.ClientSession(
            headers={"api-subscription-key": SARVAM_KEY},
            connector=aiohttp.TCPConnector(
                limit=_stt_pool_limit(),
                ttl_dns_cache=300,
                keepalive_timeout=90,
            ),
        )
        _stt_loop = loop
    return _stt_session


async def close_stt_session():
    """Release the pooled session. Safe to call when one was never opened."""
    global _stt_session, _stt_loop
    if _stt_session is not None and not _stt_session.closed:
        await _stt_session.close()
    _stt_session = None
    _stt_loop = None


async def _transcribe_sarvam(audio_path: str, language: str) -> dict:
    if not SARVAM_KEY:
        raise ValueError("SARVAM_API_KEY not set in .env")

    print(f"  {Fore.CYAN}🎙️  STT (Sarvam)...{Style.RESET_ALL}", end="", flush=True)
    t0 = time.time()

    with open(audio_path, "rb") as f:
        audio_bytes = f.read()

    form = aiohttp.FormData()
    form.add_field(
        "file", audio_bytes,
        filename=os.path.basename(audio_path),
        content_type="audio/wav",
    )
    form.add_field("model", "saaras:v3")
    form.add_field("language_code", language)
    form.add_field("mode", "transcribe")

    from core.concurrency import gated

    try:
        async with gated("sarvam_stt", "SARVAM_STT_MAX_INFLIGHT", 8):
            session = _sarvam_stt_session()
            async with session.post(
                STT_URL,
                data=form,
                timeout=aiohttp.ClientTimeout(total=STT_TIMEOUT),
            ) as resp:
                latency = time.time() - t0
                if resp.status != 200:
                    body = await resp.text()
                    print(f"\n  {Fore.RED}❌ STT {resp.status}: {body}{Style.RESET_ALL}")
                    return {"transcript": "", "error": body}

                body = await resp.json(content_type=None)
                transcript = body.get("transcript", "").strip()
                duration   = body.get("duration", 0) or 0

                print(f" {Fore.GREEN}✅ {latency:.2f}s{Style.RESET_ALL}")
                if transcript:
                    print(f"  {Fore.YELLOW}📝  \"{transcript}\"{Style.RESET_ALL}")
                else:
                    print(f"  {Fore.YELLOW}⚠️  Empty — speak louder.{Style.RESET_ALL}")

                return {
                    "transcript": transcript,
                    "duration":   duration,
                    "latency":    round(latency, 3),
                    "cost_inr":   round(duration * (30 / 3600), 4),
                    "error":      None,
                }

    except asyncio.TimeoutError:
        print(f"\n  {Fore.RED}❌ STT timeout{Style.RESET_ALL}")
        return {"transcript": "", "error": "timeout"}
    except Exception as e:
        print(f"\n  {Fore.RED}❌ STT: {e}{Style.RESET_ALL}")
        return {"transcript": "", "error": str(e)}


async def transcribe(audio_path: str, language: str) -> dict:
    """
    Convert WAV → text.
    Spanish → ElevenLabs. French → Gladia. Everything else → Sarvam.
    """
    if is_spanish_language(language):
        from core.elevenlabs_service import transcribe as eleven_transcribe
        return await eleven_transcribe(audio_path, language)
    if is_french_language(language):
        from core.gladia_service import transcribe as gladia_transcribe
        return await gladia_transcribe(audio_path, language)

    return await _transcribe_sarvam(audio_path, language)

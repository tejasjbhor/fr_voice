"""
core/elevenlabs_service.py — ElevenLabs STT/TTS

STT: Spanish (es-ES) only. French STT is Gladia.
TTS: Spanish and French. Marathi / Hindi / English stay on Sarvam.
"""

import asyncio
import io
import os
import time
import wave

import aiohttp
from colorama import Fore, Style
from dotenv import load_dotenv

load_dotenv()

ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "")
ELEVENLABS_VOICE_NAME = os.getenv("ELEVENLABS_VOICE_NAME", "")
ELEVENLABS_STT_MODEL_ID = os.getenv("ELEVENLABS_STT_MODEL_ID", "scribe_v2")
ELEVENLABS_TTS_MODEL_ID = os.getenv("ELEVENLABS_TTS_MODEL_ID", "eleven_multilingual_v2")
ELEVENLABS_TTS_OUTPUT_FORMAT = os.getenv("ELEVENLABS_TTS_OUTPUT_FORMAT", "wav_16000")

STT_TIMEOUT = int(os.getenv("STT_TIMEOUT", 30))
TTS_TIMEOUT = int(os.getenv("TTS_TIMEOUT", 30))
# Free plans allow 2 in-flight TTS requests. Greeting + prewarm used to
# fire 6+ at once and get 429 concurrent_limit_exceeded.
ELEVENLABS_MAX_CONCURRENT = max(1, int(os.getenv("ELEVENLABS_MAX_CONCURRENT", "2")))

STT_URL = "https://api.elevenlabs.io/v1/speech-to-text"
VOICES_URL = "https://api.elevenlabs.io/v2/voices"

_voice_id_cache: str | None = None
_tts_sem: asyncio.Semaphore | None = None
_tts_sem_loop = None


def _tts_gate() -> asyncio.Semaphore:
    global _tts_sem, _tts_sem_loop
    loop = asyncio.get_running_loop()
    if _tts_sem is None or _tts_sem_loop is not loop:
        _tts_sem = asyncio.Semaphore(ELEVENLABS_MAX_CONCURRENT)
        _tts_sem_loop = loop
    return _tts_sem


def _lang_base(language: str) -> str:
    return (language or "").split("-")[0].strip().lower()


def is_spanish_language(language: str) -> bool:
    return _lang_base(language) == "es"


def _tts_provider_for(language: str) -> str:
    base = _lang_base(language).upper()
    return (os.getenv(f"TTS_PROVIDER_{base}") or "").strip().lower()


def uses_elevenlabs_tts(language: str) -> bool:
    """True when this language is routed to ElevenLabs TTS."""
    provider = _tts_provider_for(language)
    if provider:
        return provider == "elevenlabs"
    return _lang_base(language) in ("es", "fr")


def uses_fish_tts(language: str) -> bool:
    return _tts_provider_for(language) == "fish"


def _headers() -> dict:
    return {"xi-api-key": ELEVENLABS_API_KEY}


async def _resolve_voice_id() -> str:
    global _voice_id_cache
    if _voice_id_cache:
        return _voice_id_cache
    if ELEVENLABS_VOICE_ID:
        _voice_id_cache = ELEVENLABS_VOICE_ID.strip()
        return _voice_id_cache
    if not ELEVENLABS_VOICE_NAME:
        raise ValueError(
            "Set ELEVENLABS_VOICE_ID or ELEVENLABS_VOICE_NAME in .env for Spanish mode."
        )

    async with aiohttp.ClientSession(headers=_headers()) as s:
        async with s.get(
            VOICES_URL,
            params={"search": ELEVENLABS_VOICE_NAME, "page_size": 10},
            timeout=aiohttp.ClientTimeout(total=20),
        ) as resp:
            if resp.status != 200:
                body = await resp.text()
                raise RuntimeError(f"ElevenLabs voice search failed: {resp.status}: {body}")
            data = await resp.json(content_type=None)

    voices = data.get("voices") or []
    wanted = ELEVENLABS_VOICE_NAME.strip().lower()
    for v in voices:
        name = (v.get("name") or "").strip().lower()
        if name == wanted or wanted in name:
            vid = v.get("voice_id")
            if vid:
                _voice_id_cache = str(vid)
                return _voice_id_cache

    raise ValueError(f"ElevenLabs voice not found for name: {ELEVENLABS_VOICE_NAME}")


def _pcm_to_wav(pcm: bytes, sample_rate: int, sample_width: int = 2, channels: int = 1) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm)
    return buf.getvalue()


async def transcribe(audio_path: str, language: str = "es-ES") -> dict:
    if not ELEVENLABS_API_KEY:
        raise ValueError("ELEVENLABS_API_KEY not set — required for Spanish (es-ES).")

    print(f"  {Fore.CYAN}🎙️  STT (ElevenLabs / Spanish)...{Style.RESET_ALL}", end="", flush=True)
    t0 = time.time()

    with open(audio_path, "rb") as f:
        audio_bytes = f.read()

    form = aiohttp.FormData()
    form.add_field(
        "file",
        audio_bytes,
        filename=os.path.basename(audio_path),
        content_type="audio/wav",
    )
    form.add_field("model_id", ELEVENLABS_STT_MODEL_ID)
    form.add_field("language_code", "es")

    try:
        async with aiohttp.ClientSession(headers=_headers()) as s:
            async with s.post(
                STT_URL,
                data=form,
                timeout=aiohttp.ClientTimeout(total=STT_TIMEOUT),
            ) as resp:
                latency = time.time() - t0
                if resp.status != 200:
                    body = await resp.text()
                    print(f"\n  {Fore.RED}❌ STT {resp.status}: {body}{Style.RESET_ALL}")
                    return {"transcript": "", "duration": 0, "latency": round(latency, 3), "error": body}

                body = await resp.json(content_type=None)
                transcript = (body.get("text") or body.get("transcript") or "").strip()

                print(f" {Fore.GREEN}✅ {latency:.2f}s{Style.RESET_ALL}")
                if transcript:
                    print(f"  {Fore.YELLOW}📝  \"{transcript}\"{Style.RESET_ALL}")
                else:
                    print(f"  {Fore.YELLOW}⚠️  Empty — speak louder.{Style.RESET_ALL}")

                return {
                    "transcript": transcript,
                    "duration": 0,
                    "latency": round(latency, 3),
                    "cost_inr": 0,
                    "error": None,
                }
    except asyncio.TimeoutError:
        print(f"\n  {Fore.RED}❌ STT timeout{Style.RESET_ALL}")
        return {"transcript": "", "duration": 0, "latency": 0, "error": "timeout"}
    except Exception as e:
        print(f"\n  {Fore.RED}❌ STT: {e}{Style.RESET_ALL}")
        return {"transcript": "", "duration": 0, "latency": 0, "error": str(e)}


async def synthesize_phrase(text: str, language: str = "es-ES",
                            model_hint: str | None = None) -> bytes | None:
    """
    Synthesize `text` via ElevenLabs.

    `model_hint` lets the language pack's TTS_CONFIG override the global
    ELEVENLABS_TTS_MODEL_ID without touching .env — used to route French to
    eleven_turbo_v2_5 (~35% lower latency) while Spanish stays on
    eleven_multilingual_v2.  If None, the env-var default is used.
    """
    if not ELEVENLABS_API_KEY:
        raise ValueError("ELEVENLABS_API_KEY not set — required for Spanish/French TTS.")
    if not text or not text.strip():
        return None

    model_id = (model_hint or "").strip() or ELEVENLABS_TTS_MODEL_ID
    voice_id = await _resolve_voice_id()
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    params = {"output_format": ELEVENLABS_TTS_OUTPUT_FORMAT}
    lang = _lang_base(language) or "es"
    payload = {
        "text": text.strip(),
        "model_id": model_id,
        "language_code": lang,
    }
    delays = (0.7, 1.4, 2.8)
    last_err = None

    for attempt in range(len(delays) + 1):
        try:
            async with _tts_gate():
                async with aiohttp.ClientSession(
                    headers={**_headers(), "Content-Type": "application/json"}
                ) as s:
                    async with s.post(
                        url,
                        params=params,
                        json=payload,
                        timeout=aiohttp.ClientTimeout(total=TTS_TIMEOUT),
                    ) as resp:
                        if resp.status == 200:
                            raw = await resp.read()
                            fmt = ELEVENLABS_TTS_OUTPUT_FORMAT.lower()
                            if fmt.startswith("wav_"):
                                return raw
                            if fmt.startswith("pcm_"):
                                sr = int(fmt.split("_", 1)[1])
                                return _pcm_to_wav(raw, sr)
                            return raw
                        body = await resp.text()
                        last_err = f"{resp.status}: {body}"
                        if resp.status == 429 and attempt < len(delays):
                            pass
                        else:
                            print(f"\n  {Fore.RED}❌ ElevenLabs TTS {last_err}{Style.RESET_ALL}")
                            return None
        except asyncio.TimeoutError:
            print(f"\n  {Fore.RED}❌ ElevenLabs TTS timeout{Style.RESET_ALL}")
            return None
        except Exception as e:
            print(f"\n  {Fore.RED}❌ ElevenLabs TTS: {e}{Style.RESET_ALL}")
            return None
        await asyncio.sleep(delays[attempt])

    if last_err:
        print(f"\n  {Fore.RED}❌ ElevenLabs TTS {last_err}{Style.RESET_ALL}")
    return None

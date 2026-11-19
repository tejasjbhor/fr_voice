"""
core/fish_service.py — Fish Audio TTS (free s2.1-pro-free path).
"""

import asyncio
import io
import os
import wave

import aiohttp
from colorama import Fore, Style
from dotenv import load_dotenv

load_dotenv()

FISH_API_KEY = os.getenv("FISH_API_KEY", "")
FISH_AUDIO_MODEL = os.getenv("FISH_AUDIO_MODEL", "s2.1-pro-free")
FISH_AUDIO_REFERENCE_ID = os.getenv("FISH_AUDIO_REFERENCE_ID", "")
FISH_AUDIO_LATENCY = os.getenv("FISH_AUDIO_LATENCY", "low")
FISH_AUDIO_SAMPLE_RATE = int(os.getenv("FISH_AUDIO_SAMPLE_RATE", "16000"))
# Fish API rejects values outside [100, 300].
FISH_AUDIO_CHUNK_LENGTH = min(300, max(100, int(os.getenv("FISH_AUDIO_CHUNK_LENGTH", "120"))))
TTS_TIMEOUT = int(os.getenv("TTS_TIMEOUT", 30))

TTS_URL = "https://api.fish.audio/v1/tts"

_http_session: aiohttp.ClientSession | None = None
_http_loop = None


def _lang_base(language: str) -> str:
    return (language or "").split("-")[0].strip().lower()


def _reference_id(language: str) -> str:
    base = _lang_base(language).upper()
    specific = (os.getenv(f"FISH_AUDIO_REFERENCE_ID_{base}") or "").strip()
    return specific or FISH_AUDIO_REFERENCE_ID.strip()


def _session() -> aiohttp.ClientSession:
    global _http_session, _http_loop
    loop = asyncio.get_running_loop()
    if _http_session is None or _http_session.closed or _http_loop is not loop:
        _http_session = aiohttp.ClientSession(
            headers={
                "Authorization": f"Bearer {FISH_API_KEY}",
                "model": FISH_AUDIO_MODEL,
            },
            connector=aiohttp.TCPConnector(limit=8, keepalive_timeout=90),
        )
        _http_loop = loop
    return _http_session


def _pcm_to_wav(pcm: bytes, sample_rate: int, sample_width: int = 2, channels: int = 1) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm)
    return buf.getvalue()


def _as_wav(raw: bytes) -> bytes:
    if raw[:4] == b"RIFF":
        return raw
    if raw[:4] == b"\x1aE\xdf\xa3":  # webm/mkv
        return raw
    # Fish sometimes returns raw PCM when format=wav is not honoured.
    if len(raw) > 100 and raw[:4] != b"ID3" and raw[:3] != b"\xff\xfb":
        try:
            return _pcm_to_wav(raw, FISH_AUDIO_SAMPLE_RATE)
        except Exception:
            return raw
    return raw


def _payload(text: str, language: str, pace, temperature, fmt: str, sample_rate: int) -> dict:
    if not FISH_API_KEY:
        raise ValueError("FISH_API_KEY not set — required for Fish TTS.")
    ref = _reference_id(language)
    if not ref:
        raise ValueError("FISH_AUDIO_REFERENCE_ID not set — required for Fish TTS.")
    speed = 0.92 if pace is None else max(0.7, min(1.15, float(pace)))
    temp = 0.85 if temperature is None else float(temperature)
    return {
        "text": text.strip(),
        "reference_id": ref,
        "format": fmt,
        "sample_rate": sample_rate,
        "latency": FISH_AUDIO_LATENCY,
        "chunk_length": FISH_AUDIO_CHUNK_LENGTH,
        "normalize": True,
        "temperature": temp,
        "top_p": 0.8,
        "prosody": {
            "speed": speed,
            "volume": 0,
            "normalize_loudness": True,
        },
    }


async def stream_pcm(text: str, language: str = "fr-FR",
                     pace: float | None = None,
                     temperature: float | None = None,
                     sample_rate: int = 8000,
                     chunk_bytes: int = 1600):
    """
    Yield raw 16-bit mono PCM as Fish generates it.

    First bytes arrive in ~0.5 s regardless of sentence length, against 3-5 s
    for the full WAV of a long sentence, and Fish generates about twice as fast
    as real time, so playback started on the first chunk does not run dry.
    """
    if not text or not text.strip():
        return
    payload = _payload(text, language, pace, temperature, "pcm", sample_rate)
    carry = b""
    first = True
    try:
        s = _session()
        async with s.post(
            TTS_URL,
            json=payload,
            timeout=aiohttp.ClientTimeout(total=TTS_TIMEOUT),
        ) as resp:
            if resp.status != 200:
                body = await resp.text()
                print(f"\n  {Fore.RED}❌ Fish TTS {resp.status}: {body}{Style.RESET_ALL}")
                return
            async for chunk in resp.content.iter_chunked(chunk_bytes):
                data = carry + chunk
                if first:
                    first = False
                    if data[:4] == b"RIFF" and len(data) >= 44:
                        data = data[44:]
                # Keep sample alignment across network chunk boundaries.
                cut = len(data) - (len(data) % 2)
                carry = data[cut:]
                if cut:
                    yield data[:cut]
    except asyncio.TimeoutError:
        print(f"\n  {Fore.RED}❌ Fish TTS stream timeout{Style.RESET_ALL}")
    except asyncio.CancelledError:
        raise
    except Exception as e:
        print(f"\n  {Fore.RED}❌ Fish TTS stream: {e}{Style.RESET_ALL}")


async def close_session():
    global _http_session, _http_loop
    if _http_session is not None and not _http_session.closed:
        await _http_session.close()
    _http_session = None
    _http_loop = None


async def synthesize_phrase(text: str, language: str = "fr-FR",
                             pace: float | None = None,
                             temperature: float | None = None) -> bytes | None:
    if not text or not text.strip():
        return None
    payload = _payload(text, language, pace, temperature, "wav", FISH_AUDIO_SAMPLE_RATE)

    try:
        s = _session()
        async with s.post(
            TTS_URL,
            json=payload,
            timeout=aiohttp.ClientTimeout(total=TTS_TIMEOUT),
        ) as resp:
            if resp.status != 200:
                body = await resp.text()
                print(f"\n  {Fore.RED}❌ Fish TTS {resp.status}: {body}{Style.RESET_ALL}")
                return None
            return _as_wav(await resp.read())
    except asyncio.TimeoutError:
        print(f"\n  {Fore.RED}❌ Fish TTS timeout{Style.RESET_ALL}")
        return None
    except Exception as e:
        print(f"\n  {Fore.RED}❌ Fish TTS: {e}{Style.RESET_ALL}")
        return None

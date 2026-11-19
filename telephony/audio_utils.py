"""PCM / WAV conversions and VAD helpers for phone audio."""

import audioop
import base64
import io
import json
import wave

from telephony.config import (
    CHANNELS,
    CHUNK_SIZE,
    FREJUN_CHUNK_SIZE,
    FREJUN_RECORD,
    PHONE_SAMPLE_RATE,
    SAMPLE_WIDTH,
    SARVAM_SAMPLE_RATE,
    VAD_SILENCE_THRESHOLD,
)
from telephony.log import setup_logging

log = setup_logging()


def pcm_8k_to_wav_16k(pcm_8k: bytes) -> bytes:
    pcm_16k, _ = audioop.ratecv(
        pcm_8k, SAMPLE_WIDTH, CHANNELS,
        PHONE_SAMPLE_RATE, SARVAM_SAMPLE_RATE, None,
    )
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(SAMPLE_WIDTH)
        wf.setframerate(SARVAM_SAMPLE_RATE)
        wf.writeframes(pcm_16k)
    return buf.getvalue()


def wav_bytes_to_pcm_8k(wav_bytes: bytes) -> bytes:
    buf = io.BytesIO(wav_bytes)
    with wave.open(buf, "rb") as wf:
        frames = wf.readframes(wf.getnframes())
        src_rate = wf.getframerate()
        nchan = wf.getnchannels()
        width = wf.getsampwidth()
    if width != SAMPLE_WIDTH:
        # Unexpected width — best-effort leave as-is (Sarvam is PCM16)
        pass
    if nchan > 1:
        frames = audioop.tomono(frames, SAMPLE_WIDTH, 0.5, 0.5)
    if src_rate != PHONE_SAMPLE_RATE:
        pcm_8k, _ = audioop.ratecv(
            frames, SAMPLE_WIDTH, CHANNELS,
            src_rate, PHONE_SAMPLE_RATE, None,
        )
        return pcm_8k
    return frames


def rms(chunk: bytes) -> float:
    if not chunk:
        return 0.0
    try:
        return audioop.rms(chunk, SAMPLE_WIDTH)
    except Exception:
        return 0.0


def is_silence(chunk: bytes) -> bool:
    return rms(chunk) < VAD_SILENCE_THRESHOLD


def frejun_stream_flow_payload(ws_url: str) -> dict:
    """Build FreJun CallFlow.stream response (SDK or fallback JSON)."""
    try:
        from teler import CallFlow
        return CallFlow.stream(
            ws_url=ws_url,
            chunk_size=FREJUN_CHUNK_SIZE,
            record=FREJUN_RECORD,
        )
    except Exception as e:
        log.warning(f"CallFlow.stream via SDK failed ({e}); using fallback JSON")
        return {
            "action": "stream",
            "ws_url": ws_url,
            "chunk_size": FREJUN_CHUNK_SIZE,
            "record": FREJUN_RECORD,
        }


def is_placeholder(val: str) -> bool:
    if not val or not str(val).strip():
        return True
    low = str(val).lower().strip()
    if low in ("+33", "+91", "https://", "http://", "wss://"):
        return True
    return any(
        x in low
        for x in ("your_", "xxxx", "example", "ngrok-url", "placeholder", "fill")
    )

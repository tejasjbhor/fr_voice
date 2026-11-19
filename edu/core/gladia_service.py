"""
core/gladia_service.py — Gladia STT (French)

Upload a WAV, start a Solaria-3 job, poll until done.
TTS stays on ElevenLabs — Gladia has no speech synthesis.

Used when USER_LANGUAGE=fr-FR. Other languages are unchanged.
"""

import asyncio
import os
import time

import aiohttp
from colorama import Fore, Style
from dotenv import load_dotenv

load_dotenv()

GLADIA_KEY = os.getenv("GLADIA_API_KEY", "")
GLADIA_MODEL = os.getenv("GLADIA_MODEL", "solaria-3")
GLADIA_BASE = os.getenv("GLADIA_API_URL", "https://api.gladia.io").rstrip("/")
STT_TIMEOUT = int(os.getenv("STT_TIMEOUT", "30"))
POLL_MS = int(os.getenv("GLADIA_POLL_INTERVAL_MS", "250"))

UPLOAD_URL = f"{GLADIA_BASE}/v2/upload"
JOB_URL = f"{GLADIA_BASE}/v2/pre-recorded"


def is_french_language(language: str) -> bool:
    base = (language or "").split("-")[0].strip().lower()
    return base == "fr"


def _headers() -> dict:
    return {"x-gladia-key": GLADIA_KEY}


def _transcript_from(body: dict) -> str:
    result = body.get("result") or {}
    transcription = result.get("transcription") or {}
    return (transcription.get("full_transcript") or "").strip()


def _duration_from(body: dict) -> float:
    meta = (body.get("result") or {}).get("metadata") or {}
    dur = meta.get("audio_duration")
    if dur is None:
        file_meta = body.get("file") or {}
        if isinstance(file_meta, dict):
            dur = file_meta.get("audio_duration")
    try:
        return float(dur or 0)
    except (TypeError, ValueError):
        return 0.0


async def transcribe(audio_path: str, language: str = "fr-FR") -> dict:
    if not GLADIA_KEY:
        raise ValueError("GLADIA_API_KEY not set — required for French (fr-FR).")

    print(f"  {Fore.CYAN}🎙️  STT (Gladia / French)...{Style.RESET_ALL}", end="", flush=True)
    t0 = time.time()
    timeout = aiohttp.ClientTimeout(total=STT_TIMEOUT)

    try:
        async with aiohttp.ClientSession(headers=_headers()) as s:
            with open(audio_path, "rb") as f:
                audio_bytes = f.read()
            form = aiohttp.FormData()
            form.add_field(
                "audio",
                audio_bytes,
                filename=os.path.basename(audio_path) or "turn.wav",
                content_type="audio/wav",
            )
            async with s.post(UPLOAD_URL, data=form, timeout=timeout) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    print(f"\n  {Fore.RED}❌ Gladia upload {resp.status}: {body}{Style.RESET_ALL}")
                    return {"transcript": "", "duration": 0, "latency": round(time.time() - t0, 3), "error": body}
                uploaded = await resp.json(content_type=None)

            audio_url = uploaded.get("audio_url") or ""
            if not audio_url:
                err = "Gladia upload returned no audio_url"
                print(f"\n  {Fore.RED}❌ {err}{Style.RESET_ALL}")
                return {"transcript": "", "duration": 0, "latency": round(time.time() - t0, 3), "error": err}

            payload = {
                "audio_url": audio_url,
                "model": GLADIA_MODEL,
                "language_config": {"languages": ["fr"]},
            }
            async with s.post(JOB_URL, json=payload, timeout=timeout) as resp:
                if resp.status not in (200, 201):
                    body = await resp.text()
                    print(f"\n  {Fore.RED}❌ Gladia job {resp.status}: {body}{Style.RESET_ALL}")
                    return {"transcript": "", "duration": 0, "latency": round(time.time() - t0, 3), "error": body}
                job = await resp.json(content_type=None)

            job_id = job.get("id") or ""
            result_url = job.get("result_url") or (f"{JOB_URL}/{job_id}" if job_id else "")
            if not result_url:
                err = "Gladia job returned no id"
                print(f"\n  {Fore.RED}❌ {err}{Style.RESET_ALL}")
                return {"transcript": "", "duration": 0, "latency": round(time.time() - t0, 3), "error": err}

            deadline = t0 + STT_TIMEOUT
            poll_s = max(0.15, POLL_MS / 1000)
            body = job
            while time.time() < deadline:
                status = (body.get("status") or "").lower()
                if status == "done":
                    break
                if status in ("error", "failed"):
                    err = str(body.get("error") or body)
                    print(f"\n  {Fore.RED}❌ Gladia job failed: {err}{Style.RESET_ALL}")
                    return {"transcript": "", "duration": 0, "latency": round(time.time() - t0, 3), "error": err}
                await asyncio.sleep(poll_s)
                async with s.get(result_url, timeout=timeout) as resp:
                    if resp.status != 200:
                        body_text = await resp.text()
                        print(f"\n  {Fore.RED}❌ Gladia poll {resp.status}: {body_text}{Style.RESET_ALL}")
                        return {"transcript": "", "duration": 0, "latency": round(time.time() - t0, 3), "error": body_text}
                    body = await resp.json(content_type=None)
            else:
                print(f"\n  {Fore.RED}❌ STT timeout{Style.RESET_ALL}")
                return {"transcript": "", "duration": 0, "latency": round(time.time() - t0, 3), "error": "timeout"}

        latency = time.time() - t0
        transcript = _transcript_from(body)
        duration = _duration_from(body)
        print(f" {Fore.GREEN}✅ {latency:.2f}s{Style.RESET_ALL}")
        if transcript:
            print(f"  {Fore.YELLOW}📝  \"{transcript}\"{Style.RESET_ALL}")
        else:
            print(f"  {Fore.YELLOW}⚠️  Empty — speak louder.{Style.RESET_ALL}")
        return {
            "transcript": transcript,
            "duration": duration,
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

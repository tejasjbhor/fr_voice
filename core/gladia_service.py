"""
core/gladia_service.py — Gladia STT (French)

Live WebSocket (solaria-1) while the mic is open, so the transcript is
ready when they stop. Falls back to pre-recorded Solaria-3 upload+poll.
"""

import asyncio
import json
import os
import time

import aiohttp
from colorama import Fore, Style
from dotenv import load_dotenv

load_dotenv()

GLADIA_KEY = os.getenv("GLADIA_API_KEY", "")
GLADIA_MODEL = os.getenv("GLADIA_MODEL", "solaria-3")
GLADIA_LIVE_MODEL = os.getenv("GLADIA_LIVE_MODEL", "solaria-1")
GLADIA_BASE = os.getenv("GLADIA_API_URL", "https://api.gladia.io").rstrip("/")
GLADIA_LIVE = os.getenv("GLADIA_LIVE", "true").lower() == "true"
STT_TIMEOUT = int(os.getenv("STT_TIMEOUT", "30"))
POLL_MS = int(os.getenv("GLADIA_POLL_INTERVAL_MS", "250"))
AUDIO_SAMPLE_RATE = int(os.getenv("AUDIO_SAMPLE_RATE", "16000"))

UPLOAD_URL = f"{GLADIA_BASE}/v2/upload"
JOB_URL = f"{GLADIA_BASE}/v2/pre-recorded"
LIVE_URL = f"{GLADIA_BASE}/v2/live"


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


class LiveSession:
    """Gladia /v2/live — PCM in, finals out. Safe to feed from the audio thread."""

    def __init__(self, sample_rate: int | None = None):
        self.sample_rate = int(sample_rate or AUDIO_SAMPLE_RATE)
        self.has_final = False
        self.finals: list[str] = []
        self.partial = ""
        self.error = None
        self._out: asyncio.Queue = asyncio.Queue()
        self._done = asyncio.Event()
        self._http: aiohttp.ClientSession | None = None
        self._ws = None
        self._recv_task = None
        self._pump_task = None

    def feed(self, data: bytes):
        try:
            self._out.put_nowait(data)
        except Exception:
            pass

    async def start(self) -> bool:
        if not GLADIA_KEY:
            self.error = "GLADIA_API_KEY not set"
            return False
        payload = {
            "model": GLADIA_LIVE_MODEL,
            "encoding": "wav/pcm",
            "sample_rate": self.sample_rate,
            "bit_depth": 16,
            "channels": 1,
            "endpointing": 0.25,
            "maximum_duration_without_endpointing": 8,
            "language_config": {"languages": ["fr"], "code_switching": False},
            "messages_config": {"receive_partial_transcripts": True},
        }
        timeout = aiohttp.ClientTimeout(total=None, sock_connect=15, sock_read=None)
        try:
            self._http = aiohttp.ClientSession(
                headers=_headers(),
                timeout=timeout,
            )
            async with self._http.post(
                LIVE_URL, json=payload,
                timeout=aiohttp.ClientTimeout(total=12),
            ) as resp:
                if resp.status not in (200, 201):
                    self.error = f"live init {resp.status}: {await resp.text()}"
                    return False
                body = await resp.json(content_type=None)
            url = body.get("url") or ""
            if not url:
                self.error = "live init returned no url"
                return False
            self._ws = await self._http.ws_connect(url, heartbeat=20)
            self._recv_task = asyncio.create_task(self._recv())
            self._pump_task = asyncio.create_task(self._pump())
            return True
        except Exception as e:
            self.error = str(e)
            await self.close()
            return False

    async def _pump(self):
        try:
            while True:
                chunk = await self._out.get()
                if chunk is None:
                    if self._ws and not self._ws.closed:
                        await self._ws.send_str('{"type":"stop_recording"}')
                    return
                if self._ws and not self._ws.closed:
                    await self._ws.send_bytes(chunk)
        except Exception as e:
            self.error = str(e)
            self._done.set()

    def _ingest(self, body: dict):
        typ = body.get("type") or ""
        if typ == "transcript":
            data = body.get("data") or {}
            utt = data.get("utterance") or {}
            text = (utt.get("text") or "").strip()
            if not text:
                return
            if data.get("is_final"):
                self.finals.append(text)
                self.has_final = True
                self.partial = ""
            else:
                self.partial = text
        elif typ in ("post_final_transcript", "end_recording"):
            self._done.set()

    async def _recv(self):
        try:
            async for msg in self._ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    try:
                        self._ingest(json.loads(msg.data))
                    except (TypeError, ValueError, json.JSONDecodeError):
                        pass
                elif msg.type in (
                    aiohttp.WSMsgType.CLOSE,
                    aiohttp.WSMsgType.CLOSED,
                    aiohttp.WSMsgType.ERROR,
                ):
                    break
        except Exception as e:
            self.error = str(e)
        finally:
            self._done.set()

    def transcript(self) -> str:
        joined = " ".join(self.finals).strip()
        return joined or (self.partial or "").strip()

    async def finish(self, wait_s: float = 2.0) -> str:
        try:
            self._out.put_nowait(None)
        except Exception:
            pass
        # Finals often already arrived during the pause — don't sit on Gladia for 2s.
        timeout = 0.35 if self.has_final else min(wait_s, 1.0)
        try:
            await asyncio.wait_for(self._done.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            pass
        text = self.transcript()
        await self.close()
        return text

    async def close(self):
        for task in (self._recv_task, self._pump_task):
            if task and not task.done():
                task.cancel()
        if self._ws is not None and not self._ws.closed:
            try:
                await self._ws.close()
            except Exception:
                pass
        if self._http is not None and not self._http.closed:
            try:
                await self._http.close()
            except Exception:
                pass
        self._ws = None
        self._http = None


def _stt_result(transcript: str, duration: float, latency: float,
                error=None, path: str | None = None) -> dict:
    return {
        "transcript": transcript or "",
        "duration": duration,
        "latency": round(latency, 3),
        "cost_inr": 0,
        "error": error,
        "path": path,
    }


def _print_transcript(transcript: str, latency: float, live: bool):
    tag = "live" if live else "French"
    print(f"  {Fore.CYAN}🎙️  STT (Gladia / {tag})...{Style.RESET_ALL}", end="", flush=True)
    print(f" {Fore.GREEN}✅ {latency:.2f}s{Style.RESET_ALL}")
    if transcript:
        print(f"  {Fore.YELLOW}📝  \"{transcript}\"{Style.RESET_ALL}")
    else:
        print(f"  {Fore.YELLOW}⚠️  Empty — speak louder.{Style.RESET_ALL}")


async def record_and_transcribe(output_path: str) -> dict:
    """Record the mic while streaming PCM to Gladia Live. Transcript ready on stop."""
    from core.audio import record_audio, get_audio_duration

    if not GLADIA_LIVE:
        wav = await record_audio(output_path=output_path)
        if not wav:
            return _stt_result("", 0, 0, error="no audio", path=None)
        result = await transcribe(wav)
        result["path"] = wav
        return result

    # Connect BEFORE listening so PCM is not stuck behind a late handshake.
    live = LiveSession()
    ok = await live.start()
    if not ok:
        if live.error:
            print(f"  {Fore.YELLOW}⚠️  Live STT: {live.error} — batch fallback{Style.RESET_ALL}")
        else:
            await live.close()
        wav = await record_audio(output_path=output_path)
        if not wav:
            return _stt_result("", 0, 0, error="no audio", path=None)
        result = await transcribe(wav)
        result["path"] = wav
        return result

    loop = asyncio.get_running_loop()

    def on_pcm(data: bytes):
        loop.call_soon_threadsafe(live.feed, data)

    def stop_early():
        return live.has_final

    wav = await record_audio(
        output_path=output_path,
        on_pcm=on_pcm,
        stop_early=stop_early,
    )
    t_stop = time.time()
    if not wav:
        await live.close()
        return _stt_result("", 0, 0, error="no audio", path=None)

    duration = get_audio_duration(wav)
    transcript = await live.finish(wait_s=0.9)
    latency = time.time() - t_stop
    if transcript:
        _print_transcript(transcript, latency, live=True)
        return _stt_result(transcript, duration, latency, path=wav)

    print(f"  {Fore.YELLOW}⚠️  Live STT empty — batch fallback{Style.RESET_ALL}")
    result = await transcribe(wav)
    result["path"] = wav
    return result


async def transcribe_file_live(audio_path: str, language: str = "fr-FR") -> dict:
    """Stream an already-captured WAV over Gladia Live (barge-in path)."""
    if not GLADIA_LIVE:
        return await transcribe(audio_path, language)

    print(f"  {Fore.CYAN}🎙️  STT (Gladia / live)...{Style.RESET_ALL}", end="", flush=True)
    t0 = time.time()
    live = LiveSession()
    if not await live.start():
        print(f" {Fore.YELLOW}fallback{Style.RESET_ALL}")
        return await transcribe(audio_path, language)

    try:
        import soundfile as sf
        import numpy as np
        data, _sr = sf.read(audio_path, dtype="int16")
        if getattr(data, "ndim", 1) > 1:
            data = data[:, 0]
        pcm = np.ascontiguousarray(data).tobytes()
        step = max(3200, AUDIO_SAMPLE_RATE * 2 // 5)
        for i in range(0, len(pcm), step):
            live.feed(pcm[i:i + step])
        transcript = await live.finish(wait_s=2.5)
        latency = time.time() - t0
        if transcript:
            print(f" {Fore.GREEN}✅ {latency:.2f}s{Style.RESET_ALL}")
            print(f"  {Fore.YELLOW}📝  \"{transcript}\"{Style.RESET_ALL}")
            return _stt_result(transcript, len(pcm) / (AUDIO_SAMPLE_RATE * 2), latency, path=audio_path)
        print(f" {Fore.YELLOW}empty — batch{Style.RESET_ALL}")
        return await transcribe(audio_path, language)
    except Exception as e:
        await live.close()
        print(f" {Fore.YELLOW}{e} — batch{Style.RESET_ALL}")
        return await transcribe(audio_path, language)

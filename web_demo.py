"""
Browser demo — colleagues open a link and talk to Camille.

  Local:   .venv\\Scripts\\python.exe web_demo.py
  Open:    http://127.0.0.1:8000

  Host:    uvicorn web_demo:app --host 0.0.0.0 --port %PORT%
           Set WEB_DEMO_PASSWORD and the same API keys as .env.

Mic only works on localhost or HTTPS.
"""

from __future__ import annotations

import asyncio
import base64
import hmac
import io
import json
import os
import tempfile
import time
import uuid
import wave
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

load_dotenv()

from core.database import setup_database, seed_test_user, upsert_demo_user
from core.gladia_service import LiveSession, transcribe as gladia_batch
from core.llm_service import check as check_llm
from core.tts_service import text_to_speech_full
from edu import config as edu_config
from services.conversation_engine import iter_spoken_reply
from shared.lang import voice_language

WEB_DIR = Path(__file__).resolve().parent / "web"
PASSWORD = (os.getenv("WEB_DEMO_PASSWORD") or "").strip()
PORT = int(os.getenv("WEB_DEMO_PORT") or os.getenv("SERVER_PORT") or "8000")
MAX_CALLS = int(os.getenv("WEB_DEMO_MAX_CALLS", "4"))
SAMPLE_RATE = int(os.getenv("AUDIO_SAMPLE_RATE", "16000"))
LANGUAGE = (os.getenv("USER_LANGUAGE") or "hi-IN").strip()

app = FastAPI(title="Maîtria voice demo", docs_url=None, redoc_url=None)
if WEB_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")

_lang = None
_active = 0
_active_lock = asyncio.Lock()


def _lang_service():
    global _lang
    if _lang is None:
        if edu_config.IS_EDUCATION:
            from edu.lang_loader import load_edu_lang_service
            _lang = load_edu_lang_service(LANGUAGE)
        else:
            from shared.lang import load_lang_service
            _lang = load_lang_service(LANGUAGE)
    return _lang


def _greeting(lang_service, name: str, history) -> str:
    builder = getattr(lang_service, "build_greeting", None)
    if callable(builder):
        try:
            return builder(name, history)
        except Exception:
            pass
    return lang_service.GREETING.format(name=name)


def _pcm_to_wav(pcm: bytes, rate: int = SAMPLE_RATE) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(pcm)
    return buf.getvalue()


def _check_password(given: str) -> bool:
    if not PASSWORD:
        return False
    a = (given or "").strip().encode("utf-8")
    b = PASSWORD.encode("utf-8")
    if len(a) != len(b):
        return False
    return hmac.compare_digest(a, b)


@app.on_event("startup")
async def _startup():
    if not PASSWORD:
        raise RuntimeError("Set WEB_DEMO_PASSWORD in .env before starting the demo.")
    setup_database()
    seed_test_user()
    check_llm()
    _lang_service()
    print(f"Browser demo → http://127.0.0.1:{PORT}")
    print("Share the public HTTPS URL + the demo password. Mic needs HTTPS (or localhost).")


@app.get("/")
async def index():
    page = WEB_DIR / "index.html"
    if not page.is_file():
        return JSONResponse({"error": "web/index.html missing"}, status_code=500)
    return FileResponse(
        page,
        headers={"Cache-Control": "no-store, max-age=0"},
    )


@app.get("/health")
async def health():
    return {"ok": True, "calls": _active, "max": MAX_CALLS}


@app.websocket("/ws")
async def voice_ws(ws: WebSocket):
    global _active
    await ws.accept()
    async with _active_lock:
        if _active >= MAX_CALLS:
            await ws.send_json({"type": "error", "text": "Trop d'appels en cours. Réessayez dans une minute."})
            await ws.close()
            return
        _active += 1

    session = None
    lang = _lang_service()
    live: LiveSession | None = None
    pcm_buf = bytearray()
    listening = False

    async def send_json(payload: dict):
        await ws.send_json(payload)

    async def send_wav(wav: bytes | None):
        if wav:
            await ws.send_bytes(wav)

    async def close_live():
        nonlocal live
        if live is not None:
            await live.close()
            live = None

    print(f"WS connected from {ws.client}")
    try:
        first = await asyncio.wait_for(ws.receive_json(), timeout=20)
        if first.get("type") != "auth" or not _check_password(str(first.get("password") or "")):
            print("WS auth failed")
            await send_json({"type": "error", "text": "Wrong password. Use: demo"})
            await ws.close()
            return
        print("WS auth ok")

        name = (first.get("name") or "vous").strip()[:40] or "vous"
        phone = "+339" + f"{int(uuid.uuid4().int % 10**8):08d}"
        user = upsert_demo_user(name=name, phone=phone, language=LANGUAGE)
        if not user:
            await send_json({"type": "error", "text": "Impossible de créer la session."})
            await ws.close()
            return

        if edu_config.IS_EDUCATION:
            from edu.session_manager import EduSessionManager
            session = EduSessionManager(user, lang)
        else:
            from services.session_manager import SessionManager
            session = SessionManager(user, lang)

        greeting = _greeting(lang, session.user_name, session.history_summary)
        tts_cfg = lang.TTS_CONFIG
        voice_lang = voice_language(lang)
        print("session ready, sending greeting")
        await send_json({"type": "ready", "name": session.user_name, "agent": getattr(lang, "agent_name", None) or os.getenv("EDU_AGENT_NAME", "Camille")})
        await send_json({"type": "status", "text": "Camille vous appelle…"})
        greet = await text_to_speech_full(
            greeting, language=voice_lang,
            speaker=tts_cfg["speaker"], pace=tts_cfg["pace"],
            temperature=tts_cfg.get("temperature"),
            pause_ms=tts_cfg.get("pause_ms"),
        )
        session.record_sathi_turn(greeting, tts_chars=0)
        await send_json({"type": "assistant", "text": greeting})
        await send_wav(greet.get("wav_bytes"))
        await send_json({"type": "listen"})

        while True:
            msg = await ws.receive()
            if msg.get("type") == "websocket.disconnect":
                break

            if msg.get("bytes") is not None:
                if not listening:
                    continue
                chunk = msg["bytes"]
                pcm_buf.extend(chunk)
                if live is None:
                    live = LiveSession()
                    if not await live.start():
                        await live.close()
                        live = None
                if live is not None and chunk:
                    live.feed(chunk)
                continue

            data = msg.get("text")
            if not data:
                continue
            try:
                payload = json.loads(data)
            except json.JSONDecodeError:
                continue
            kind = payload.get("type")

            if kind == "audio_turn":
                await send_json({"type": "status", "text": "Un instant…"})
                t0 = time.time()
                transcript = ""
                raw_b64 = payload.get("data") or ""
                mime = (payload.get("mime") or "audio/webm").lower()
                try:
                    audio_bytes = base64.b64decode(raw_b64)
                except Exception:
                    audio_bytes = b""
                if len(audio_bytes) < 200:
                    await send_json({"type": "status", "text": "Rien reçu. Recliquez Start talking."})
                    await send_json({"type": "listen"})
                    continue
                ext = ".webm"
                if "ogg" in mime:
                    ext = ".ogg"
                elif "mp4" in mime or "m4a" in mime:
                    ext = ".mp4"
                elif "wav" in mime:
                    ext = ".wav"
                tmp = tempfile.NamedTemporaryFile(suffix=ext, delete=False)
                try:
                    tmp.write(audio_bytes)
                    tmp.close()
                    result = await gladia_batch(tmp.name, language=LANGUAGE)
                    transcript = (result.get("transcript") or "").strip()
                finally:
                    try:
                        os.unlink(tmp.name)
                    except OSError:
                        pass

                if not transcript:
                    await send_json({"type": "status", "text": "Je n'ai rien entendu. Réessayez."})
                    await send_json({"type": "listen"})
                    continue

                await send_json({"type": "user", "text": transcript, "stt_s": round(time.time() - t0, 2)})
                call_done = False
                async for item in iter_spoken_reply(session, lang, transcript):
                    if item.get("kind") == "phrase":
                        await send_json({"type": "assistant", "text": item.get("text") or ""})
                        await send_wav(item.get("wav"))
                    elif item.get("kind") == "done":
                        call_done = bool(item.get("call_done"))
                if call_done:
                    await send_json({"type": "end", "text": "Appel terminé."})
                    break
                await send_json({"type": "listen"})

            elif kind == "hangup":
                await send_json({"type": "end", "text": "À bientôt."})
                break

    except WebSocketDisconnect:
        print("WS disconnected")
    except asyncio.TimeoutError:
        print("WS auth timeout")
        try:
            await send_json({"type": "error", "text": "Connexion trop lente. Rechargez la page."})
        except Exception:
            pass
    except Exception as e:
        try:
            await send_json({"type": "error", "text": "La ligne a coupé. Rechargez la page."})
        except Exception:
            pass
        print(f"web_demo error: {e}")
    finally:
        await close_live()
        async with _active_lock:
            _active = max(0, _active - 1)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("web_demo:app", host="0.0.0.0", port=PORT, reload=False)

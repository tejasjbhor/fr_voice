"""FastAPI application for phone bridge."""

import os
import sys
from contextlib import asynccontextmanager
import asyncio

from colorama import init
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.console_utf8 import configure_console_utf8
from core.tts_service import close_http_session
from telephony.adapters import exotel, frejun, plivo, twilio
from telephony.log import setup_logging
from telephony.routes import app_api, common, local_call
from telephony.startup import startup_banner

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Root .env must win over any stale shell vars / nested edu/.env leftovers.
load_dotenv(os.path.join(_ROOT, ".env"), override=True)
init(autoreset=True)
configure_console_utf8()
setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await startup_banner()
    from core.database import recordings_info
    from telephony.daily_calls import scheduler_enabled, tick

    rec = recordings_info()
    print(f"  Recordings: {rec['dir']} ({rec['wav_files']} wav)")

    stop = asyncio.Event()

    async def _scheduler_loop():
        await asyncio.sleep(20)
        while not stop.is_set():
            try:
                result = await tick()
                if result.get("due"):
                    print(f"  Scheduler tick: {result}")
            except Exception as e:
                print(f"  Scheduler tick error: {e}")
            try:
                await asyncio.wait_for(stop.wait(), timeout=30)
            except asyncio.TimeoutError:
                pass

    task = None
    if scheduler_enabled():
        task = asyncio.create_task(_scheduler_loop())
    try:
        yield
    finally:
        stop.set()
        if task:
            task.cancel()
        # The Sarvam connection is pooled and kept alive across calls, so it
        # outlives any one session and has to be closed with the app.
        await close_http_session()
        from core.fish_service import close_session as close_fish_session
        await close_fish_session()


def create_app() -> FastAPI:
    app = FastAPI(title="AI Sathi Call Server", lifespan=lifespan)
    # Capacitor APK / local web UI call this API from another origin.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    common.register(app)
    app_api.register(app)
    local_call.register(app)
    exotel.register(app)
    frejun.register(app)
    twilio.register(app)
    plivo.register(app)
    # After API/websocket routes so GET / serves the Capacitor UI on Render.
    common.mount_mobile_ui(app)
    return app


app = create_app()

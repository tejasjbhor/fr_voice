"""Call server startup banner and DB init."""

import asyncio
import os

from colorama import Fore, Style

from core.database import seed_test_user, setup_database, sync_user_from_env
from core.llm_service import CLAUDE_MODEL, LLM_PROVIDER, OLLAMA_MODEL
from telephony.config import (
    APP_ENV,
    AUTO_DIAL_DELAY_S,
    AUTO_DIAL_ON_START,
    IS_PRODUCTION,
    EXOTEL_SID,
    FREJUN_API_KEY,
    FREJUN_FROM_NUMBER,
    PLIVO_AUTH_ID,
    PLIVO_AUTH_TOKEN,
    PLIVO_PHONE_NUMBER,
    SERVER_PORT,
    SERVER_PUBLIC_URL,
    TELEPHONY_PROVIDER,
    TWILIO_ACCOUNT_SID,
    TWILIO_AUTH_TOKEN,
    TWILIO_PHONE_NUMBER,
    USER_PHONE,
)


async def _auto_dial_user_phone():
    """Ring USER_PHONE via the active telephony provider (outbound)."""
    phone = USER_PHONE or (os.getenv("USER_PHONE") or "").strip()
    if not phone:
        print(f"{Fore.YELLOW}⚠️  AUTO_DIAL_ON_START set but USER_PHONE empty{Style.RESET_ALL}")
        return
    if not SERVER_PUBLIC_URL:
        print(f"{Fore.YELLOW}⚠️  AUTO_DIAL skipped — set SERVER_PUBLIC_URL first{Style.RESET_ALL}")
        return

    delay = max(0.5, AUTO_DIAL_DELAY_S)
    print(
        f"{Fore.CYAN}📞  Auto-dial in {delay:.0f}s → {phone} "
        f"({TELEPHONY_PROVIDER}){Style.RESET_ALL}"
    )
    await asyncio.sleep(delay)

    ok = False
    try:
        if TELEPHONY_PROVIDER == "twilio":
            from telephony.adapters.twilio import make_twilio_outbound_call
            ok = bool(await asyncio.to_thread(make_twilio_outbound_call, phone))
        elif TELEPHONY_PROVIDER == "plivo":
            from telephony.adapters.plivo import make_plivo_outbound_call
            ok = bool(await asyncio.to_thread(make_plivo_outbound_call, phone))
        elif TELEPHONY_PROVIDER == "frejun":
            from telephony.adapters.frejun import make_frejun_outbound_call
            ok = await make_frejun_outbound_call(phone)
        elif TELEPHONY_PROVIDER == "exotel":
            from telephony.adapters.exotel import (
                exotel_websocket_url,
                make_exotel_outbound_call,
            )
            ok = await asyncio.to_thread(
                make_exotel_outbound_call, phone, exotel_websocket_url()
            )
        else:
            print(
                f"{Fore.YELLOW}⚠️  AUTO_DIAL not supported for "
                f"TELEPHONY_PROVIDER={TELEPHONY_PROVIDER}{Style.RESET_ALL}"
            )
            return
    except Exception as e:
        print(f"{Fore.RED}❌ Auto-dial failed: {e}{Style.RESET_ALL}")
        return

    if ok:
        print(f"{Fore.GREEN}✅ Calling {phone} — pick up your phone{Style.RESET_ALL}")
    else:
        print(
            f"{Fore.RED}❌ Auto-dial failed — check Twilio logs / verified numbers"
            f"{Style.RESET_ALL}"
        )


async def startup_banner():
    from edu import config as edu_config
    from inbound import config as inbound_config

    if inbound_config.IS_INBOUND:
        product = f"Inbound helpline ({inbound_config.SERVICE_NAME})"
    elif edu_config.IS_EDUCATION:
        product = "Maîtria (education)"
    else:
        product = "AI Sathi"
    print(f"\n{Fore.BLUE}{'═'*60}")
    print(f"  📞  {product} Call Server")
    print(f"  Provider: {TELEPHONY_PROVIDER}")
    print(f"  PRODUCT: {inbound_config.PRODUCT}")
    print(f"  Port: {SERVER_PORT}")
    print(f"  Public URL: {SERVER_PUBLIC_URL or '⚠️  NOT SET'}")
    public = SERVER_PUBLIC_URL.rstrip("/") if SERVER_PUBLIC_URL else ""
    ws = public.replace("https://", "wss://").replace("http://", "ws://") if public else ""
    if TELEPHONY_PROVIDER == "frejun":
        print(f"  FreJun flow: {public}/frejun/flow" if public else "  FreJun flow: (set SERVER_PUBLIC_URL)")
        print(f"  FreJun WS:   .../frejun/media-stream")
    elif TELEPHONY_PROVIDER == "twilio":
        print(f"  Twilio voice: {public}/twilio/voice" if public else "  Twilio voice: (set SERVER_PUBLIC_URL)")
        print(f"  Twilio WS:    .../twilio/media-stream")
        print(f"  From number:  {TWILIO_PHONE_NUMBER or '(set TWILIO_PHONE_NUMBER)'}")
    elif TELEPHONY_PROVIDER == "plivo":
        print(f"  Plivo voice: {public}/plivo/voice" if public else "  Plivo voice: (set SERVER_PUBLIC_URL)")
        print(f"  Plivo WS:    .../plivo/media-stream")
        print(f"  From number:  {PLIVO_PHONE_NUMBER or '(set PLIVO_PHONE_NUMBER)'}")
    elif TELEPHONY_PROVIDER == "local":
        print(f"  LOCAL dummy calls — no Twilio/Exotel")
        print(f"  After Call Saathi now → open http://127.0.0.1:{SERVER_PORT}/local-call/<id>")
        print(f"  Emulator Backend URL → http://10.0.2.2:{SERVER_PORT}")
    else:
        print(f"  Exotel WS: {ws}/call/audio" if public else "  Exotel WS: (set SERVER_PUBLIC_URL)")
    model = f"Claude {CLAUDE_MODEL}" if LLM_PROVIDER == "claude" else f"Ollama {OLLAMA_MODEL}"
    print(f"  LLM: {model}")
    from core.concurrency import configured_limit
    from telephony.call_slots import capacity_snapshot
    from telephony.daily_calls import scheduler_enabled
    from telephony.outbound import resolve_outbound_provider

    cap = capacity_snapshot()
    print(f"  Outbound dial: {resolve_outbound_provider()}")
    print(f"  Scheduler: {'ON' if scheduler_enabled() else 'OFF (set SCHEDULER_ENABLED=1 on the dialer only)'}")
    print(
        f"  Call slots: "
        f"{'off' if not cap['max_concurrent_calls'] else cap['max_concurrent_calls']}"
        f" ({cap['backend']})"
    )
    print(
        f"  Sarvam gates: STT={configured_limit('sarvam_stt','SARVAM_STT_MAX_INFLIGHT',8)}"
        f" TTS={configured_limit('sarvam_tts','SARVAM_TTS_MAX_INFLIGHT',8)}"
        f" | Claude={configured_limit('claude','CLAUDE_MAX_INFLIGHT',8) or 'off'}"
    )
    slots = cap.get("max_concurrent_calls") or 0
    if 1 <= slots <= 16:
        print(f"  Pilot mode: {slots} concurrent max —  "
              f"{slots + 1}th call gets busy-out (Twilio Say / Exotel close)")
    if AUTO_DIAL_ON_START:
        print(f"  Auto-dial: ON → {USER_PHONE or '(set USER_PHONE)'}")
        if slots > 0:
            print(f"  {Fore.YELLOW}⚠️  AUTO_DIAL_ON_START with a call cap — "
                  f"prefer manual dial during concurrency tests{Style.RESET_ALL}")
    if scheduler_enabled() and slots > 0:
        print(f"  {Fore.YELLOW}⚠️  Scheduler ON during capped pilot — "
              f"set SCHEDULER_ENABLED=0 to avoid burning Twilio/Sarvam{Style.RESET_ALL}")
    print(f"{'═'*60}{Style.RESET_ALL}\n")

    setup_database()

    # Single-user PoC conveniences: seed_test_user() invents a "Ramesh" if the
    # table is empty, and sync_user_from_env() rewrites the first active user
    # from .env. Both are wrong against a real user table, so production skips
    # them — a deploy must never edit somebody's record.
    if IS_PRODUCTION:
        print(f"{Fore.CYAN}ℹ️  APP_ENV={APP_ENV}: skipping test-user seed and "
              f".env user sync{Style.RESET_ALL}")
    elif inbound_config.IS_INBOUND:
        # Helpline guests are created per caller — do not rewrite the first
        # DB row from leftover USER_NAME / USER_PHONE PoC values.
        print(f"{Fore.CYAN}ℹ️  PRODUCT=inbound: skipping .env user sync "
              f"(callers become inbound_guest rows){Style.RESET_ALL}")
        seed_test_user()
    else:
        seed_test_user()
        sync_user_from_env()

    if not SERVER_PUBLIC_URL:
        print(f"{Fore.YELLOW}⚠️  SERVER_PUBLIC_URL not set")
        print(f"   ngrok http {SERVER_PORT}")
        print(f"   then set SERVER_PUBLIC_URL=https://xxx.ngrok.io{Style.RESET_ALL}\n")

    if TELEPHONY_PROVIDER == "exotel" and not EXOTEL_SID:
        print(f"{Fore.YELLOW}⚠️  Exotel credentials not set{Style.RESET_ALL}\n")
    if TELEPHONY_PROVIDER == "frejun" and not FREJUN_API_KEY:
        print(f"{Fore.YELLOW}⚠️  FreJun/Teler API key not set (FREJUN_API_KEY){Style.RESET_ALL}\n")
    if TELEPHONY_PROVIDER == "frejun" and not FREJUN_FROM_NUMBER:
        print(f"{Fore.YELLOW}⚠️  FREJUN_FROM_NUMBER not set{Style.RESET_ALL}\n")
    if TELEPHONY_PROVIDER == "twilio" and (
        not TWILIO_ACCOUNT_SID or not TWILIO_AUTH_TOKEN or not TWILIO_PHONE_NUMBER
    ):
        print(f"{Fore.YELLOW}⚠️  Twilio incomplete — set TWILIO_ACCOUNT_SID, "
              f"TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER{Style.RESET_ALL}\n")
    if TELEPHONY_PROVIDER == "plivo" and (
        not PLIVO_AUTH_ID or not PLIVO_AUTH_TOKEN or not PLIVO_PHONE_NUMBER
    ):
        print(f"{Fore.YELLOW}⚠️  Plivo incomplete — set PLIVO_AUTH_ID, "
              f"PLIVO_AUTH_TOKEN, PLIVO_PHONE_NUMBER{Style.RESET_ALL}\n")

    if AUTO_DIAL_ON_START:
        asyncio.create_task(_auto_dial_user_phone())

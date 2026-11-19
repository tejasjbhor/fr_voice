"""
main.py v9 — AI Sathi — Free Conversation + Silent Extraction
=============================================================
Local mic mode. For Exotel phone calls: python call_server.py
                                 + scheduler: python scheduler.py

Architecture:
  - Language service loaded based on USER_LANGUAGE in .env
  - SessionManager tracks state, runs silent extractor each turn
  - ConversationEngine handles one turn cleanly
  - Personality prompt is free conversation — no checklist
  - Health data collected silently, NOT by direct questions
"""

import asyncio
import os
import sys
import time
from datetime import datetime

# `edu/` is a package inside the platform repo. Put the repo root on path so
# core / services / lang_services / shared resolve once (no nested mirrors).
_EDU_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_EDU_DIR)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from colorama import Fore, Back, Style, init
from tabulate import tabulate
from dotenv import load_dotenv

from core.console_utf8 import configure_console_utf8
from core.database     import (setup_database, seed_test_user, sync_user_from_env,
                                get_default_user, save_health_record, save_api_cost)
from core.tts_service  import text_to_speech_full, prewarm_phrases
from core.audio        import play_wav_bytes, check_microphone
from core.extractor    import deep_extract
from core.alert_engine import analyse
from core.llm_service  import check, LLM_PROVIDER, CLAUDE_MODEL, OLLAMA_MODEL

from core.call_recorder import CallRecorder, RECORD_CALL
from services.session_manager     import SessionManager
from services.conversation_engine import run_turn, thinking_sounds_for
from shared.lang                  import load_lang_service, voice_language
from edu import config as edu_config

load_dotenv()
configure_console_utf8()
init(autoreset=True)

def _greeting_for(lang_service, name: str, history_summary) -> str:
    """Context-aware greeting, falling back to the plain constant."""
    builder = getattr(lang_service, "build_greeting", None)
    if callable(builder):
        try:
            return builder(name, history_summary)
        except Exception:
            pass
    return lang_service.GREETING.format(name=name)


def _closing_for(lang_service, name: str, session) -> str:
    """Closing matched to how the call went, falling back to the constant."""
    builder = getattr(lang_service, "build_closing", None)
    if callable(builder):
        try:
            return builder(name, session.build_llm_context())
        except Exception:
            pass
    return lang_service.CLOSING.format(name=name)


ALERT_COLORS = {"green":Fore.GREEN,"yellow":Fore.YELLOW,
                "orange":Fore.YELLOW+Style.BRIGHT,"red":Fore.RED,
                "emergency":Back.RED+Fore.WHITE}
ALERT_EMOJIS = {"green":"🟢","yellow":"🟡","orange":"🟠","red":"🔴","emergency":"🚨"}


def print_banner(lang_name: str):
    model = CLAUDE_MODEL if LLM_PROVIDER=="claude" else OLLAMA_MODEL
    product = "EDU admissions" if edu_config.IS_EDUCATION else "AI SATHI v9"
    print(f"\n{Fore.BLUE}{'═'*62}")
    print(f"  🤖  {product} — {lang_name} | {model}")
    print(f"  Local mic test")
    print(f"{'═'*62}{Style.RESET_ALL}\n")


async def startup() -> bool:
    print(f"{Fore.CYAN}Startup...{Style.RESET_ALL}\n")
    ok = True
    lang = (os.getenv("USER_LANGUAGE") or "en-IN").strip()
    base = lang.split("-")[0].lower()
    if base == "fr":
        if not os.getenv("GLADIA_API_KEY", "").strip():
            print(f"{Fore.RED}❌ GLADIA_API_KEY missing (French STT){Style.RESET_ALL}"); ok = False
        else:
            print(f"{Fore.GREEN}✅ Gladia key found{Style.RESET_ALL}")
        if not os.getenv("ELEVENLABS_API_KEY", "").strip():
            print(f"{Fore.RED}❌ ELEVENLABS_API_KEY missing (French TTS){Style.RESET_ALL}"); ok = False
        else:
            print(f"{Fore.GREEN}✅ ElevenLabs key found{Style.RESET_ALL}")
    elif base == "es":
        if not os.getenv("ELEVENLABS_API_KEY", "").strip():
            print(f"{Fore.RED}❌ ELEVENLABS_API_KEY missing{Style.RESET_ALL}"); ok = False
        else:
            print(f"{Fore.GREEN}✅ ElevenLabs key found{Style.RESET_ALL}")
    else:
        key = os.getenv("SARVAM_API_KEY","")
        if not key or "your_" in key:
            print(f"{Fore.RED}❌ SARVAM_API_KEY missing{Style.RESET_ALL}"); ok = False
        else:
            print(f"{Fore.GREEN}✅ Sarvam key found{Style.RESET_ALL}")
    if not check(): ok = False
    try: setup_database(); seed_test_user(); sync_user_from_env()
    except Exception as e: print(f"{Fore.RED}❌ DB: {e}{Style.RESET_ALL}"); ok = False
    if not check_microphone(): ok = False
    return ok


async def end_call(session: SessionManager, lang_service):
    language = session.language
    name     = session.user_name
    tts_cfg  = lang_service.TTS_CONFIG

    print(f"\n{Fore.BLUE}{'═'*62}")
    print(f"  📋  Processing call...")
    print(f"{'═'*62}{Style.RESET_ALL}\n")

    # Closing message — skipped after a farewell turn, where she has already
    # said goodbye in her own words and would otherwise say it twice.
    if session.phase != "farewell":
        closing = _closing_for(lang_service, name, session)
        print(f"  {Fore.GREEN}🤖  {closing}{Style.RESET_ALL}")
        close_r = await text_to_speech_full(closing, language=voice_language(lang_service),
                                             speaker=tts_cfg["speaker"],
                                             pace=tts_cfg["pace"],
                                             temperature=tts_cfg.get("temperature"),
                                             pause_ms=tts_cfg.get("pause_ms"))
        if close_r.get("wav_bytes"):
            if session.call_recorder:
                session.call_recorder.append_silence(400)
                session.call_recorder.append_wav_bytes(close_r["wav_bytes"])
            await play_wav_bytes(close_r["wav_bytes"])
        session.total_tts_chars += close_r.get("char_count",0)

    # Save merged call audio (you + Sathi)
    if session.call_recorder:
        session.call_recorder.save()

    if edu_config.IS_EDUCATION:
        health = {}
    else:
        # Deep extraction from full conversation
        conv_text = "\n".join(
            f"{'User' if m['role']=='user' else 'Sathi'}: {m['content']}"
            for m in session.history
        )
        health = await deep_extract(conv_text, lang_service.NAME)

    # Merge fast-extracted data with deep extraction
    # Deep extraction wins for quality, fast_extracted fills gaps
    fast = session.extracted
    final_health = {**fast, **{k:v for k,v in health.items()
                                if v is not None and v is not False}}

    if final_health and not edu_config.IS_EDUCATION:
        save_health_record(session.user["id"], session.session_id, final_health)
        print(f"  {Fore.GREEN}✅  Health record saved{Style.RESET_ALL}")

    if edu_config.IS_EDUCATION:
        session.persist_outcome()

    # Save costs — from this session's own meter
    llm_costs = session.usage.as_dict()
    costs = save_api_cost(
        session.user["id"], session.session_id,
        session.total_stt_sec,
        session.total_tts_chars,
        session.total_tokens,
        llm_cost_inr=session.llm_cost_inr,
        llm_cache_write_tokens=session.llm_cache_write_tokens,
        llm_cache_read_tokens=session.llm_cache_read_tokens,
    )

    alert_level, alert_reason = analyse(session.user["id"])

    # Summary
    print(f"\n{Fore.BLUE}{'═'*62}")
    print(f"  📊  {datetime.now().strftime('%d %b %Y %H:%M')}")
    print(f"{'═'*62}{Style.RESET_ALL}\n")
    print(f"  👤  {name} | {session.session_id[:16]}...\n")

    if final_health:
        rows = []
        for lbl,k,ib in [("BP","bp_systolic",False),("Sugar","sugar_fasting",False),
                          ("Sleep","sleep_quality",False),("Food","food_intake",False),
                          ("Water","water_intake",False),("Mood","mood",False),
                          ("Dizzy","dizziness",True),("Chest","chest_discomfort",True)]:
            if ib:
                if final_health.get(k): rows.append([f"  {lbl}","⚠️ Yes"])
            else:
                if k == "bp_systolic" and final_health.get(k):
                    rows.append(["  BP", f"{final_health['bp_systolic']}/{final_health.get('bp_diastolic')}"])
                elif k != "bp_systolic" and final_health.get(k):
                    rows.append([f"  {lbl}", str(final_health[k])])
        if rows: print(tabulate(rows, tablefmt="plain"))
        print()

    # Fast-extracted this call
    if session.extracted:
        print(f"  {Fore.CYAN}⚡ Silently extracted this call:{Style.RESET_ALL}")
        for k,v in session.extracted.items():
            if v: print(f"     {k}: {v}")
        print()

    model_lbl = f"Claude {CLAUDE_MODEL}" if LLM_PROVIDER=="claude" else f"Ollama {OLLAMA_MODEL}"
    llm_str   = f"₹{llm_costs.get('cost_inr',0):.4f}" if LLM_PROVIDER=="claude" else "₹0 FREE"
    print(tabulate([
        ["  🎙️  STT", f"{session.total_stt_sec:.1f}s",   f"₹{costs.get('stt',0):.4f}"],
        ["  🔊  TTS", f"{session.total_tts_chars}ch",     f"₹{costs.get('tts',0):.4f}"],
        [f"  🧠  {model_lbl}", "", llm_str],
        ["  ──────","──────","──────────────"],
        ["  TOTAL","",f"₹{costs.get('total',0):.4f}"],
    ], tablefmt="plain"))

    if alert_level:
        c = ALERT_COLORS.get(alert_level, Fore.WHITE)
        e = ALERT_EMOJIS.get(alert_level, "•")
        print(f"\n  {c}{e}  ALERT: {alert_level.upper()}")
        if alert_reason and alert_reason != "All reported normal":
            print(f"  📌  {alert_reason}")
        family = session.user.get("family_name","Family")
        if alert_level in ("orange","red","emergency"):
            print(f"  📱  → Notify {family}: {alert_reason}")
        print(Style.RESET_ALL)

    print(f"\n{Fore.BLUE}{'═'*62}{Style.RESET_ALL}\n")


async def run_sathi():
    if not await startup():
        print(f"\n{Fore.RED}❌ Fix errors above then retry.{Style.RESET_ALL}\n")
        sys.exit(1)

    user = get_default_user()
    if not user:
        print(f"{Fore.RED}❌ No user. Run: python core/database.py{Style.RESET_ALL}")
        sys.exit(1)

    language     = user.get("language","fr-FR")
    if edu_config.IS_EDUCATION:
        from edu.lang_loader import load_edu_lang_service
        from edu.session_manager import EduSessionManager
        language = user.get("language") or edu_config.DEFAULT_LANGUAGE
        lang_service = load_edu_lang_service(language)
        session = EduSessionManager(user, lang_service)
    else:
        lang_service = load_lang_service(language)
        session = SessionManager(user, lang_service)
    voice_lang   = voice_language(lang_service)
    print_banner(lang_service.NAME)

    if RECORD_CALL:
        session.call_recorder = CallRecorder(session.session_id, user_name=user.get("name", "user"))
        print(f"{Fore.CYAN}💾  Call recording ON → recordings/{Style.RESET_ALL}")

    print(f"{Fore.GREEN}👤  {user.get('name')} | {language} | {lang_service.NAME}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}🎭  TTS: {lang_service.TTS_CONFIG['speaker']} "
          f"pace={lang_service.TTS_CONFIG['pace']}{Style.RESET_ALL}\n")

    # Greeting
    name     = session.user_name
    greeting = _greeting_for(lang_service, name, session.history_summary)
    print(f"{Fore.GREEN}🤖  Sathi: {greeting}{Style.RESET_ALL}")
    tts_cfg  = lang_service.TTS_CONFIG

    # Warm the filler cache in the background so the first "hmm..." is instant.
    asyncio.ensure_future(prewarm_phrases(
        thinking_sounds_for(tts_cfg), language=voice_lang,
        speaker=tts_cfg["speaker"], pace=tts_cfg["pace"],
        temperature=tts_cfg.get("temperature")))

    greet_r  = await text_to_speech_full(greeting, language=voice_lang,
                                          speaker=tts_cfg["speaker"],
                                          pace=tts_cfg["pace"],
                                          temperature=tts_cfg.get("temperature"),
                                          pause_ms=tts_cfg.get("pause_ms"))
    if greet_r.get("wav_bytes"):
        if session.call_recorder:
            session.call_recorder.append_wav_bytes(greet_r["wav_bytes"])
            session.call_recorder.append_silence(400)
        await play_wav_bytes(greet_r["wav_bytes"])
    session.total_tts_chars += greet_r.get("char_count",0)
    session.record_sathi_turn(greeting, tts_chars=0)

    print(f"\n{Fore.YELLOW}💬  Speak freely. Say '{lang_service.EXIT_WORDS[0]}' to end.{Style.RESET_ALL}\n")

    try:
        while True:
            session.start_turn()
            result = await run_turn(session, lang_service)

            session.total_stt_sec   += result.get("stt_sec",0)
            session.total_tts_chars += result.get("tts_chars",0)

            if not result.get("continue",True): break
            if session.is_call_done():
                print(f"\n{Fore.YELLOW}⏰  Call complete.{Style.RESET_ALL}")
                break

        await end_call(session, lang_service)
        print(f"{Fore.GREEN}✅  Done.{Style.RESET_ALL}\n")
    except KeyboardInterrupt:
        if session.call_recorder:
            session.call_recorder.save()
        print(f"\n\n{Fore.YELLOW}👋  Sathi signing off.{Style.RESET_ALL}\n")


if __name__ == "__main__":
    try:
        asyncio.run(run_sathi())
    except KeyboardInterrupt:
        print(f"\n\n{Fore.YELLOW}👋  Sathi signing off.{Style.RESET_ALL}\n")

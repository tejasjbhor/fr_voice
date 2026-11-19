# -*- coding: utf-8 -*-
"""
smoke_local.py — scripted end-to-end smoke test (no microphone)
================================================================
Drives the real main.py pipeline for English, Marathi and Hindi:

  greeting -> N turns -> exit phrase -> deep extraction -> alert

Each scripted user line is spoken by Sarvam TTS (a different speaker than
Sathi), written to a WAV, and fed to the real STT. So this exercises the full
chain — STT, prompt build, LLM stream, per-phrase TTS, silent extractor,
exit detection, deep extraction and the alert engine.

Speaker playback is stubbed out so timings reflect generation latency rather
than how long the audio takes to play through the speakers.

Run:  venv\\Scripts\\python.exe smoke_local.py
      venv\\Scripts\\python.exe smoke_local.py en      (single language)
"""

import asyncio
import os
import shutil
import sys
import time

from colorama import Fore, Style, init
from dotenv import load_dotenv

from core.console_utf8 import configure_console_utf8

load_dotenv()
configure_console_utf8()
init(autoreset=True)

import core.audio as audio_mod
import services.conversation_engine as ce
from core.database import setup_database, seed_test_user, get_default_user
from core.extractor import deep_extract
from core.alert_engine import analyse
from core.llm_service import (reset_costs, get_costs, LLM_PROVIDER,
                              CLAUDE_MODEL, _model_for)
from core.tts_service import synthesize_phrase
from services.session_manager import SessionManager

# Voices for the fake "user" — bulbul:v3 speakers, deliberately not Sathi's
# (Sathi is aditya in English, priya in Hindi/Marathi)
USER_VOICE = {"en-IN": "ashutosh", "hi-IN": "rahul", "mr-IN": "rahul"}
FALLBACK_USER_VOICE = "amit"


# ── Scripts ───────────────────────────────────────────────────────
# Each entry: (text, checks)
#   checks: set of tags asserted against Sathi's reply
#     "no_question"  -> reply must contain no question mark
#     "brief"        -> at most 2 sentences
#     "exit"         -> this line must end the call
SCRIPTS = {
    "en-IN": [
        ("I am not feeling too good today. My head has been aching since morning.", set()),
        ("No, I could not eat anything. I did not even make breakfast.", set()),
        ("Please suggest one thing I can do right now.", {"no_question"}),
        ("Okay thank you so much. Bye.", {"exit"}),
    ],
    "mr-IN": [
        ("आज बरं वाटत नाही. सकाळपासून डोकं दुखतंय.", set()),
        ("नाही, जेवण झालं नाही. मनच नाही झालं आज.", set()),
        ("काय करावं ते सांगा, एक उपाय सांगा.", {"no_question"}),
        ("बरं साथी, धन्यवाद. बाय.", {"exit"}),
    ],
    "hi-IN": [
        ("आज तबियत ठीक नहीं है। सुबह से गर्दन में दर्द हो रहा है।", set()),
        ("तुम बहुत बोलती हो। कम बोलो।", {"brief"}),
        ("घुटने के दर्द के लिए कुछ सुझाव दो।", {"no_question"}),
        ("ठीक है साथी फोन रखो अभी", {"exit"}),
    ],
}

LANG_NAMES = {"en-IN": "English", "mr-IN": "Marathi", "hi-IN": "Hindi"}
ALIASES = {"en": "en-IN", "mr": "mr-IN", "hi": "hi-IN"}


def load_lang_service(code: str):
    if code == "mr-IN":
        import lang_services.marathi as svc
    elif code == "hi-IN":
        import lang_services.hindi as svc
    else:
        import lang_services.english as svc
    return svc


# ── Fake mic ──────────────────────────────────────────────────────

class ScriptedMic:
    """Serves pre-synthesized WAVs in place of record_audio()."""

    def __init__(self):
        self.queue = []
        self.real_record = ce.record_audio
        self.real_play = audio_mod.play_wav_bytes

    def load(self, wav_paths):
        self.queue = list(wav_paths)

    async def record_audio(self, output_path="user_input.wav", duration=None):
        if not self.queue:
            return None
        src = self.queue.pop(0)
        shutil.copyfile(src, output_path)
        return output_path

    def install(self):
        ce.record_audio = self.record_audio
        # Silence playback everywhere it is used
        async def _noop(*_a, **_k):
            return None
        audio_mod.play_wav_bytes = _noop
        ce.AudioPlayer = _SilentPlayer

    def restore(self):
        ce.record_audio = self.real_record
        audio_mod.play_wav_bytes = self.real_play


class _SilentPlayer:
    """Drop-in for AudioPlayer that records timings but plays nothing."""

    def __init__(self, on_enqueue=None):
        self.on_enqueue = on_enqueue
        self.chunks = 0

    async def start(self):
        return None

    async def enqueue(self, wav_bytes):
        self.chunks += 1
        if self.on_enqueue and wav_bytes:
            self.on_enqueue(wav_bytes)

    async def drain(self):
        return None

    async def stop(self):
        return None


# ── Synthesis of the scripted user lines ──────────────────────────

async def make_user_wavs(language, lines, outdir):
    os.makedirs(outdir, exist_ok=True)
    voice = USER_VOICE.get(language, FALLBACK_USER_VOICE)
    paths = []
    for i, (text, _) in enumerate(lines, start=1):
        path = os.path.join(outdir, f"{language}_{i}.wav")
        if not os.path.exists(path):
            wav = await synthesize_phrase(text, language=language,
                                          speaker=voice, pace=1.0)
            if not wav:
                wav = await synthesize_phrase(text, language=language,
                                              speaker=FALLBACK_USER_VOICE, pace=1.0)
            if not wav:
                print(f"  {Fore.RED}✗ could not synthesize: {text[:40]}{Style.RESET_ALL}")
                return None
            with open(path, "wb") as f:
                f.write(wav)
        paths.append(path)
    return paths


# ── Reply checks ──────────────────────────────────────────────────

_GREET_MARKERS = ["नमस्ते", "नमस्कार", "sathi here", "sathi बोल", "मी sathi"]


def check_reply(reply: str, tags: set) -> list:
    problems = []
    if not reply.strip():
        return ["empty reply"]
    if "\n" in reply:
        problems.append("contains line break")
    sentences = [s for s in reply.replace("!", ".").replace("?", ".")
                 .replace("।", ".").split(".") if s.strip()]
    if len(sentences) > 3:
        problems.append(f"{len(sentences)} sentences (max 3)")
    if "brief" in tags and len(sentences) > 2:
        problems.append(f"asked to be brief but used {len(sentences)} sentences")
    qs = reply.count("?")
    if qs > 1:
        problems.append(f"{qs} questions (max 1)")
    if "no_question" in tags and qs > 0:
        problems.append("asked a question when a remedy was requested")
    low = reply.lower()
    if any(m in low for m in _GREET_MARKERS):
        problems.append("re-greeted mid-call")
    return problems


# ── One language run ──────────────────────────────────────────────

async def run_language(language, mic, user) -> dict:
    lang_svc = load_lang_service(language)
    lines = SCRIPTS[language]
    name = LANG_NAMES[language]
    model = _model_for(language) if LLM_PROVIDER == "claude" else "ollama"

    print(f"\n{Fore.BLUE}{'='*70}")
    print(f"  {name}  ({language})   model: {model}")
    print(f"{'='*70}{Style.RESET_ALL}")

    wavs = await make_user_wavs(language, lines, "_smoke_audio")
    if not wavs:
        return {"language": name, "error": "TTS failed for user lines"}
    mic.load(wavs)

    session_user = dict(user)
    session_user["language"] = language
    session = SessionManager(session_user, lang_svc)
    reset_costs()

    # ── START: greeting ───────────────────────────────────────────
    _greet = getattr(lang_svc, "build_greeting", None)
    greeting = (_greet(session.user_name, session.history_summary)
                if callable(_greet)
                else lang_svc.GREETING.format(name=session.user_name))
    t0 = time.time()
    greet_wav = await synthesize_phrase(greeting, language=language,
                                       speaker=lang_svc.TTS_CONFIG["speaker"],
                                       pace=lang_svc.TTS_CONFIG["pace"])
    greet_ms = (time.time() - t0) * 1000
    print(f"\n  {Fore.GREEN}START  Sathi: {greeting}{Style.RESET_ALL}")
    print(f"         greeting TTS {greet_ms:.0f}ms "
          f"{'ok' if greet_wav else Fore.RED + 'TTS FAILED' + Style.RESET_ALL}")
    session.record_sathi_turn(greeting, tts_chars=0)

    turns, issues, ended_on_exit = [], [], False

    for idx, (user_line, tags) in enumerate(lines, start=1):
        session.start_turn()
        t_turn = time.time()
        result = await ce.run_turn(session, lang_svc)
        elapsed = time.time() - t_turn

        heard = (result.get("user_text") or "").strip()
        reply = (result.get("sathi_text") or "").strip()

        print(f"\n  {Fore.YELLOW}TURN {idx}{Style.RESET_ALL}")
        print(f"    said  : {user_line}")
        print(f"    heard : {heard}")

        if not result.get("continue", True):
            issues.append(f"turn {idx}: call ended unexpectedly")
            print(f"    {Fore.RED}-> call ended unexpectedly{Style.RESET_ALL}")
            turns.append({"idx": idx, "elapsed": elapsed, "ended": True})
            break

        print(f"    Sathi : {reply}")
        problems = check_reply(reply, tags)
        if problems:
            for p in problems:
                issues.append(f"turn {idx}: {p}")
            print(f"    {Fore.RED}-> {'; '.join(problems)}{Style.RESET_ALL}")
        else:
            print(f"    {Fore.GREEN}-> reply checks ok{Style.RESET_ALL}")
        print(f"    time  : {elapsed:.2f}s total")

        turns.append({"idx": idx, "elapsed": elapsed,
                      "heard": heard, "reply": reply, "ended": False})

        # A goodbye no longer hangs up on the spot: she answers it on this turn
        # and the call closes straight after (session.phase == "farewell").
        if session.is_call_done():
            if "exit" in tags:
                ended_on_exit = True
                print(f"    {Fore.GREEN}-> answered the goodbye, then ended "
                      f"(correct){Style.RESET_ALL}")
            break

        if "exit" in tags:
            issues.append(f"turn {idx}: exit phrase NOT detected")
            print(f"    {Fore.RED}-> exit phrase not detected{Style.RESET_ALL}")

    # ── END: closing + deep extraction + alert ────────────────────
    # Mirrors main.end_call: after a farewell turn she has already said goodbye
    # in her own words, so the fixed closing would be a second goodbye.
    if session.phase == "farewell":
        print(f"\n  {Fore.GREEN}END    (she said goodbye herself — no fixed "
              f"closing){Style.RESET_ALL}")
    else:
        builder = getattr(lang_svc, "build_closing", None)
        closing = (builder(session.user_name, session.build_llm_context())
                   if callable(builder)
                   else lang_svc.CLOSING.format(name=session.user_name))
        print(f"\n  {Fore.GREEN}END    Sathi: {closing}{Style.RESET_ALL}")

    conv = "\n".join(f"{'User' if m['role']=='user' else 'Sathi'}: {m['content']}"
                     for m in session.history)
    t0 = time.time()
    health = await deep_extract(conv, lang_svc.NAME)
    extract_s = time.time() - t0
    merged = {**session.extracted,
              **{k: v for k, v in health.items() if v not in (None, False)}}

    print(f"\n  extraction ({extract_s:.2f}s): "
          f"{ {k: v for k, v in merged.items() if v} or 'nothing found'}")
    if not merged:
        issues.append("deep extraction found nothing")

    level, reason = analyse(session_user["id"])
    print(f"  alert: {level} — {reason}")

    costs = get_costs()
    return {
        "language": name,
        "model": model,
        "turns": turns,
        "issues": issues,
        "ended_on_exit": ended_on_exit,
        "extracted": merged,
        "extract_s": extract_s,
        "cost_inr": costs.get("cost_inr", 0.0),
    }


# ── Main ──────────────────────────────────────────────────────────

async def main():
    wanted = [ALIASES.get(a, a) for a in sys.argv[1:]] or ["en-IN", "mr-IN", "hi-IN"]

    if not os.getenv("SARVAM_API_KEY", "").strip():
        print(f"{Fore.RED}SARVAM_API_KEY missing — cannot run smoke test{Style.RESET_ALL}")
        return 1

    setup_database()
    seed_test_user()
    user = get_default_user()
    if not user:
        print(f"{Fore.RED}No user in DB{Style.RESET_ALL}")
        return 1

    mic = ScriptedMic()
    mic.install()
    results = []
    try:
        for lang in wanted:
            results.append(await run_language(lang, mic, user))
    finally:
        mic.restore()

    # ── Report ────────────────────────────────────────────────────
    print(f"\n{Fore.BLUE}{'='*70}")
    print("  SMOKE TEST SUMMARY")
    print(f"{'='*70}{Style.RESET_ALL}\n")

    total_issues = 0
    for r in results:
        if r.get("error"):
            print(f"  {Fore.RED}{r['language']}: {r['error']}{Style.RESET_ALL}")
            total_issues += 1
            continue
        spoken = [t for t in r["turns"] if not t["ended"]]
        times = [t["elapsed"] for t in spoken]
        avg = sum(times) / len(times) if times else 0
        worst = max(times) if times else 0
        issues = r["issues"]
        total_issues += len(issues)
        mark = f"{Fore.GREEN}PASS" if not issues else f"{Fore.RED}{len(issues)} ISSUE(S)"
        print(f"  {r['language']:8} {mark}{Style.RESET_ALL}  "
              f"model={r['model']}")
        print(f"           turns={len(spoken)} avg={avg:.2f}s worst={worst:.2f}s "
              f"exit={'ok' if r['ended_on_exit'] else 'MISSED'} "
              f"extract={r['extract_s']:.2f}s cost=₹{r['cost_inr']:.4f}")
        fields = [k for k, v in r["extracted"].items() if v]
        print(f"           captured: {', '.join(fields) if fields else 'nothing'}")
        for i in issues:
            print(f"           {Fore.RED}- {i}{Style.RESET_ALL}")
        print()

    if total_issues == 0:
        print(f"  {Fore.GREEN}ALL LANGUAGES PASSED{Style.RESET_ALL}\n")
        return 0
    print(f"  {Fore.RED}{total_issues} issue(s) found{Style.RESET_ALL}\n")
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

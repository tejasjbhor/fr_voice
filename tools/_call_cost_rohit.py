"""Full cost breakdown for the latest Rohit en-IN call (session 90b3765c)."""
from __future__ import annotations

import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sathi_poc.db")

# App rate card (core/database.py + core/llm_service.py)
STT_INR_PER_HOUR = 30.0
TTS_INR_PER_10K_CHARS = 30.0
# Haiku 4.5 ₹/token
HAIKU_IN = 0.000083
HAIKU_OUT = 0.000415

# Actual Twilio charge for this call SID (from Twilio API): -$0.19840 USD
TWILIO_USD_THIS_CALL = float(os.getenv("TWILIO_USD_THIS_CALL", "0.19840"))
USD_INR = float(os.getenv("USD_INR", "83.5"))

# From server log for this call
LOG_SESSION = "90b3765c"
LOG_DURATION_SEC = 181.6
LOG_TURNS = 12
LOG_LLM_IN = 28071
LOG_LLM_OUT = 328
LOG_LLM_INR = 2.4660
LOG_RECORDING_SEC = 83.2  # mixed WAV length saved to disk (not billable)


def main() -> None:
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row

    user = c.execute(
        "SELECT id, name, phone, language FROM users WHERE name LIKE '%Rohit%' LIMIT 1"
    ).fetchone()
    print("=== user ===")
    print(dict(user) if user else None)

    # Turns for this session
    turns = c.execute(
        """
        SELECT id, session_id, role, language, prompt_version,
               char_count, audio_duration, created_at,
               substr(message, 1, 80) AS msg
        FROM conversations
        WHERE session_id LIKE ?
        ORDER BY id
        """,
        (f"%{LOG_SESSION}%",),
    ).fetchall()

    if not turns:
        # fallback: latest Rohit user turns
        turns = c.execute(
            """
            SELECT id, session_id, role, language, prompt_version,
                   char_count, audio_duration, created_at,
                   substr(message, 1, 80) AS msg
            FROM conversations
            WHERE user_id = ?
            ORDER BY id DESC LIMIT 40
            """,
            (user["id"] if user else -1,),
        ).fetchall()
        turns = list(reversed(turns))

    print(f"\n=== turns ({len(turns)}) ===")
    session_id = turns[0]["session_id"] if turns else None
    user_chars = 0
    agent_chars = 0
    stt_audio_sec = 0.0
    for t in turns:
        role = t["role"]
        chars = t["char_count"] or len(t["msg"] or "")
        dur = t["audio_duration"] or 0.0
        if role == "user":
            user_chars += chars
            stt_audio_sec += float(dur or 0)
        else:
            agent_chars += chars
        print(
            f"  [{t['created_at']}] {role:9} lang={t['language']} "
            f"pv={t['prompt_version']} chars={chars} audio={dur} | {t['msg']}"
        )

    costs = None
    if session_id:
        costs = c.execute(
            "SELECT * FROM api_costs WHERE session_id LIKE ? ORDER BY id DESC LIMIT 1",
            (f"%{session_id[:8]}%",),
        ).fetchone()
    if not costs and user:
        costs = c.execute(
            "SELECT * FROM api_costs WHERE user_id=? ORDER BY id DESC LIMIT 1",
            (user["id"],),
        ).fetchone()
    if not costs:
        costs = c.execute("SELECT * FROM api_costs ORDER BY id DESC LIMIT 1").fetchone()

    print("\n=== api_costs row ===")
    print(dict(costs) if costs else None)

    # Prefer DB numbers; fall back to log
    duration_sec = LOG_DURATION_SEC
    minutes = duration_sec / 60.0

    if costs:
        stt_sec = float(costs["stt_seconds"] or 0)
        tts_chars = int(costs["tts_chars"] or 0)
        llm_tokens = int(costs["llm_tokens"] or 0)
        cache_w = int(costs["llm_cache_write_tokens"] or 0)
        cache_r = int(costs["llm_cache_read_tokens"] or 0)
        stt_inr = float(costs["stt_cost_inr"] or 0)
        tts_inr = float(costs["tts_cost_inr"] or 0)
        llm_inr = float(costs["llm_cost_inr"] or 0)
        total_api = float(costs["total_cost_inr"] or 0)
    else:
        stt_sec = stt_audio_sec or (LOG_RECORDING_SEC * 0.5)  # rough
        tts_chars = agent_chars
        llm_tokens = LOG_LLM_IN + LOG_LLM_OUT
        cache_w = cache_r = 0
        stt_inr = round(stt_sec * (STT_INR_PER_HOUR / 3600), 4)
        tts_inr = round(tts_chars * (TTS_INR_PER_10K_CHARS / 10000), 4)
        llm_inr = LOG_LLM_INR
        total_api = round(stt_inr + tts_inr + llm_inr, 4)

    # Reconcile Claude from log token split if helpful
    llm_check = LOG_LLM_IN * HAIKU_IN + LOG_LLM_OUT * HAIKU_OUT

    twilio_usd = TWILIO_USD_THIS_CALL
    twilio_inr = twilio_usd * USD_INR
    twilio_per_min_usd = twilio_usd / minutes
    grand = total_api + twilio_inr

    print("\n" + "=" * 64)
    print("ROHIT en-IN CALL — FULL COST SYNTHESIS")
    print("=" * 64)
    print(f"Session:     {session_id or LOG_SESSION}")
    print(f"Duration:    {duration_sec:.1f}s  ({minutes:.3f} min)  |  {LOG_TURNS} turns")
    print(f"Language:    en-IN / prompt en-v12 (from log + packs)")
    print(f"Recording:   {LOG_RECORDING_SEC}s mixed WAV on disk (not a billable meter)")
    print()
    print("--- usage ---")
    print(f"  STT audio seconds:     {stt_sec:.2f}s")
    print(f"  TTS characters:        {tts_chars}")
    print(f"  LLM tokens (total):    {llm_tokens}  (log: {LOG_LLM_IN} in / {LOG_LLM_OUT} out)")
    print(f"  LLM cache write:       {cache_w}")
    print(f"  LLM cache read:        {cache_r}  (0 = persona cache did not engage — expected for en Haiku)")
    print(f"  User chars (turns):    {user_chars}")
    print(f"  Agent chars (turns):   {agent_chars}")
    print()
    # STT duration was not metered (Sarvam body.duration missing → 0).
    # Estimate from saved mixed recording (~half is user speech) as a floor.
    stt_est_sec = LOG_RECORDING_SEC * 0.5
    stt_est_inr = round(stt_est_sec * (STT_INR_PER_HOUR / 3600), 4)
    api_with_stt_est = round(total_api - stt_inr + stt_est_inr, 4)

    print("--- rate card (what the app uses) ---")
    print(f"  Sarvam STT:   Rs {STT_INR_PER_HOUR}/hour of audio  (= Rs {STT_INR_PER_HOUR/60:.4f}/min audio)")
    print(f"  Sarvam TTS:   Rs {TTS_INR_PER_10K_CHARS} / 10,000 chars")
    print(f"  Claude Haiku: Rs {HAIKU_IN}/input tok  +  Rs {HAIKU_OUT}/output tok")
    print(f"  Twilio (actual): ${twilio_usd:.5f} this call  (= ${twilio_per_min_usd:.4f}/min)")
    print(f"  FX assumption:   1 USD = Rs {USD_INR}")
    print()
    print("--- cost this call ---")
    print(f"  Claude LLM:            Rs {llm_inr:.4f}")
    print(f"    (sanity from log tokens @ Haiku, no cache): Rs {llm_check:.4f}")
    print(f"  Sarvam STT (metered):  Rs {stt_inr:.4f}   << metered 0s (Sarvam duration missing)")
    print(f"  Sarvam STT (estimate): Rs {stt_est_inr:.4f}   << ~{stt_est_sec:.0f}s user audio from recording")
    print(f"  Sarvam TTS:            Rs {tts_inr:.4f}   ({tts_chars} chars)")
    print(f"  API subtotal (DB):     Rs {total_api:.4f}")
    print(f"  API + STT estimate:    Rs {api_with_stt_est:.4f}")
    print(f"  Twilio voice (actual): Rs {twilio_inr:.2f}  (${twilio_usd:.5f})")
    grand2 = api_with_stt_est + twilio_inr
    print(f"  GRAND (DB API+Twilio): Rs {grand:.2f}")
    print(f"  GRAND (+STT est):      Rs {grand2:.2f}")
    print()
    print("--- per minute (wall-clock call, 3.027 min) ---")
    print(f"  API only (DB):         Rs {total_api / minutes:.4f} / min")
    print(f"  API + STT est:         Rs {api_with_stt_est / minutes:.4f} / min")
    print(f"  Twilio alone:          Rs {twilio_inr / minutes:.4f} / min  (${twilio_per_min_usd:.4f}/min)")
    print(f"  API + Twilio:          Rs {grand / minutes:.4f} / min")
    print(f"  All-in (+STT est):     Rs {grand2 / minutes:.4f} / min")
    print()
    print("--- share of DB API bill ---")
    if total_api > 0:
        print(f"  Claude:  {100 * llm_inr / total_api:5.1f}%")
        print(f"  STT:     {100 * stt_inr / total_api:5.1f}%")
        print(f"  TTS:     {100 * tts_inr / total_api:5.1f}%")
    print()
    print("Note: English Haiku persona is below the 4096-token cache floor,")
    print("so every turn re-pays the full prompt — that is why Claude dominates.")


if __name__ == "__main__":
    main()

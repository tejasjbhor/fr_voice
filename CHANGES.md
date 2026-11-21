# Maitria Voice Service — Patch Notes

All fixes apply to `core/`, `services/`, and `lang_services/` at the repo
root. Nested mirror copies under `edu/` / `edu_app/` were removed.

---

## Inbound helpline module (2026-11-20)

New `inbound/` product (edu-style): `PRODUCT=inbound` makes unknown callers
`inbound_guest` users, loads HI/MR/EN helpline packs, skips health extract,
appends `inbound/data/queries.jsonl`. Same 8-call concurrency gates. Guide:
`inbound/README.md`.

---

## 8-call concurrency pilot tuned (2026-11-20)

`.env` + safer code defaults for a budget pilot: `MAX_CONCURRENT_CALLS=8`,
Sarvam/Claude in-flight 8, Twilio-only outbound, `OPEN_DIALER=true`,
scheduler and auto-dial off, `SERVER_PUBLIC_URL` stripped of spaces.
Outbound over capacity returns HTTP **503** `capacity_full`.
Curl template: `scripts/pilot_outbound_examples.cmd`.
Guide: `docs/PILOT_8_CALLS.md`.

---

## Production concurrency gates (2026-11-20)

**Problem:** One process could open unlimited Twilio/Exotel sockets and stampede
Sarvam / Claude past account rate limits, turning a spike into 429s for every
live call.

**Fix:**
- `core/concurrency.py` — env-driven semaphores (`SARVAM_STT_MAX_INFLIGHT`,
  `SARVAM_TTS_MAX_INFLIGHT`, `CLAUDE_MAX_INFLIGHT`).
- `telephony/call_slots.py` — `MAX_CONCURRENT_CALLS` with `memory` or
  `postgres` backend; Twilio busy TwiML + Exotel socket refuse.
- `telephony/outbound.py` — shared dial path + capacity check;
  `OUTBOUND_PROVIDER` override; `OUTBOUND_CPS` pacing in the scheduler.
- Call replicas set `SCHEDULER_ENABLED=0`; one dialer keeps it on.

Defaults leave the PoC unlimited (`MAX_CONCURRENT_CALLS=0`). Vendor plan
upgrades are still required for 1k+ live calls — these gates only enforce
what the account already allows.

---

## Fix 1 — STT session pooling (`core/stt_service.py`)

**Problem:** `_transcribe_sarvam()` opened a fresh `aiohttp.ClientSession`
on every turn, paying a TCP + TLS handshake (~150–300 ms) before each STT
request. The TTS side had already fixed this in a prior commit via
`_sarvam_session()`, but STT was never aligned.

**Fix:** Added a module-level `_sarvam_stt_session()` that reuses a
keep-alive pooled session (same pattern as `tts_service.py`). A
`close_stt_session()` teardown helper mirrors `close_http_session()`.

**Impact:** Saves ~150–300 ms per turn for all Hindi, Marathi, and English
callers. No change for French (Gladia) or Spanish (ElevenLabs).

---

## Fix 2 — French TTS: temperature + thinking sounds (`lang_services/french/tts_config.py`)

**Problem (temperature):** `temperature: 0.85` was too high for Camille's
composed professional persona, causing unpredictable prosody variation — tone
wobbled between turns.

**Fix:** Lowered to `0.68`. Consistent, calm delivery while preserving
natural French intonation.

**Problem (thinking sounds):** The thinking-sound list contained some
French fillers but was missing the most natural native-speaker acknowledgements.

**Fix:** Expanded to include `"Tout à fait..."`, `"Bien sûr..."`,
`"Effectivement..."`. Soft subset (safe over difficult news) stays with
`"Hmm..."`, `"Je vois..."`, `"D'accord..."`.

**Added:** `"elevenlabs_model_hint": "eleven_turbo_v2_5"` — advisory field
read by `tts_service.py` to route French ElevenLabs calls to the turbo model
(~35% lower latency) without requiring an `.env` change.

---

## Fix 3 — ElevenLabs turbo model for French (`core/elevenlabs_service.py`)

**Problem:** `synthesize_phrase()` always used the global
`ELEVENLABS_TTS_MODEL_ID` (defaulting to `eleven_multilingual_v2`), with no
way for a language pack to elect a faster model.

**Fix:** Added optional `model_hint: str | None` parameter. When provided,
it overrides `ELEVENLABS_TTS_MODEL_ID` for that call. French TTS_CONFIG sets
`"elevenlabs_model_hint": "eleven_turbo_v2_5"` which shaves ~35% off French
TTS latency with no quality regression at conversational speech rates.

---

## Fix 4 — TTS fallback chain (`core/tts_service.py`)

**Problem:** When Fish Audio or ElevenLabs returned `None` (timeout, 4xx,
network error), `synthesize_phrase()` propagated `None` straight to the
AudioPlayer queue. The caller heard silence and assumed the call had dropped.

**Fix:** Explicit fallback chain:
- Fish failure on HI/MR/EN → falls back to Sarvam and logs a warning.
- Fish failure on FR/ES → logs; no viable fallback (Sarvam lacks FR/ES
  voice quality), returns `None` gracefully.
- ElevenLabs failure → falls back to Sarvam when `SARVAM_KEY` is present;
  audio quality may differ but the call stays live.
- Sarvam failure → logs and returns `None` (last resort; silence once is
  acceptable, silence every turn is the old behaviour).

`model_hint` is now threaded through `text_to_speech_full()`,
`synthesize_cached()`, `prewarm_phrases()`, and the cache key so the French
turbo model is used consistently for greetings, closings, fillers, and
mid-call phrases.

---

## Fix 5 — Abbreviation-aware sentence splitting (`core/tts_service.py`)

**Problem:** `_split_sentences()` used a plain `(?<=[.!?])\\s+` regex. A
response containing "M. Dupont a confirmé." split into `["M.", "Dupont a
confirmé."]`. TTS synthesised `"M."` alone with sentence-final intonation —
sounding clipped and broken. Same issue with Dr., Mme., Prof., etc.

**Fix:** Added `_ABBREV_RE` — a compiled regex matching common French,
English, and Spanish title abbreviations. The splitter accumulates fragments
ending with an abbreviation dot into `pending` and re-joins them with the
next segment before emitting. Covers: M, Mme, Mlle, Dr, Me, Prof, Sr, Sra,
Mr, Mrs, Ms, St, Etc, etc, vs, Jr, Yr, no, No.

---

## Fix 6 — Echo detection threshold (`services/conversation_engine.py`)

**Problem:** `_looks_like_echo()` used a 65% word-overlap threshold. A
caller saying "Hmm, right, I understand" after Camille said "I see, right?"
hit 67% overlap and was silently discarded as playback echo.

**Fix:**
- Raised word-overlap threshold from `0.65` → `0.75`.
- Added 8-word length guard: utterances longer than 8 words skip the
  overlap check entirely — they almost certainly contain novel content even
  if they share common filler words with Sathi.

---

## Fix 7 — Abbreviation guard in streaming splitter (`services/conversation_engine.py`)

**Problem:** The streaming `_split()` function (which feeds LLM tokens into
TTS phrases in real time) used the same bare `_SENTENCE_RE` with no
abbreviation awareness. Mid-stream "Dr. Chen recommends..." would split at
"Dr." and emit it as a standalone phrase.

**Fix:** Added `_ABBREV_RE` (same pattern as Fix 5) and injected a
`continue` guard in the `for chunk in complete:` loop — chunks ending with
an abbreviation are accumulated in `pending` instead of being emitted.

---

## Files changed

| File | Fixes applied |
|---|---|
| `core/stt_service.py` | Fix 1 |
| `core/tts_service.py` | Fix 4, 5 (+ model_hint threading for Fix 3) |
| `core/elevenlabs_service.py` | Fix 3 |
| `lang_services/french/tts_config.py` | Fix 2 |
| `services/conversation_engine.py` | Fix 6, 7 |
| `edu/core/*`, `edu_app/core/*` | Mirror of all core fixes |
| `edu/lang_services/french/tts_config.py` | Mirror of Fix 2 |
| `edu_app/lang_services/french/tts_config.py` | Mirror of Fix 2 |
| `edu/services/conversation_engine.py` | Mirror of Fix 6, 7 |
| `edu_app/services/conversation_engine.py` | Mirror of Fix 6, 7 |

---

## What was deliberately NOT changed

- **VAD silence threshold** (`SILENCE_SECONDS=0.65` in `.env`) — already at
  a good value; further reduction risks cutting off slower speakers.
- **POST_TTS_LISTEN_GAP_S** (`0.35` in `.env`) — already tuned; telephony
  mode doesn't need a separate value since the env already reflects a phone
  deployment setting.
- **Marathi pace** (0.80) — intentionally slow for elderly users per the
  TTS config comments; not a bug.
- **Sonnet override for Marathi** — a product decision (quality over speed
  for MR); the thinking-sound repeat logic already handles the latency.
- **SQLite** — infrastructure change outside scope of this patch.
- **ElevenLabs semaphore** — the per-loop approach is correct for the current
  single-event-loop deployment model.

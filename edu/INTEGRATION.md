# Integration

`edu/` adds files. It does not modify any existing file. To turn the education
product on you need **two edits in `telephony/session.py`**, both gated behind
an environment flag, so `PRODUCT` unset leaves Saathicare byte-for-byte as it is
today.

Unified diffs are in `edu/patches/telephony_session.diff`. What they do and why
is below.

---

## 1. Drop the package in

```bash
cp -r edu/ /path/to/sathicare/
```

No new Python dependencies. `edu/` uses only what `requirements.txt` already
pulls in.

## 2. Configure

Add to `.env`:

```bash
PRODUCT=education
INSTITUTION_FILE=edu/data/institutions/xyz_international_school.json

EDU_AGENT_NAME=Aanya
EDU_AGENT_ROLE=admissions counsellor
EDU_DEFAULT_LANGUAGE=en-IN

EDU_TONE=warm
EDU_FORMALITY=medium
EDU_VERBOSITY=concise
EDU_SALES_INTENSITY=low
EDU_PATIENCE=high

EDU_MAX_CALL_TURNS=30
EDU_WIND_DOWN_TURNS=3
EDU_HISTORY_TURNS=14
EDU_MAX_CALL_COST_INR=25

EDU_CALL_WINDOW_START=09:00
EDU_CALL_WINDOW_END=20:00
EDU_MAX_ATTEMPTS_PER_LEAD=3
EDU_MIN_HOURS_BETWEEN_ATTEMPTS=24
```

## 3. Verify before touching any code

All three run offline. No API calls, no cost, no telephony.

```bash
python -m edu.tools.prospectus_lint      # facts + cache-floor verdict
python -m edu.tools.smoke_edu en-IN      # scripted call, all the way to outcome
python -m edu.tools.smoke_edu hi-IN
python -m edu.tools.smoke_edu mr-IN
python -m edu.tools.eval_rules           # every checker fires
```

`smoke_edu` prints a contract check first. If that fails, the pack is missing a
name the call engine reaches for and the call would have died on a live parent.

## 4. The two edits

### Edit 1 — the language pack loader

In `telephony/session.py`, where the pack is bound for the call (around line
142, `lang_svc = load_lang_service(...)`):

```python
# before
lang_svc = load_lang_service(user.get("language") or USER_LANGUAGE)

# after
from edu import config as edu_config

if edu_config.IS_EDUCATION:
    from edu.lang_loader import load_edu_lang_service
    lang_svc = load_edu_lang_service(user.get("language") or edu_config.DEFAULT_LANGUAGE)
else:
    lang_svc = load_lang_service(user.get("language") or USER_LANGUAGE)
```

### Edit 2 — the session manager

Where `SessionManager(user, lang_svc)` is constructed:

```python
# before
session = SessionManager(user, lang_svc)

# after
if edu_config.IS_EDUCATION:
    from edu.session_manager import EduSessionManager
    session = EduSessionManager(user, lang_svc)
else:
    session = SessionManager(user, lang_svc)
```

That is the whole integration. `services/conversation_engine.py`,
`core/stt_service.py`, `core/tts_service.py`, `core/llm_service.py`,
`shared/prompts.py` and every language pack under `lang_services/` are
untouched.

### Optional — persist the lead outcome

In the call teardown path, after the existing `save_conversation`:

```python
if edu_config.IS_EDUCATION:
    session.persist_outcome()   # never raises; returns None if the store is down
```

`persist_outcome()` creates its own two tables (`edu_leads`,
`edu_call_outcomes`) on first use via `create_all()`. It does not touch
`core/models.py` and needs no Alembic revision — see the note at the top of
`edu/lead_store.py` for why that matters in this repo specifically.

---

## What is deliberately NOT wired up

**Outbound campaigns.** `scheduler.py` and `daily_calls.py` dial one user per
day at a fixed time. Admissions needs lead lists, concurrency caps, retry on
no-answer and callback windows. `edu/compliance.py` provides the gate
(`check(lead)` before dialling, `note_attempt()` after) but the dialler itself
is not written — it needs decisions about concurrency and provider limits that
depend on your Twilio/Exotel account.

**Barge-in.** Nothing in the codebase can interrupt playback. The turn is
record → 1.0s silence → STT → LLM → TTS. A parent cannot cut in halfway through
a fee explanation. Fixing it needs streaming ASR plus a cancel path on
`OrderedTtsQueue`, which is a real piece of work and is not attempted here.

**Mid-call language switching.** Not supported and not switchable from config.
`core/stt_service.transcribe()` takes a fixed Sarvam `language_code` resolved
once per call. One language per lead. See the note in `edu/lang_loader.py`.

**Multi-tenancy.** Single institution, env-driven, as scoped. Every module was
written so the migration is mechanical — `Institution.from_row()` is already
stubbed, and the lead tables carry column names chosen for an eventual
`institution_id` foreign key.

---

## Before pointing this at real parents

1. **Add any new model to `CLAUDE_COST`** in `core/llm_service.py`. `_rates_for()`
   bills an unlisted model at Haiku rates with a warning, so costs silently
   under-report.

2. **Confirm the cache is actually hitting.** `prospectus_lint` predicts it;
   only a live call proves it. Check that `cache_read_input_tokens` is above
   zero from turn 2. A working cache and a broken one look identical in
   `input_tokens` alone.

3. **Native review of the Hindi and Marathi packs.** The word lists are
   inherited from Saathicare and are sound. The few-shots are new and have not
   been through `prompt_eval`. Marathi needs the most — CLAUDE.md records it as
   having both the worst violation rates and the thinnest data of the four
   packs.

4. **Legal review of the lead list.** `edu/compliance.py` enforces a calling
   window, attempt caps and suppression. It cannot tell you whether a given
   list is lawful to call under TRAI's UCC rules. Answer that before the first
   campaign.

5. **Read twenty transcripts by hand.** `eval_rules` catches the mechanical
   failures. It cannot tell you whether she sounded like a counsellor or a
   telemarketer, and that distinction is the entire product.

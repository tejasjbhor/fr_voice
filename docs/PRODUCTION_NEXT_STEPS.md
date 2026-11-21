# Production next steps — handoff for Claude / colleague

**Repo:** `d:\fr_voice` (Windows). Interpreter: `.\venv\Scripts\python.exe`  
**Audience:** engineer + Claude implementing the *remaining* production path.  
**Already done (do not redo):** concurrency semaphores, call slots, Twilio/Exotel busy-out, outbound helper, `OUTBOUND_CPS`, `SCHEDULER_ENABLED` dialer split. See `CHANGES.md` section “Production concurrency gates”.

**Goal of this guide:** take the system from “gates exist, PoC defaults” to **small production** (about 20–100 concurrent HI/MR/EN calls on Exotel and/or Twilio), proven under load.  
**Not in this guide:** Sarvam/Claude *account* plan upgrades, carrier channel contracts, academy/hotel product packs (separate work).

Read `CLAUDE.md` before changing prompts, Alembic, or language packs.

---

## How to use this with Claude

1. Open this repo in Cursor.
2. Paste **one phase at a time** (Phase A, then B, …). Do not ask Claude to “do everything”.
3. After each phase: run the **Acceptance** checks. Commit only if the human asks.
4. Shell: use **cmd**, not PowerShell (`cd /d D:\fr_voice`).
5. Do **not** commit `.env` secrets. Do **not** weaken healthcare `resolve_user` production refusal unless the phase explicitly says so for a *separate* inbound product number.

---

## Current baseline (what exists today)

| Piece | Status |
|---|---|
| Per-call `SessionManager` + `UsageMeter` | Done |
| `SARVAM_*_MAX_INFLIGHT`, `CLAUDE_MAX_INFLIGHT` | Done (env) |
| `MAX_CONCURRENT_CALLS` + `CALL_SLOTS_BACKEND=memory` or `postgres` | Done |
| Twilio busy TwiML / Exotel refuse socket | Done |
| `OUTBOUND_PROVIDER`, `OUTBOUND_CPS`, `SCHEDULER_ENABLED` | Done |
| Defaults | **8-call Twilio pilot active** in `.env` — see `docs/PILOT_8_CALLS.md` |
| Postgres in production | Optional / often unset → SQLite |
| Multi-process + LB | Not done |
| Load test harness | Not done |
| Number → product map | Not done |

---

## Phase A — Postgres as system of record

**Why:** SQLite locks under concurrent writers. Slots with `CALL_SLOTS_BACKEND=postgres` need a shared DB.

### Tasks for Claude

1. Confirm `DATABASE_URL` resolution in `core/db_engine.py` (already supports Postgres).
2. Document required `.env` (do not put real passwords in the doc):

```env
DATABASE_URL=postgresql+psycopg://USER:PASS@HOST:5432/sathi
APP_ENV=production
CALL_SLOTS_BACKEND=postgres
MAX_CONCURRENT_CALLS=20
```

3. On first boot with Postgres: ensure `setup_database()` / Alembic path works. **Read the Alembic traps in `CLAUDE.md`** — do not stamp head blindly on a half-migrated DB; verify `alembic_version` matches newest file in `alembic/versions/`.
4. Add a short “Postgres checklist” subsection to `RUN.md` if missing.
5. Optional hardening: set SQLAlchemy `pool_size` / `max_overflow` from env (e.g. `DB_POOL_SIZE=10`, `DB_MAX_OVERFLOW=20`) in `core/db_engine.py` — only when URL is Postgres.

### Acceptance

```bat
cd /d D:\fr_voice
.venv\Scripts\python.exe -c "from core.db_engine import resolve_database_url, get_engine; from sqlalchemy import text; print(resolve_database_url()); get_engine().connect().execute(text('SELECT 1')); print('db ok')"
.venv\Scripts\python.exe call_server.py
```

- `GET /health` → `"database": {"ok": true, "backend": "postgres"}`
- One real or local call still writes a `conversations` row and an `api_costs` row correctly.
- `call_capacity` table appears after first slot acquire (or after explicit init).

### Out of scope for A

Multi-replica deploy, load test, product packs.

---

## Phase B — Turn on safe production caps

**Why:** Code gates are useless while env says unlimited.

### Tasks for Claude

1. Propose `.env` values for a **20-call** pilot (human sets real numbers from vendor dashboards):

```env
MAX_CONCURRENT_CALLS=20
CALL_SLOTS_BACKEND=postgres
SARVAM_STT_MAX_INFLIGHT=16
SARVAM_TTS_MAX_INFLIGHT=32
SARVAM_STT_POOL_LIMIT=16
SARVAM_TTS_POOL_LIMIT=32
CLAUDE_MAX_INFLIGHT=20
OUTBOUND_CPS=2
SCHEDULER_ENABLED=1
OUTBOUND_PROVIDER=auto
APP_ENV=production
```

2. Startup banner already prints gates — verify numbers match env after restart.
3. Manual busy-out test:
   - Temporarily set `MAX_CONCURRENT_CALLS=1`
   - Hold one live call
   - Place/inbound a second call → Twilio hears busy message; Exotel socket closes
   - End first call → second call works again
4. Confirm `/health` `capacity.active` / `available` move correctly (postgres backend).

### Acceptance

- Second call refused at cap; slot released in `finally` (no permanent “full” after all calls end).
- No change to language packs / prompts unless required for bugs found.

### Human prerequisite (not Claude)

- Sarvam Dashboard → Rate Limits ≥ the `SARVAM_*` numbers
- Claude Console → Rate limits ≥ expected RPM/ITPM for 20 concurrent turns
- Exotel/Twilio account has ≥ 20 channels

---

## Phase C — Dialer vs call-worker split (single machine first)

**Why:** Two `call_server` processes with scheduler ON double-dial the same elder.

### Tasks for Claude

1. Document two process roles in `RUN.md`:

| Role | Env | Runs |
|---|---|---|
| **dialer** | `SCHEDULER_ENABLED=1` | scheduler tick + optional outbound API |
| **worker** | `SCHEDULER_ENABLED=0` | WebSockets only (Twilio/Exotel media) |

2. Same `DATABASE_URL`, same `CALL_SLOTS_BACKEND=postgres`, same `SERVER_PUBLIC_URL` (or LB URL).
3. Ensure only one dialer marks `last_scheduled_on` / places outbound (already true if only one has scheduler on — verify no other auto-dial path: `AUTO_DIAL_ON_START` must be `false` on workers).
4. Optional: add `ROLE=dialer|worker` env that sets scheduler defaults and prints clearly in `startup_banner` (nice-to-have, not required).

### Acceptance

- Two processes up; only dialer logs “Scheduler tick”.
- Inbound media can hit either worker; slots stay consistent via Postgres.
- No duplicate daily dials for the same user on the same day.

---

## Phase D — Load test harness (HI / MR / EN)

**Why:** Without a harness, “production ready” is a guess.

### Tasks for Claude

1. Add `tools/loadtest/` (or `tools/load_calls.py`) that can:
   - Spin N **synthetic** sessions — prefer **no real PSTN** first.
   - Recommended v1: N concurrent tasks each exercising Sarvam STT/TTS + one Claude turn with a tiny fixture WAV / text path, gated by the same env semaphores — measures 429 rate and latency.
   - Better v2: local telephony provider path (`TELEPHONY_PROVIDER=local`) × N session drivers if feasible.
2. Report: success %, p50/p95 turn latency, count of HTTP 429, slot acquire failures.
3. Document how to run:

```bat
cd /d D:\fr_voice
set MAX_CONCURRENT_CALLS=20
set SARVAM_TTS_MAX_INFLIGHT=32
.venv\Scripts\python.exe -m tools.loadtest.run --concurrency 20 --lang hi-IN
```

4. Do **not** blast real phone numbers. Do **not** hardcode API keys in the tool.

### Acceptance

- 20 concurrent synthetic turns complete with **zero** sustained 429s (transient retry OK if documented).
- Raising concurrency above `MAX_CONCURRENT_CALLS` produces clean refusals, not process crashes.
- Hindi, Marathi, English each run at least once at concurrency 10.

### Stretch

- 50 concurrent on one process; record Sarvam/Claude dashboard usage.

---

## Phase E — Multi-worker deploy notes + health

**Why:** 100+ live calls need more than one process.

### Tasks for Claude

1. Write `docs/DEPLOY_CONCURRENCY.md` with a concrete topology:

```
LB (idle timeout > max call length, WebSocket sticky not required)
  ├── call_server worker × N   SCHEDULER_ENABLED=0
  └── dialer × 1               SCHEDULER_ENABLED=1
Postgres shared
Exotel + Twilio webhooks → LB public URL
```

2. Planning numbers (starting point, not gospel):
   - ~80–120 live sockets per worker process
   - `MAX_CONCURRENT_CALLS` = sum of fleet capacity (enforced in Postgres)
   - Split `SARVAM_*_MAX_INFLIGHT` **per process** so `N × per_process ≤ account limit`
3. Extend `/health` if needed: include process role, slot backend, and optionally git sha / build id from env.
4. Document Render/Docker/nginx idle timeout pitfall (must exceed longest call; server already WS-pings every 20s).

### Acceptance

- Doc is copy-pasteable for ops.
- Two workers + one dialer can be started locally on two ports behind a simple reverse proxy **or** documented why cloud LB is required for WebSocket.

---

## Phase F — Dual carrier by dialled number (optional, after D)

**Why:** Inbound already mounts both; outbound still picks one via `OUTBOUND_PROVIDER` / `TELEPHONY_PROVIDER`.

### Tasks for Claude

1. Add a small config map (env JSON or DB table later):

```env
# Example — implement as you see fit, keep simple
# NUMBER_ROUTES=+9122...:exotel:healthcare,+1618...:twilio:healthcare
```

2. On inbound: resolve product/provider from **To** number (Twilio) / virtual number (Exotel).
3. On outbound: choose Exotel vs Twilio from destination country **or** from the user’s assigned line — document the rule clearly.
4. **Do not** mix healthcare extraction into anonymous helpline callers in the same user row.

### Acceptance

- One process answers a Twilio inbound and an Exotel inbound in the same hour.
- Outbound to `+91…` can go Exotel while `+1…` goes Twilio without restarting with a different `TELEPHONY_PROVIDER`.

---

## Phase G — Anonymous / product inbound (only if product needs it)

**Why:** Healthcare production currently **refuses** unknown callers (`telephony/user_resolver.py`). Academy/hotel/helpline need the opposite on *those* numbers only.

### Tasks for Claude

1. Gate by dialled number / product flag — **never** globally disable production refusal for healthcare.
2. Create ephemeral or “lead” records for unknown callers on non-healthcare products (see `edu/` pattern).
3. Keep Saathi healthcare packs unchanged unless explicitly requested.

### Acceptance

- Unknown caller on healthcare number → still refused in `APP_ENV=production`.
- Unknown caller on product number → answered into the correct pack, no write into another patient’s health history.

---

## Recommended order for your colleague

```
A (Postgres) → B (caps on) → C (dialer/worker) → D (load test)
        → E (multi-worker docs/deploy)
        → F / G only when a second product or dual-outbound is scheduled
```

Stop and report if any phase fails acceptance. Do not skip D.

---

## Prompt template to paste into Claude (one phase)

```text
Read docs/PRODUCTION_NEXT_STEPS.md and CLAUDE.md.
Implement ONLY Phase <LETTER> exactly as written.
Do not change language pack personas or PROMPT_VERSION unless the phase requires it.
Use cmd on Windows. Do not commit unless I ask.
When done, list files changed and run the Acceptance checks for that phase.
```

---

## What “small production ready” means (definition of done)

All of the following are true:

1. Postgres in use; SQLite not used for the deployed env.
2. `MAX_CONCURRENT_CALLS` > 0 and busy-out verified.
3. One dialer + ≥1 worker; no double daily dials.
4. Load test at 20 concurrent HI/MR/EN with no crash / no sustained vendor 429s.
5. `/health` shows db ok + capacity.
6. Human confirmed Sarvam + Claude + carrier quotas ≥ the configured caps.

Until then, call the system **production-capable scaffolding**, not production-proven.

---

## Explicit non-goals (send back to product / ops, not Claude)

- Buy Sarvam Growth/Enterprise or raise Claude tier
- Buy 1000 Exotel/Twilio channels
- Kumbh / academy / hotel prompt packs
- Raising env caps to 1500 without Phase D evidence

Those are account and product decisions. Code cannot invent vendor quota.

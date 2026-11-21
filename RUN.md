# How to run `fr_voice` (copy / paste)

All commands are for **Windows CMD**.

Open a terminal and go to the repo:

```bat
cd /d D:\fr_voice
```

Use this Python:

```bat
.venv\Scripts\python.exe
```

Your secrets stay in `.env` (already in this folder). Do not paste keys into chat.

---

## 0) One-time check

```bat
cd /d D:\fr_voice
.venv\Scripts\python.exe -c "from shared.lang import load_lang_service; print(load_lang_service('hi-IN').CODE, load_lang_service('mr-IN').CODE, load_lang_service('en-IN').CODE)"
```

Expected: `hi-IN mr-IN en-IN`

---

## 1) Fastest test — no mic, no phone, no UI

Scripted full pipeline (STT → LLM → TTS):

```bat
cd /d D:\fr_voice
.venv\Scripts\python.exe smoke_local.py hi
```

Other languages:

```bat
.venv\Scripts\python.exe smoke_local.py en
.venv\Scripts\python.exe smoke_local.py mr
```

All three:

```bat
.venv\Scripts\python.exe smoke_local.py
```

---

## 2) Local mic call (talk on PC speakers/mic)

Set language in `.env` (edit the file):

```env
USER_LANGUAGE=hi-IN
```

Options: `hi-IN` | `mr-IN` | `en-IN`

Then run:

```bat
cd /d D:\fr_voice
.venv\Scripts\python.exe main.py
```

Speak after the greeting. Hang up by saying a normal goodbye / exit phrase.

---

## 3) Platform server (API + optional UI)

### Start server

```bat
cd /d D:\fr_voice
.venv\Scripts\python.exe call_server.py
```

Leave this window open. Default port: `8000`.

### Health check (new CMD window)

```bat
curl http://127.0.0.1:8000/health
```

### Useful URLs

| What | URL |
|---|---|
| Mobile / web UI | http://127.0.0.1:8000/ |
| Demo dialer page | http://127.0.0.1:8000/demo |
| Health | http://127.0.0.1:8000/health |

---

## 4) Call without UI — curl

For easy curl testing, set in `.env`:

```env
OPEN_DIALER=true
TELEPHONY_PROVIDER=local
```

Restart `call_server.py`, then:

```bat
curl -X POST http://127.0.0.1:8000/call/outbound -H "Content-Type: application/json" -d "{\"to_number\":\"+9198XXXXXXXX\",\"name\":\"Anagha\",\"language\":\"hi-IN\"}"
```

Change:

- phone → real E.164 number
- language → `hi-IN` / `mr-IN` / `en-IN`

### If `TELEPHONY_PROVIDER=local`

Response includes `local_call_url`. Open that URL in the browser on this PC to talk (type as the user, hear TTS).

Example shape:

```text
http://127.0.0.1:8000/local-call/<session_id>
```

### If `TELEPHONY_PROVIDER=twilio` (real phone)

In `.env`:

```env
TELEPHONY_PROVIDER=twilio
OPEN_DIALER=true
SERVER_PUBLIC_URL=https://YOUR-NGROK-OR-RENDER-URL
```

Expose local server (separate window):

```bat
ngrok http 8000
```

Put the ngrok HTTPS URL into `SERVER_PUBLIC_URL`, restart `call_server.py`, then run the same curl. Your phone should ring.

---

## 5) UI flow (optional)

1. Start server (`call_server.py`)
2. Open http://127.0.0.1:8000/
3. Register / add person / **Call Saathi now**
4. For local mode, open the returned local-call page on PC

---

## 6) Daily scheduler (optional)

Server must already be running.

```bat
cd /d D:\fr_voice
.venv\Scripts\python.exe scheduler.py
```

With several call-server replicas, run the scheduler on **one** dialer only:

```env
SCHEDULER_ENABLED=1
OUTBOUND_CPS=2
```

On every other replica:

```env
SCHEDULER_ENABLED=0
```

---

## 7) Concurrency pilot (2–8 Twilio calls) — active defaults

See **`docs/PILOT_8_CALLS.md`**. Current `.env` targets **8** live calls on Twilio + PAYG Sarvam (no Exotel, scheduler off). Ramp 2 → 4 → 8, then confirm the 9th gets busy-out.

## 8) Production concurrency (scale later)

Defaults in a fresh clone used to keep PoC unlimited (`MAX_CONCURRENT_CALLS=0`). This repo’s `.env` is now on the 8-call pilot.

| Env | Meaning |
|---|---|
| `MAX_CONCURRENT_CALLS` | Live-call cap. Twilio gets a busy message; Exotel closes the socket. |
| `CALL_SLOTS_BACKEND` | `memory` (one process) or `postgres` (shared across replicas). |
| `SARVAM_STT_MAX_INFLIGHT` / `SARVAM_TTS_MAX_INFLIGHT` | Our gates — set at or under Sarvam Dashboard → Rate Limits. |
| `CLAUDE_MAX_INFLIGHT` | Our Claude gate — set under Console → Rate limits. |
| `OUTBOUND_PROVIDER` | `auto` / `twilio` / `exotel` (inbound for both stays mounted). |

`GET /health` reports `capacity` so you can see active vs max.

Load order: 50 → 100 concurrent on one process, then add replicas + `CALL_SLOTS_BACKEND=postgres`. Raising only the env numbers does nothing if the Sarvam/Claude **plan** is still Pay-as-you-go / Start.

---

## Quick map — what should I run?

| Goal | Command |
|---|---|
| Quick AI pipeline test | `smoke_local.py hi` |
| Talk on PC mic | `main.py` |
| Full platform / curl / UI | `call_server.py` |
| Real phone call | `call_server.py` + Twilio + public URL |
| Fake phone (no Twilio) | `TELEPHONY_PROVIDER=local` + curl/UI |

---

## Common fixes

**Port busy**

```bat
netstat -ano | findstr :8000
```

Or set another port in `.env`:

```env
SERVER_PORT=8001
```

**Wrong language**  
Change `USER_LANGUAGE` in `.env`, restart the process.

**Curl outbound rejected / auth error**  
Set `OPEN_DIALER=true` in `.env` and restart `call_server.py`.

**Import / pack missing**

```bat
cd /d D:\fr_voice
.venv\Scripts\python.exe -c "from shared.lang import load_lang_service; print(load_lang_service('hi-IN').CODE)"
```

---

## Do not use these folders for running

- `D:\edu_voice` — older / partial copy
- `C:\Users\Tejas\Downloads\saathitest` — older archive

Use only:

```bat
cd /d D:\fr_voice
```

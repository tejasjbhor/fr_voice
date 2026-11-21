# Concurrency pilot — 2 to 8 live Twilio calls

Budget-first slice: prove production-shaped concurrency on **Pay-as-you-go Sarvam**, **personal Claude**, and **Twilio (~$20)**. Exotel and Sarvam Pro are out of scope for this pilot.

## What is configured (`.env`)

| Setting | Value | Why |
|---|---|---|
| `MAX_CONCURRENT_CALLS` | `8` | 9th call busy-out / outbound `503` |
| `CALL_SLOTS_BACKEND` | `memory` | One `call_server` process |
| `SARVAM_*_MAX_INFLIGHT` / pool | `8` | PAYG ~60 req/min |
| `CLAUDE_MAX_INFLIGHT` | `8` | One stream per live call |
| `OUTBOUND_PROVIDER` | `twilio` | Exotel credits empty |
| `OPEN_DIALER` | `true` | curl works without app login |
| `SCHEDULER_ENABLED` | `0` | No daily dial burn |
| `AUTO_DIAL_ON_START` | `false` | Dial on demand only |
| `OUTBOUND_CPS` | `1` | One new dial per second |
| `TTS_PROVIDER_EN/HI/MR` | `sarvam` | **No Fish** for EN/HI/MR — Sarvam bulbul:v3 (Priya) only |
| `STT_PROVIDER_EN/HI/MR` | `sarvam` | **No Fish** for EN/HI/MR — Sarvam STT only |

## Run server

```bat
cd /d D:\fr_voice
.venv\Scripts\python.exe call_server.py
```

Other window (fresh ngrok URL → `.env` `SERVER_PUBLIC_URL`, **restart** server):

```bat
ngrok http 8000
```

**Mobile demo (laptop):** open `https://YOUR-NGROK/demo`  
**Mobile demo (Render free, wake then dial):** see [`docs/RENDER_DEMO.md`](RENDER_DEMO.md) — laptop flow stays unchanged.

Twilio Console → your number → Voice webhook:

`POST https://YOUR-NGROK/twilio/voice`

Banner must show: `Call slots: 8`, `Pilot mode`, `Scheduler: OFF`, `Outbound dial: twilio`.

## Where do names / numbers go?

**Not in one list.** Each live call = one phone.

| What you want | What you do |
|---|---|
| Call **one** person | One CMD + one curl (name + number) |
| **2–8 concurrent** | **2–8 CMD windows**, each with a different name + number |

Template (edit and run in its own CMD): `scripts\pilot_outbound_examples.cmd`

### CMD pattern (copy per person)

```bat
curl -X POST http://127.0.0.1:8000/call/outbound -H "Content-Type: application/json" -d "{\"to_number\":\"+3374XXXXXXX\",\"name\":\"Tejas\",\"language\":\"en-IN\"}"
```

Second CMD — different phone:

```bat
curl -X POST http://127.0.0.1:8000/call/outbound -H "Content-Type: application/json" -d "{\"to_number\":\"+3365XXXXXXX\",\"name\":\"Alex\",\"language\":\"hi-IN\"}"
```

Start windows ~1s apart. Both answer and stay on the line = **2 concurrent**.

Success JSON looks like `{"status":"dialing",...}`.  
Over capacity: HTTP **503** `{"error":"capacity_full",...}`.

## Test ramp

1. **2 calls** — two CMDs, two phones  
2. **4 calls** — four CMDs  
3. **8 calls** — eight CMDs; all hear the agent  
4. **9th CMD** — expect `capacity_full` (or Twilio busy if inbound)

Busy-out without 9 phones: set `MAX_CONCURRENT_CALLS=1`, two dials → second fails; set back to `8`.

While live:

```bat
curl http://127.0.0.1:8000/health
```

`capacity.active` should match how many calls are still up.

## Stop rules

- Sarvam credits low → stop  
- Twilio balance under ~$5 → stop  
- Sustained `429` → drop gates to 4 and retest  

## Smoke (no phone)

```bat
cd /d D:\fr_voice
.venv\Scripts\python.exe tools\_smoke_concurrency.py
```

## Inbound product (step 2) — enabled when `PRODUCT=inbound`

See **`inbound/README.md`**. Same 8-call cap. Callers dial your Twilio number;
unknown numbers become helpline guests; queries land in `inbound/data/queries.jsonl`.

Switch back to healthcare outbound: `PRODUCT=health`.

## Not this pilot

- Exotel, Postgres multi-worker, 50+ concurrent, Sarvam Pro  

# Inbound helpline module

Opposite of outbound Saathi healthcare: **people call our Twilio number**, the
agent answers queries, records details, and replies in Hindi / Marathi / English.

Shares the same call engine, Sarvam/Claude gates, and `MAX_CONCURRENT_CALLS=8`
pilot cap. Does **not** write health extraction rows.

## Enable

In `.env`:

```env
PRODUCT=inbound
INBOUND_AGENT_NAME=Sathi
INBOUND_SERVICE_NAME=Sathi Helpline
INBOUND_DEFAULT_LANGUAGE=hi-IN
```

Restart `call_server.py`. Banner shows `Inbound helpline` and `PRODUCT: inbound`.

To return to healthcare outbound: `PRODUCT=health` (or remove `PRODUCT`).

## How callers reach you

1. Server + ngrok running; Twilio voice webhook → `POST {SERVER_PUBLIC_URL}/twilio/voice`
2. Up to **8 people** dial `TWILIO_PHONE_NUMBER` at once
3. Unknown numbers become `inbound_guest` users (`schedule_enabled=false`)
4. 9th concurrent call → busy-out (same as pilot)

Language: `INBOUND_DEFAULT_LANGUAGE`, or guessed from `+91` → Hindi / else English.
One language per call (no mid-call switch).

## Records

Each finished call appends one JSON line to `inbound/data/queries.jsonl`
(topic, location, callback, urgency, summary snippet, cost).

## Offline check

```bat
cd /d D:\fr_voice
.venv\Scripts\python.exe -m inbound.tools.smoke_inbound hi-IN
.venv\Scripts\python.exe -m inbound.tools.smoke_inbound en-IN
.venv\Scripts\python.exe -m inbound.tools.smoke_inbound mr-IN
```

## Layout

| Path | Role |
|---|---|
| `config.py` | `PRODUCT=inbound` switch |
| `persona.py` | Shared helpline persona |
| `packs/` | HI / MR / EN scripts + Saathi word lists |
| `session_manager.py` | Query extract + longer turn cap |
| `store.py` | Guest user + JSONL outcomes |

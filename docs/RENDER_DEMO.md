# Render free demo (keep laptop working)

Same app, two hosts:

| | Laptop | Render |
|--|--|--|
| Start | `.venv\Scripts\python.exe call_server.py` + `ngrok http 8000` | Docker on Render |
| Demo page | `https://YOUR-NGROK/demo` | `https://YOUR-SERVICE.onrender.com/demo` |
| Config | local `.env` | Render **Environment** |

Do **not** put `.env` in git. Laptop keeps using your local `.env`.

---

## Step 1 — Push code to GitHub

If the repo is not on GitHub yet, create a repo and push (omit `.env`).

```bat
cd /d D:\fr_voice
git status
```

You need at least: `Dockerfile`, `Procfile`, `call_server.py`, `docs/RENDER_DEMO.md`.

---

## Step 2 — Create Web Service on Render

1. Open [https://dashboard.render.com](https://dashboard.render.com) → Sign up / log in.  
2. **New** → **Web Service**.  
3. Connect the GitHub repo `fr_voice` (or your fork).  
4. Settings:

| Field | Value |
|--|--|
| Name | `sathi-call-server` (any name) |
| Region | Closest to you (or Singapore / Frankfurt) |
| Runtime | **Docker** |
| Branch | `main` (or your working branch) |
| Instance | **Free** |
| Health check path | `/health` |

5. Click **Create Web Service** (you will add env vars next — can create first, then add, then redeploy).

---

## Step 3 — Environment variables on Render

Dashboard → your service → **Environment** → add these.

### Required for phone demos

Copy values from your local `.env` (same keys, Render UI — not the file):

```
SERVER_PUBLIC_URL=https://YOUR-SERVICE.onrender.com
```

*(After first deploy, Render shows the URL — paste it here with **no** trailing slash, then save + redeploy.)*

```
OPEN_DIALER=true
SCHEDULER_ENABLED=0
AUTO_DIAL_ON_START=false
TELEPHONY_PROVIDER=twilio
OUTBOUND_PROVIDER=twilio
MAX_CONCURRENT_CALLS=8
PRODUCT=health

TTS_PROVIDER_EN=sarvam
TTS_PROVIDER_HI=sarvam
TTS_PROVIDER_MR=sarvam
STT_PROVIDER_EN=sarvam
STT_PROVIDER_HI=sarvam
STT_PROVIDER_MR=sarvam

SARVAM_API_KEY=...
TWILIO_ACCOUNT_SID=...
TWILIO_AUTH_TOKEN=...
TWILIO_PHONE_NUMBER=...
```

Also set your Claude / Anthropic key the same way your local `.env` names it (whatever `call_server` already uses).

Optional but useful:

```
APP_SECRET=long-random-string
APP_ENV=production
```

Leave `DATABASE_URL` empty for a quick demo (SQLite inside the container).  
**Note:** Free Render **wipes local disk** when the service sleeps — demo users may disappear after idle. Fine for live demos; add Render Postgres later if you need persistence.

---

## Step 4 — Point Twilio at Render

Twilio Console → your number → Voice:

| Webhook | URL |
|--|--|
| A call comes in | `POST https://YOUR-SERVICE.onrender.com/twilio/voice` |
| Call status (optional) | `POST https://YOUR-SERVICE.onrender.com/twilio/status` |

When you switch back to **laptop + ngrok**, put the ngrok URLs here again (or use a second Twilio number for Render).

---

## Step 5 — Wait for deploy, then demo from phone

1. Render → **Logs** until you see `Uvicorn running` / Application startup.  
2. On your **mobile browser** open:

```
https://YOUR-SERVICE.onrender.com/demo
```

3. Wait until the page says **Server awake** (Free cold start can take ~1 minute).  
4. Enter **Name**, **Phone** (`+91…`), **Language** → **Call now**.  
5. Place more calls within ~15 minutes so the free instance stays warm.  
6. If it slept: open `/demo` again first, wait for awake, then dial.

Also check: `https://YOUR-SERVICE.onrender.com/health`

---

## Step 6 — Laptop still works (unchanged)

```bat
cd /d D:\fr_voice
ngrok http 8000
```

Put ngrok HTTPS into local `.env` → `SERVER_PUBLIC_URL=...`  
Restart:

```bat
.venv\Scripts\python.exe call_server.py
```

Twilio webhooks → that ngrok URL.  
Demo: `https://YOUR-NGROK/demo`

---

## Troubleshooting

| Symptom | Fix |
|--|--|
| Page spins 1 min then loads | Normal Free cold start |
| Call fails / no audio | Twilio webhook still points at old ngrok; update to Render |
| `SERVER_PUBLIC_URL` wrong | Must match the live `https://….onrender.com` exactly |
| Dial rejected / login | `OPEN_DIALER` must be `true` on Render |
| Wrong voice (Fish) | Set `TTS_PROVIDER_EN/HI/MR=sarvam` on Render |
| Capacity full | Wait for a call to end (`MAX_CONCURRENT_CALLS`) |
| She talks but does not hear you | Render Logs: look for `Twilio inbound audio OK`, `VAD: silence after`, `STT (Sarvam)`. If no inbound line → audio not arriving. If VAD never fires → set `SILENCE_THRESHOLD=200`. If STT errors → check `SARVAM_API_KEY` / STT providers = sarvam. Wait until she finishes before speaking. |

---

## Cost reminder

Render Free = host only. **Twilio + Sarvam + Claude still bill per call.**

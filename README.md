# fr_voice — Maîtria French voice agent

French admissions demo (Camille). Languages: **French** (`fr-FR`) and optional **English** (`en-IN`).

## Voice stack

| Language | STT | TTS |
|---|---|---|
| **French (`fr-FR`)** | Gladia | Fish Audio |
| English (`en-IN`) | Sarvam | Sarvam |

## Run

**Local mic:**
```
cd /d d:\fr_voice
.venv\Scripts\python.exe main.py
```

**Phone (Twilio outbound to USER_PHONE):**
```
.venv\Scripts\python.exe call_server.py
```
(with ngrok + `SERVER_PUBLIC_URL` set; `AUTO_DIAL_ON_START=true` rings your phone)

Do not paste keys into chat.

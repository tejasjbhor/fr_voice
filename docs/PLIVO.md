# Plivo (India) — Saathi voice

Cheaper India domestic telephony (~₹0.38/min). Same Saathi stack (Sarvam + Claude); only the phone pipe changes.

## Env

```
TELEPHONY_PROVIDER=plivo
OUTBOUND_PROVIDER=plivo
PLIVO_AUTH_ID=...
PLIVO_AUTH_TOKEN=...
PLIVO_PHONE_NUMBER=+9122...
SERVER_PUBLIC_URL=https://fr-voice.onrender.com
```

Leave Twilio vars in place if you still want US/international dials later.

## Plivo Console

1. **Voice → Applications → saathi**
   - Answer URL: `https://YOUR-PUBLIC/plivo/voice` (POST)
   - Hangup URL: `https://YOUR-PUBLIC/plivo/hangup` (POST)
2. **Phone Numbers → your number → Application = saathi**

## Routes (mounted always)

| Path | Role |
|--|--|
| `POST/GET /plivo/voice` | Answer XML → bidirectional Stream |
| `POST/GET /plivo/hangup` | Hangup callback |
| `WS /plivo/media-stream` | μ-law audio in/out |

## Local test

```bat
ngrok http 8000
```

Put ngrok HTTPS into `SERVER_PUBLIC_URL`, set providers to `plivo`, restart `call_server`, update Plivo Answer URL to ngrok, then `/demo` Call.

## Notes

- India numbers need KYC; domestic calling rules apply.
- Media Streams use `playAudio` / `clearAudio` (not Twilio’s `media` / `clear`).
- Twilio routes stay live — both providers can answer inbound; outbound follows `OUTBOUND_PROVIDER`.

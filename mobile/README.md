# Saathi Care — phone UI + Android APK

Lives in this repo under `mobile/`. Backend is the rest of the repo (Render or `python call_server.py`).

**Not for Play Store yet.** Debug APK / browser only.

## Local dummy calls (Android Studio + PC, no Twilio)

1. In `.env` set `TELEPHONY_PROVIDER=local` (and keep Claude/Sarvam keys for the AI).
2. Start the server:
   ```bat
   venv\Scripts\python.exe call_server.py
   ```
3. Emulator / APK → **Profile → Backend URL** → `http://10.0.2.2:8000` → Save.
4. Register as Subscriber → add a person → **Call Saathi now**.
5. App shows a **local call URL** (also copied). Open it on the **PC** browser:
   `http://127.0.0.1:8000/local-call/<id>`
6. Type as the elder, hear Saathi (TTS), click **End call**.
7. In the app → **Refresh last call** → transcript + health (same as production).

When ready for real phones: set `TELEPHONY_PROVIDER=twilio` (or exotel/frejun), point Backend URL at Render, rebuild.

## Roles

| Role | How they get the app |
|---|---|
| **Subscriber** | Install APK / open Render URL → register as Subscriber → add people → **Share invite** (smartphone elders only) |
| **User (elder, smartphone)** | Opens invite link `/?invite=CODE` → register with the **same phone** the subscriber added → companion home |
| **User (calls only, no smartphone)** | **Does not register.** Subscriber adds them with “No smartphone — calls only”. They only answer Saathi’s phone call. |
| **You (platform)** | Web: `/admin.html` (PIN) — not required in the APK for v1 |

## End-to-end flows

**Subscriber (family phone)**  
Register → OTP → add person (name + E.164 + language) → Schedule tab → Call Saathi now → after hang-up, open person → **Refresh last call** for transcript + health.

**Calls-only elder (voice phone)**  
Subscriber adds with “No smartphone — calls only”. No invite, no app. Schedule + Call Saathi now from subscriber’s phone.

**Smartphone elder**  
Subscriber shares invite → elder opens link → register as User with same phone → companion home (Call Saathi, SOS, refresh).

Transcript is **not live** during the call — saved on server after hang-up; tap Refresh last call (~30s after end for health notes).

**Android APK:** Profile → Backend URL should be `https://saathicare-plj8.onrender.com` (auto on native app after sync).

**iPhone/iPad (no Mac):** Safari → Render URL → Add to Home Screen (same UI, no native build).

## Invite flow (built-in)

1. Subscriber adds a person (name + E.164 phone).
2. Open that person → **Share invite link with this person**.
3. Elder opens the link (WhatsApp / SMS).
4. Elder completes OTP + consents on that phone.
5. They land on the User (companion) home, linked to the family.

API:
- `GET /api/invite/{code}` — public preview
- `POST /api/invite/accept` — elder joins (Bearer token)
- `POST /api/invite/refresh` — new code (old link dies)

## Fastest: Render web

https://saathicare-plj8.onrender.com/

## Local browser against Render

```bat
cd mobile
npm start
```

http://localhost:4173

## Build a debug Android APK

Needs: Node.js LTS + Android Studio (SDK).

```bat
cd mobile
npm install
npm install @capacitor/core @capacitor/cli @capacitor/android @capacitor/app @capacitor/share
npx cap add android
npx cap sync
npx cap open android
```

In Android Studio: **Build → Build Bundle(s) / APK(s) → Build APK(s)**  
APK path: `mobile\android\app\build\outputs\apk\debug\app-debug.apk`

Share that file with subscribers for field testing (sideload). Play Store comes later (signing + listing).

### After UI changes

```bat
cd mobile
npx cap sync
```

Then rebuild the APK in Android Studio.

### Deep links (optional next step)

Invite links already work as `https://YOUR_RENDER/?invite=CODE`.  
For App Links that open the installed APK, add an Android intent-filter for your Render host after the first debug APK works.

# AWS Mumbai — 2 concurrent call pilot (follow this in order)

**Goal:** Run Saathi on **EC2 `t3.medium` in Mumbai (`ap-south-1`)** with **max 2 live calls**, Plivo + Sarvam + Claude.  
**Your $83 credit** covers the EC2 time. Plivo/Sarvam/Claude bill separately.

Repo already set for 2 calls: `MAX_CONCURRENT_CALLS=2` (+ matching Sarvam/Claude gates).

---

## Before you start (laptop checklist)

Have these ready (from `D:\fr_voice\.env`):

- [ ] `PLIVO_AUTH_ID` / `PLIVO_AUTH_TOKEN` / `PLIVO_PHONE_NUMBER`
- [ ] `CLAUDE_API_KEY`
- [ ] `SARVAM_API_KEY`
- [ ] Plivo console login (Application `saathi` + number `+912269854791`)
- [ ] AWS login with credit visible
- [ ] Optional: a domain, **or** use DuckDNS (free) for HTTPS

---

## Step 1 — AWS region

1. Open [AWS Console](https://console.aws.amazon.com/)
2. Top-right region → **Asia Pacific (Mumbai) `ap-south-1`**

---

## Step 2 — Security group

1. **VPC → Security Groups → Create**
2. Name: `sathi-pilot-sg`
3. Inbound rules:

| Type | Port | Source |
|--|--|--|
| SSH | 22 | **My IP** only |
| HTTP | 80 | `0.0.0.0/0` |
| HTTPS | 443 | `0.0.0.0/0` |

4. Create security group

---

## Step 3 — Launch EC2 `t3.medium`

1. **EC2 → Instances → Launch instance**
2. Name: `sathi-mumbai-pilot`
3. AMI: **Ubuntu Server 22.04 LTS**
4. Instance type: **`t3.medium`**
5. Key pair: create/download a `.pem` (keep it safe)
6. Network: select security group `sathi-pilot-sg`
7. Storage: **30 GB gp3**
8. Launch

---

## Step 4 — Elastic IP

1. **EC2 → Elastic IPs → Allocate**
2. **Associate** with instance `sathi-mumbai-pilot`
3. Copy the public IP, e.g. `13.x.x.x`  
   You will use this until HTTPS DNS is ready.

---

## Step 5 — SSH in

On your Windows PC (PowerShell or CMD), from the folder with the `.pem`:

```bat
ssh -i your-key.pem ubuntu@13.x.x.x
```

(First time: say `yes` to fingerprint.)

---

## Step 6 — Install Docker + git

On the EC2 box:

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl git
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker ubuntu
newgrp docker
docker --version
```

---

## Step 7 — Clone the repo

```bash
cd ~
git clone https://github.com/tejasjbhor/fr_voice.git
cd fr_voice
git checkout master
git pull
```

---

## Step 8 — Create `.env` on the server

```bash
mkdir -p ~/fr_voice/deploy/aws
cd ~/fr_voice/deploy/aws
cp .env.aws.example .env
nano .env
```

Fill **every blank** from your laptop `.env`. Important lines:

```env
SERVER_PUBLIC_URL=https://YOUR_HOST_HERE
TELEPHONY_PROVIDER=plivo
OUTBOUND_PROVIDER=plivo
MAX_CONCURRENT_CALLS=2
SARVAM_STT_MAX_INFLIGHT=2
SARVAM_TTS_MAX_INFLIGHT=2
CLAUDE_MAX_INFLIGHT=2
PLIVO_AUTH_ID=...
PLIVO_AUTH_TOKEN=...
PLIVO_PHONE_NUMBER=+912269854791
CLAUDE_API_KEY=...
SARVAM_API_KEY=...
```

Save (`Ctrl+O`, Enter, `Ctrl+X`).

> Leave `SERVER_PUBLIC_URL` as a placeholder until Step 10, then edit again.

---

## Step 9 — Build and start the app

```bash
cd ~/fr_voice/deploy/aws
docker compose up -d --build
docker compose logs -f --tail=80
```

Wait until you see something like:

- `Provider: plivo`
- `Call slots: 2`
- `Uvicorn running`

Detach logs: `Ctrl+C` (container keeps running).

Quick check from the box:

```bash
curl -s http://127.0.0.1:8000/health
```

---

## Step 10 — HTTPS (pick ONE path)

### Option A — You have a domain (best)

1. DNS **A record**: `calls.yourdomain.com` → Elastic IP  
2. Install Caddy:

```bash
sudo apt-get install -y debian-keyring debian-archive-keyring apt-transport-https
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt-get update
sudo apt-get install -y caddy
```

3. Configure reverse proxy:

```bash
sudo tee /etc/caddy/Caddyfile >/dev/null <<'EOF'
calls.yourdomain.com {
    reverse_proxy 127.0.0.1:8000
}
EOF
sudo systemctl reload caddy
```

4. Edit env:

```bash
nano ~/fr_voice/deploy/aws/.env
# set: SERVER_PUBLIC_URL=https://calls.yourdomain.com
cd ~/fr_voice/deploy/aws
docker compose up -d
```

### Option B — No domain yet (temporary test with nip.io)

```bash
# Replace 13-x-x-x with your Elastic IP using dashes
# Example IP 13.232.10.5 → 13-232-10-5.nip.io
```

Install Caddy as in Option A, then:

```bash
sudo tee /etc/caddy/Caddyfile >/dev/null <<'EOF'
13-232-10-5.nip.io {
    reverse_proxy 127.0.0.1:8000
}
EOF
sudo systemctl reload caddy
```

Set:

```env
SERVER_PUBLIC_URL=https://13-232-10-5.nip.io
```

Restart compose. Open that HTTPS URL in a browser.

---

## Step 11 — Point Plivo at AWS

1. Plivo → **Voice → Applications → saathi**
2. **Answer URL:** `https://YOUR_HOST/plivo/voice`  method **POST**
3. **Hangup URL:** `https://YOUR_HOST/plivo/hangup`  method **POST**
4. **Phone Numbers** → `+91 22 6985 4791` → Application = **saathi** → Update

---

## Step 12 — Test 1 call

1. Phone browser: `https://YOUR_HOST/demo`
2. Wait until **Server ready**
3. Name + **Indian** number + language → **Call**
4. On EC2 logs:

```bash
cd ~/fr_voice/deploy/aws
docker compose logs -f --tail=100
```

Expect: `Provider: plivo`, `Call slots: 2`, correct `lang=...`, STT + Claude replies.

---

## Step 13 — Test 2 concurrent calls

1. Open `/demo` in **two** browser tabs (or two phones)
2. Dial **two different Indian numbers** within a few seconds
3. Both should talk
4. A **3rd** dial should get busy / fail capacity (`MAX_CONCURRENT_CALLS=2`)

---

## Step 14 — When finished testing (save credit)

```bash
# stop app
cd ~/fr_voice/deploy/aws && docker compose down

# stop EC2 billing for compute
# AWS Console → EC2 → Instance → Instance state → Stop
```

Start again later: **Start instance** → `docker compose up -d` on the box.

---

## Useful commands

```bash
cd ~/fr_voice/deploy/aws
docker compose ps
docker compose logs -f --tail=100
docker compose restart
git -C ~/fr_voice pull && docker compose up -d --build
```

Health: `https://YOUR_HOST/health`  
Demo: `https://YOUR_HOST/demo`

---

## Troubleshooting

| Problem | Fix |
|--|--|
| Plivo dials but no audio / no WS | `SERVER_PUBLIC_URL` must be **https** matching Caddy host; Plivo Answer URL same host |
| Wrong language (Ramesh/Hindi) | Redeploy latest code (caller `?from=` fix); confirm demo user phone matches |
| `Call slots: 8` in banner | `.env` still has 8 — set all gates to **2**, recreate container |
| Out of memory | You launched micro by mistake — use **`t3.medium`** |
| Claude 401 | Bad/expired `CLAUDE_API_KEY` on the server `.env` |
| HTTPS fail | DNS not pointing at Elastic IP yet; wait a few minutes |

---

## Cost reminder

- **AWS $83 credit** → EC2 `t3.medium` time  
- **Plivo / Sarvam / Claude** → still paid per call (not from AWS credit)

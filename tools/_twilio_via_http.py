"""Fetch Twilio call price via REST (no twilio package needed)."""
import os
import base64
import json
import urllib.request
from dotenv import load_dotenv

load_dotenv(override=True)

sid = os.getenv("TWILIO_ACCOUNT_SID")
token = os.getenv("TWILIO_AUTH_TOKEN")
call_sid = "CA06d12321faefa2d68c5a7c968de01a5c"
url = f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Calls/{call_sid}.json"
auth = base64.b64encode(f"{sid}:{token}".encode()).decode()
req = urllib.request.Request(url, headers={"Authorization": f"Basic {auth}"})
with urllib.request.urlopen(req, timeout=30) as resp:
    data = json.loads(resp.read().decode())
for k in ("sid", "status", "direction", "duration", "price", "price_unit", "to", "from", "start_time", "end_time"):
    print(f"{k}: {data.get(k)}")
